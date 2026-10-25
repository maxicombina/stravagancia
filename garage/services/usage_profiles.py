"""Versioned defaults and explicit ride exceptions, resolved as UUID sets.

Ordinary changes capture server time under the owner lock and never rewrite an
old version. Explicit *_history APIs are the boundary for historical changes.
The resolver takes that same lock for a consistent snapshot of profile versions,
installations, retirement dates, ride corrections and manual overrides.
"""
from dataclasses import dataclass
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from garage.models import (Bike, Installation, Item, RetirementInterval, Ride, UsageOverride, UsageProfile, UsageProfileItem)
from garage.ride_values import aware_instant
from garage.sports import profile_covers
from .ownership import InventoryNotFound, InventoryWriteError, _lock_owner, get_inventory, scoped_inventory

_UNCHANGED = object()


def _error(field, message, code):
    return InventoryWriteError({field: ValidationError(message, code=code)})


def _mutate(actor, operation, *, rebuild=True):
    try:
        with transaction.atomic():
            owner = _lock_owner(actor)
            result = operation(owner)
            if rebuild:
                from .usage import _rebuild_all_locked
                _rebuild_all_locked(owner)
            return result
    except IntegrityError as error:
        constraint = getattr(getattr(error.__cause__, "diag", None), "constraint_name", None)
        if constraint == "garage_usageprofile_series_no_overlap":
            raise _error("started_at", "Profile versions in the same series cannot overlap.", "profile_overlap") from error
        if constraint == "garage_usageoverride_unique":
            raise _error("item", "This ride already has an exception for this item.", "override_conflict") from error
        if constraint == "garage_usageprofileitem_unique":
            raise _error("items", "Include each item once.", "duplicate_item") from error
        raise


def _instant(value, field, *, optional=False):
    if optional and value is None:
        return None
    try:
        return aware_instant(value)
    except ValidationError as error:
        raise InventoryWriteError({field: error}) from error


def _ordinary_start(at):
    now = timezone.now()
    value = now if at is None else _instant(at, "started_at")
    if value < now:
        raise _error("started_at", "Use an explicit historical operation for past dates.", "historical_change_required")
    return value


def _reference(owner, model, value, field, *, optional=False):
    if optional and value is None:
        return None
    try:
        return get_inventory(owner, model, value.pk if isinstance(value, model) else value)
    except InventoryNotFound:
        raise _error(field, "Choose one of your own resources.", "invalid_reference") from None


def _items(owner, values):
    if not isinstance(values, (list, tuple, set, frozenset)):
        raise _error("items", "Supply a collection of your items.", "invalid_items")
    resolved = {}
    for value in values:
        item = _reference(owner, Item, value, "items")
        resolved[item.pk] = item
    return list(resolved.values())


def _assign(owner, profile, values):
    allowed = {"name", "bike", "sport_type", "started_at", "ended_at", "notes"}
    for field, value in values.items():
        if field not in allowed:
            raise _error(field, "This field cannot be written.", "immutable_field" if field in {"id", "pk", "owner", "owner_id", "series_id"} else "invalid_field")
        if field == "bike":
            value = _reference(owner, Bike, value, field, optional=True)
        elif field in {"started_at", "ended_at"}:
            value = _instant(value, field, optional=field == "ended_at")
        elif field == "sport_type":
            if not isinstance(value, str):
                raise _error(field, "Use a modality key or a blank general modality.", "invalid_sport_type")
            value = value.strip().lower()
        setattr(profile, field, value)


def _validate(obj):
    try:
        obj.full_clean(validate_constraints=False)
    except ValidationError as error:
        raise InventoryWriteError(error.error_dict) from error


def _memberships(owner, profile, items):
    for item in items:
        membership = UsageProfileItem(owner=owner, profile=profile, item=item)
        _validate(membership)
        membership.save(force_insert=True)


def _create(owner, started_at, /, *, items, **values):
    if "started_at" in values:
        raise _error("started_at", "Choose at for an ordinary creation, or use the explicit historical API.", "immutable_field")
    members = _items(owner, items)
    profile = UsageProfile(owner=owner)
    _assign(owner, profile, {"started_at": started_at, **values})
    _validate(profile)
    profile.save(force_insert=True)
    _memberships(owner, profile, members)
    return profile


def create_profile(actor, /, *, items, at=None, **values):
    """Pass no at to use server time; supplied dates must be in the future."""
    return _mutate(actor, lambda owner: _create(owner, _ordinary_start(at), items=items, **values))


def create_profile_history(actor, /, *, items, started_at, **values):
    """Explicitly authorize a version whose validity can affect past rides."""
    return _mutate(actor, lambda owner: _create(owner, _instant(started_at, "started_at"), items=items, **values))


def _revise(owner, profile_id, at, items, values):
    previous = get_inventory(owner, UsageProfile, profile_id)
    if at <= previous.started_at or (previous.ended_at is not None and at >= previous.ended_at):
        raise _error("started_at", "Split strictly inside this profile version's interval.", "invalid_interval")
    members = (_items(owner, items) if items is not _UNCHANGED else
               _items(owner, list(scoped_inventory(owner, UsageProfileItem).filter(profile=previous).values_list("item_id", flat=True))))
    candidate = UsageProfile(owner=owner, series_id=previous.series_id, name=previous.name, bike=previous.bike,
                             sport_type=previous.sport_type, started_at=at, ended_at=previous.ended_at, notes=previous.notes)
    _assign(owner, candidate, values)
    # The split instant is fixed. A caller cannot move either interval via values.
    if candidate.started_at != at or candidate.ended_at != previous.ended_at:
        raise _error("started_at", "A revision inherits its split and existing end.", "immutable_field")
    _validate(candidate)
    previous.ended_at = at
    _validate(previous)
    previous.save(update_fields=["ended_at", "updated_at"])
    candidate.save(force_insert=True)
    _memberships(owner, candidate, members)
    return candidate


def revise_profile(actor, profile_id, /, *, at=None, items=_UNCHANGED, **values):
    """Close the old version and open a future one, keeping its series UUID."""
    return _mutate(actor, lambda owner: _revise(owner, profile_id, _ordinary_start(at), items, values))


def revise_profile_history(actor, profile_id, /, *, at, items=_UNCHANGED, **values):
    return _mutate(actor, lambda owner: _revise(owner, profile_id, _instant(at, "started_at"), items, values))


def update_profile_history(actor, profile_id, /, *, items=_UNCHANGED, **values):
    """Explicit correction of an existing version, not an ordinary default edit."""
    def operation(owner):
        profile = get_inventory(owner, UsageProfile, profile_id)
        members = _items(owner, items) if items is not _UNCHANGED else None
        _assign(owner, profile, values)
        _validate(profile)
        profile.save()
        if members is not None:
            scoped_inventory(owner, UsageProfileItem).filter(profile=profile).delete()
            _memberships(owner, profile, members)
        return profile
    return _mutate(actor, operation)


def delete_profile_history(actor, profile_id, /):
    return _mutate(actor, lambda owner: get_inventory(owner, UsageProfile, profile_id).delete())


def set_usage_override(actor, /, *, ride, item, action):
    def operation(owner):
        own_ride = _reference(owner, Ride, ride, "ride")
        own_item = _reference(owner, Item, item, "item")
        if not isinstance(action, str) or action not in UsageOverride.Action.values:
            raise _error("action", "Choose include or exclude.", "invalid_action")
        override = scoped_inventory(owner, UsageOverride).filter(ride=own_ride, item=own_item).first()
        if override is None:
            override = UsageOverride(owner=owner, ride=own_ride, item=own_item)
        override.action = action
        _validate(override)
        override.save()
        return override
    return _mutate(actor, operation)


def delete_usage_override(actor, override_id, /):
    return _mutate(actor, lambda owner: get_inventory(owner, UsageOverride, override_id).delete())


@dataclass(frozen=True)
class UsageReason:
    kind: str
    resource_id: UUID
    root_item_id: UUID


@dataclass(frozen=True)
class UsageResolution:
    item_ids: frozenset[UUID]
    provenance: dict[UUID, frozenset[UsageReason]]
    excluded_item_ids: frozenset[UUID]
    skipped_retired_item_ids: frozenset[UUID]
    unknown_started_at: bool


@dataclass(frozen=True)
class UsageResolverContext:
    owner_id: int
    items: dict
    bikes: dict
    retirement_intervals: tuple
    installations: tuple
    profiles: tuple
    memberships: tuple
    overrides_by_ride: dict


def _load_context(owner):
    """Private owner-scoped snapshot; caller holds the owner row lock."""
    overrides = {}
    for override in UsageOverride.objects.filter(owner_id=owner.pk).only("id", "ride_id", "item_id", "action"):
        overrides.setdefault(override.ride_id, []).append(override)
    return UsageResolverContext(owner.pk,
        {item.pk: item for item in Item.objects.filter(owner_id=owner.pk).only("id", "retired_at")},
        {bike.pk: bike for bike in Bike.objects.filter(owner_id=owner.pk).only("id", "retired_at")},
        tuple(RetirementInterval.objects.filter(owner_id=owner.pk)),
        tuple(Installation.objects.filter(owner_id=owner.pk).only("id", "item_id", "bike_id", "parent_item_id", "started_at", "ended_at")),
        tuple(UsageProfile.objects.filter(owner_id=owner.pk).only("id", "bike_id", "sport_type", "started_at", "ended_at")),
        tuple(UsageProfileItem.objects.filter(owner_id=owner.pk, profile__owner_id=owner.pk, item__owner_id=owner.pk)
              .values_list("profile_id", "item_id")), overrides)


def _resolve(owner, ride, *, context=None):
    at = ride.started_at
    if at is None:
        return UsageResolution(frozenset(), {}, frozenset(), frozenset(), True)
    context = _load_context(owner) if context is None else context
    if context.owner_id != owner.pk or ride.owner_id != owner.pk:
        raise _error("ride", "Use this owner's resolution snapshot.", "invalid_reference")
    owned_items = context.items
    retired = {pk for pk, item in owned_items.items() if item.retired_at is not None and item.retired_at <= at}
    inactive = [interval for interval in context.retirement_intervals if interval.started_at <= at < interval.ended_at]
    retired.update(interval.item_id for interval in inactive if interval.item_id is not None)
    available = set(owned_items) - retired
    edges = {}
    roots = []
    bike = context.bikes.get(ride.bike_id)
    bike_available = (bike is not None and (bike.retired_at is None or bike.retired_at > at)
                      and not any(interval.bike_id == ride.bike_id for interval in inactive))
    for installation in context.installations:
        if installation.started_at > at or (installation.ended_at is not None and installation.ended_at <= at):
            continue
        if installation.parent_item_id is not None:
            edges.setdefault(installation.parent_item_id, set()).add(installation.item_id)
        elif bike_available and installation.bike_id == ride.bike_id:
            roots.append((installation.item_id, UsageReason("bike_installation", installation.pk, installation.item_id)))
    # Family matching (garage-030): `cycling` covers every cycling key, a specific key only itself.
    profiles = {profile.pk for profile in context.profiles if profile.started_at <= at
                and (profile.ended_at is None or profile.ended_at > at)
                and (profile.bike_id is None or (bike_available and profile.bike_id == ride.bike_id))
                and profile_covers(profile.sport_type, ride.sport_type)}
    for profile_id, item_id in context.memberships:
        if profile_id in profiles:
            roots.append((item_id, UsageReason("profile", profile_id, item_id)))
    overrides = [override for override in context.overrides_by_ride.get(ride.pk, ()) if override.item_id in owned_items]
    explicitly_excluded = {override.item_id for override in overrides if override.action == UsageOverride.Action.EXCLUDE}
    includes = [override for override in overrides if override.action == UsageOverride.Action.INCLUDE]
    reasons = {}
    skipped = set()

    def walk(root, *, stop_excluded=False):
        found = set()
        pending = [root]
        while pending:
            node = pending.pop()
            if node in found:
                continue
            if node in retired:
                skipped.add(node)
                continue
            if node not in available or (stop_excluded and node in explicitly_excluded):
                continue
            found.add(node)
            pending.extend(edges.get(node, ()))
        return found

    for root, reason in roots:
        for item_id in walk(root):
            reasons.setdefault(item_id, set()).add(reason)
    excluded = set()
    for root in explicitly_excluded:
        excluded.update(walk(root))
    resolved = set(reasons) - excluded
    # Each explicit inclusion restores its subtree until another explicit
    # exclusion. A still deeper explicit inclusion can restore the next branch.
    for override in includes:
        reason = UsageReason("manual_include", override.pk, override.item_id)
        for item_id in walk(override.item_id, stop_excluded=True):
            resolved.add(item_id)
            reasons.setdefault(item_id, set()).add(reason)
    resolved -= explicitly_excluded
    return UsageResolution(frozenset(resolved), {item_id: frozenset(reasons[item_id]) for item_id in resolved},
                           frozenset(excluded - resolved), frozenset(skipped), False)


def resolve_ride_usage(actor, ride_id, /):
    """Pure result, no ItemUsage rows or incremental counters are written."""
    return _mutate(actor, lambda owner: _resolve(owner, get_inventory(owner, Ride, ride_id)), rebuild=False)
