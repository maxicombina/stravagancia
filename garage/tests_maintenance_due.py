from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Event
from time import monotonic, sleep

import pytest
from django.db import close_old_connections, connection, transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .models import ItemUsage, MaintenanceRule, Ride, ServiceEvent, ServiceType, UsageMaterializationState
from .services.maintenance import save_maintenance
from .services.maintenance_due import maintenance_due
from .services.ownership import _lock_owner
from .tests_maintenance import at, baseline, data, event


def rule(data, **values):
    return save_maintenance(data.owner, MaintenanceRule, item=data.item, service_type=data.kind, anchor_at=at(), **values)


def facts(data, start, *, distance='100.000', moving=None, timer='9000', bike=True):
    # Deliberate synthetic facts let tests model uninitialized and partial states.
    ride = Ride.objects.create(owner=data.owner, started_at=start, bike=data.bike if bike else None,
                               distance_m=Decimal(distance) if distance is not None else None,
                               moving_time_s=Decimal(moving) if moving is not None else None, timer_time_s=Decimal(timer))
    if start is not None:
        ItemUsage.objects.create(owner=data.owner, item=data.item, ride=ride, started_at=start, bike=ride.bike,
                                 distance_m=ride.distance_m, moving_time_s=ride.moving_time_s, timer_time_s=ride.timer_time_s)
    return ride


def initialized(data):
    UsageMaterializationState.objects.update_or_create(owner=data.owner, defaults={'initialized_at':at()})


@pytest.mark.parametrize('elapsed,status', [(0,'current'), (8,'current'), (9,'soon'), (10,'due'), (11,'due')])
def test_calendar_exact_and_soon_boundaries_despite_unmounted(data, elapsed, status):
    rule(data, calendar_days=10)
    result = maintenance_due(data.owner, at=at()+timedelta(days=elapsed))[0]
    assert result.status == status
    assert result.metrics[0].coverage == 'complete'
    assert result.metrics[0].remaining == max(0, 10-elapsed)


@pytest.mark.parametrize('metric', ['distance_m','moving_time_s','ride_count'])
def test_empty_interval_is_complete_zero_without_materialization(data, metric):
    rule(data, **{metric:1})
    facts(data, None)
    result = maintenance_due(data.owner, at=at())[0]
    assert result.status == 'current'
    assert result.metrics[0].value == 0 and result.metrics[0].coverage == 'complete'


@pytest.mark.parametrize('value,status', [('89.999','unknown'), ('90.000','unknown'), ('100.000','due')])
def test_partial_lower_bound_never_current_or_soon(data, value, status):
    rule(data, distance_m=100)
    facts(data, at(2), distance=value)
    initialized(data)
    result = maintenance_due(data.owner, at=at(3))[0]
    assert result.status == status
    assert result.metrics[0].coverage == 'partial'


def test_uninitialized_stale_facts_cannot_prove_due(data):
    rule(data, distance_m=100)
    facts(data, at(2), distance='999')
    result = maintenance_due(data.owner, at=at(3))[0]
    assert result.status == 'unknown' and result.metrics[0].value is None
    assert not result.materialization_current


def test_baselines_are_event_specific_and_do_not_double_count(data):
    rule(data, distance_m=500)
    ev = event(data)
    baseline(data, ev)
    facts(data, at(2), distance='900')
    facts(data, at(3), distance='100')
    facts(data, at(4), distance='500')
    initialized(data)
    result = maintenance_due(data.owner, at=at(4))[0]
    assert result.metrics[0].value == Decimal('223.456')
    assert result.status == 'unknown'
    assert result.event == ev
    assert maintenance_due(data.owner, at=at(3))[0].metrics[0].value == Decimal('123.456')
    later = save_maintenance(data.owner, ServiceEvent, item=data.item, service_type=data.kind, performed_at=at(3))
    result = maintenance_due(data.owner, at=at(4))[0]
    assert result.event == later and result.metrics[0].value == 100


@pytest.mark.parametrize('value,status', [('80','current'),('90','soon'),('100','due')])
@pytest.mark.parametrize('estimated', [False,True])
def test_exact_baseline_without_materialization_and_estimated_label(data, value, status, estimated):
    rule(data, distance_m=100)
    ev=event(data)
    from .services.baselines import record_baseline
    record_baseline(data.owner,item=data.item,metric='distance_m',scope='service',service_event=ev,cut_at=at(3),value=Decimal(value),is_estimated=estimated)
    facts(data, at(2), distance='999')
    result=maintenance_due(data.owner,at=at(3))[0]
    assert result.status == status and result.metrics[0].coverage == 'complete'
    assert result.metrics[0].value == Decimal(value) and result.is_estimated == estimated


def test_missing_moving_not_replaced_with_timer_and_due_wins_unknown(data):
    rule(data, moving_time_s=10, distance_m=100)
    facts(data, at(2), moving=None)
    initialized(data)
    result=maintenance_due(data.owner,at=at(3))[0]
    assert result.status == 'due'
    assert next(m for m in result.metrics if m.name=='moving_time_s').status=='unknown'


def test_missing_and_future_references_are_unknown(data):
    r=rule(data, calendar_days=1)
    save_maintenance(data.owner,MaintenanceRule,r.pk,anchor_at=at(5))
    assert maintenance_due(data.owner,at=at(3))[0].status=='unknown'
    save_maintenance(data.owner,MaintenanceRule,r.pk,anchor_at=None)
    assert maintenance_due(data.owner,at=at(10))[0].reference_at is None


def test_lubrication_reset_does_not_reset_replacement(data):
    rule(data, calendar_days=10)
    replacement=save_maintenance(data.owner,ServiceType,name='Replace')
    other=save_maintenance(data.owner,MaintenanceRule,item=data.item,service_type=replacement,anchor_at=at(),calendar_days=10)
    save_maintenance(data.owner,ServiceEvent,item=data.item,service_type=data.kind,performed_at=at(10))
    results={r.rule.pk:r for r in maintenance_due(data.owner,at=at(11))}
    assert results[other.pk].status=='due'
    assert next(r for r in results.values() if r.rule.service_type_id==data.kind.pk).status=='current'


def test_bike_exact_usage_no_component_sum_and_owner_context(data):
    save_maintenance(data.owner,MaintenanceRule,bike=data.bike,service_type=data.kind,anchor_at=at(),distance_m=100,ride_count=2)
    facts(data,at(2),distance='50')
    facts(data,at(3),distance='500',bike=False)
    facts(data,None)
    result=maintenance_due(data.owner,at=at(4))[0]
    assert result.status=='unknown' and result.metrics[0].value==50
    assert result.metrics[1].value==1
    assert result.pending_started_rides==1 and result.unknown_bike_rides==1


def test_large_calendar_and_timezone_elapsed_24_hours(data):
    r=rule(data,calendar_days=2147483647)
    save_maintenance(data.owner,MaintenanceRule,r.pk,anchor_at=datetime(1,1,1,tzinfo=timezone.utc))
    assert maintenance_due(data.owner,at=datetime.max.replace(tzinfo=timezone.utc))[0].status=='current'
    from zoneinfo import ZoneInfo
    start=datetime(2026,3,28,12,tzinfo=ZoneInfo('Europe/Madrid'))
    save_maintenance(data.owner,MaintenanceRule,r.pk,anchor_at=start,calendar_days=1)
    result=maintenance_due(data.owner,at=datetime(2026,3,29,12,tzinfo=ZoneInfo('Europe/Madrid')))[0]
    assert result.status=='soon'
    assert abs(result.metrics[0].value - Decimal(23)/24) < Decimal('1e-27')


def test_private_ui_get_readonly_labels_owner_scope_and_query_budget(data):
    rule(data, calendar_days=10)
    save_maintenance(data.other,MaintenanceRule,service_type=data.foreign,bike=__import__('garage.models',fromlist=['Bike']).Bike.objects.create(owner=data.other,name='HIDDEN'),calendar_days=1,anchor_at=at())
    client=Client()
    assert client.get(reverse('garage:maintenance')).status_code==302
    client.force_login(data.owner)
    for route in ['garage:maintenance','garage:index']:
        with CaptureQueriesContext(connection) as queries:
            response=client.get(reverse(route))
        assert response.status_code==200
        assert b'90 %' in response.content and b'HIDDEN' not in response.content and b'SECRET' not in response.content
        assert not any(q['sql'].lstrip().split()[0].upper() in {'INSERT','UPDATE','DELETE'} for q in queries)
    for i in range(30):
        kind=save_maintenance(data.owner,ServiceType,name=f'Type{i}')
        save_maintenance(data.owner,MaintenanceRule,item=data.item,service_type=kind,calendar_days=10,anchor_at=at())
    with CaptureQueriesContext(connection) as queries:
        assert len(maintenance_due(data.owner,at=at(2)))==31
    assert len(queries)<=12


def test_metric_display_preserves_exact_comparison(data):
    rule(data,distance_m=Decimal('1000.001'))
    facts(data,at(2),distance='1000.000'); initialized(data)
    metric=maintenance_due(data.owner,at=at(3))[0].metrics[0]
    assert metric.status=='unknown' and metric.remaining==Decimal('.001')
    assert metric.display_value==1 and metric.display_threshold==Decimal('1.000001')


@pytest.mark.django_db(transaction=True)
def test_snapshot_waits_for_owner_domain_mutation(data, monkeypatch):
    r=rule(data,calendar_days=10)
    locked, proceed, reader_started=Event(),Event(),Event()
    backend_pids={}
    from .services import maintenance_due as due_module
    original_lock=due_module._lock_owner
    def read_lock(actor):
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_backend_pid()')
            backend_pids['reader']=cursor.fetchone()[0]
        reader_started.set()
        return original_lock(actor)
    monkeypatch.setattr(due_module,'_lock_owner',read_lock)
    def writer():
        close_old_connections()
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute('SELECT pg_backend_pid()')
                    backend_pids['writer']=cursor.fetchone()[0]
                _lock_owner(data.owner); locked.set(); assert proceed.wait(15)
                save_maintenance(data.owner,MaintenanceRule,r.pk,calendar_days=1)
                save_maintenance(data.owner,ServiceEvent,item=data.item,service_type=data.kind,performed_at=at(3))
        finally:
            connection.close()
    def reader():
        close_old_connections()
        try:
            return maintenance_due(data.owner,at=at(3))[0]
        finally:
            connection.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        mutation=pool.submit(writer)
        try:
            assert locked.wait(5)
            reading=pool.submit(reader); assert reader_started.wait(5)
            deadline=monotonic()+5
            while True:
                with connection.cursor() as cursor:
                    cursor.execute('SELECT pg_blocking_pids(%s)', [backend_pids['reader']])
                    blockers=cursor.fetchone()[0]
                if backend_pids['writer'] in blockers:
                    break
                assert not reading.done(), 'Snapshot finished before blocking on the owner mutation'
                assert monotonic()<deadline, 'Snapshot never blocked on the owner mutation'
                sleep(.01)
            assert not reading.done()
        finally:
            proceed.set()
        mutation.result(timeout=5); result=reading.result(timeout=5)
    assert result.rule.calendar_days==1 and result.reference_at==at(3) and result.status=='current'


@pytest.mark.parametrize('days,status', [(9,'unknown'),(10,'due')])
def test_combined_calendar_and_unknown_usage_priorities(data, days, status):
    rule(data, calendar_days=10, moving_time_s=100)
    assert maintenance_due(data.owner,at=at()+timedelta(days=days))[0].status==status


def test_exact_baseline_only_completes_its_metric(data):
    rule(data,distance_m=1000,moving_time_s=100)
    baseline(data,event(data))
    result=maintenance_due(data.owner,at=at(3))[0]
    assert result.metrics[0].coverage=='complete'
    assert result.metrics[1].coverage=='partial' and result.status=='unknown'


def test_lifetime_acquisition_and_wrong_event_baselines_never_reset_rule(data):
    rule(data,distance_m=100)
    from .services.baselines import record_baseline
    record_baseline(data.owner,item=data.item,scope='lifetime',metric='distance_m',cut_at=at(3),value=Decimal('999'))
    from .services.ownership import update_inventory
    from .models import Item
    update_inventory(data.owner,Item,data.item.pk,acquisition_anchor_at=at())
    record_baseline(data.owner,item=data.item,scope='acquisition',metric='distance_m',cut_at=at(3),value=Decimal('999'))
    other_type=save_maintenance(data.owner,ServiceType,name='Other')
    other_event=save_maintenance(data.owner,ServiceEvent,item=data.item,service_type=other_type,performed_at=at(2))
    record_baseline(data.owner,item=data.item,scope='service',metric='distance_m',service_event=other_event,cut_at=at(3),value=Decimal('999'))
    assert maintenance_due(data.owner,at=at(3))[0].metrics[0].value==0


def test_service_baselines_are_independent_per_metric_and_latest_cut(data):
    rule(data,distance_m=200,moving_time_s=10,ride_count=3)
    ev=event(data)
    from .services.baselines import record_baseline
    record_baseline(data.owner,item=data.item,scope='service',metric='distance_m',service_event=ev,cut_at=at(2),value=Decimal('999'))
    record_baseline(data.owner,item=data.item,scope='service',metric='distance_m',service_event=ev,cut_at=at(3),value=Decimal('100'))
    record_baseline(data.owner,item=data.item,scope='service',metric='moving_time_s',service_event=ev,cut_at=at(4),value=Decimal('9'))
    facts(data,at(3),distance='50',moving='3');initialized(data)
    result=maintenance_due(data.owner,at=at(4))[0]
    assert [m.value for m in result.metrics]==[150,9,1]
    assert result.status=='unknown'


def test_exact_fractional_limit_and_cutoff_exclusion(data):
    rule(data,distance_m=Decimal('1000.000'))
    facts(data,at(2),distance='999.999');initialized(data)
    facts(data,at(3),distance='0.001')
    assert maintenance_due(data.owner,at=at(3))[0].status=='unknown'
    assert maintenance_due(data.owner,at=at(3)+timedelta(microseconds=1))[0].status=='due'


def test_invalid_cutoff_and_inactive_actor(data):
    from django.core.exceptions import PermissionDenied,ValidationError
    with pytest.raises(ValidationError):
        maintenance_due(data.owner,at=datetime(2026,1,1))
    data.owner.is_active=False;data.owner.save()
    with pytest.raises(PermissionDenied):
        maintenance_due(data.owner,at=at())


def test_future_baseline_event_and_other_target_event_do_not_supply_reference(data):
    rule(data,distance_m=100)
    ev=event(data)
    from .services.baselines import record_baseline
    record_baseline(data.owner,item=data.item,scope='service',metric='distance_m',service_event=ev,cut_at=at(5),value=Decimal('999'))
    save_maintenance(data.owner,ServiceEvent,item=data.item,service_type=data.kind,performed_at=at(6))
    save_maintenance(data.owner,ServiceEvent,bike=data.bike,service_type=data.kind,performed_at=at(3))
    result=maintenance_due(data.owner,at=at(4))[0]
    assert result.event==ev and result.metrics[0].value==0
    assert result.status=='unknown'
