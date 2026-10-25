"""Published admin maintenance workflows remain private for staff and superusers."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.contrib import admin, messages
from django.contrib.admin.models import DELETION, LogEntry
from django.contrib.messages import get_messages
from django.db import close_old_connections, connection, transaction

from . import admin as garage_admin
from .models import Bike, Category, Item, MaintenanceRule, Photo, PhotoStorageObject, ServiceEvent, ServiceType, UsageBaseline
from .services.baselines import record_baseline
from .services.maintenance import save_maintenance
from .services.ownership import create_inventory
from .tests_admin import actor, admin_url, other
from .tests_maintenance import at


@pytest.fixture
def inventory(actor, other):
    def owned(user, prefix):
        category = create_inventory(user, Category, name=prefix + ' category')
        return SimpleNamespace(
            item=create_inventory(user, Item, category=category, name=prefix + ' item'),
            bike=create_inventory(user, Bike, name=prefix + ' bike'),
            kind=save_maintenance(user, ServiceType, name=prefix + ' type'),
        )
    return SimpleNamespace(own=owned(actor, 'OWN'), foreign=owned(other, 'FOREIGNSECRET'))


def payload(model, inventory, **changes):
    values = {'_save': 'Save', 'notes': 'own maintenance'}
    if model is ServiceType:
        values['name'] = 'New service type'
    else:
        values.update(item=inventory.own.item.pk, service_type=inventory.own.kind.pk, time_zone='UTC')
        if model is ServiceEvent:
            values.update(performed_at='2026-01-02T00:00:00.123456', amount='12.34', currency='EUR')
        else:
            values.update(distance_m='123.456', moving_time_s='1.001', calendar_days='30', anchor_at='2026-01-01T00:00:00.123456')
    values.update(changes)
    return values


@pytest.mark.parametrize('model', [ServiceType, ServiceEvent, MaintenanceRule])
def test_admin_add_edit_delete_preserves_actor_identity_and_precision(model, actor, other, inventory, client):
    data = payload(model, inventory, owner=other.pk, id=inventory.foreign.kind.pk)
    assert client.post(admin_url(model, 'add'), data).status_code == 302
    obj = model.objects.filter(owner=actor, notes='own maintenance').get()
    identity = obj.pk
    assert obj.owner_id == actor.pk and identity != inventory.foreign.kind.pk
    if model is ServiceEvent:
        assert obj.performed_at.microsecond == 123456 and obj.amount == Decimal('12.34') and obj.currency == 'EUR'
    elif model is MaintenanceRule:
        assert obj.anchor_at.microsecond == 123456
        assert (obj.distance_m, obj.moving_time_s) == (Decimal('123.456'), Decimal('1.001'))
    data['notes'] = 'edited maintenance'
    assert client.post(admin_url(model, 'change', obj), data).status_code == 302
    obj.refresh_from_db()
    assert obj.pk == identity and obj.owner_id == actor.pk and obj.notes == 'edited maintenance'
    assert client.get(admin_url(model, 'delete', obj)).status_code == 200
    assert client.post(admin_url(model, 'delete', obj), {'post': 'yes'}).status_code == 302
    assert not model.objects.filter(pk=identity).exists()


@pytest.mark.parametrize('model', [ServiceEvent, MaintenanceRule])
@pytest.mark.parametrize('field', ['item', 'bike', 'service_type'])
def test_admin_related_choices_and_forged_post_are_owner_scoped(model, field, actor, inventory, client):
    response = client.get(admin_url(model, 'add'))
    assert response.status_code == 200
    form = response.context['adminform'].form
    own = inventory.own.kind if field == 'service_type' else getattr(inventory.own, field)
    foreign = inventory.foreign.kind if field == 'service_type' else getattr(inventory.foreign, field)
    assert list(form.fields[field].queryset) == [own]
    assert b'FOREIGNSECRET' not in response.content
    data = payload(model, inventory, **{field: foreign.pk})
    if field == 'bike':
        data['item'] = ''
    response = client.post(admin_url(model, 'add'), data)
    assert response.status_code == 200 and field in response.context['adminform'].form.errors
    assert not model.objects.filter(owner=actor).exists()


@pytest.mark.parametrize('model', [ServiceType, ServiceEvent, MaintenanceRule])
def test_admin_list_forged_edit_and_bulk_selection_never_reach_foreign_rows(model, actor, other, inventory, client):
    if model is ServiceType:
        own, foreign = inventory.own.kind, inventory.foreign.kind
    else:
        extra = {'performed_at': at(2)} if model is ServiceEvent else {'calendar_days': 30}
        own = save_maintenance(actor, model, item=inventory.own.item, service_type=inventory.own.kind, **extra)
        foreign = save_maintenance(other, model, item=inventory.foreign.item, service_type=inventory.foreign.kind, **extra)
    response = client.get(admin_url(model, 'changelist'))
    assert response.status_code == 200 and list(response.context['cl'].queryset) == [own]
    assert b'FOREIGNSECRET' not in response.content
    for action in ('change', 'delete'):
        response = client.post(admin_url(model, action, foreign), payload(model, inventory, post='yes'))
        assert response.status_code in (302, 404)
    response = client.post(admin_url(model, 'changelist'), {
        'action': 'delete_selected', '_selected_action': [str(own.pk), str(foreign.pk)], 'post': 'yes',
    })
    assert response.status_code == 302
    assert not model.objects.filter(pk=own.pk).exists() and model.objects.filter(pk=foreign.pk, owner=other).exists()


def test_admin_duplicate_service_type_and_rule_are_form_errors(actor, inventory, client):
    response = client.post(admin_url(ServiceType, 'add'), payload(ServiceType, inventory, name=' own type '))
    assert response.status_code == 200 and response.context['adminform'].form.errors
    save_maintenance(actor, MaintenanceRule, item=inventory.own.item, service_type=inventory.own.kind, calendar_days=30)
    response = client.post(admin_url(MaintenanceRule, 'add'), payload(MaintenanceRule, inventory))
    assert response.status_code == 200 and response.context['adminform'].form.errors
    assert MaintenanceRule.objects.filter(owner=actor).count() == 1


def test_admin_service_readings_protect_edit_single_delete_and_bulk_delete(actor, inventory, client):
    ev = save_maintenance(actor, ServiceEvent, item=inventory.own.item, service_type=inventory.own.kind, performed_at=at(2))
    reading = record_baseline(actor, item=inventory.own.item, metric='distance_m', scope='service',
                              service_event=ev, cut_at=at(3), value='1.001')
    response = client.post(admin_url(ServiceEvent, 'change', ev), payload(ServiceEvent, inventory, performed_at='2026-01-04T00:00'))
    assert response.status_code == 200 and response.context['adminform'].form.errors
    ev.refresh_from_db();assert ev.performed_at == at(2)
    response = client.post(admin_url(ServiceEvent, 'delete', ev), {'post': 'yes'})
    assert response.status_code == 200 and response.context['protected']
    response = client.post(admin_url(ServiceEvent, 'changelist'), {
        'action': 'delete_selected', '_selected_action': [str(ev.pk)], 'post': 'yes',
    })
    assert response.status_code == 200 and response.context['protected']
    assert ServiceEvent.objects.filter(pk=ev.pk).exists() and reading.__class__.objects.filter(pk=reading.pk).exists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('bulk', [False, True], ids=['single', 'bulk'])
@pytest.mark.parametrize('reference_kind', ['reading', 'photo'])
def test_admin_delete_conflict_after_preflight_rolls_back_events_and_log(
        bulk, reference_kind, actor, inventory, client, monkeypatch):
    protected = save_maintenance(actor, ServiceEvent, item=inventory.own.item,
                                 service_type=inventory.own.kind, performed_at=at(2))
    first = save_maintenance(actor, ServiceEvent, item=inventory.own.item,
                             service_type=inventory.own.kind, performed_at=at(3)) if bulk else None
    modeladmin = admin.site._registry[ServiceEvent]
    preflight = modeladmin.get_deleted_objects
    delete = garage_admin.delete_maintenance
    reference = {}
    deleted = []
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_backend_pid()')
        request_pid = cursor.fetchone()[0]

    def commit_reference():
        # Use an independent real connection: the incoming reference must
        # survive the request's rollback, as it would in another request.
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET statement_timeout = '5s'")
                cursor.execute('SELECT pg_backend_pid()')
                assert cursor.fetchone()[0] != request_pid
            if reference_kind == 'reading':
                obj = record_baseline(actor, item=inventory.own.item, metric='distance_m', scope='service',
                                      service_event=protected, cut_at=at(4), value='1.001')
            else:
                # Synthetic committed photo metadata; no external storage I/O.
                with transaction.atomic():
                    stored = PhotoStorageObject.objects.create(
                        owner=actor, key=f'garage/photos/{uuid4().hex}.webp', size_bytes=10,
                        width=1, height=1, sha256='a' * 64, state='live')
                    obj = Photo.objects.create(owner=actor, service_event=protected, storage_object=stored)
            return obj.pk
        finally:
            connection.close()

    def stale_preflight(objects, request):
        result = preflight(objects, request)
        assert not result[2] and not result[3]
        assert not reference
        with ThreadPoolExecutor(max_workers=1) as pool:
            reference['pk'] = pool.submit(commit_reference).result(timeout=10)
        return result

    def observe_delete(user, model, resource_id):
        delete(user, model, resource_id)
        deleted.append(resource_id)
        assert not ServiceEvent.objects.filter(pk=resource_id).exists()

    monkeypatch.setattr(modeladmin, 'get_deleted_objects', stale_preflight)
    monkeypatch.setattr(garage_admin, 'delete_maintenance', observe_delete)
    if bulk:
        url = admin_url(ServiceEvent, 'changelist')
        data = {'action': 'delete_selected', '_selected_action': [str(first.pk), str(protected.pk)], 'post': 'yes'}
    else:
        url = admin_url(ServiceEvent, 'delete', protected)
        data = {'post': 'yes'}
    response = client.post(url, data)
    assert response.status_code == 302 and response.url == url
    feedback = list(get_messages(response.wsgi_request))
    assert [(message.level, str(message)) for message in feedback] == [
        (messages.ERROR, 'This resource has interventions, readings or photos.')]
    assert deleted == ([first.pk] if bulk else [])
    selected = [protected.pk] + ([first.pk] if bulk else [])
    assert ServiceEvent.objects.filter(pk__in=selected, owner=actor).count() == len(selected)
    reference_model = UsageBaseline if reference_kind == 'reading' else Photo
    assert reference_model.objects.filter(pk=reference['pk'], service_event=protected, owner=actor).exists()
    assert not LogEntry.objects.filter(user=actor, action_flag=DELETION,
                                       object_id__in=[str(pk) for pk in selected]).exists()
