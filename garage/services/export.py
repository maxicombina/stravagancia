"""Versioned, own-data export. Explicit allowlists; never serialize model internals."""
import csv
import io
import json
import logging
from datetime import date, datetime, timezone as utc_timezone
from decimal import Decimal
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile

from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from garage import models as m
from garage.ride_values import CORE_METRICS, RIDE_FIELDS, RIDE_METRICS, SOURCE_FIELDS, decode_manual, validate_provenance
from .ownership import _lock_owner

logger = logging.getLogger(__name__)

FORMAT = 'garage-export'
VERSION = 1
MAX_ROWS = 100_000
COMMON = ('id', 'created_at', 'updated_at')
PHYSICAL = ('name', 'brand', 'model', 'serial_number', 'acquired_on', 'acquisition_anchor_at', 'retired_at', 'notes', 'purchase_amount', 'purchase_currency')
TARGET = ('item_id', 'bike_id', 'service_type_id')
# garage-030 phase 3, additive: elevation, power and energy go last in every CSV that gains them.
ADDED_METRICS = tuple(field for field in RIDE_METRICS if field not in CORE_METRICS)
RIDE_COLUMNS = (*(field for field in RIDE_FIELDS if field not in ADDED_METRICS and field != 'bike'),
                'bike_id', 'manual_overrides', 'field_provenance', 'excluded_fields', *ADDED_METRICS)
# Adding a model field cannot silently expand the portable format.
TABLES = {
    # garage-041, additive: the chosen icon key ('' = deduced from the names), last so CSV readers by position keep working.
    'categories': (m.Category, ('name', 'notes', 'is_archived', 'icon')),
    'bikes': (m.Bike, PHYSICAL),
    'items': (m.Item, (*PHYSICAL, 'category_id')),
    'installations': (m.Installation, ('item_id', 'bike_id', 'parent_item_id', 'slot', 'started_at', 'ended_at', 'notes')),
    'service_types': (m.ServiceType, ('name', 'notes')),
    'service_events': (m.ServiceEvent, (*TARGET, 'performed_at', 'notes', 'amount', 'currency')),
    'maintenance_rules': (m.MaintenanceRule, (*TARGET, 'distance_m', 'moving_time_s', 'ride_count', 'calendar_days', 'anchor_at', 'notes',
                                              'elevation_gain_m')),
    'snoozes': (m.MaintenanceSnooze, ('rule_id', 'started_at', 'ended_at', 'reference_at', 'reference_event_id', 'distance_m', 'moving_time_s',
                                      'ride_count', 'calendar_days', 'notes', 'elevation_gain_m')),
    'baselines': (m.UsageBaseline, ('item_id', 'service_event_id', 'metric', 'scope', 'cut_at', 'value', 'source', 'is_estimated', 'notes')),
    'retirements': (m.RetirementInterval, ('item_id', 'bike_id', 'started_at', 'ended_at')),
    'profiles': (m.UsageProfile, ('series_id', 'name', 'bike_id', 'sport_type', 'started_at', 'ended_at', 'notes')),
    'profile_items': (m.UsageProfileItem, ('profile_id', 'item_id')),
    'overrides': (m.UsageOverride, ('ride_id', 'item_id', 'action')),
    'rides': (m.Ride, ()),
    'sources': (m.ActivitySource, ('ride_id', 'source_kind', 'file_hash', 'session_index', 'parser_version', 'observations_updated_at', 'withdrawn_at',
                                   'external_id', 'gear_id', 'possible_duplicate')),
    # garage-030, additive: Strava gear ids and the own bike each stands for. Account and events are never exported.
    'strava_gear': (m.StravaGear, ('gear_id', 'name', 'retired', 'bike_id')),
    'photos': (m.Photo, ('bike_id', 'item_id', 'service_event_id')),
}
REFERENCES = {'category_id': 'categories', 'bike_id': 'bikes', 'item_id': 'items', 'parent_item_id': 'items',
              'service_type_id': 'service_types', 'service_event_id': 'service_events', 'profile_id': 'profiles', 'ride_id': 'rides',
              'rule_id': 'maintenance_rules'}


class ExportError(Exception):
    """Safe public error: carries no records, IDs or underlying validator details."""
    def __init__(self, *, too_large=False):
        self.too_large = too_large
        super().__init__('El volumen supera el límite de exportación.' if too_large else
                         'No se puede exportar: hay datos con referencias o procedencia inválidas.')


def scalar(value):
    if isinstance(value, datetime):
        return value.astimezone(utc_timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (Decimal, UUID)):
        return str(value)
    return value


def _record(obj, fields):
    return {field: scalar(getattr(obj, field)) for field in (*COMMON, *fields)}


def _ride(obj, sources, bikes, gear_links):
    manual = decode_manual(obj.manual_overrides)
    validate_provenance(obj.field_provenance)
    if manual.get('bike') is not None and (manual['bike'] not in bikes or manual['bike'] != obj.bike_id):
        raise ExportError()
    if obj.bike_id is not None and obj.bike_id not in bikes:
        raise ExportError()
    record = _record(obj, ())
    record['manual_overrides'] = {field: scalar(value) for field, value in manual.items()}
    provenance, excluded = {}, []
    for field in RIDE_FIELDS:
        entry = obj.field_provenance.get(field, {'kind': 'unknown', 'source_id': None, 'updated_at': None})
        kind = entry['kind']
        observed = getattr(obj, field + '_id' if field == 'bike' else field)
        if kind == 'manual':
            if field not in manual or observed != (manual[field] or '' if field in ('name', 'sport_type', 'notes') else manual[field]):
                raise ExportError()
        elif field in manual:
            raise ExportError()
        if kind in ('fit', 'strava'):
            source = sources.get(UUID(entry['source_id']))
            if source is None or source.ride_id != obj.pk or source.withdrawn_at is not None or source.source_kind != kind:
                raise ExportError()
            if field == 'bike':
                # Only a Strava gear link resolves a bike from a source.
                if kind != 'strava' or not source.gear_id or gear_links.get(source.gear_id) != observed:
                    raise ExportError()
            elif field not in SOURCE_FIELDS or observed != getattr(source, field):
                raise ExportError()
        if kind == 'unknown':
            excluded.append(field)
        else:
            record['bike_id' if field == 'bike' else field] = scalar(observed)
        provenance[field] = {'kind': kind, 'source_id': str(UUID(entry['source_id'])) if entry['source_id'] else None,
                             'updated_at': scalar(datetime.fromisoformat(entry['updated_at'])) if entry['updated_at'] else None}
    record['field_provenance'] = provenance
    record['excluded_fields'] = excluded
    return record


def export_snapshot(actor):
    """Serialize under the same owner lock as writes; no materialization or storage I/O."""
    where = ('owner', None)
    try:
        with transaction.atomic():
            owner = _lock_owner(actor)
            tables, total = {}, 0
            for name, (model, _) in TABLES.items():
                rows = list(model.objects.filter(owner_id=owner.pk).order_by('pk')[:MAX_ROWS - total + 1])
                total += len(rows)
                if total > MAX_ROWS:
                    raise ExportError(too_large=True)
                tables[name] = {obj.pk: obj for obj in rows}
            storage = {obj.pk: obj for obj in m.PhotoStorageObject.objects.filter(owner_id=owner.pk,
                       pk__in=[photo.storage_object_id for photo in tables['photos'].values()])
                       .only('id', 'state', 'width', 'height', 'size_bytes', 'sha256')}
            data = {}
            for name, (_, fields) in TABLES.items():
                records = []
                for obj in tables[name].values():
                    where = (name, obj.pk)
                    for field in fields:
                        if field in REFERENCES:
                            value = getattr(obj, field)
                            if value is not None and value not in tables[REFERENCES[field]]:
                                raise ExportError()
                    if name == 'rides':
                        record = _ride(obj, tables['sources'], tables['bikes'],
                                       {gear.gear_id: gear.bike_id for gear in tables['strava_gear'].values()})
                    else:
                        record = _record(obj, fields)
                    if name == 'sources':
                        if obj.source_kind not in m.SOURCE_KINDS:
                            raise ExportError()
                        if obj.withdrawn_at is None:
                            record.update({field: scalar(getattr(obj, field)) for field in SOURCE_FIELDS})
                    if name == 'baselines' and obj.service_event_id:
                        if tables['service_events'][obj.service_event_id].item_id != obj.item_id:
                            raise ExportError()
                    if name == 'photos':
                        blob = storage.get(obj.storage_object_id)
                        if blob is None or blob.state != 'live':
                            raise ExportError()
                        record.update({field: getattr(blob, field) for field in ('width', 'height', 'size_bytes', 'sha256')})
                        record['content_path'] = reverse('garage:photo-content', args=[obj.pk])
                    records.append(record)
                data[name] = records
            return {'format': FORMAT, 'version': VERSION, 'exported_at': scalar(timezone.now()),
                    'units': {'distance_m': 'metres', 'moving_time_s': 'seconds', 'timer_time_s': 'seconds',
                              'elapsed_time_s': 'seconds', 'calendar_days': '24-hour days', 'ride_count': 'count',
                              'elevation_gain_m': 'metres', 'average_power_w': 'watts', 'max_power_w': 'watts',
                              'weighted_power_w': 'watts', 'energy_kj': 'kilojoules',
                              'value': 'unit of the row metric', 'amount': 'decimal in the row ISO 4217 currency',
                              'purchase_amount': 'decimal in the row ISO 4217 purchase_currency'},
                    'omitted': ['item_usage (rebuild from rides and temporal assignments)', 'import_runs (operational progress)',
                                'photo binaries and storage objects', 'raw FIT', 'legacy API data', 'user credentials',
                                'Strava account, tokens and webhook events'],
                    'tables': data}
    except (ExportError, ValidationError, ValueError, TypeError, AttributeError, OverflowError) as error:
        if isinstance(error, ExportError) and error.too_large:
            raise
        # Server-side diagnosis only: own table/row and error class, never values or foreign IDs.
        logger.warning('Garage export rejected at %s %s (%s)', where[0], where[1], type(error).__name__)
        raise ExportError() from None


def json_bytes(snapshot):
    return json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')


def csv_cell(value):
    if value is None:
        return r'\N'
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    elif isinstance(value, bool):
        value = 'true' if value else 'false'
    else:
        value = str(value)
    # Excel interprets formulas even after whitespace. Tabs/CR are dangerous too.
    if value.lstrip().startswith(('=', '+', '-', '@')) or any(char in value[:len(value)-len(value.lstrip())] for char in ('\t', '\r')):
        return "'" + value
    return value


def csv_zip(snapshot):
    """One relational table per CSV; JSON is the exact preservation format."""
    out = io.BytesIO()
    with ZipFile(out, 'w', ZIP_DEFLATED) as archive:
        manifest = {key: value for key, value in snapshot.items() if key != 'tables'}
        manifest['csv'] = {'null': r'\N', 'encoding': 'UTF-8', 'formula_protection': 'leading apostrophe',
                           'authority': 'JSON export preserves exact strings and null/presence', 'tables': {}}
        for name, (_, fields) in TABLES.items():
            rows = snapshot['tables'][name]
            extras = {'rides': RIDE_COLUMNS,
                      'sources': SOURCE_FIELDS,  # its phase-3 metrics are already last
                      'photos': ('width', 'height', 'size_bytes', 'sha256', 'content_path')}.get(name, ())
            columns = list(dict.fromkeys((*COMMON, *fields, *extras)))
            manifest['csv']['tables'][name] = {'rows': len(rows), 'columns': columns}
            stream = io.StringIO(newline='')
            writer = csv.writer(stream, quoting=csv.QUOTE_ALL)
            writer.writerow(columns)
            writer.writerows([[csv_cell(row.get(field)) for field in columns] for row in rows])
            archive.writestr(name + '.csv', stream.getvalue().encode('utf-8'))
        archive.writestr('manifest.json', json_bytes(manifest))
    return out.getvalue()
