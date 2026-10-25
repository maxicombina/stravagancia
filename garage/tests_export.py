"""Synthetic exports: privacy, exact reconstruction facts and read-only requests."""
import csv
import hashlib
import io
import json
from datetime import timedelta
from decimal import Decimal
from zipfile import ZipFile

import pytest
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from . import models as m
from .services.export import ExportError, TABLES, csv_zip, export_snapshot, json_bytes, scalar
from .services.rides import create_manual_ride, correct_ride, import_fit_session, withdraw_source
from .tests_maintenance import at, data


def graph(owner, label):
    category = m.Category.objects.create(owner=owner, name=label)
    bike = m.Bike.objects.create(owner=owner, name=label, serial_number=label+'serial', purchase_amount=Decimal('12.30'), purchase_currency='EUR')
    item = m.Item.objects.create(owner=owner, category=category, name=label, acquisition_anchor_at=at(), notes='line one\n"line two"')
    second = m.Item.objects.create(owner=owner, category=category, name=label+'B')
    for obj, start, end in [(item,1,3),(second,3,5),(item,5,7)]:
        m.Installation.objects.create(owner=owner, item=obj, bike=bike, slot='saddle', started_at=at(start), ended_at=at(end))
    kind = m.ServiceType.objects.create(owner=owner, name=label)
    event = m.ServiceEvent.objects.create(owner=owner, item=item, service_type=kind, performed_at=at(2), amount=Decimal('23.40'), currency='EUR')
    rule = m.MaintenanceRule.objects.create(owner=owner, item=item, service_type=kind, distance_m=Decimal('1234.567'), calendar_days=20)
    m.MaintenanceSnooze.objects.create(owner=owner, rule=rule, started_at=at(3), ended_at=at(4), reference_at=at(2), reference_event_id=event.pk, distance_m=Decimal('100.5'), calendar_days=7, notes=label)
    m.UsageBaseline.objects.create(owner=owner, item=item, service_event=event, metric='distance_m', scope='service', cut_at=at(3), value=Decimal('123.456'))
    m.RetirementInterval.objects.create(owner=owner, item=item, started_at=at(8), ended_at=at(9))
    profile = m.UsageProfile.objects.create(owner=owner, name=label, bike=bike, started_at=at())
    m.UsageProfileItem.objects.create(owner=owner, profile=profile, item=item)
    ride = create_manual_ride(owner, started_at=at(2).replace(microsecond=123456), bike=bike, distance_m=Decimal('1000.001'), moving_time_s=None, timer_time_s=Decimal('42.001'), notes=label)
    import_fit_session(owner, file_hash=hashlib.sha256(item.pk.bytes).hexdigest(), session_index=0, parser_version='v1', observations={'started_at': at(2), 'distance_m': Decimal('50.001')}, ride_id=ride.pk)
    m.UsageOverride.objects.create(owner=owner, ride=ride, item=item, action='include')
    m.StravaGear.objects.create(owner=owner, gear_id='b' + bike.pk.hex[:12], name=label, bike=bike)  # garage-030 table
    blob = m.PhotoStorageObject.objects.create(owner=owner, key='garage/photos/'+item.pk.hex+'.webp', state='live', size_bytes=100, width=10, height=10, sha256='a'*64)
    m.Photo.objects.create(owner=owner, service_event=event, storage_object=blob)
    return bike,item,ride


def foreign_ids(user):
    """Every identifier of another user's Garage that must never appear in an export."""
    ids = {str(pk) for model, _ in TABLES.values() for pk in model.objects.filter(owner=user).values_list('pk', flat=True)}
    ids |= {str(pk) for pk in m.PhotoStorageObject.objects.filter(owner=user).values_list('pk', flat=True)}
    ids |= {str(pk) for pk in m.UsageProfile.objects.filter(owner=user).values_list('series_id', flat=True)}
    return ids | set(m.ActivitySource.objects.filter(owner=user).values_list('file_hash', flat=True))


def exported_text(snapshot):
    with ZipFile(io.BytesIO(csv_zip(snapshot))) as archive:
        return json_bytes(snapshot).decode(), ''.join(archive.read(name).decode() for name in archive.namelist())


def test_full_graph_privacy_and_reconstruction(data):
    bike,item,ride = graph(data.owner,'Own')
    foreign = graph(data.other,'FOREIGN_SECRET')
    for actor, label, prohibited, stranger in [(data.owner,'Own','FOREIGN_SECRET',data.other),(data.other,'FOREIGN_SECRET','Own',data.owner)]:
        snapshot = export_snapshot(actor)
        assert all(snapshot['tables'][name] for name in TABLES)
        hidden = foreign_ids(stranger)
        for raw in exported_text(snapshot):
            assert prohibited not in raw and label in raw
            assert not [value for value in hidden if value in raw]
            assert 'storage_object' not in raw and '.webp' not in raw and 'owner_id' not in raw
    snapshot = export_snapshot(data.owner)['tables']
    ownride = next(row for row in snapshot['rides'] if row['id'] == str(ride.pk))
    assert ownride['started_at'] == '2026-01-02T00:00:00.123456Z'
    assert ownride['distance_m'] == '1000.001' and ownride['timer_time_s'] == '42.001'
    assert ownride['moving_time_s'] is None and ownride['manual_overrides']['moving_time_s'] is None
    assert 'moving_time_s' not in ownride['excluded_fields']
    assert 'elapsed_time_s' not in ownride and 'elapsed_time_s' in ownride['excluded_fields']
    second = m.Item.objects.get(owner=data.owner, name='OwnB')
    saddle = sorted((row['started_at'], row['ended_at'], row['item_id'], row['slot']) for row in snapshot['installations'] if row['bike_id'] == str(bike.pk))
    assert saddle == [(scalar(at(1)), scalar(at(3)), str(item.pk), 'saddle'), (scalar(at(3)), scalar(at(5)), str(second.pk), 'saddle'),
                      (scalar(at(5)), scalar(at(7)), str(item.pk), 'saddle')]
    baseline = next(row for row in snapshot['baselines'] if row['item_id'] == str(item.pk))
    assert (baseline['metric'], baseline['scope'], baseline['cut_at'], baseline['value']) == ('distance_m', 'service', scalar(at(3)), '123.456')
    assert any(row['id']==baseline['service_event_id'] and row['item_id']==str(item.pk) for row in snapshot['service_events'])
    photo = m.Photo.objects.get(owner=data.owner)
    exported = next(row for row in snapshot['photos'] if row['id'] == str(photo.pk))
    assert exported['content_path'] == reverse('garage:photo-content', args=[photo.pk])
    assert (exported['width'], exported['height'], exported['size_bytes'], exported['sha256']) == (10, 10, 100, 'a'*64)
    profile = m.UsageProfile.objects.get(owner=data.owner, name='Own')
    assert next(row for row in snapshot['profiles'] if row['id'] == str(profile.pk))['series_id'] == str(profile.series_id)
    assert next(row for row in snapshot['bikes'] if row['name'] == 'Own')['purchase_amount'] == '12.30'


def test_nested_mount_open_retirement_and_normalized_provenance(data):
    shoes = m.Item.objects.create(owner=data.owner, category=data.item.category, name='shoes', retired_at=at(9))
    cleat = m.Item.objects.create(owner=data.owner, category=data.item.category, name='cleat')
    nested = m.Installation.objects.create(owner=data.owner, item=cleat, parent_item=shoes, slot='left', started_at=at(1), ended_at=at(4))
    ride, source = fit(data.owner)
    provenance = dict(ride.field_provenance)
    provenance['distance_m'] = {'kind': 'fit', 'source_id': '{' + str(source.pk).upper() + '}', 'updated_at': '2026-01-01T01:00:00+01:00'}
    m.Ride.objects.filter(pk=ride.pk).update(field_provenance=provenance)
    snapshot = export_snapshot(data.owner)['tables']
    row = next(row for row in snapshot['installations'] if row['id'] == str(nested.pk))
    assert (row['parent_item_id'], row['bike_id'], row['ended_at']) == (str(shoes.pk), None, scalar(at(4)))
    assert next(row for row in snapshot['items'] if row['id'] == str(shoes.pk))['retired_at'] == scalar(at(9))
    assert snapshot['rides'][0]['field_provenance']['distance_m'] == {'kind': 'fit', 'source_id': str(source.pk), 'updated_at': '2026-01-01T00:00:00.000000Z'}
    assert snapshot['sources'][0]['id'] == str(source.pk)


def fit(owner, **kwargs):
    return import_fit_session(owner, file_hash='c'*64, session_index=0, parser_version='v1',
                              observations={'started_at': at(2), 'distance_m': Decimal('123.456'), 'name':'FIT'}, **kwargs)


def test_fit_active_and_withdrawn_no_observations(data):
    ride, source = fit(data.owner)
    snapshot = export_snapshot(data.owner)['tables']
    assert snapshot['rides'][0]['field_provenance']['distance_m']['source_id'] == str(source.pk)
    assert snapshot['sources'][0]['distance_m'] == '123.456'
    correct_ride(data.owner, ride.pk, notes='keep', distance_m=None)
    withdraw_source(data.owner, source.pk)
    snapshot = export_snapshot(data.owner)['tables']
    assert snapshot['rides'][0]['distance_m'] is None
    assert snapshot['rides'][0]['manual_overrides']['distance_m'] is None
    assert 'name' not in snapshot['sources'][0] and 'distance_m' not in snapshot['sources'][0]
    assert snapshot['sources'][0]['withdrawn_at'] is not None


CORRUPTIONS = {  # case -> table where the export must stop
    'foreign_bike': 'rides', 'foreign_bike_without_provenance': 'rides', 'foreign_category': 'items',
    'foreign_baseline': 'baselines', 'baseline_event_other_item': 'baselines', 'foreign_photo': 'photos',
    'photo_not_live': 'photos', 'foreign_storage': 'photos', 'foreign_profile': 'profile_items',
    'foreign_profile_bike': 'profiles', 'foreign_override': 'overrides', 'foreign_installation_item': 'installations',
    'foreign_installation_parent': 'installations', 'foreign_installation_bike': 'installations',
    'foreign_retirement': 'retirements', 'foreign_event_type': 'service_events', 'foreign_rule_type': 'maintenance_rules',
    'foreign_source_ride': 'sources', 'manual_foreign': 'rides', 'manual_unknown': 'rides', 'provenance_unknown': 'rides',
    'foreign_source': 'rides', 'different_ride_source': 'rides', 'withdrawn_source': 'rides', 'manual_mismatch': 'rides',
    'unsupported_kind': 'rides', 'missing_manual': 'rides', 'manual_without_provenance': 'rides'}


def fit_only(ride, source, value):
    """Ride whose only trusted field is FIT distance equal to the source: only the source checks can fail."""
    m.Ride.objects.filter(pk=ride.pk).update(distance_m=value, manual_overrides={},
                                             field_provenance={'distance_m': {'kind': 'fit', 'source_id': str(source.pk), 'updated_at': None}})


@pytest.mark.parametrize('corruption', CORRUPTIONS)
def test_corruption_fails_closed(data, corruption, caplog):
    bike,item,ride = graph(data.owner,'OWN')
    foreignbike,foreignitem,foreignride = graph(data.other,'FOREIGN_SECRET')
    own_installations = m.Installation.objects.filter(owner=data.owner, bike=bike)
    if corruption == 'foreign_bike': m.Ride.objects.filter(pk=ride.pk).update(bike=foreignbike)
    elif corruption == 'foreign_bike_without_provenance': m.Ride.objects.filter(pk=ride.pk).update(bike=foreignbike, manual_overrides={}, field_provenance={})
    elif corruption == 'foreign_category': m.Item.objects.filter(pk=item.pk).update(category=foreignitem.category)
    elif corruption == 'foreign_baseline': m.UsageBaseline.objects.filter(owner=data.owner).update(service_event=m.ServiceEvent.objects.get(owner=data.other))
    elif corruption == 'baseline_event_other_item':
        other_item = m.Item.objects.get(owner=data.owner, name='OWNB')
        other_event = m.ServiceEvent.objects.create(owner=data.owner, item=other_item, service_type=m.ServiceType.objects.get(owner=data.owner, name='OWN'), performed_at=at(2))
        m.UsageBaseline.objects.filter(owner=data.owner, scope='service').update(service_event=other_event)
    elif corruption == 'foreign_photo':
        m.Photo.objects.filter(owner=data.owner).update(item=foreignitem,service_event=None)
    elif corruption == 'photo_not_live': m.PhotoStorageObject.objects.filter(owner=data.owner).update(state='cleanup', cleanup_after=at(1))
    elif corruption == 'foreign_storage': m.PhotoStorageObject.objects.filter(owner=data.owner).update(owner=data.other)
    elif corruption == 'foreign_profile': m.UsageProfileItem.objects.filter(owner=data.owner).update(profile=m.UsageProfile.objects.get(owner=data.other))
    elif corruption == 'foreign_profile_bike': m.UsageProfile.objects.filter(owner=data.owner).update(bike=foreignbike)
    elif corruption == 'foreign_override': m.UsageOverride.objects.filter(owner=data.owner).update(ride=foreignride)
    elif corruption == 'foreign_installation_item': own_installations.filter(started_at=at(3)).update(item=foreignitem)
    elif corruption == 'foreign_installation_parent': own_installations.filter(started_at=at(3)).update(bike=None, parent_item=foreignitem)
    elif corruption == 'foreign_installation_bike': own_installations.filter(started_at=at(3)).update(bike=foreignbike, slot=None)
    elif corruption == 'foreign_retirement': m.RetirementInterval.objects.filter(owner=data.owner).update(item=None, bike=foreignbike)
    elif corruption == 'foreign_event_type': m.ServiceEvent.objects.filter(owner=data.owner).update(service_type=data.foreign)
    elif corruption == 'foreign_rule_type': m.MaintenanceRule.objects.filter(owner=data.owner).update(service_type=data.foreign)
    elif corruption == 'foreign_source_ride': m.ActivitySource.objects.filter(owner=data.owner).update(ride=foreignride)
    elif corruption == 'manual_foreign': m.Ride.objects.filter(pk=ride.pk).update(manual_overrides={'bike':str(foreignbike.pk)})
    elif corruption == 'manual_unknown': m.Ride.objects.filter(pk=ride.pk).update(manual_overrides={'token':'FOREIGN_SECRET'})
    elif corruption == 'provenance_unknown': m.Ride.objects.filter(pk=ride.pk).update(field_provenance={'notes':{'kind':'manual','source_id':None,'updated_at':None,'token':'SECRET'}})
    elif corruption == 'foreign_source': fit_only(ride, fit(data.other)[1], Decimal('123.456'))
    elif corruption == 'different_ride_source': fit_only(ride, fit(data.owner)[1], Decimal('123.456'))
    elif corruption == 'withdrawn_source':
        own = m.ActivitySource.objects.get(owner=data.owner, ride=ride)
        withdraw_source(data.owner, own.pk)
        fit_only(ride, own, Decimal('50.001'))
    elif corruption == 'manual_mismatch': m.Ride.objects.filter(pk=ride.pk).update(distance_m=Decimal('999'))
    elif corruption == 'missing_manual': m.Ride.objects.filter(pk=ride.pk).update(manual_overrides={})
    elif corruption == 'manual_without_provenance': m.Ride.objects.filter(pk=ride.pk).update(field_provenance={})
    elif corruption == 'unsupported_kind': m.Ride.objects.filter(pk=ride.pk).update(field_provenance={'notes':{'kind':'strava','source_id':None,'updated_at':None}})
    data.owner.is_superuser = data.owner.is_staff = True
    data.owner.save()
    with caplog.at_level('WARNING', logger='garage.services.export'):
        with pytest.raises(ExportError) as error: export_snapshot(data.owner)
    assert 'FOREIGN_SECRET' not in str(error.value)
    rejection = [record.getMessage() for record in caplog.records if record.name == 'garage.services.export']
    assert len(rejection) == 1 and rejection[0].startswith(f'Garage export rejected at {CORRUPTIONS[corruption]} ')
    hidden = foreign_ids(data.other)
    assert not [value for value in hidden if value in rejection[0] or value in str(error.value)]
    client=Client();client.force_login(data.owner)
    for route in ('export-json', 'export-csv'):
        response=client.get(reverse('garage:'+route))
        assert response.status_code==409
        assert not [value for value in hidden if value.encode() in response.content]


def test_unknown_field_value_omitted_without_reclassification(data):
    ride=m.Ride.objects.create(owner=data.owner, name='UNTRUSTED', notes='SECRET_API', field_provenance={'name':{'kind':'unknown','source_id':None,'updated_at':None}})
    row=export_snapshot(data.owner)['tables']['rides'][0]
    assert 'name' not in row and 'notes' not in row
    assert row['field_provenance']['name']['kind']=='unknown'
    assert row['manual_overrides']=={}


@pytest.mark.parametrize('value', ['=1+1',' +cmd','\n@SUM(1)','\tformula','\rformula','  -10','@cmd','  =x',' \ttext',' \rtext'])
def test_csv_formula_protection_and_quoted_newlines(data,value):
    m.Category.objects.create(owner=data.owner,name=value,notes='"quoted"\nsecond line')
    snapshot=export_snapshot(data.owner)
    with ZipFile(io.BytesIO(csv_zip(snapshot))) as archive:
        rows=list(csv.DictReader(io.StringIO(archive.read('categories.csv').decode())))
        row=next(row for row in rows if row['name'].endswith(value))
        assert row['name']=="'"+value
        assert row['notes']=='"quoted"\nsecond line'
        manifest=json.loads(archive.read('manifest.json'))
        assert manifest['version']==1 and manifest['csv']['null']==r'\N'
    assert next(row for row in snapshot['tables']['categories'] if row['name']==value)['name']==value


def test_empty_exports_headers_manifest_and_no_secrets(db,django_user_model,settings):
    owner=django_user_model.objects.create_user(username='empty',password='SUPERSECRET')
    settings.SECRET_KEY='SECRET_SETTING'
    snapshot=export_snapshot(owner)
    assert all(rows==[] for rows in snapshot['tables'].values())
    assert 'SECRET' not in json_bytes(snapshot).decode()
    with ZipFile(io.BytesIO(csv_zip(snapshot))) as archive:
        assert set(archive.namelist())=={name+'.csv' for name in TABLES}|{'manifest.json'}
        assert len(list(csv.reader(io.StringIO(archive.read('items.csv').decode()))))==1
    client=Client();client.force_login(owner)
    assert json.loads(client.get(reverse('garage:export-json')).content)['tables']==snapshot['tables']
    with ZipFile(io.BytesIO(client.get(reverse('garage:export-csv')).content)) as archive:
        assert all(table['rows']==0 for table in json.loads(archive.read('manifest.json'))['csv']['tables'].values())
    owner.is_active=False;owner.save()
    with pytest.raises(PermissionDenied): export_snapshot(owner)


def test_csv_tables_match_json_and_manifest(data):
    bike,item,ride = graph(data.owner,'Own')
    snapshot=export_snapshot(data.owner)
    with ZipFile(io.BytesIO(csv_zip(snapshot))) as archive:
        manifest=json.loads(archive.read('manifest.json'))
        assert manifest['version']==1 and manifest['units']==snapshot['units'] and 'tables' not in manifest
        for name in TABLES:
            rows=list(csv.reader(io.StringIO(archive.read(name+'.csv').decode())))
            assert rows[0]==manifest['csv']['tables'][name]['columns']
            assert len(rows)-1==manifest['csv']['tables'][name]['rows']==len(snapshot['tables'][name])
            assert {row[0] for row in rows[1:]}=={row['id'] for row in snapshot['tables'][name]}
        exported=next(row for row in snapshot['tables']['rides'] if row['id']==str(ride.pk))
        row=next(row for row in csv.DictReader(io.StringIO(archive.read('rides.csv').decode())) if row['id']==str(ride.pk))
    assert row['bike_id']==str(bike.pk) and row['distance_m']=='1000.001' and row['moving_time_s']==r'\N'
    assert row['elapsed_time_s']==r'\N' and 'elapsed_time_s' in json.loads(row['excluded_fields'])
    assert json.loads(row['manual_overrides'])==exported['manual_overrides']
    assert json.loads(row['field_provenance'])==exported['field_provenance']


def test_query_budget_no_writes_or_n_plus_one(data):
    graph(data.owner,'ONE')
    with CaptureQueriesContext(connection) as queries: export_snapshot(data.owner)
    small=len(queries)
    graph(data.owner,'TWO')
    with CaptureQueriesContext(connection) as queries: export_snapshot(data.owner)
    assert len(queries)==small and small<=22
    assert any('FOR UPDATE' in query['sql'] for query in queries)
    assert not any(query['sql'].lstrip().upper().startswith(('INSERT','UPDATE','DELETE')) for query in queries)


@pytest.mark.parametrize('route',['export','export-json','export-csv'])
def test_get_auth_method_download_and_cache(data,route):
    client=Client();url=reverse('garage:'+route)
    response=client.get(url)
    assert response.status_code==302 and 'no-store' in response['Cache-Control']
    client.force_login(data.owner)
    assert client.post(url).status_code==405
    response=client.get(url)
    assert response.status_code==200 and 'no-store' in response['Cache-Control'] and 'private' in response['Cache-Control']
    if route!='export':
        assert 'attachment' in response['Content-Disposition']
        assert response['X-Content-Type-Options']=='nosniff'


def test_volume_limit_fails_without_partial_file(data,monkeypatch):
    graph(data.owner,'Own')
    rows=sum(len(table) for table in export_snapshot(data.owner)['tables'].values())
    monkeypatch.setattr('garage.services.export.MAX_ROWS',rows)
    assert sum(len(table) for table in export_snapshot(data.owner)['tables'].values())==rows
    monkeypatch.setattr('garage.services.export.MAX_ROWS',rows-1)
    with pytest.raises(ExportError) as error: export_snapshot(data.owner)
    assert error.value.too_large
    client=Client();client.force_login(data.owner)
    assert client.get(reverse('garage:export-json')).status_code==413


def test_download_does_not_write_or_touch_storage(data,monkeypatch):
    graph(data.owner,'Own')
    def forbidden(*args,**kwargs):
        raise AssertionError('Export must not access storage')
    monkeypatch.setattr('garage.storage.PrivatePhotoStorage.signed_download_url', forbidden)
    monkeypatch.setattr('garage.storage.PrivatePhotoStorage.read', forbidden)
    monkeypatch.setattr('garage.storage.PrivatePhotoStorage.__init__', forbidden)
    monkeypatch.setattr('garage.services.photos.signed_photo_url', forbidden)
    client=Client();client.force_login(data.owner)
    for route in ('export-json','export-csv'):
        with CaptureQueriesContext(connection) as queries:
            response=client.get(reverse('garage:'+route))
        assert response.status_code==200
        assert not any(q['sql'].lstrip().upper().startswith(('INSERT','UPDATE','DELETE')) for q in queries)


@pytest.mark.django_db(transaction=True)
def test_snapshot_waits_for_committed_owner_mutation(data, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from time import monotonic, sleep
    from django.db import close_old_connections, transaction
    from .services import export as export_module
    from .services.ownership import _lock_owner
    locked, proceed, started = Event(), Event(), Event()
    pids = {}
    original = export_module._lock_owner
    def read_lock(actor):
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_backend_pid()'); pids['reader'] = cursor.fetchone()[0]
        started.set()
        return original(actor)
    monkeypatch.setattr(export_module, '_lock_owner', read_lock)
    def writer():
        close_old_connections()
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute('SELECT pg_backend_pid()'); pids['writer'] = cursor.fetchone()[0]
                _lock_owner(data.owner)
                locked.set(); assert proceed.wait(15)
                m.Bike.objects.filter(pk=data.bike.pk).update(name='COMMITTED BIKE')
                m.Item.objects.filter(pk=data.item.pk).update(notes='COMMITTED ITEM')
        finally:
            connection.close()
    def reader():
        close_old_connections()
        try:
            return export_snapshot(data.owner)
        finally:
            connection.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        mutation = pool.submit(writer)
        try:
            assert locked.wait(5)
            reading = pool.submit(reader); assert started.wait(5)
            deadline = monotonic()+5
            while True:
                with connection.cursor() as cursor:
                    cursor.execute('SELECT pg_blocking_pids(%s)', [pids['reader']]); blockers=cursor.fetchone()[0]
                if pids['writer'] in blockers:
                    break
                assert not reading.done()
                assert monotonic()<deadline
                sleep(.01)
        finally:
            proceed.set()
        mutation.result(timeout=5); snapshot=reading.result(timeout=5)
    assert snapshot['tables']['bikes'][0]['name']=='COMMITTED BIKE'
    assert snapshot['tables']['items'][0]['notes']=='COMMITTED ITEM'


@pytest.mark.parametrize('source', ['manual','manual_garmin_reading','garmin','garmin_manual',' GARMIN ','probikegarage','custom sensor label'])
def test_baseline_export_keeps_value_and_declared_label_verbatim(data,source):
    # Readings are typed by their owner; the label is exported as written and never filters the value.
    m.UsageBaseline.objects.create(owner=data.owner,item=data.item,metric='distance_m',scope='lifetime',cut_at=at(),value=Decimal('987654321.123'),source=source)
    snapshot=export_snapshot(data.owner)
    row=snapshot['tables']['baselines'][0]
    assert row['source']==source and row['item_id']==str(data.item.pk)
    assert row['value']=='987654321.123' and 'excluded_fields' not in row and 'exclusion_reason' not in row
    with ZipFile(io.BytesIO(csv_zip(snapshot))) as archive:
        rows=list(csv.DictReader(io.StringIO(archive.read('baselines.csv').decode())))
        assert rows[0]['value']=='987654321.123' and rows[0]['source']==source
        assert json.loads(archive.read('manifest.json'))['csv']['tables']['baselines']['columns']==['id','created_at','updated_at',*TABLES['baselines'][1]]
