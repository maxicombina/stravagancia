"""Review one ride from the phone: its bike and the rider gear that counted.

Candidates are recomputed by the server: owned items available at the ride
start (not retired, no retirement interval), not mounted at that instant, and
either in a usage profile valid then or already carrying an exception on this
ride. Exceptions of non-candidates (e.g. mounted components) are never touched.
A save applies the bike correction and the candidate exceptions under the owner
lock and rebuilds usage once, mirroring the public services' result.
"""
from copy import copy
from dataclasses import dataclass, replace
from decimal import Decimal
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from garage.models import ActivitySource, Bike, Item, Ride, UsageMaterializationState, UsageOverride
from garage.ride_values import decode_manual
from garage.sports import profile_covers
from .ownership import InventoryNotFound, InventoryWriteError, _lock_owner, get_inventory, scoped_inventory
from .usage_profiles import _load_context, _resolve

UNCHANGED = object()
NO_BIKE = "none"


def _error(field, message, code):
    return InventoryWriteError({field: ValidationError(message, code=code)})


def bike_key(bike_id):
    return NO_BIKE if bike_id is None else str(bike_id)


@dataclass(frozen=True)
class Candidate:
    item: Item
    usual: frozenset          # bike keys whose usual resolution includes the item
    selected: bool            # counts in the reviewed state (current or hypothetical)
    override: str | None      # current exception action on this ride


@dataclass(frozen=True)
class Effect:
    label: str
    icon: str
    target: object
    sign: int
    distance_m: Decimal | None
    moving_time_s: Decimal | None
    elevation_gain_m: Decimal | None = None


@dataclass(frozen=True)
class ReviewState:
    ride: Ride
    resolvable: bool
    bikes: tuple
    current_key: str
    bike_decided: bool
    selected_key: str
    candidates: tuple
    effects: tuple
    stale_includes: tuple
    mounted: int
    changed: bool
    explicit_bike: bool = False
    source: str = ""

    @property
    def selected_gear(self):
        return frozenset(candidate.item.pk for candidate in self.candidates if candidate.selected)


@dataclass(frozen=True)
class ReviewResult:
    ride: Ride
    bike_changed: bool
    overrides_changed: bool


def _available(context, at, *, item_id=None, bike_id=None):
    model = context.items.get(item_id) if item_id is not None else context.bikes.get(bike_id)
    if model is None or (model.retired_at is not None and model.retired_at <= at):
        return False
    field = "item_id" if item_id is not None else "bike_id"
    value = item_id if item_id is not None else bike_id
    return not any(getattr(interval, field) == value and interval.started_at <= at < interval.ended_at
                   for interval in context.retirement_intervals)


def _candidate_ids(context, ride):
    at = ride.started_at
    mounted = {installation.item_id for installation in context.installations
               if installation.started_at <= at and (installation.ended_at is None or installation.ended_at > at)}
    valid_profiles = {profile.pk for profile in context.profiles
                      if profile.started_at <= at and (profile.ended_at is None or profile.ended_at > at)
                      and profile_covers(profile.sport_type, ride.sport_type)}
    in_profiles = {item_id for profile_id, item_id in context.memberships if profile_id in valid_profiles}
    with_override = {override.item_id for override in context.overrides_by_ride.get(ride.pk, ())}
    return {item_id for item_id in in_profiles | with_override
            if item_id not in mounted and _available(context, at, item_id=item_id)}


def _with_overrides(context, ride, overrides):
    return replace(context, overrides_by_ride={**context.overrides_by_ride, ride.pk: list(overrides)})


def _hypothetical(ride, bike_id):
    copy_ride = copy(ride)
    copy_ride.bike_id = bike_id
    return copy_ride


def _plan(owner, context, ride, candidates, bike_id, gear):
    """Desired candidate exceptions for bike_id and the gear that must count."""
    others = [override for override in context.overrides_by_ride.get(ride.pk, ()) if override.item_id not in candidates]
    base = _resolve(owner, _hypothetical(ride, bike_id), context=_with_overrides(context, ride, others)).item_ids
    desired = {}
    for item_id in candidates:
        if item_id in gear and item_id not in base:
            desired[item_id] = UsageOverride.Action.INCLUDE
        elif item_id not in gear and item_id in base:
            desired[item_id] = UsageOverride.Action.EXCLUDE
    synthetic = others + [UsageOverride(owner_id=owner.pk, ride_id=ride.pk, item_id=item_id, action=action)
                          for item_id, action in desired.items()]
    return desired, others, _with_overrides(context, ride, synthetic)


def _bike_value(owner, bike, *, context=None, ride=None):
    if bike is UNCHANGED or bike is None:
        return bike
    try:
        pk = get_inventory(owner, Bike, getattr(bike, "pk", bike)).pk
    except (InventoryNotFound, ValidationError, ValueError):
        raise _error("bike", "Elige una de tus bicis.", "invalid_reference") from None
    if context is not None and pk != ride.bike_id and not _available(context, ride.started_at, bike_id=pk):
        raise _error("bike", "Esa bici estaba retirada en la fecha de la salida.", "retired_reference")
    return pk


def _mount_root(context, item_id, at):
    """Bike that carries item_id at instant at (following nested mounts), or None."""
    parents = {i.item_id: (i.bike_id, i.parent_item_id) for i in context.installations
               if i.started_at <= at and (i.ended_at is None or i.ended_at > at)}
    seen = set()
    while item_id in parents and item_id not in seen:
        seen.add(item_id)
        bike_id, parent_id = parents[item_id]
        if bike_id is not None:
            return bike_id
        item_id = parent_id
    return None


def _source(ride):
    """Origin from the active sources (garage-030); a source-less ride is manual only if it was corrected by hand."""
    from .strava_sources import origin_label
    kinds = set(ActivitySource.objects.filter(owner_id=ride.owner_id, ride_id=ride.pk, withdrawn_at__isnull=True)
                .values_list("source_kind", flat=True))
    if kinds:
        return origin_label(kinds)
    manual = {entry.get("kind") for entry in (ride.field_provenance or {}).values() if isinstance(entry, dict)}
    return "Manual" if "manual" in manual else ""


def _gear_ids(gear):
    try:
        return frozenset(value if isinstance(value, UUID) else UUID(str(getattr(value, "pk", value))) for value in gear)
    except (TypeError, ValueError, AttributeError):
        raise _error("gear", "Elige material de la lista.", "invalid_reference") from None


def _bikes(owner, context, at):
    return tuple(bike for bike in Bike.objects.filter(owner=owner).order_by("name", "id")
                 if _available(context, at, bike_id=bike.pk))


def review_state(actor, ride_id, /, *, bike=UNCHANGED, gear=None):
    """Current or hypothetical review of one ride. Read-only."""
    with transaction.atomic():
        owner = _lock_owner(actor)
        ride = get_inventory(owner, Ride, ride_id)
        manual = decode_manual(ride.manual_overrides)
        if ride.started_at is None:
            return ReviewState(ride, False, (), bike_key(ride.bike_id), "bike" in manual, bike_key(ride.bike_id), (), (), (), 0, False,
                               source=_source(ride))
        context = _load_context(owner)
        bikes = _bikes(owner, context, ride.started_at)
        candidates = _candidate_ids(context, ride)
        selected_bike = ride.bike_id if bike is UNCHANGED else _bike_value(owner, bike, context=context, ride=ride)
        current = _resolve(owner, ride, context=context).item_ids
        usual = {}
        for option in [None, *[b.pk for b in bikes]]:
            others = [o for o in context.overrides_by_ride.get(ride.pk, ()) if o.item_id not in candidates]
            for item_id in _resolve(owner, _hypothetical(ride, option), context=_with_overrides(context, ride, others)).item_ids & candidates:
                usual.setdefault(item_id, set()).add(bike_key(option))
        if gear is None:
            chosen = (current & candidates) if bike is UNCHANGED else frozenset(
                item_id for item_id in candidates if bike_key(selected_bike) in usual.get(item_id, ()))
        else:
            chosen = _gear_ids(gear)
            if not chosen <= candidates:
                raise _error("gear", "Elige material de la lista.", "invalid_reference")
        _, others, planned = _plan(owner, context, ride, candidates, selected_bike, chosen)
        resolution = _resolve(owner, _hypothetical(ride, selected_bike), context=planned)
        after = resolution.item_ids
        mounted = sum(any(reason.kind == "bike_installation" for reason in resolution.provenance.get(item_id, ())) for item_id in after)
        changed_ids = (after - current) | (current - after)
        # Exceptions that keep counting a component carried by another bike than the selected one.
        stale_ids = {o.item_id for o in others if o.action == UsageOverride.Action.INCLUDE
                     and _mount_root(context, o.item_id, ride.started_at) not in (None, selected_bike)}
        items = {item.pk: item for item in Item.objects.filter(owner=owner, pk__in=candidates | changed_ids | stale_ids).select_related("category")}
        overrides = {override.item_id: override.action for override in context.overrides_by_ride.get(ride.pk, ())}
        effects = []
        if selected_bike != ride.bike_id:
            names = {b.pk: b for b in Bike.objects.filter(owner=owner, pk__in=[pk for pk in (ride.bike_id, selected_bike) if pk])}
            if ride.bike_id in names:
                effects.append(Effect(names[ride.bike_id].name, "bike", names[ride.bike_id], -1, ride.distance_m, ride.moving_time_s,
                                      ride.elevation_gain_m))
            if selected_bike in names:
                effects.append(Effect(names[selected_bike].name, "bike", names[selected_bike], 1, ride.distance_m, ride.moving_time_s,
                                      ride.elevation_gain_m))
        for item_id in sorted(changed_ids, key=lambda pk: (items[pk].name.lower(), str(pk))):
            effects.append(Effect(items[item_id].name, "item", items[item_id], 1 if item_id in after else -1, ride.distance_m,
                                  ride.moving_time_s, ride.elevation_gain_m))
        stale = tuple(sorted((items[item_id] for item_id in stale_ids), key=lambda item: (item.name.lower(), str(item.pk))))
        bike_write = bike is not UNCHANGED and ("bike" not in manual or ride.bike_id != selected_bike)
        candidate_rows = tuple(Candidate(items[item_id], frozenset(usual.get(item_id, ())), item_id in chosen, overrides.get(item_id))
                               for item_id in sorted(candidates, key=lambda pk: (items[pk].name.lower(), str(pk))))
        return ReviewState(ride, True, bikes, bike_key(ride.bike_id), "bike" in manual, bike_key(selected_bike), candidate_rows,
                           tuple(effects), stale, mounted, bool(changed_ids) or bike_write, bike is not UNCHANGED, _source(ride))


def review_ride(actor, ride_id, /, *, bike, gear):
    """Save the reviewed bike and gear for one ride, with a single usage rebuild."""
    from . import rides as ride_service
    from .usage import _rebuild_all_locked, _rebuild_ride_locked
    with transaction.atomic():
        owner = _lock_owner(actor)
        ride = get_inventory(owner, Ride, ride_id)
        if ride.started_at is None:
            raise _error("ride", "La salida no tiene inicio conocido; corrígela antes de revisar su material.", "start_required")
        context = _load_context(owner)
        candidates = _candidate_ids(context, ride)
        chosen = _gear_ids(gear)
        if not chosen <= candidates:
            raise _error("gear", "Elige material de la lista.", "invalid_reference")
        manual = decode_manual(ride.manual_overrides)
        selected_bike = ride.bike_id if bike is UNCHANGED else _bike_value(owner, bike, context=context, ride=ride)
        desired, _, _ = _plan(owner, context, ride, candidates, selected_bike, chosen)
        existing = {override.item_id: override for override in
                    scoped_inventory(owner, UsageOverride).filter(ride=ride, item_id__in=candidates)}
        overrides_changed = False
        for item_id in candidates:
            action, current = desired.get(item_id), existing.get(item_id)
            if action is None and current is not None:
                current.delete()
                overrides_changed = True
            elif action is not None and (current is None or current.action != action):
                override = current or UsageOverride(owner=owner, ride=ride, item_id=item_id)
                override.action = action
                try:
                    override.full_clean()
                except ValidationError as error:
                    raise InventoryWriteError(error.error_dict) from error
                override.save()
                overrides_changed = True
        bike_changed = bike is not UNCHANGED and ("bike" not in manual or ride.bike_id != selected_bike)
        if bike_changed:
            # Same semantics as correct_ride(bike=...): manual provenance, rebuild deferred.
            ride.manual_overrides = ride.manual_overrides | ride_service._manual_values(owner, {"bike": selected_bike})
            ride.field_provenance["bike"] = {"kind": "manual", "source_id": None, "updated_at": timezone.now().isoformat()}
            ride = ride_service._recalculate(owner, ride, rebuild=False)
        initialized = UsageMaterializationState.objects.filter(owner=owner, initialized_at__isnull=False).exists()
        if overrides_changed and not initialized:
            _rebuild_all_locked(owner)
        elif overrides_changed or bike_changed:
            _rebuild_ride_locked(owner, ride)
        return ReviewResult(ride, bike_changed, overrides_changed)


def resolve_rides(actor, rides):
    """One locked snapshot to resolve the material of several rides (list pages)."""
    with transaction.atomic():
        owner = _lock_owner(actor)
        context = _load_context(owner)
        return {ride.pk: _resolve(owner, ride, context=context) for ride in rides if ride.owner_id == owner.pk}
