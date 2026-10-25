"""Private FIT preview, checkpointed replay and explicit history corrections.

A preview reads no more than the FIT parser limit and writes nothing. ImportRun
stores only the immutable file hash/session manifest; uploaded bytes and names
never enter the database, session, URL or logs. Cursor counts positions in that
manifest, not original FIT session indices. Each source+checkpoint commits in
one owner-locked transaction, so retrying an interrupted prefix is idempotent.
"""
from dataclasses import dataclass
from datetime import datetime
import re
from uuid import UUID

from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from garage.importers.fit import PARSER_VERSION, parse_fit, select_sessions
from garage.models import ActivitySource, Bike, ImportRun, Ride
from garage.ride_values import CORE_METRICS, aware_instant
from .ownership import _lock_owner, get_inventory, require_actor, scoped_inventory
from .rides import (advance_import_run, correct_ride, create_import_run, import_fit_session)
from .strava_sources import fit_join_target

PREVIEW_SALT = 'garage.fit-preview.v1'
PREVIEW_MAX_AGE = 3600
MAX_BATCH_RIDES = 100


def error(code, message):
    raise ValidationError(message, code=code)


def period(start=None, end=None):
    start = aware_instant(start) if start is not None else None
    end = aware_instant(end) if end is not None else None
    if start is not None and end is not None and end <= start:
        error('invalid_period', 'El final debe ser posterior al inicio del período.')
    return start, end


@dataclass(frozen=True)
class PreviewSession:
    session_index: int
    started_at: datetime
    sport_type: str
    observations: dict
    existing_ride_id: UUID | None
    candidate_count: int
    in_period: bool
    strava_ride_id: UUID | None = None  # the single Strava-only ride this session would join (garage-030)


@dataclass(frozen=True)
class HistoryPreview:
    sessions: tuple[PreviewSession, ...]
    token: str | None
    selected_indices: tuple[int, ...]


def preview_fit(actor, source, *, session_indices=None, requested_from=None, requested_to=None):
    owner = require_actor(actor)
    start, end = period(requested_from, requested_to)
    parsed = parse_fit(source)
    selected = ()
    # Inspection of a multi-session file never silently chooses its sessions.
    if session_indices is not None or len(parsed.sessions) == 1:
        selected = select_sessions(parsed, session_indices)
        if any((start is not None and row.started_at < start) or (end is not None and row.started_at >= end) for row in selected):
            error('outside_period', 'La selección contiene sesiones fuera del período solicitado [inicio, final).')
    sources = {row.session_index: row for row in scoped_inventory(owner, ActivitySource).filter(file_hash=parsed.file_hash)}
    rows = []
    for row in parsed.sessions:
        same = sources.get(row.session_index)
        candidates = scoped_inventory(owner, Ride).filter(started_at=row.started_at, sport_type=row.sport_type)
        if row.distance_m is not None:
            candidates = candidates.filter(distance_m=row.distance_m)
        if same:
            candidates = candidates.exclude(pk=same.ride_id)
        join = None if same or row.sport_type != 'cycling' else fit_join_target(owner, row.observations(), file_hash=parsed.file_hash)[0]
        rows.append(PreviewSession(row.session_index, row.started_at, row.sport_type, row.observations(),
            same.ride_id if same else None, candidates.count(),
            (start is None or row.started_at >= start) and (end is None or row.started_at < end),
            join.pk if join else None))
    token = None
    indices = tuple(row.session_index for row in selected)
    if indices:
        token = signing.dumps({'owner': str(owner.pk), 'file_hash': parsed.file_hash, 'sessions': list(indices),
            'from': start.isoformat() if start else None, 'to': end.isoformat() if end else None,
            'parser': parsed.parser_version}, salt=PREVIEW_SALT, compress=False)
    return HistoryPreview(tuple(rows), token, indices)


def preview_manifest(owner, token):
    if not isinstance(token, str) or len(token) > 5000:
        error('invalid_preview', 'La previsualización no es válida.')
    try:
        value = signing.loads(token, salt=PREVIEW_SALT, max_age=PREVIEW_MAX_AGE)
    except (signing.BadSignature, TypeError, ValueError):
        error('invalid_preview', 'La previsualización no es válida o ha caducado. Vuelve a previsualizar el FIT.')
    if (not isinstance(value, dict) or set(value) != {'owner', 'file_hash', 'sessions', 'from', 'to', 'parser'}
            or value['owner'] != str(owner.pk) or value['parser'] != PARSER_VERSION
            or not isinstance(value['file_hash'], str) or re.fullmatch(r'[0-9a-f]{64}', value['file_hash']) is None
            or not isinstance(value['sessions'], list) or not value['sessions'] or len(value['sessions']) > 100
            or any(type(index) is not int or not 0 <= index <= 99 for index in value['sessions'])
            or value['sessions'] != sorted(set(value['sessions']))):
        error('invalid_preview', 'La previsualización no corresponde a este usuario o selección.')
    try:
        start, end = period(datetime.fromisoformat(value['from']) if value['from'] is not None else None,
                            datetime.fromisoformat(value['to']) if value['to'] is not None else None)
    except (TypeError, ValueError, ValidationError):
        error('invalid_preview', 'El período de previsualización no es válido.')
    return value, start, end


def start_fit_import(actor, source, token, *, budget=20):
    owner = require_actor(actor)
    manifest, start, end = preview_manifest(owner, token)
    parsed = parse_fit(source)
    if parsed.file_hash != manifest['file_hash']:
        error('preview_file_mismatch', 'El FIT reenviado no coincide con la previsualización.')
    selected = select_sessions(parsed, manifest['sessions'])
    if any((start is not None and row.started_at < start) or (end is not None and row.started_at >= end) for row in selected):
        error('outside_period', 'Las sesiones no corresponden al período previsualizado.')
    _budget(budget)
    run = create_import_run(owner, requested_from=start, requested_to=end, total=len(selected),
                            file_hash=parsed.file_hash, session_indices=list(manifest['sessions']))
    return _resume_parsed(owner, run.pk, parsed, budget)


def _budget(value):
    if type(value) is not int or not 1 <= value <= 100:
        error('invalid_budget', 'Procesa entre una y cien sesiones por paso.')


def resume_fit_import(actor, run_id, source, *, budget=20):
    owner = require_actor(actor)
    run = get_inventory(owner, ImportRun, run_id)
    _budget(budget)
    # Reject unauthorized/terminal work before touching the uploaded stream.
    if run.state in ('completed', 'cancelled'):
        return run
    parsed = parse_fit(source)
    return _resume_parsed(owner, run_id, parsed, budget)


def _resume_parsed(actor, run_id, parsed, budget):
    for attempt in range(budget):
        with transaction.atomic():
            owner = _lock_owner(actor)
            run = get_inventory(owner, ImportRun, run_id)
            if run.state in ('completed', 'cancelled'):
                return run
            if run.file_hash != parsed.file_hash:
                error('resume_file_mismatch', 'Reenvía exactamente el FIT original de este trabajo.')
            selected = select_sessions(parsed, run.session_indices)
            start, end = period(run.requested_from, run.requested_to)
            if any((start is not None and row.started_at < start) or (end is not None and row.started_at >= end) for row in selected):
                error('outside_period', 'El archivo no corresponde al período solicitado.')
            if run.total != len(selected) or not 0 <= run.cursor <= len(selected):
                error('invalid_manifest', 'El manifiesto o progreso del trabajo no es válido.')
            if run.cursor == len(selected):
                if run.state != 'running':
                    run = advance_import_run(owner, run.pk, state='running')
                return advance_import_run(owner, run.pk, state='completed', processed=len(selected), errors=[])
            session = selected[run.cursor]
            run = advance_import_run(owner, run.pk, state='running')
            try:
                # The nested savepoint ensures source/rebuild failure writes nothing
                # for this slot, while earlier completed checkpoints remain durable.
                with transaction.atomic():
                    import_fit_session(owner, file_hash=parsed.file_hash, session_index=session.session_index,
                        parser_version=parsed.parser_version, observations=session.observations(), import_run_id=run.pk)
                    next_cursor = run.cursor + 1
                    next_state = 'completed' if next_cursor == len(selected) else 'running'
                    run = advance_import_run(owner, run.pk, state=next_state, cursor=next_cursor,
                                             processed=max(run.processed, next_cursor), errors=[])
            except ValidationError:
                return advance_import_run(owner, run.pk, state='failed', processed=max(run.processed, run.cursor + 1),
                    errors=[{'code': 'conflict', 'session_index': session.session_index}])
            if run.state == 'completed':
                return run
    with transaction.atomic():
        owner = _lock_owner(actor)
        run = get_inventory(owner, ImportRun, run_id)
        if run.state == 'running':
            run = advance_import_run(owner, run.pk, state='paused')
        return run


def cancel_fit_import(actor, run_id):
    return advance_import_run(actor, run_id, state='cancelled')


@dataclass(frozen=True)
class BikeBatchResult:
    changed_ids: tuple[UUID, ...]
    skipped_ids: tuple[UUID, ...]


def assign_pending_bikes(actor, ride_ids, bike):
    if not isinstance(ride_ids, (list, tuple)) or not ride_ids or len(ride_ids) > MAX_BATCH_RIDES:
        error('invalid_batch', 'Selecciona entre una y cien salidas propias.')
    with transaction.atomic():
        owner = _lock_owner(actor)
        destination = get_inventory(owner, Bike, bike.pk if isinstance(bike, Bike) else bike) if bike is not None else None
        # Resolve every reference before the first write; mixed-owner batches fail whole.
        rides = {ride.pk: ride for ride in (get_inventory(owner, Ride, key) for key in ride_ids)}
        changed, skipped = [], []
        for ride in sorted(rides.values(), key=lambda row: str(row.pk)):
            if ride.bike_id is not None or 'bike' in ride.manual_overrides:
                skipped.append(ride.pk)
                continue
            correct_ride(owner, ride.pk, bike=destination.pk if destination else None)
            changed.append(ride.pk)
        return BikeBatchResult(tuple(changed), tuple(skipped))


def history_queryset(actor, *, requested_from=None, requested_to=None, pending=False):
    start, end = period(requested_from, requested_to)
    rides = scoped_inventory(actor, Ride)
    if start is not None:
        rides = rides.filter(started_at__gte=start)
    if end is not None:
        rides = rides.filter(started_at__lt=end)
    if pending:
        # Elevation and power never make a ride pending (garage-030 phase 3): the original four measurements only.
        missing = Q(bike__isnull=True) | Q(started_at__isnull=True) | Q(sport_type='')
        for field in CORE_METRICS:
            missing |= Q(**{field + '__isnull': True})
        rides = rides.filter(missing)
    return rides.select_related('bike').order_by('-started_at', '-pk')


def coverage(actor, *, requested_from=None, requested_to=None):
    rides = history_queryset(actor, requested_from=requested_from, requested_to=requested_to)
    return {'observed': rides.count(), 'missing_bike': rides.filter(bike__isnull=True).count(),
            'missing_fields': {field: rides.filter(**{field + '__isnull': True}).count() for field in CORE_METRICS},
            'unknown_start': scoped_inventory(actor, Ride).filter(started_at__isnull=True).count(),
            'completeness': 'unknown'}
