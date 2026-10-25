from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from threading import Barrier
from types import SimpleNamespace

import pytest
from django.contrib.admin.sites import site
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import Client, RequestFactory
from django.urls import reverse

from .maintenance_forms import MaintenanceRuleForm, ServiceEventForm
from .models import Bike, Category, Item, MaintenanceRule, ServiceEvent, ServiceType, UsageBaseline
from .services.baselines import UsageObservation, latest_baseline, record_baseline, summarize_usage, update_baseline
from .services.maintenance import delete_maintenance, maintenance_reference, save_maintenance
from .services.ownership import InventoryNotFound, InventoryWriteError, create_inventory


def at(day=1):
    return datetime(2026, 1, day, tzinfo=timezone.utc)


@pytest.fixture
def data(db, django_user_model):
    owner = django_user_model.objects.create_user(username='maintenance')
    other = django_user_model.objects.create_user(username='foreign')
    category = create_inventory(owner, Category, name='parts')
    item = create_inventory(owner, Item, category=category, name='chain', acquired_on=at().date())
    bike = create_inventory(owner, Bike, name='bike')
    kind = save_maintenance(owner, ServiceType, name='Lubricate')
    foreign = save_maintenance(other, ServiceType, name='SECRET')
    return SimpleNamespace(owner=owner, other=other, item=item, bike=bike, kind=kind, foreign=foreign)


def event(data, **kwargs):
    return save_maintenance(data.owner, ServiceEvent, item=data.item, service_type=data.kind, performed_at=at(2), **kwargs)


def baseline(data, ev, **kwargs):
    return record_baseline(data.owner, item=data.item, metric='distance_m', scope='service', service_event=ev, cut_at=at(3), value=Decimal('123.456'), **kwargs)


@pytest.mark.parametrize('name', [None, '', '   '])
@pytest.mark.parametrize('operation', ['model', 'create', 'update'])
def test_service_type_empty_name_is_validation_error_without_writes(data, name, operation):
    before = list(ServiceType.objects.order_by('id').values('id', 'owner_id', 'name', 'notes'))
    error_class = ValidationError if operation == 'model' else InventoryWriteError
    with pytest.raises(error_class) as error:
        if operation == 'model':
            ServiceType(owner=data.owner, name=name).full_clean()
        else:
            resource_id = data.kind.pk if operation == 'update' else None
            save_maintenance(data.owner, ServiceType, resource_id, name=name, notes='rejected change')
    assert 'name' in error.value.message_dict
    assert list(ServiceType.objects.order_by('id').values('id', 'owner_id', 'name', 'notes')) == before


@pytest.mark.parametrize('field,value', [('distance_m','0'), ('distance_m','-1'), ('moving_time_s','0.0001'), ('moving_time_s',1.5), ('ride_count',True), ('ride_count',Decimal('1.1')), ('calendar_days',0)])
def test_thresholds_reject_invalid(data, field, value):
    with pytest.raises(ValidationError):
        save_maintenance(data.owner, MaintenanceRule, item=data.item, service_type=data.kind, **{field:value})


def test_thresholds_independent_and_explicit_reference(data):
    rule = save_maintenance(data.owner, MaintenanceRule, item=data.item, service_type=data.kind, distance_m=Decimal('123.456'), moving_time_s=Decimal('1.001'), ride_count=5, calendar_days=30)
    assert maintenance_reference(data.owner, rule.pk, at=at(10)) == (None,None)
    rule = save_maintenance(data.owner, MaintenanceRule, rule.pk, anchor_at=at())
    assert maintenance_reference(data.owner, rule.pk, at=at(10)) == (None,at())
    replace = save_maintenance(data.owner, ServiceType, name='Replace')
    save_maintenance(data.owner, ServiceEvent, item=data.item, service_type=replace, performed_at=at(9))
    ev = event(data)
    save_maintenance(data.owner, ServiceEvent, bike=data.bike, service_type=data.kind, performed_at=at(8))
    save_maintenance(data.owner, ServiceEvent, item=data.item, service_type=data.kind, performed_at=at(15))
    assert maintenance_reference(data.owner, rule.pk, at=at(10)) == (ev,at(2))
    assert maintenance_reference(data.owner, rule.pk, at=at(1)) == (None,at())


@pytest.mark.parametrize('values', [{}, {'item':'self','bike':'self'}])
def test_event_xor_sql(data, values):
    values = {key:getattr(data,key) for key in values}
    with pytest.raises(IntegrityError), transaction.atomic():
        ServiceEvent.objects.create(owner=data.owner, service_type=data.kind, performed_at=at(), **values)


@pytest.mark.parametrize('field,value', [('distance_m',0),('moving_time_s',-1),('ride_count',0),('calendar_days',0)])
def test_rule_positive_sql(data, field, value):
    with pytest.raises(IntegrityError), transaction.atomic():
        MaintenanceRule.objects.create(owner=data.owner, item=data.item, service_type=data.kind, **{field:value})


def test_rule_empty_and_unique_sql(data):
    with pytest.raises(IntegrityError), transaction.atomic():
        MaintenanceRule.objects.create(owner=data.owner, item=data.item, service_type=data.kind)
    MaintenanceRule.objects.create(owner=data.owner,item=data.item,service_type=data.kind,calendar_days=30)
    with pytest.raises(IntegrityError), transaction.atomic():
        MaintenanceRule.objects.create(owner=data.owner,item=data.item,service_type=data.kind,distance_m=1)


def test_owner_and_catalog(data):
    save_maintenance(data.other, ServiceType, name='Lubricate')
    with pytest.raises(ValidationError):
        save_maintenance(data.owner, ServiceType, name=' lubricate ')
    with pytest.raises(ValidationError):
        save_maintenance(data.owner, ServiceEvent, item=data.item, service_type=data.foreign, performed_at=at())
    ev=event(data)
    with pytest.raises(InventoryNotFound):
        save_maintenance(data.other, ServiceEvent, ev.pk, notes='attack')
    with pytest.raises(ValidationError):
        save_maintenance(data.owner, ServiceEvent, owner_id=data.other.pk)


@pytest.mark.parametrize('amount,currency', [(1.5,'EUR'),(True,'EUR'),(Decimal('1.001'),'EUR'),(Decimal('NaN'),'EUR'),(Decimal('Infinity'),'EUR'),(Decimal('-1'),'EUR'),(Decimal('1'),None),(None,'EUR'),(Decimal('1'),'ZZZ')])
def test_money_rejects(data,amount,currency):
    with pytest.raises(ValidationError):
        event(data,amount=amount,currency=currency)


def test_money_precision_no_conversion(data):
    a=event(data,amount=Decimal('12.34'),currency='EUR')
    b=event(data,amount=Decimal('0.01'),currency='USD')
    a.refresh_from_db();b.refresh_from_db()
    assert (a.amount,a.currency,b.amount,b.currency)==(Decimal('12.34'),'EUR',Decimal('0.01'),'USD')


def test_service_baselines_isolated_and_mutation_guard(data):
    a=event(data);b=event(data)
    first=baseline(data,a);second=baseline(data,b)
    assert first.pk!=second.pk
    assert baseline(data,a).pk==first.pk
    with pytest.raises(ValidationError):
        save_maintenance(data.owner,ServiceEvent,a.pk,performed_at=at(4))
    with pytest.raises(ValidationError):
        record_baseline(data.owner,item=data.item,metric='distance_m',scope='service',service_event=a,cut_at=at(),value=0)
    with pytest.raises(IntegrityError),transaction.atomic():
        UsageBaseline.objects.create(owner=data.owner,item=data.item,metric='distance_m',scope='lifetime',service_event=a,cut_at=at(),value=0)


def test_service_baseline_collision_is_domain_error_and_atomic(data):
    ev = event(data)
    first = baseline(data, ev)
    second = record_baseline(data.owner, item=data.item, metric='distance_m', scope='service',
                            service_event=ev, cut_at=at(4), value=Decimal('2.001'))
    with pytest.raises(ValidationError) as error:
        update_baseline(data.owner, second.pk, cut_at=first.cut_at, value=Decimal('9.001'), notes='discard')
    assert error.value.error_dict['cut_at'][0].code == 'baseline_conflict'
    second.refresh_from_db()
    assert (second.cut_at, second.value, second.notes) == (at(4), Decimal('2.001'), '')
    assert not connection.needs_rollback
    with pytest.raises(IntegrityError), transaction.atomic():
        UsageBaseline.objects.create(owner=data.owner, item=data.item, metric='distance_m', scope='service',
                                     service_event=ev, cut_at=first.cut_at, value=0)


@pytest.mark.parametrize('reference', ['absent', 'foreign', 'other_item', 'bike'])
def test_service_baseline_requires_same_owned_item_event(data, reference):
    own_second = create_inventory(data.owner, Item, name='other chain', category=data.item.category)
    foreign_category = create_inventory(data.other, Category, name='foreign parts')
    foreign_item = create_inventory(data.other, Item, name='foreign chain', category=foreign_category)
    references = {
        'absent': None,
        'foreign': save_maintenance(data.other, ServiceEvent, item=foreign_item,
                                    service_type=data.foreign, performed_at=at()),
        'other_item': save_maintenance(data.owner, ServiceEvent, item=own_second,
                                      service_type=data.kind, performed_at=at()),
        'bike': save_maintenance(data.owner, ServiceEvent, bike=data.bike,
                                service_type=data.kind, performed_at=at()),
    }
    with pytest.raises(ValidationError):
        record_baseline(data.owner, item=data.item, metric='distance_m', scope='service',
                        service_event=references[reference], cut_at=at(3), value=0)
    assert not UsageBaseline.objects.exists()


@pytest.mark.parametrize('change', ['item', 'bike', 'service_type', 'performed_at'])
def test_event_reference_changes_rejected_until_readings_removed(data, change):
    ev = event(data)
    reading = baseline(data, ev)
    values = {
        'item': {'item': create_inventory(data.owner, Item, name='chain 2', category=data.item.category)},
        'bike': {'item': None, 'bike': data.bike},
        'service_type': {'service_type': save_maintenance(data.owner, ServiceType, name='Replace')},
        'performed_at': {'performed_at': at(4)},
    }[change]
    with pytest.raises(ValidationError):
        save_maintenance(data.owner, ServiceEvent, ev.pk, **values)
    ev.refresh_from_db()
    assert (ev.item_id, ev.bike_id, ev.service_type_id, ev.performed_at) == (data.item.pk, None, data.kind.pk, at(2))
    assert save_maintenance(data.owner, ServiceEvent, ev.pk, notes='Correction', amount=Decimal('0.00'), currency='EUR').notes == 'Correction'
    with pytest.raises(ValidationError):
        delete_maintenance(data.owner, ServiceEvent, ev.pk)
    reading.delete()
    assert save_maintenance(data.owner, ServiceEvent, ev.pk, **values)


def test_service_reading_cut_equal_event_and_before_cutoff(data):
    ev = event(data)
    reading = record_baseline(data.owner, item=data.item, metric='moving_time_s', scope='service',
                              service_event=ev, cut_at=at(2), value=Decimal('0.000'))
    assert latest_baseline(data.owner, data.item.pk, metric='moving_time_s', scope='service',
                           service_event=ev, at=at()) is None
    before = summarize_usage(data.owner, data.item.pk, metric='moving_time_s', scope='service', service_event=ev, at=at())
    assert before.total is None and before.observed is None
    exact = summarize_usage(data.owner, data.item.pk, metric='moving_time_s', scope='service', service_event=ev, at=at(2))
    assert exact.total == 0 and exact.coverage_complete and exact.baseline == reading


def test_used_item_cannot_offer_or_post_intervention_scope(data, client):
    from .web_forms import UsedItemWebForm
    form = UsedItemWebForm(user=data.owner)
    for metric in ('distance', 'time', 'rides'):
        assert {value for value, _ in form.fields[f'previous_{metric}_scope'].choices} == {'lifetime', 'acquisition'}
    client.force_login(data.owner)
    response = client.post(reverse('garage:item-used-create'), {
        'name': 'forged used item', 'category': data.item.category_id, 'time_zone': 'UTC',
        'previous_distance': '1', 'previous_distance_cut': '2026-01-03T00:00',
        'previous_distance_scope': 'service', 'reading_source': 'manual',
    })
    assert response.status_code == 200 and 'previous_distance_scope' in response.context['form'].errors
    assert not Item.objects.filter(name='forged used item').exists() and not UsageBaseline.objects.exists()


def test_service_usage_boundaries_unknown_and_lifetime_not_reused(data):
    ev=event(data)
    record_baseline(data.owner,item=data.item,metric='distance_m',scope='lifetime',cut_at=at(3),value=Decimal('10000'))
    obs=[UsageObservation(data.owner.pk,data.item.pk,'distance_m',at(day),Decimal(value)) for day,value in [(1,'90'),(2,'1.001'),(3,'2.002'),(4,'99')]]
    args=dict(metric='distance_m',scope='service',service_event=ev,at=at(4),observations=obs)
    unknown=summarize_usage(data.owner,data.item.pk,**args)
    assert unknown.total is None and unknown.observed==Decimal('3.003')
    known=summarize_usage(data.owner,data.item.pk,**args,observations_complete=True)
    assert known.total==Decimal('3.003') and known.coverage_complete
    baseline(data,ev)
    read=summarize_usage(data.owner,data.item.pk,**args)
    assert read.total==Decimal('125.458') and not read.coverage_complete
    hours=summarize_usage(data.owner,data.item.pk,metric='moving_time_s',scope='service',service_event=ev,at=at(4))
    assert hours.total is None


@pytest.mark.parametrize('wall', ['2026-03-29T02:30','2026-10-25T02:30'])
def test_form_dst(data,wall):
    form=ServiceEventForm({'item':data.item.pk,'service_type':data.kind.pk,'performed_at':wall,'time_zone':'Europe/Madrid'},user=data.owner)
    assert not form.is_valid() and 'performed_at' in form.errors


@pytest.mark.parametrize('model,form_class,field', [(ServiceEvent, ServiceEventForm, 'performed_at'),
                                                 (MaintenanceRule, MaintenanceRuleForm, 'anchor_at')])
def test_edit_form_preserves_microseconds_and_explicit_units(data, model, form_class, field):
    instant = at(2).replace(microsecond=123456)
    values = {field: instant, 'item': data.item, 'service_type': data.kind}
    if model is MaintenanceRule:
        values.update(distance_m=Decimal('123.456'), moving_time_s=Decimal('1.001'))
    obj = save_maintenance(data.owner, model, **values)
    shown = form_class(user=data.owner, instance=obj)
    assert '2026-01-02T00:00:00.123456' in str(shown[field])
    payload = {'item': data.item.pk, 'service_type': data.kind.pk, field: '2026-01-02T00:00:00.123456', 'time_zone': 'UTC'}
    if model is MaintenanceRule:
        assert shown.fields['distance_m'].label == 'Distancia (metros)'
        assert shown.fields['moving_time_s'].label == 'Tiempo en movimiento (segundos)'
        payload.update(distance_m='123.456', moving_time_s='1.001')
    edit = form_class(payload, user=data.owner, instance=obj)
    assert edit.is_valid(), edit.errors
    saved = edit.save();saved.refresh_from_db()
    assert getattr(saved, field) == instant
    if model is MaintenanceRule:
        assert (saved.distance_m, saved.moving_time_s) == (Decimal('123.456'), Decimal('1.001'))


def test_service_reading_web_selector_and_save(data, client):
    ev = event(data)
    client.force_login(data.owner)
    url = reverse('garage:baseline-create', args=[data.item.pk])
    shown = client.get(url)
    assert shown.status_code == 200
    labels = str(shown.context['form']['service_event'])
    assert 'Lubricate: chain' in labels and '2026-01-02' in labels
    payload = {'metric': 'moving_time_s', 'scope': 'service', 'service_event': ev.pk,
               'cut_at': '2026-01-03T00:00:00.123456', 'time_zone': 'UTC', 'value': '1.001', 'source': 'manual'}
    assert client.post(url, payload).status_code == 302
    reading = UsageBaseline.objects.get()
    assert reading.service_event_id == ev.pk and reading.value == Decimal('1.001')
    assert reading.cut_at.microsecond == 123456


def test_form_and_private_ui(data,client):
    payload={'item':data.item.pk,'service_type':data.kind.pk,'performed_at':'2026-01-02T12:30','time_zone':'Europe/Madrid','amount':'12.34','currency':'EUR'}
    form=ServiceEventForm(payload,user=data.owner)
    assert form.is_valid(),form.errors
    ev=form.save();assert ev.performed_at.hour==11
    url=reverse('garage:service-event-detail',args=[ev.pk])
    assert client.get(url).status_code==302
    client.force_login(data.other);assert client.get(url).status_code==404
    client.force_login(data.owner)
    detail = client.get(url)
    assert detail.status_code == 200 and b'Lubricate' in detail.content and b'12,34' in detail.content and b'EUR' in detail.content
    listing = client.get(reverse('garage:maintenance'))
    assert listing.status_code == 200 and b'Lubricate' in listing.content and b'SECRET' not in listing.content
    secured=Client(enforce_csrf_checks=True);secured.force_login(data.owner)
    assert secured.post(reverse('garage:service-event-create'),payload).status_code==403
    assert client.get(reverse('garage:service-event-delete',args=[ev.pk])).status_code==405


def test_admin_owner(data):
    request=RequestFactory().get('/admin/');request.user=data.owner
    admin=site._registry[ServiceType]
    assert list(admin.get_queryset(request))==[data.kind]
    request.user=data.other
    assert not admin.has_change_permission(request,data.kind)


@pytest.mark.django_db(transaction=True)
def test_concurrent_service_readings_upsert(django_user_model):
    owner=django_user_model.objects.create_user(username='race-service')
    cat=create_inventory(owner,Category,name='parts');item=create_inventory(owner,Item,name='chain',category=cat)
    kind=save_maintenance(owner,ServiceType,name='Lubricate')
    ev=save_maintenance(owner,ServiceEvent,item=item,service_type=kind,performed_at=at())
    barrier=Barrier(2)
    def write():
        close_old_connections()
        try:
            actor=django_user_model.objects.get(pk=owner.pk);barrier.wait(timeout=10)
            return record_baseline(actor,item=item.pk,metric='distance_m',scope='service',service_event=ev.pk,cut_at=at(2),value=Decimal('1.001')).pk
        finally:close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(write) for _ in range(2)];ids=[f.result(timeout=20) for f in futures]
    assert ids[0]==ids[1] and UsageBaseline.objects.count()==1


@pytest.mark.django_db(transaction=True)
def test_event_photo_lifecycle_owner_quota_and_cleanup(django_user_model,monkeypatch):
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.test import override_settings
    from .services import photos
    from .models import Photo, PhotoStorageObject
    from .tests_photos_domain import MemoryPhotoStorage, image_bytes
    owner=django_user_model.objects.create_user(username='event-photo')
    other=django_user_model.objects.create_user(username='photo-other')
    bike=create_inventory(owner,Bike,name='bike')
    kind=save_maintenance(owner,ServiceType,name='Inspect')
    ev=save_maintenance(owner,ServiceEvent,bike=bike,service_type=kind,performed_at=at())
    backend=MemoryPhotoStorage();monkeypatch.setattr(photos,'get_photo_storage',lambda:backend)
    client=Client();client.force_login(owner)
    url=reverse('garage:service-event-photo-create',args=[ev.pk])
    assert client.get(url).status_code==200
    response=client.post(url,{'photo':SimpleUploadedFile('secret.png',image_bytes())})
    assert response.status_code==302
    photo=Photo.objects.get();assert photo.service_event_id==ev.pk and photo.item_id is None and photo.bike_id is None
    assert client.get(reverse('garage:service-event-detail',args=[ev.pk])).status_code==200
    with override_settings(GARAGE_PHOTO_OWNER_QUOTA_BYTES=1):
        with pytest.raises(ValidationError):
            photos.upload_photo(owner,target_model=ServiceEvent,target_id=ev.pk,source=image_bytes(),storage=backend)
    client.force_login(other);backend.calls.clear()
    assert client.post(url,{'photo':SimpleUploadedFile('bad.png',image_bytes())}).status_code==404
    assert client.get(reverse('garage:photo-content',args=[photo.pk])).status_code==404
    assert backend.calls==[]
    alternate = create_inventory(owner, Bike, name='alternate')
    with pytest.raises(ValidationError):
        save_maintenance(owner, ServiceEvent, ev.pk, bike=alternate)
    ev.refresh_from_db();photo.refresh_from_db()
    assert ev.bike_id == bike.pk and photo.service_event_id == ev.pk
    with pytest.raises(ValidationError):
        delete_maintenance(owner, ServiceEvent, ev.pk)
    with pytest.raises(ValidationError):
        save_maintenance(owner,ServiceEvent,ev.pk,bike=None,item=None)
    client.force_login(owner)
    assert client.post(reverse('garage:photo-replace',args=[photo.pk]),{'photo':SimpleUploadedFile('replacement.png',image_bytes('blue'))}).status_code==302
    assert Photo.objects.get().pk==photo.pk
    backend.fail_delete=True
    assert client.post(reverse('garage:photo-delete',args=[photo.pk])).status_code==302
    assert not Photo.objects.exists() and PhotoStorageObject.objects.filter(state='cleanup').exists()
    backend.fail_delete=False
    from django.utils import timezone as django_timezone
    PhotoStorageObject.objects.update(cleanup_after=django_timezone.now())
    photos.retry_photo_cleanup(storage=backend)
    assert not PhotoStorageObject.objects.exists()


def test_purchase_and_a_b_a_mounts_preserve_type_reference_and_service_usage(data):
    from .services.installations import create_installation
    from .services.ownership import update_inventory
    from .services.rides import create_manual_ride
    from .services.usage import summarize_item_usage

    rule = save_maintenance(data.owner, MaintenanceRule, item=data.item, service_type=data.kind, distance_m='1000')
    replacement = save_maintenance(data.owner, ServiceType, name='Replace')
    replace_rule = save_maintenance(data.owner, MaintenanceRule, item=data.item, service_type=replacement, distance_m='2000')
    ev = event(data)
    record_baseline(data.owner, item=data.item, metric='distance_m', scope='service', service_event=ev, cut_at=at(2), value='0')
    other_item = create_inventory(data.owner, Item, name='temporary chain', category=data.item.category)
    create_installation(data.owner, item=data.item, bike=data.bike, started_at=at(), ended_at=at(5))
    create_installation(data.owner, item=other_item, bike=data.bike, started_at=at(5), ended_at=at(8))
    create_installation(data.owner, item=data.item, bike=data.bike, started_at=at(8))
    for day, distance in [(3, '1.001'), (6, '90'), (9, '2.002')]:
        create_manual_ride(data.owner, bike=data.bike, started_at=at(day), distance_m=distance, moving_time_s='1.001')
    update_inventory(data.owner, Item, data.item.pk, acquired_on=at(8).date(), acquisition_anchor_at=at(8))
    assert maintenance_reference(data.owner, rule.pk, at=at(10)) == (ev, at(2))
    assert maintenance_reference(data.owner, replace_rule.pk, at=at(10)) == (None, None)
    reading = summarize_item_usage(data.owner, data.item.pk, metric='distance_m', scope='service', service_event=ev, at=at(10)).reading
    assert reading.total == Decimal('3.003') and not reading.coverage_complete


@pytest.mark.parametrize('kind', ['service-type', 'service-event', 'maintenance-rule'])
def test_private_crud_all_maintenance_resources(data, client, kind):
    payloads = {
        'service-type': {'name': 'Inspect'},
        'service-event': {'item': data.item.pk, 'service_type': data.kind.pk,
                          'performed_at': '2026-01-03T12:00', 'time_zone': 'UTC'},
        'maintenance-rule': {'bike': data.bike.pk, 'service_type': data.kind.pk,
                             'calendar_days': '30', 'time_zone': 'UTC'},
    }
    model = {'service-type': ServiceType, 'service-event': ServiceEvent, 'maintenance-rule': MaintenanceRule}[kind]
    payload = payloads[kind]
    client.force_login(data.owner)
    assert client.post(reverse(f'garage:{kind}-create'), payload).status_code == 302
    obj = model.objects.filter(owner=data.owner).exclude(pk=data.kind.pk).get()
    payload['notes'] = 'owned correction'
    assert client.post(reverse(f'garage:{kind}-edit', args=[obj.pk]), payload).status_code == 302
    obj.refresh_from_db();assert obj.notes == 'owned correction'
    client.force_login(data.other)
    for action in ['edit', 'delete']:
        assert client.post(reverse(f'garage:{kind}-{action}', args=[obj.pk]), payload).status_code == 404
    client.force_login(data.owner)
    assert client.post(reverse(f'garage:{kind}-delete', args=[obj.pk])).status_code == 302
    assert not model.objects.filter(pk=obj.pk).exists()
