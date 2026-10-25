from datetime import timedelta
from decimal import Decimal, localcontext

import pytest
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .models import Bike, Category, Item, ServiceEvent, ServiceType, UsageBaseline, UsageMaterializationState
from .services.baselines import record_baseline
from .services.installations import create_installation
from .services.maintenance import save_maintenance
from .services.ownership import InventoryNotFound, InventoryWriteError, create_inventory, update_inventory
from .services.rides import correct_ride, create_manual_ride, delete_ride
from .services.statistics import statistics
from .services.usage import rebuild_usage
from .services.usage_profiles import create_profile_history
from .statistics_forms import StatisticsForm
from .tests_maintenance import at, data
from .tests_maintenance_due import facts, initialized


def itemrow(report, target):
    return next(row for row in report.rows if row.target.pk == target.pk)


def ride(data, day, distance='1000.001', **kwargs):
    return create_manual_ride(data.owner, started_at=at(day), bike=data.bike, distance_m=Decimal(distance), **kwargs)


def reading(data, *, scope='lifetime', cut=3, value='10000.001', metric='distance_m', **kwargs):
    return record_baseline(data.owner, item=data.item, metric=metric, scope=scope, cut_at=at(cut), value=Decimal(value), source=kwargs.pop('source','manual'), **kwargs)


def test_two_bikes_alternating_saddles_and_rebuild_correction_delete(data):
    second = create_inventory(data.owner, Bike, name='B')
    saddle = create_inventory(data.owner, Item, category=data.item.category, name='Second saddle')
    for obj, bike, start, end in [(data.item,data.bike,1,3),(data.item,second,3,5),(data.item,data.bike,5,None),(saddle,second,1,3),(saddle,data.bike,3,5),(saddle,second,5,None)]:
        create_installation(data.owner, item=obj, bike=bike, started_at=at(start), ended_at=at(end) if end else None, slot='saddle')
    rides = []
    for day, bike in [(2,data.bike),(2,second),(4,data.bike),(4,second),(6,data.bike),(6,second)]:
        rides.append(create_manual_ride(data.owner, started_at=at(day), bike=bike, distance_m=Decimal('1000.001'), moving_time_s=Decimal('3600.001')))
    rebuild_usage(data.owner)
    report = statistics(data.owner, started_from=at(1), started_to=at(7))
    row = itemrow(report,data.item)
    assert row.observed[0].value == Decimal('3000.003')
    assert row.observed[1].value == Decimal('10800.003')
    assert row.observed[2].value == 3
    assert [b.metrics[0].value for b in row.installations] == [Decimal('1000.001')]*3
    assert {b.label:b.metrics[2].value for b in row.bikes} == {'bike':2,'B':1}
    assert itemrow(report,data.bike).observed[2].value == 3
    correct_ride(data.owner, rides[0].pk, bike=second, distance_m=Decimal('123.456'))
    delete_ride(data.owner, rides[4].pk)
    rebuild_usage(data.owner)
    report = statistics(data.owner, started_to=at(7))
    assert itemrow(report,data.item).observed[0].value == Decimal('1000.001')
    assert itemrow(report,saddle).observed[0].value == Decimal('3123.459')
    assert itemrow(report,data.bike).observed[2].value == 1


def test_shared_gear_is_deduplicated_and_snapshot_bike_not_current_mount(data):
    second = create_inventory(data.owner,Bike,name='B')
    shoe = create_inventory(data.owner,Item,category=data.item.category,name='Shoes')
    create_profile_history(data.owner,name='Shared gear',items=[data.item,shoe],started_at=at())
    create_installation(data.owner,item=data.item,bike=data.bike,started_at=at())
    ride(data,2)
    create_manual_ride(data.owner,started_at=at(3),bike=second,distance_m=Decimal('2000'))
    rebuild_usage(data.owner)
    report=statistics(data.owner,started_to=at(4))
    for obj in (data.item,shoe):
        row=itemrow(report,obj)
        assert row.observed[2].value == 2
        assert {b.label:b.metrics[2].value for b in row.bikes} == {'bike':1,'B':1}
    assert itemrow(report,data.item).installations[0].metrics[2].value == 1
    filtered=statistics(data.owner,started_from=at(3),started_to=at(4),bike=second,category=data.item.category)
    assert {r.target.pk for r in filtered.rows} == {data.item.pk,shoe.pk}
    assert itemrow(filtered,data.item).observed[0].value == 2000


@pytest.mark.parametrize('initialized_state',[False,True])
def test_unknown_null_metrics_timer_and_context(data,initialized_state):
    facts(data,at(2),distance=None,moving=None,timer='9900')
    facts(data,None)
    facts(data,at(3),bike=False)
    if initialized_state: initialized(data)
    report=statistics(data.owner,started_from=at(2),started_to=at(3))
    row=itemrow(report,data.item)
    assert row.observed[0].value is None and row.observed[1].value is None
    assert row.observed[2].value == (1 if initialized_state else None)
    assert itemrow(report,data.bike).observed[1].value is None
    assert report.pending_started_rides==1 and report.unknown_bike_rides==0
    assert statistics(data.owner,started_to=at(4)).unknown_bike_rides==1
    assert not row.observed[0].complete


def test_empty_owner_observed_zero_is_not_lifetime_total(data):
    row=itemrow(statistics(data.owner,started_to=at(3)),data.item)
    assert row.observed[0].value==0
    assert row.totals[0].metrics[0].value is None
    assert not row.observed[0].complete


@pytest.mark.parametrize('cut',[2,4,5])
def test_baseline_total_separate_from_filtered_period_and_bike(data,cut):
    facts(data,at(1),distance='500')
    facts(data,at(3),distance='1000')
    facts(data,at(4),distance='2000')
    initialized(data)
    b=reading(data,cut=cut)
    row=itemrow(statistics(data.owner,started_from=at(3),started_to=at(5),bike=data.bike,item=data.item),data.item)
    assert row.observed[0].value==3000
    assert row.bikes[0].metrics[0].value==3000
    total=row.totals[0].metrics[0]
    assert total.value==b.value+({2:3000,4:2000,5:0}[cut])
    assert total.complete==(cut==5)
    assert total.baseline==b


def test_totals_preserve_known_baseline_with_missing_contributions(data):
    facts(data,at(3),distance=None)
    initialized(data)
    b=reading(data,cut=2)
    total=itemrow(statistics(data.owner,started_to=at(4)),data.item).totals[0].metrics[0]
    assert total.value==b.value and total.missing_values==1 and not total.complete


def test_uninitialized_baseline_exact_cut_only_is_known(data):
    facts(data,at(2),distance='99999')
    reading(data,cut=3)
    row=itemrow(statistics(data.owner,started_to=at(3)),data.item)
    assert row.observed[0].value is None
    assert row.totals[0].metrics[0].value==Decimal('10000.001')
    assert row.totals[0].metrics[0].complete
    assert itemrow(statistics(data.owner,started_to=at(4)),data.item).totals[0].metrics[0].value is None


def test_same_type_intervention_periods_and_independent_latest(data):
    replace=save_maintenance(data.owner,ServiceType,name='Replace')
    ev1=save_maintenance(data.owner,ServiceEvent,item=data.item,service_type=data.kind,performed_at=at(2))
    ev2=save_maintenance(data.owner,ServiceEvent,item=data.item,service_type=data.kind,performed_at=at(4))
    ev3=save_maintenance(data.owner,ServiceEvent,item=data.item,service_type=replace,performed_at=at(3))
    save_maintenance(data.owner,ServiceEvent,bike=data.bike,service_type=data.kind,performed_at=at(3))
    save_maintenance(data.owner,ServiceEvent,item=data.item,service_type=data.kind,performed_at=at(9))
    for day in (2,3,4,5): facts(data,at(day),distance='100')
    initialized(data)
    reading(data,scope='service',cut=3,value='250',service_event=ev1)
    reading(data,scope='service',cut=4,value='9999',service_event=ev2)
    row=itemrow(statistics(data.owner,started_from=at(5),started_to=at(6)),data.item)
    blocks={b.reference.pk:b for b in row.interventions}
    assert blocks[ev1.pk].end==at(4) and blocks[ev1.pk].metrics[0].value==350
    assert blocks[ev2.pk].metrics[0].value==10199
    assert blocks[ev3.pk].metrics[0].value==300
    latest={b.reference.service_type_id:b.reference.pk for b in row.totals if b.reference}
    assert latest=={data.kind.pk:ev2.pk,replace.pk:ev3.pk}


@pytest.mark.parametrize('distance,estimated,expected_reason', [('0',False,'Distancia cero'),('2000',True,'Lectura estimada'),('2000',False,'')])
def test_cost_per_km_only_complete_matching_acquisition_scope(data,distance,estimated,expected_reason):
    update_inventory(data.owner,Item,data.item.pk,acquisition_anchor_at=at(),purchase_amount=Decimal('20'),purchase_currency='EUR')
    data.item.refresh_from_db()
    reading(data,scope='acquisition',cut=5,value=distance,is_estimated=estimated)
    for currency,amount in [('EUR','10.00'),('USD','7.00')]:
        save_maintenance(data.owner,ServiceEvent,item=data.item,service_type=data.kind,performed_at=at(2),amount=Decimal(amount),currency=currency)
    row=itemrow(statistics(data.owner,started_from=at(4),started_to=at(5),item=data.item,bike=data.bike),data.item)
    assert row.observed[0].value==0
    costs={c.currency:c for c in row.costs}
    assert costs['EUR'].amount==30 and costs['USD'].amount==7
    assert all(c.reason==expected_reason for c in costs.values())
    assert costs['EUR'].per_km==(Decimal('15') if not expected_reason else None)
    assert costs['USD'].per_km==(Decimal('3.5') if not expected_reason else None)
    assert all('todas las bicis' in c.scope for c in costs.values())


def test_partial_costs_and_unknown_money_do_not_create_ratios(data):
    facts(data,at(2),distance='2000')
    initialized(data)
    save_maintenance(data.owner,ServiceEvent,item=data.item,service_type=data.kind,performed_at=at(2),amount=Decimal('0'),currency='EUR')
    save_maintenance(data.owner,ServiceEvent,item=data.item,service_type=data.kind,performed_at=at(3))
    row=itemrow(statistics(data.owner,started_to=at(4)),data.item)
    assert row.costs[0].amount==0 and row.costs[0].per_km is None
    assert row.costs[0].reason=='Costes sin importe o moneda' and row.unknown_costs==1


def test_decimal_aggregation_exact_under_small_external_context(data):
    for _ in range(12): facts(data,at(2),distance='9999999999999999.999',moving='9999999999999999.999')
    initialized(data)
    with localcontext() as context:
        context.prec=6
        row=itemrow(statistics(data.owner,started_to=at(3)),data.item)
    assert row.observed[0].value==Decimal('119999999999999999.988')
    assert row.observed[1].value==Decimal('119999999999999999.988')


@pytest.mark.parametrize('field,model',[('bike',Bike),('category',Category),('item',Item)])
def test_private_forged_foreign_filter_404_without_leak(data,field,model):
    if model is Item:
        cat=create_inventory(data.other,Category,name='SECRET')
        obj=create_inventory(data.other,Item,category=cat,name='SECRET')
    else: obj=create_inventory(data.other,model,name='SECRET')
    with pytest.raises(InventoryNotFound): statistics(data.owner,**{field:obj.pk})
    client=Client();client.force_login(data.owner)
    assert client.get(reverse('garage:statistics'),{field:obj.pk,'time_zone':'UTC'}).status_code==404
    assert client.get(reverse('garage:statistics'),{field:'malformed','time_zone':'UTC'}).status_code==404


@pytest.mark.parametrize('local',['2026-03-29T02:30:00','2026-10-25T02:30:00'])
def test_statistics_filters_reject_dst_invalid_local_times(data,local):
    form=StatisticsForm({'time_zone':'Europe/Madrid','started_from':local},user=data.owner)
    assert not form.is_valid() and 'started_from' in form.errors


def test_form_microseconds_dates_utc_bounds_and_invalid_interval(data):
    form=StatisticsForm({'time_zone':'Europe/Madrid','started_from':'2026-01-02','started_to':'2026-01-03T01:00:00.123456'},user=data.owner)
    assert form.is_valid(),form.errors
    assert form.cleaned_data['started_from']==at(2)-timedelta(hours=1)
    assert form.cleaned_data['started_to']==at(3)+timedelta(microseconds=123456)
    with pytest.raises(InventoryWriteError): statistics(data.owner,started_from=at(3),started_to=at(3))
    with pytest.raises(InventoryWriteError): statistics(data.owner,started_to=at(3).replace(tzinfo=None))


def test_readonly_get_auth_methods_render_and_query_budget(data):
    create_profile_history(data.owner,name='Shared gear',items=[data.item],started_at=at())
    ride(data,2,moving_time_s=Decimal('3600'))
    client=Client()
    assert client.get(reverse('garage:statistics')).status_code==302
    client.force_login(data.owner)
    with CaptureQueriesContext(connection) as queries:
        response=client.get(reverse('garage:statistics'),{'time_zone':'UTC','started_from':'2026-01-01','started_to':'2026-01-03'})
    assert response.status_code==200
    assert b'Horas en movimiento' in response.content and b'Estad' in response.content
    assert 'no-store' in response.headers['Cache-Control']
    assert not any(q['sql'].lstrip().split()[0].upper() in {'INSERT','UPDATE','DELETE'} for q in queries)
    assert client.post(reverse('garage:statistics')).status_code==405
    # More targets do not add queries: aggregation and reading selection are in Python.
    for i in range(15): create_inventory(data.owner,Item,category=data.item.category,name=f'Extra {i}')
    with CaptureQueriesContext(connection) as queries:
        report=statistics(data.owner,started_to=at(3))
    assert len(report.rows)==17 and len(queries)<=14


def test_microsecond_period_half_open_and_future_baseline_costs_excluded(data):
    begin=at(3)+timedelta(microseconds=123456)
    end=begin+timedelta(microseconds=2)
    for instant in (begin-timedelta(microseconds=1),begin,begin+timedelta(microseconds=1),end):
        facts(data,instant,distance='0.001')
    initialized(data)
    reading(data,cut=4,value='9000')
    save_maintenance(data.owner,ServiceEvent,item=data.item,service_type=data.kind,performed_at=end,amount=Decimal('99'),currency='EUR')
    row=itemrow(statistics(data.owner,started_from=begin,started_to=end),data.item)
    assert row.observed[0].value==Decimal('0.002') and row.observed[2].value==2
    assert row.totals[0].metrics[0].value is None and not row.costs


def test_acquisition_costs_exclude_prior_events_and_unknown_purchase_blocks_ratio(data):
    update_inventory(data.owner,Item,data.item.pk,acquisition_anchor_at=at(3))
    data.item.refresh_from_db()
    reading(data,scope='acquisition',cut=5,value='2000')
    save_maintenance(data.owner,ServiceEvent,item=data.item,service_type=data.kind,performed_at=at(2),amount=Decimal('999'),currency='EUR')
    save_maintenance(data.owner,ServiceEvent,item=data.item,service_type=data.kind,performed_at=at(4),amount=Decimal('10'),currency='EUR')
    row=itemrow(statistics(data.owner,started_from=at(3),started_to=at(5)),data.item)
    assert len(row.costs)==2 and all(c.amount==10 for c in row.costs)
    assert row.costs[1].per_km is None and row.costs[1].reason=='Costes sin importe o moneda'


def test_baseline_source_estimated_and_scope_visible_html(data):
    reading(data,cut=3,is_estimated=True,source='manual_garmin_reading')
    client=Client();client.force_login(data.owner)
    response=client.get(reverse('garage:statistics'),{'time_zone':'UTC','started_to':'2026-01-03'})
    assert response.status_code==200
    text=response.content.decode()
    assert 'manual_garmin_reading' in text and 'Lectura estimada' in text
    assert 'todas las bicis' in text and 'no se reparte entre períodos ni bicis' in text


def test_uninitialized_distribution_does_not_expose_stale_attribution(data):
    facts(data,at(2))
    row=itemrow(statistics(data.owner,started_to=at(3)),data.item)
    assert row.bikes==() and row.observed[2].value is None


def test_readonly_empty_and_baseline_only_queries_do_not_create_state(data):
    reading(data,cut=3)
    before=UsageMaterializationState.objects.filter(owner=data.owner).count()
    with CaptureQueriesContext(connection) as queries:
        row=itemrow(statistics(data.owner,started_from=at(2),started_to=at(3),item=data.item),data.item)
    assert row.bikes==() and row.totals[0].metrics[0].complete
    assert UsageMaterializationState.objects.filter(owner=data.owner).count()==before
    assert not any(q['sql'].lstrip().split()[0].upper() in {'INSERT','UPDATE','DELETE'} for q in queries)


def test_empty_service_interval_is_complete_zero_without_initialization(data):
    facts(data,at(2))
    save_maintenance(data.owner,ServiceEvent,item=data.item,service_type=data.kind,performed_at=at(3))
    row=itemrow(statistics(data.owner,started_to=at(3)),data.item)
    assert all(m.value==0 and m.complete for m in row.interventions[0].metrics)
    assert all(m.value==0 and m.complete for m in row.totals[-1].metrics)


def test_unknown_cost_entries_deduplicated_across_scopes(data):
    update_inventory(data.owner,Item,data.item.pk,acquisition_anchor_at=at(),purchase_amount=Decimal('20'),purchase_currency='EUR')
    save_maintenance(data.owner,ServiceEvent,item=data.item,service_type=data.kind,performed_at=at(2))
    row=itemrow(statistics(data.owner,started_to=at(3)),data.item)
    assert row.unknown_costs==1


def test_bike_acquisition_costs_use_direct_rides_no_component_sums(data):
    update_inventory(data.owner,Bike,data.bike.pk,acquisition_anchor_at=at(2),purchase_amount=Decimal('250'),purchase_currency='EUR')
    facts(data,at(1),distance='99999')
    facts(data,at(2),distance='2000')
    save_maintenance(data.owner,ServiceEvent,bike=data.bike,service_type=data.kind,performed_at=at(2),amount=Decimal('10'),currency='EUR')
    row=itemrow(statistics(data.owner,started_from=at(3),started_to=at(4)),data.bike)
    assert row.observed[0].value==0 and row.totals[0].metrics[0].value==2000
    assert row.costs[0].amount==260 and row.costs[0].per_km is None
    assert 'Histórico parcial' in row.costs[0].reason


def test_metric_specific_latest_baselines_do_not_cross_scopes(data):
    facts(data,at(3),distance='100',moving='3600')
    initialized(data)
    reading(data,cut=2,value='1000')
    reading(data,cut=3,value='2000')
    reading(data,cut=2,value='7200',metric='moving_time_s')
    reading(data,cut=4,value='999999',metric='moving_time_s')
    row=itemrow(statistics(data.owner,started_to=at(3)+timedelta(hours=1)),data.item)
    assert row.totals[0].metrics[0].value==2100
    assert row.totals[0].metrics[1].value==10800
    assert row.totals[0].metrics[2].value is None
    assert all(m.value is None for m in row.totals[1].metrics)
