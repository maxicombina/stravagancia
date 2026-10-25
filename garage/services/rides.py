"""Actor-owned manual/FIT/Strava rides, field provenance and bounded resumable jobs.

No legacy Activity, provider token, file path or raw FIT content enters this
API. Source observations are complete snapshots, not patches. Exact retries
preserve precedence; only changed observations or explicit reactivation advance
observations_updated_at. Every mutation locks the owner before resolving IDs.
Precedence per field is manual > fit > strava > unknown, the most recent source
within a class (garage-030); a specific Strava cycling sport beats FIT's generic
`cycling`, and the bike comes from a Strava gear link unless corrected by hand.
"""
import re

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from garage.models import SOURCE_KINDS, ActivitySource, Bike, ImportRun, Ride, StravaGear
from garage.ride_values import (RIDE_FIELDS, RIDE_METRICS, SOURCE_FIELDS, aware_instant, decode_manual,
                               encode_manual, validate_run_errors, validate_run_manifest)
from garage.sports import GENERIC_CYCLING, is_specific_cycling
from garage.validators import exact_usage_value
from .ownership import InventoryNotFound, InventoryWriteError, _lock_owner, get_inventory, scoped_inventory


def _error(field, message, code):
    return InventoryWriteError({field: ValidationError(message, code=code)})


def _validate(obj):
    try:
        obj.full_clean()
    except ValidationError as error:
        raise InventoryWriteError(error.error_dict) from error


def _validate_trusted(obj, *, exclude=()):
    """Batch paths (Strava pages, garage-030 review): field formats and the model's own
    clean() (owner-scoped references, immutability, provenance) without one query per
    constraint. PostgreSQL still enforces every UNIQUE and CHECK constraint; a violation
    raises IntegrityError and the caller's savepoint discards that activity."""
    try:
        obj.full_clean(exclude=exclude, validate_unique=False, validate_constraints=False)
    except ValidationError as error:
        raise InventoryWriteError(error.error_dict) from error


def _mutate(actor, operation):
    try:
        with transaction.atomic():
            return operation(_lock_owner(actor))
    except IntegrityError as error:
        name = getattr(getattr(error.__cause__, "diag", None), "constraint_name", None)
        if name == "garage_activitysource_identity_unique":
            raise _error("file_hash", "This session already has a source.", "source_conflict") from error
        if name == "garage_activitysource_strava_unique":
            raise _error("external_id", "This Strava activity already has a source.", "source_conflict") from error
        raise


def _bike(owner, value):
    if value is None:
        return None
    try:
        return get_inventory(owner, Bike, value.pk if isinstance(value, Bike) else value)
    except InventoryNotFound:
        raise _error("bike", "Choose one of your own bikes.", "invalid_reference") from None


def _manual_values(owner, values):
    if not isinstance(values, dict):
        raise _error("manual_overrides", "Supply a field mapping.", "invalid_fields")
    values = dict(values)
    if "bike" in values:
        bike = _bike(owner, values["bike"])
        values["bike"] = bike.pk if bike else None
    try:
        return encode_manual(values)
    except ValidationError as error:
        raise InventoryWriteError({"manual_overrides": error}) from error


CLASS_ORDER = {kind: rank for rank, kind in enumerate(SOURCE_KINDS)}


def _gear_bike(owner, sources):
    """Bike linked to the gear of the preferred active Strava source, and that source."""
    strava = [source for source in sources if source.source_kind == "strava" and source.gear_id]
    if not strava:
        return None, None
    links = dict(StravaGear.objects.filter(owner_id=owner.pk, gear_id__in={source.gear_id for source in strava},
                                           bike__isnull=False).values_list("gear_id", "bike_id"))
    for source in strava:
        if source.gear_id in links:
            return links[source.gear_id], source
    return None, None


def _recalculate(owner, ride, *, rebuild=True, trusted=False):
    """rebuild=False lets a caller holding the owner lock batch several changes
    into one rebuild of this ride (garage-031 ride review). trusted=True is the
    Strava batch path: the owner FK and the bike come from this owner's own rows."""
    manual = decode_manual(ride.manual_overrides)
    # trusted: the caller holds this owner's lock, so the owner need not be read again.
    scope = ActivitySource.objects.filter(owner_id=owner.pk) if trusted else scoped_inventory(owner, ActivitySource)
    sources = [] if ride._state.adding else list(scope.filter(ride=ride, withdrawn_at__isnull=True)
                   .order_by("-observations_updated_at", "-id"))
    # Stable sort: class first (FIT measures, Strava fills), most recent within a class.
    sources.sort(key=lambda source: CLASS_ORDER.get(source.source_kind, len(CLASS_ORDER)))
    provenance = {}
    now = timezone.now().isoformat()
    for field in RIDE_FIELDS:
        value = None
        source = None
        if field in manual:
            value = manual[field]
            old = ride.field_provenance.get(field, {})
            stamp = old.get("updated_at") if old.get("kind") == "manual" else now
            provenance[field] = {"kind": "manual", "source_id": None, "updated_at": stamp}
        elif field in SOURCE_FIELDS:
            for candidate in sources:
                observed = getattr(candidate, field)
                if observed is not None and observed != "":
                    value, source = observed, candidate
                    break
            if field == "sport_type" and source is not None and source.source_kind == "fit" and value == GENERIC_CYCLING:
                # The only cross-class exception: Strava's specific cycling sport refines FIT's generic one.
                specific = next((candidate for candidate in sources if candidate.source_kind == "strava"
                                 and is_specific_cycling(candidate.sport_type)), None)
                if specific is not None:
                    value, source = specific.sport_type, specific
            provenance[field] = {"kind": source.source_kind if source else "unknown", "source_id": str(source.pk) if source else None,
                                 "updated_at": source.observations_updated_at.isoformat() if source else None}
        elif field == "bike":
            value, source = _gear_bike(owner, sources)
            provenance[field] = {"kind": "strava" if source else "unknown", "source_id": str(source.pk) if source else None,
                                 "updated_at": source.observations_updated_at.isoformat() if source else None}
        else:
            provenance[field] = {"kind": "unknown", "source_id": None, "updated_at": None}
        if field == "bike" and trusted:
            ride.bike_id = value  # validated below by Ride.clean() against this owner's bikes
        elif field == "bike":
            ride.bike = _bike(owner, value)
        else:
            setattr(ride, field, (value or "") if field in {"name", "sport_type", "notes"} else value)
    ride.field_provenance = provenance
    if trusted:
        _validate_trusted(ride, exclude=("owner", "bike"))  # Ride.clean() rechecks the bike is the owner's
    else:
        _validate(ride)
    ride.save()
    if rebuild:
        from .usage import _rebuild_ride_locked
        _rebuild_ride_locked(owner, ride)
    return ride


def create_manual_ride(actor, /, **values):
    def operation(owner):
        if values.get("started_at") is None:
            raise _error("started_at", "A new ride requires a known start.", "start_required")
        ride = Ride(owner=owner, manual_overrides=_manual_values(owner, values))
        return _recalculate(owner, ride)
    return _mutate(actor, operation)


def correct_ride(actor, ride_id, /, **values):
    """Key presence, including NULL, overrides all current and future sources."""
    def operation(owner):
        ride = get_inventory(owner, Ride, ride_id)
        changes = _manual_values(owner, values)
        if changes.get("started_at", "unchanged") is None:
            raise _error("started_at", "Clear a source correction explicitly instead of inventing an unknown start.", "start_required")
        ride.manual_overrides = ride.manual_overrides | changes
        for field in changes:
            ride.field_provenance[field] = {"kind": "manual", "source_id": None, "updated_at": timezone.now().isoformat()}
        return _recalculate(owner, ride)
    return _mutate(actor, operation)


def clear_manual_corrections(actor, ride_id, *, fields):
    """Explicitly restore source resolution for selected fields."""
    def operation(owner):
        ride = get_inventory(owner, Ride, ride_id)
        if (not isinstance(fields, (list, tuple)) or any(not isinstance(field, str) for field in fields)
                or not set(fields).issubset(RIDE_FIELDS)):
            raise _error("fields", "Choose supported fields.", "invalid_fields")
        had_start = ride.started_at is not None
        ride.manual_overrides = {key: value for key, value in ride.manual_overrides.items() if key not in fields}
        result = _recalculate(owner, ride)
        if had_start and result.started_at is None:
            raise _error("started_at", "A correction cannot remove the only known start.", "start_required")
        return result
    return _mutate(actor, operation)


def _snapshot(values):
    if not isinstance(values, dict) or not set(values).issubset(SOURCE_FIELDS):
        raise _error("observations", "Only minimal source observations are accepted.", "invalid_fields")
    snapshot = {}
    for field in SOURCE_FIELDS:
        value = values.get(field)
        if field == "started_at":
            if value is None:
                raise _error(field, "An imported session requires a known start.", "start_required")
            try:
                value = aware_instant(value)
            except ValidationError as error:
                raise InventoryWriteError({field: error}) from error
        elif field in RIDE_METRICS and value is not None:
            try:
                value = exact_usage_value(value)
            except ValidationError as error:
                raise InventoryWriteError({field: error}) from error
        elif field in {"name", "sport_type"}:
            value = "" if value is None else value
            if not isinstance(value, str) or len(value) > 150:
                raise _error(field, "Enter a short text observation.", "invalid_value")
        snapshot[field] = value
    return snapshot


def import_fit_session(actor, /, *, file_hash, session_index, parser_version, observations,
                       ride_id=None, import_run_id=None, reactivate=False):
    """Hash/session is stable per owner. A target ride must be explicitly owned."""
    def operation(owner):
        if not isinstance(file_hash, str) or re.fullmatch(r"[0-9a-f]{64}", file_hash) is None:
            raise _error("file_hash", "Enter a SHA256 file hash.", "invalid_hash")
        if not isinstance(parser_version, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", parser_version) is None:
            raise _error("parser_version", "Enter a short parser version.", "invalid_parser_version")
        if type(session_index) is not int or not 0 <= session_index <= 2147483647:
            raise _error("session_index", "Enter a nonnegative session index.", "invalid_session")
        if type(reactivate) is not bool:
            raise _error("reactivate", "Use an explicit boolean.", "invalid_value")
        snapshot = _snapshot(observations)
        target = get_inventory(owner, Ride, ride_id) if ride_id is not None else None
        run = get_inventory(owner, ImportRun, import_run_id) if import_run_id is not None else None
        if run is not None and run.file_hash and (run.file_hash != file_hash or session_index not in run.session_indices):
            raise _error("import_run_id", "This session does not belong to the job manifest.", "manifest_mismatch")
        source = scoped_inventory(owner, ActivitySource).filter(file_hash=file_hash, session_index=session_index).first()
        if source is not None:
            if target is not None and target.pk != source.ride_id:
                raise _error("ride_id", "An existing source cannot be moved to another ride.", "source_ride_immutable")
            if source.withdrawn_at is not None and not reactivate:
                raise _error("reactivate", "Explicitly reactivate this withdrawn source.", "source_withdrawn")
            changed = any(getattr(source, field) != value for field, value in snapshot.items())
            if changed or source.withdrawn_at is not None:
                source.observations_updated_at = timezone.now()
            source.withdrawn_at = None
            ride = get_inventory(owner, Ride, source.ride_id)
        else:
            duplicate = False
            if target is None:
                # garage-030: a new FIT joins a ride only when that ride comes from Strava alone and is the single match.
                from .strava_sources import fit_join_target
                target, duplicate = fit_join_target(owner, snapshot, file_hash=file_hash)
            ride = target or Ride(owner=owner)
            if ride._state.adding:
                ride.started_at = snapshot["started_at"]
                _validate(ride)
                ride.save(force_insert=True)
            source = ActivitySource(owner=owner, ride=ride, file_hash=file_hash, session_index=session_index)
            source.possible_duplicate = duplicate
        for field, value in snapshot.items():
            setattr(source, field, value)
        source.parser_version = parser_version
        if import_run_id is not None:
            source.import_run = run
        _validate(source)
        source.save()
        return _recalculate(owner, ride), source
    return _mutate(actor, operation)


def withdraw_source(actor, source_id, /):
    def operation(owner):
        source = get_inventory(owner, ActivitySource, source_id)
        if source.withdrawn_at is None:
            source.withdrawn_at = timezone.now()
            source.save(update_fields=["withdrawn_at", "updated_at"])
        return _recalculate(owner, get_inventory(owner, Ride, source.ride_id))
    return _mutate(actor, operation)


def delete_ride(actor, ride_id, /):
    return _mutate(actor, lambda owner: get_inventory(owner, Ride, ride_id).delete())


def create_import_run(actor, /, *, requested_from=None, requested_to=None, total=None, file_hash="", session_indices=None,
                      source_kind="fit"):
    def operation(owner):
        if not isinstance(source_kind, str) or source_kind not in SOURCE_KINDS:
            raise _error("source_kind", "Choose a supported import source.", "invalid_value")
        selection = [] if session_indices is None else session_indices
        job_total = len(selection) if file_hash and total is None and isinstance(selection, list) else total
        try:
            validate_run_manifest(file_hash, selection, job_total)
        except ValidationError as error:
            raise InventoryWriteError({"session_indices": error}) from error
        run = ImportRun(owner=owner, total=job_total, file_hash=file_hash, session_indices=selection, source_kind=source_kind)
        if source_kind == "strava":
            run.items_imported = run.items_skipped = 0
        for field, value in (("requested_from", requested_from), ("requested_to", requested_to)):
            if value is not None:
                try:
                    value = aware_instant(value)
                except ValidationError as error:
                    raise InventoryWriteError({field: error}) from error
            setattr(run, field, value)
        _counter(job_total, "total", nullable=True)
        _validate(run)
        run.save(force_insert=True)
        return run
    return _mutate(actor, operation)


def _counter(value, field, *, nullable=False):
    if nullable and value is None:
        return
    if type(value) is not int or not 0 <= value <= 2147483647:
        raise _error(field, "Enter a bounded nonnegative integer.", "invalid_progress")


TRANSITIONS = {
    "pending": {"pending", "running", "cancelled"},
    "running": {"running", "paused", "completed", "failed", "cancelled"},
    "paused": {"paused", "running", "cancelled"},
    "failed": {"failed", "running", "cancelled"},
    "completed": {"completed"}, "cancelled": {"cancelled"},
}


def advance_import_run(actor, run_id, /, *, state=None, processed=None, cursor=None, total=None, errors=None,
                       items_imported=None, items_skipped=None):
    """Processed counts attempted session slots, including rejected sessions.

    Cursor is the checkpointed contiguous prefix, not a path or provider token.
    It cannot exceed processed, and completion requires all work checkpointed.
    """
    def operation(owner):
        run = get_inventory(owner, ImportRun, run_id)
        next_state = run.state if state is None else state
        if not isinstance(next_state, str) or next_state not in TRANSITIONS[run.state]:
            raise _error("state", "This import state transition is not allowed.", "invalid_transition")
        terminal = run.state in {"completed", "cancelled"}
        for field, value in (("processed", processed), ("cursor", cursor), ("total", total),
                             ("items_imported", items_imported), ("items_skipped", items_skipped)):
            if value is None:
                continue
            _counter(value, field)
            old = getattr(run, field)
            if (old is not None and value < old) or (terminal and value != old):
                raise _error(field, "Import progress cannot move backwards or change after completion.", "invalid_progress")
            setattr(run, field, value)
        if errors is not None:
            try:
                validate_run_errors(errors)
            except ValidationError as error:
                raise InventoryWriteError({"errors": error}) from error
            if terminal and errors != run.errors:
                raise _error("errors", "A terminal run cannot be changed.", "invalid_transition")
            run.errors = errors
        run.state = next_state
        _validate(run)
        run.save()
        return run
    return _mutate(actor, operation)


def delete_import_run(actor, run_id, /):
    """Job metadata is disposable; source and normalized ride survive SET_NULL."""
    return _mutate(actor, lambda owner: get_inventory(owner, ImportRun, run_id).delete())
