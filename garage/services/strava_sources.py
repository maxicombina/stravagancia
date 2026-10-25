"""Strava activities as Garage sources (garage-030): mapping, linking and moves.

Helpers prefixed with an underscore or documented as "locked" run under the
caller's owner lock inside its transaction and never call Strava. Public
services (`link_gear`, `separate_source`, `merge_source`, `dismiss_duplicate`,
`remove_strava_data`) take the owner lock themselves.

Identity: one ActivitySource per owner and Strava activity id, with
file_hash = sha256("strava:{athlete}:{activity}") and session_index 0, so the
existing hash and identity constraints hold unchanged.

Linking is deterministic and only across classes: a Strava activity joins the
single owner ride whose comparison point (each active FIT source, or the ride's
effective start and distance when it has no active FIT) starts within 90 s and
whose distance differs by at most 2 % of the larger one (or is unknown). No
candidate ⇒ new ride; several, or one that already has an active Strava source
⇒ new ride marked `possible_duplicate`. A FIT that arrives later joins only a
ride that has an active Strava source and no active FIT. Never FIT↔FIT or
Strava↔Strava.

Data Strava deleted (confirmed 404), activities that stopped being cycling and
«Quitar lo sincronizado» delete the Strava source row (API Policy §6.3/§7.4).
A ride left with no source rows and no manual *measurement* correction
(start, sport, distance, the three times, elevation and power) is deleted with its usage. «Unir
con…» is the person's own move: the ride it empties is kept when it has any
manual correction (name, bike and notes included) or a usage exception.

Cost (garage-030 review): a page is stored through one StravaBatch that loads
the page's known sources, its gear and the comparison points near its starts
once, so a new activity costs a bounded number of queries (tested) instead of
scanning the owner's rides; field formats and clean() run for every row, while
UNIQUE and CHECK constraints are left to PostgreSQL (a violation rolls back
only that activity's savepoint).
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import re
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from garage.models import ActivitySource, Bike, Ride, StravaAccount, StravaEvent, StravaGear, UsageOverride
from garage.ride_values import POWER_METRICS, RIDE_FIELDS, RIDE_METRICS, SOURCE_FIELDS, aware_instant, plausible
from garage.sports import CYCLING_KEYS, strava_sport
from garage.validators import exact_usage_value
from .ownership import InventoryNotFound, _lock_owner, get_inventory, require_actor
from .rides import _error, _mutate, _recalculate, _validate, _validate_trusted

PARSER_VERSION = "strava-api-v3"
MATCH_WINDOW = timedelta(seconds=90)
MATCH_DISTANCE = Decimal("0.02")
MERGE_WINDOW = timedelta(hours=6)
MERGE_LIMIT = 10
# Elevation and power typed by hand are measurements too (garage-030 phase 3).
MEASUREMENT_FIELDS = frozenset(("started_at", "sport_type", *RIDE_METRICS))
GEAR_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,40}")
# Garage field -> Strava activity key. Strava's kilojoules are already kJ; its weighted
# average watts are Strava's own weighting (stored as weighted_power_w, not Garmin's NP).
OBSERVED = {"distance_m": "distance", "moving_time_s": "moving_time", "elapsed_time_s": "elapsed_time",
            "elevation_gain_m": "total_elevation_gain", "average_power_w": "average_watts", "max_power_w": "max_watts",
            "weighted_power_w": "weighted_average_watts", "energy_kj": "kilojoules"}


def identity_hash(athlete_id, activity_id):
    return sha256(f"strava:{athlete_id}:{activity_id}".encode()).hexdigest()


@dataclass(frozen=True)
class StravaObservation:
    activity_id: int
    athlete_id: int | None
    sport_type: str | None
    values: dict
    gear_id: str


def _metric(value):
    """Exact Decimal or int from parse_float=Decimal JSON; anything else is unknown, never a float."""
    if value is None or isinstance(value, (bool, float)) or not isinstance(value, (int, Decimal)):
        return None
    try:
        return exact_usage_value(value)
    except ValidationError:
        return None


def _start(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("start")
    try:
        instant = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("start") from None
    if timezone.is_naive(instant):
        raise ValueError("start")
    return aware_instant(instant)


def parse_activity(data):
    """Minimal observation of a Strava activity summary or detail; ValueError when unusable."""
    if not isinstance(data, dict):
        raise ValueError("payload")
    activity_id = data.get("id")
    if type(activity_id) is not int or not 0 < activity_id <= 2 ** 63 - 1:
        raise ValueError("id")
    athlete = data.get("athlete")
    athlete_id = athlete.get("id") if isinstance(athlete, dict) else None
    if athlete_id is not None and type(athlete_id) is not int:
        raise ValueError("athlete")
    raw_sport = data.get("sport_type") or data.get("type")
    sport = strava_sport(raw_sport)
    name = data.get("name")
    name = name.strip()[:150] if isinstance(name, str) else ""
    gear = data.get("gear_id")
    gear = gear if isinstance(gear, str) and GEAR_PATTERN.fullmatch(gear) else ""
    values = {"started_at": _start(data.get("start_date")), "name": name, "sport_type": sport or "",
              "timer_time_s": None}  # Strava has no timer time: unknown, never moving time.
    # Without a power meter (device_watts not true) Strava estimated the power: not a measurement, unknown.
    measured_power = data.get("device_watts") is True
    for field, key in OBSERVED.items():
        values[field] = None if field in POWER_METRICS and not measured_power else plausible(field, _metric(data.get(key)))
    return StravaObservation(activity_id, athlete_id, sport, {field: values[field] for field in SOURCE_FIELDS}, gear)


def parse_for(account, data, *, require_athlete=False):
    """The observation of one of this account's activities; ValueError("athlete") for any other athlete.

    require_athlete: an activity fetched for a webhook hint must name its athlete
    (Strava always does); a list page may omit it because it is already scoped.
    """
    observation = parse_activity(data)
    if observation.athlete_id is None and require_athlete:
        raise ValueError("athlete")
    if observation.athlete_id is not None and observation.athlete_id != account.athlete_id:
        raise ValueError("athlete")
    return observation


def _close(first, second):
    if first is None or second is None:
        return True
    larger = max(first, second)
    return larger == 0 or abs(first - second) <= larger * MATCH_DISTANCE


def _is_cycling(sport):
    return sport == "" or sport in CYCLING_KEYS


@dataclass
class _Point:
    started_at: datetime | None
    distance_m: Decimal | None
    cycling: bool
    has_fit: bool
    has_strava: bool


class LinkIndex:
    """Comparison points of the owner's rides near some Strava starts (read-only, two queries).

    A ride with an active FIT is compared through each active FIT source; one
    without, through its effective start and distance. Only cycling (or unknown
    sport) rides are candidates.
    """

    def __init__(self, owner, starts):
        self.owner = owner
        self.rides = {}
        self.fit_points = {}
        starts = [start for start in starts if start is not None]
        if not starts:
            return
        low, high = min(starts) - MATCH_WINDOW, max(starts) + MATCH_WINDOW
        for ride_id, start, distance in ActivitySource.objects.filter(
                owner_id=owner.pk, source_kind="fit", withdrawn_at__isnull=True, started_at__gte=low, started_at__lte=high
        ).values_list("ride_id", "started_at", "distance_m"):
            self.fit_points.setdefault(ride_id, []).append((start, distance))
        rides = self._rides().filter(Q(started_at__gte=low, started_at__lte=high) | Q(pk__in=list(self.fit_points)))
        for row in rides:
            self._keep(row)

    def _rides(self):
        active = ActivitySource.objects.filter(ride_id=OuterRef("pk"), withdrawn_at__isnull=True)
        return (Ride.objects.filter(owner_id=self.owner.pk)
                .annotate(has_fit=Exists(active.filter(source_kind="fit")), has_strava=Exists(active.filter(source_kind="strava")))
                .values_list("pk", "started_at", "distance_m", "sport_type", "has_fit", "has_strava"))

    def _keep(self, row):
        pk, start, distance, sport, has_fit, has_strava = row
        self.rides[pk] = _Point(start, distance, _is_cycling(sport), has_fit, has_strava)

    def candidates(self, started_at, distance_m, *, exclude_ride_id=None):
        low, high = started_at - MATCH_WINDOW, started_at + MATCH_WINDOW
        found = {ride_id for ride_id, points in self.fit_points.items()
                 if any(low <= start <= high and _close(distance, distance_m) for start, distance in points)}
        found |= {ride_id for ride_id, point in self.rides.items() if not point.has_fit and point.started_at is not None
                  and low <= point.started_at <= high and _close(point.distance_m, distance_m)}
        found.discard(exclude_ride_id)
        return {ride_id for ride_id in found if ride_id in self.rides and self.rides[ride_id].cycling}

    def with_strava(self, ride_ids):
        return {ride_id for ride_id in ride_ids if ride_id in self.rides and self.rides[ride_id].has_strava}

    def note(self, ride, *, has_strava):
        """A ride this batch stored into, as recalculated (no query unless the ride was not loaded)."""
        point = self.rides.get(ride.pk)
        if point is None:  # e.g. a manual start outside this batch's window
            self.reread(ride.pk)
            return
        point.started_at, point.distance_m, point.cycling = ride.started_at, ride.distance_m, _is_cycling(ride.sport_type)
        point.has_strava = has_strava

    def added(self, ride):
        """A ride this batch created for a Strava source: no FIT yet."""
        self.rides[ride.pk] = _Point(ride.started_at, ride.distance_m, _is_cycling(ride.sport_type), False, True)

    def reread(self, ride_id):
        row = self._rides().filter(pk=ride_id).first()
        if row is None:
            self.rides.pop(ride_id, None)
            self.fit_points.pop(ride_id, None)
        else:
            self._keep(row)


def strava_candidates(owner, started_at, distance_m, *, exclude_ride_id=None):
    """Owner rides matching a Strava observation (read-only)."""
    return LinkIndex(owner, [started_at]).candidates(started_at, distance_m, exclude_ride_id=exclude_ride_id)


def _with_active(owner, ride_ids, kind):
    if not ride_ids:
        return set()
    return set(ActivitySource.objects.filter(owner_id=owner.pk, ride_id__in=ride_ids, source_kind=kind, withdrawn_at__isnull=True)
               .values_list("ride_id", flat=True))


def fit_join_target(owner, snapshot, *, file_hash=None):
    """(ride, possible_duplicate) for a new FIT session (read-only).

    It joins only a single match that is Strava-only. Any other match (several,
    or one that already has an active FIT of another file) means a new ride
    marked as possible duplicate: never FIT↔FIT, never counted twice silently.
    Sessions of the same file are not matches of each other.
    """
    start, distance = snapshot["started_at"], snapshot.get("distance_m")
    sources = ActivitySource.objects.filter(owner_id=owner.pk, withdrawn_at__isnull=True,
                                            started_at__gte=start - MATCH_WINDOW, started_at__lte=start + MATCH_WINDOW)
    if file_hash:
        sources = sources.exclude(source_kind="fit", file_hash=file_hash)
    matches = {ride_id for ride_id, observed in sources.values_list("ride_id", "distance_m") if _close(observed, distance)}
    if not matches:
        return None, False
    if len(matches) == 1 and not _with_active(owner, matches, "fit"):
        # Its matching active source can only be Strava's.
        return Ride.objects.get(owner_id=owner.pk, pk=next(iter(matches))), False
    return None, True


def ensure_gear(owner, gear_id, *, name=None, retired=None):
    """Locked: the owner's StravaGear for gear_id, created with a blank name when only observed."""
    gear = StravaGear.objects.filter(owner_id=owner.pk, gear_id=gear_id).first()
    if gear is None:
        gear = StravaGear(owner=owner, gear_id=gear_id, name=(name or "")[:150], retired=bool(retired))
    elif (name is None or name[:150] == gear.name) and (retired is None or bool(retired) == gear.retired):
        return gear
    else:
        gear.name = gear.name if name is None else name[:150]
        gear.retired = gear.retired if retired is None else bool(retired)
    _validate(gear)
    gear.save()
    return gear


def _gear_rides(owner, gear_id):
    return set(ActivitySource.objects.filter(owner_id=owner.pk, source_kind="strava", gear_id=gear_id, withdrawn_at__isnull=True)
               .values_list("ride_id", flat=True))


def _recalculate_ids(owner, ride_ids, touched):
    for ride in Ride.objects.filter(owner_id=owner.pk, pk__in=ride_ids).order_by("pk"):
        _recalculate(owner, ride, rebuild=False)
        touched.add(ride.pk)


def refresh_gear(owner, bikes, touched):
    """Locked: names and Strava's retired flag from GET /athlete `bikes`. A retired
    gear keeps its link (old rides used that bike); its rides are recalculated."""
    if not isinstance(bikes, list):
        return
    for entry in bikes[:200]:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not GEAR_PATTERN.fullmatch(entry["id"]):
            continue
        name = entry.get("name") if isinstance(entry.get("name"), str) else ""
        retired = entry.get("retired") if isinstance(entry.get("retired"), bool) else None
        before = StravaGear.objects.filter(owner_id=owner.pk, gear_id=entry["id"]).values_list("retired", flat=True).first()
        ensure_gear(owner, entry["id"], name=name.strip(), retired=retired)
        if before is not None and retired is not None and before != retired:
            _recalculate_ids(owner, _gear_rides(owner, entry["id"]), touched)


def rebuild_rides_locked(owner, ride_ids):
    """One usage reconstruction for the rides a batch touched (owner lock held)."""
    from .usage import _mark_initialized_locked, _rebuild_locked
    rides = list(Ride.objects.filter(owner_id=owner.pk, pk__in=set(ride_ids)).select_for_update().order_by("pk"))
    if not rides:
        return ()
    plans = _rebuild_locked(owner, rides)
    if Ride.objects.filter(owner_id=owner.pk).count() == len(rides):
        _mark_initialized_locked(owner)
    return plans


def _has_measurement_corrections(ride):
    return bool(MEASUREMENT_FIELDS & set(ride.manual_overrides))


def _has_any_correction(ride):
    """Name, bike and notes count too, and so do usage exceptions (UsageOverride)."""
    return bool(ride.manual_overrides) or UsageOverride.objects.filter(owner_id=ride.owner_id, ride_id=ride.pk).exists()


def _drop_if_empty(owner, ride, touched, *, keep_corrected=False, trusted=False):
    """Locked: delete a ride left without any source row nor manual measurement; else recalculate it.

    keep_corrected: the person's own move («Unir con…») keeps a ride with any
    manual correction or usage exception instead of deleting it silently.
    """
    keep = _has_any_correction(ride) if keep_corrected else _has_measurement_corrections(ride)
    if not keep and not ActivitySource.objects.filter(owner_id=owner.pk, ride_id=ride.pk).exists():
        touched.discard(ride.pk)
        ride.delete()
        return True
    _recalculate(owner, ride, rebuild=False, trusted=trusted)
    touched.add(ride.pk)
    return False


def discard_source(owner, source, touched):
    """Locked: delete a Strava source (deleted on Strava or no longer cycling). True if its ride went too."""
    if source.source_kind != "strava":
        raise _error("source", "Only Strava sources are deleted with their data.", "invalid_source")
    ride = Ride.objects.get(owner_id=owner.pk, pk=source.ride_id)
    source.delete()
    return _drop_if_empty(owner, ride, touched, trusted=True)


@dataclass(frozen=True)
class StoreOutcome:
    kind: str  # imported, updated, unchanged, skipped_sport, skipped_withdrawn, removed
    ride_id: UUID | None = None


# clean_fields() would query these FKs again; each model's clean() checks they are the owner's.
SOURCE_TRUSTED = ("owner", "ride", "import_run")
RIDE_TRUSTED = ("owner", "bike")


class StravaBatch:
    """Locked state for one page or one event (owner lock held, never calls Strava).

    The page's known Strava sources, its gear and the comparison points near
    its starts are loaded once; every store keeps them current. After a
    savepoint rolls one activity back, the caller calls reload().
    """

    def __init__(self, owner, account, observations, *, import_run=None):
        self.owner, self.account, self.import_run = owner, account, import_run
        self.observations = list(observations)
        self.reload()

    def reload(self):
        owner = self.owner
        ids = [observation.activity_id for observation in self.observations]
        self.sources = {source.external_id: source for source in ActivitySource.objects.filter(
            owner_id=owner.pk, source_kind="strava", external_id__in=ids)} if ids else {}
        gear_ids = {observation.gear_id for observation in self.observations if observation.gear_id}
        self.gear = set(StravaGear.objects.filter(owner_id=owner.pk, gear_id__in=gear_ids).values_list("gear_id", flat=True)) if gear_ids else set()
        self.index = LinkIndex(owner, [observation.values["started_at"] for observation in self.observations
                                       if observation.sport_type and observation.activity_id not in self.sources])

    def store(self, observation, touched):
        """Store one observation as a complete snapshot."""
        owner = self.owner
        source = self.sources.get(observation.activity_id)
        if observation.sport_type is None:
            if source is not None and source.withdrawn_at is None:
                ride_id = source.ride_id
                discard_source(owner, source, touched)
                del self.sources[observation.activity_id]
                self.index.reread(ride_id)
                return StoreOutcome("removed")
            return StoreOutcome("skipped_sport")
        if source is not None and source.withdrawn_at is not None:
            # The person withdrew it on purpose; a sync never reactivates it.
            return StoreOutcome("skipped_withdrawn", source.ride_id)
        if observation.gear_id and observation.gear_id not in self.gear:
            ensure_gear(owner, observation.gear_id)
            self.gear.add(observation.gear_id)
        if source is not None:
            return self._update(source, observation, touched)
        return self._insert(observation, touched)

    def _update(self, source, observation, touched):
        snapshot = observation.values
        if all(getattr(source, field) == value for field, value in snapshot.items()) and source.gear_id == observation.gear_id:
            return StoreOutcome("unchanged", source.ride_id)
        for field, value in snapshot.items():
            setattr(source, field, value)
        source.gear_id = observation.gear_id
        source.observations_updated_at = timezone.now()
        if self.import_run is not None:
            source.import_run = self.import_run
        _validate_trusted(source, exclude=SOURCE_TRUSTED)
        source.save()
        ride = Ride.objects.get(owner_id=self.owner.pk, pk=source.ride_id)
        _recalculate(self.owner, ride, rebuild=False, trusted=True)
        touched.add(ride.pk)
        self.index.note(ride, has_strava=True)
        return StoreOutcome("updated", ride.pk)

    def _insert(self, observation, touched):
        owner, account = self.owner, self.account
        start, distance = observation.values["started_at"], observation.values["distance_m"]
        candidates = self.index.candidates(start, distance)
        joinable = candidates - self.index.with_strava(candidates)
        ride = None
        if len(candidates) == 1 and joinable:
            ride = Ride.objects.get(owner_id=owner.pk, pk=next(iter(joinable)))
        if ride is None:
            ride = Ride(owner=owner, started_at=start)
            _validate_trusted(ride, exclude=RIDE_TRUSTED)
            ride.save(force_insert=True)
            created = True
        else:
            created = False
        source = ActivitySource(owner=owner, ride=ride, source_kind="strava", external_id=observation.activity_id,
                                file_hash=identity_hash(account.athlete_id, observation.activity_id), session_index=0,
                                parser_version=PARSER_VERSION, gear_id=observation.gear_id, import_run=self.import_run)
        source.possible_duplicate = bool(candidates) and ride.pk not in candidates
        for field, value in observation.values.items():
            setattr(source, field, value)
        _validate_trusted(source, exclude=SOURCE_TRUSTED)
        source.save(force_insert=True)
        _recalculate(owner, ride, rebuild=False, trusted=True)
        touched.add(ride.pk)
        self.sources[observation.activity_id] = source
        if created:
            self.index.added(ride)
        else:
            self.index.note(ride, has_strava=True)
        return StoreOutcome("imported", ride.pk)


def store_activity(owner, account, data, *, touched, import_run=None, require_athlete=False):
    """Locked: store one Strava activity as a complete snapshot; ValueError if unusable."""
    observation = parse_for(account, data, require_athlete=require_athlete)
    return StravaBatch(owner, account, [observation], import_run=import_run).store(observation, touched)


def link_gear(actor, gear_pk, bike):
    """Link a Strava gear to an own bike (or None) and recalculate the rides that used it."""
    def operation(owner):
        gear = get_inventory(owner, StravaGear, gear_pk)
        destination = None
        if bike is not None:
            try:
                destination = get_inventory(owner, Bike, getattr(bike, "pk", bike))
            except InventoryNotFound:
                raise _error("bike", "Elige una de tus bicis.", "invalid_reference") from None
        if gear.bike_id == (destination.pk if destination else None):
            return gear
        gear.bike = destination
        _validate(gear)
        gear.save(update_fields=["bike", "updated_at"])
        touched = set()
        _recalculate_ids(owner, _gear_rides(owner, gear.gear_id), touched)
        rebuild_rides_locked(owner, touched)
        return gear
    return _mutate(actor, operation)


def _move(source, ride):
    source.ride = ride
    source._allow_ride_move = True
    _validate(source)
    source.save(update_fields=["ride", "possible_duplicate", "updated_at"])


def separate_source(actor, source_id):
    """«Separar fuente»: move one active source of a ride with other active sources to a new ride."""
    def operation(owner):
        source = get_inventory(owner, ActivitySource, source_id)
        if source.withdrawn_at is not None:
            raise _error("source", "Sólo se separa una fuente activa.", "source_withdrawn")
        old = get_inventory(owner, Ride, source.ride_id)
        if not ActivitySource.objects.filter(owner_id=owner.pk, ride_id=old.pk, withdrawn_at__isnull=True).exclude(pk=source.pk).exists():
            raise _error("source", "Esta salida no tiene otra fuente activa: no hay nada que separar.", "nothing_to_separate")
        ride = Ride(owner=owner, started_at=source.started_at)
        _validate(ride)
        ride.save(force_insert=True)
        source.possible_duplicate = False
        _move(source, ride)
        touched = set()
        _recalculate_ids(owner, {old.pk, ride.pk}, touched)
        rebuild_rides_locked(owner, touched)
        return Ride.objects.get(pk=ride.pk)
    return _mutate(actor, operation)


def merge_source(actor, source_id, ride_id):
    """«Unir con…»: move an active source to another own ride lacking an active source of its class."""
    def operation(owner):
        source = get_inventory(owner, ActivitySource, source_id)
        target = get_inventory(owner, Ride, ride_id)
        if source.withdrawn_at is not None:
            raise _error("source", "Sólo se une una fuente activa.", "source_withdrawn")
        if target.pk == source.ride_id:
            raise _error("ride", "La fuente ya pertenece a esa salida.", "same_ride")
        if _with_active(owner, {target.pk}, source.source_kind):
            label = "Strava" if source.source_kind == "strava" else "FIT"
            raise _error("ride", f"Esa salida ya tiene una fuente {label} activa: nunca se unen dos del mismo tipo.", "class_taken")
        old = get_inventory(owner, Ride, source.ride_id)
        source.possible_duplicate = False
        _move(source, target)
        touched = set()
        _drop_if_empty(owner, old, touched, keep_corrected=True)
        _recalculate(owner, Ride.objects.get(pk=target.pk), rebuild=False)
        touched.add(target.pk)
        rebuild_rides_locked(owner, touched)
        return Ride.objects.get(pk=target.pk)
    return _mutate(actor, operation)


def dismiss_duplicate(actor, source_id):
    """«No es un duplicado»: clear the mark; nothing else changes."""
    def operation(owner):
        source = get_inventory(owner, ActivitySource, source_id)
        if source.possible_duplicate:
            source.possible_duplicate = False
            source.save(update_fields=["possible_duplicate", "updated_at"])
        return source
    return _mutate(actor, operation)


@dataclass(frozen=True)
class MergeCandidate:
    ride: Ride
    matches: bool


def merge_candidates(actor, source_id):
    """Rides near a source that could receive it (read-only); `matches` applies the linking rule."""
    owner = require_actor(actor)
    source = get_inventory(owner, ActivitySource, source_id)
    rides = list(Ride.objects.filter(owner_id=owner.pk, started_at__gte=source.started_at - MERGE_WINDOW,
                                     started_at__lte=source.started_at + MERGE_WINDOW).exclude(pk=source.ride_id).select_related("bike"))
    blocked = _with_active(owner, {ride.pk for ride in rides}, source.source_kind)
    rows = [MergeCandidate(ride, abs(ride.started_at - source.started_at) <= MATCH_WINDOW and _close(ride.distance_m, source.distance_m))
            for ride in rides if ride.pk not in blocked]
    rows.sort(key=lambda row: (abs(row.ride.started_at - source.started_at), str(row.ride.pk)))
    return rows[:MERGE_LIMIT]


@dataclass(frozen=True)
class MergeEffects:
    """What «Unir con…» does to the ride the source leaves (read-only, shown before the POST)."""
    corrections: tuple  # manual fields of that ride (RIDE_FIELDS keys, name, bike and notes included)
    overrides: int      # its usage exceptions
    other_sources: int  # its other source rows, active or withdrawn
    loses_start: bool   # kept without a start of its own: it becomes pending

    @property
    def deletes_ride(self):
        return not (self.corrections or self.overrides or self.other_sources)


def merge_effects(actor, source_id):
    owner = require_actor(actor)
    source = get_inventory(owner, ActivitySource, source_id)
    ride = get_inventory(owner, Ride, source.ride_id)
    others = ActivitySource.objects.filter(owner_id=owner.pk, ride_id=ride.pk).exclude(pk=source.pk)
    corrections = tuple(field for field in RIDE_FIELDS if field in ride.manual_overrides)
    overrides = UsageOverride.objects.filter(owner_id=owner.pk, ride_id=ride.pk).count()
    loses_start = "started_at" not in ride.manual_overrides and not others.filter(withdrawn_at__isnull=True).exists()
    return MergeEffects(corrections, overrides, others.count(), loses_start)


@dataclass(frozen=True)
class RemovalResult:
    sources: int
    deleted_rides: int
    kept_rides: int
    gear: int


def remove_strava_data(actor):
    """«Quitar lo sincronizado desde Strava»: every Strava source, gear link, the account row and its events.

    Rides whose only source rows were Strava and without manual measurement
    corrections are deleted with their usage; the others stay (pending if they
    lose their start). The next manual sync or import creates the account again.
    """
    with transaction.atomic():
        owner = _lock_owner(actor)
        sources = list(ActivitySource.objects.filter(owner_id=owner.pk, source_kind="strava").order_by("ride_id", "pk")
                       .values_list("pk", "ride_id"))
        ride_ids = {ride_id for _, ride_id in sources}
        ActivitySource.objects.filter(owner_id=owner.pk, source_kind="strava").delete()
        gear = StravaGear.objects.filter(owner_id=owner.pk).delete()[0]
        touched, deleted = set(), 0
        for ride in Ride.objects.filter(owner_id=owner.pk, pk__in=ride_ids).order_by("pk"):
            deleted += _drop_if_empty(owner, ride, touched)
        account = StravaAccount.objects.filter(owner_id=owner.pk).first()
        if account is not None:
            StravaEvent.objects.filter(athlete_id=account.athlete_id).delete()
            account.delete()
        rebuild_rides_locked(owner, touched)
        return RemovalResult(len(sources), deleted, len(touched), gear)


def ride_origins(owner, ride_ids):
    """{ride_id: (origin label, possible duplicate)} from active sources, in one query (read-only)."""
    kinds, duplicates = {}, set()
    for ride_id, kind, duplicate in ActivitySource.objects.filter(owner_id=owner.pk, ride_id__in=ride_ids, withdrawn_at__isnull=True
                                                                  ).values_list("ride_id", "source_kind", "possible_duplicate"):
        kinds.setdefault(ride_id, set()).add(kind)
        if duplicate:
            duplicates.add(ride_id)
    return {ride_id: (origin_label(kinds.get(ride_id, set())), ride_id in duplicates) for ride_id in ride_ids}


def origin_label(kinds):
    if {"fit", "strava"} <= kinds:
        return "Archivo FIT y Strava"
    if "fit" in kinds:
        return "Archivo FIT"
    if "strava" in kinds:
        return "Strava"
    return "Manual"

