"""Temporal installations: [start, end), owner locking and immediate SQL exclusions.

All writes, including multi-step transitions and inventory retirement, hold the
owner row lock. Raw SQL/model saves cannot guarantee relationship ownership or
temporal acyclicity and are outside the authorized write interface.
"""
from datetime import datetime, timezone as datetime_timezone
import re

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from garage.models import Bike, Installation, Item
from .ownership import InventoryNotFound, InventoryWriteError, _lock_owner, get_inventory, scoped_inventory

_UNCHANGED = object()
_OVERLAP_CODES = {
    "garage_installation_item_no_overlap": ("item", "installation_overlap", "This item is already installed during this period."),
    "garage_installation_bike_slot_no_overlap": ("slot", "slot_occupied", "This position is occupied during this period."),
    "garage_installation_parent_slot_no_overlap": ("slot", "slot_occupied", "This position is occupied during this period."),
}


def _error(field, message, code):
    return InventoryWriteError({field: ValidationError(message, code=code)})


def _instant(value, field, *, optional=False):
    if optional and value is None:
        return None
    if not isinstance(value, datetime) or timezone.is_naive(value):
        raise _error(field, "Enter an instant with an explicit time zone.", "invalid_instant")
    return value.astimezone(datetime_timezone.utc)


def _mutate(actor, operation):
    try:
        with transaction.atomic():
            owner = _lock_owner(actor)
            result = operation(owner)
            from .usage import _rebuild_all_locked
            _rebuild_all_locked(owner)
            return result
    except IntegrityError as error:
        name = getattr(getattr(error.__cause__, "diag", None), "constraint_name", None)
        if name in _OVERLAP_CODES:
            field, code, message = _OVERLAP_CODES[name]
            raise _error(field, message, code) from error
        raise


def _assign(owner, obj, values):
    allowed = {"item", "bike", "parent_item", "slot", "started_at", "ended_at", "notes"}
    for name in values:
        if name not in allowed:
            code = "immutable_field" if name in {"id", "pk", "owner", "owner_id", "created_at", "updated_at"} else "invalid_field"
            raise _error(name, "This field cannot be written.", code)
    for name, value in values.items():
        if name in {"item", "bike", "parent_item"}:
            model = Bike if name == "bike" else Item
            if value is None and name != "item":
                setattr(obj, name, None)
                continue
            resource_id = value.pk if isinstance(value, model) else value
            try:
                value = get_inventory(owner, model, resource_id)
            except InventoryNotFound:
                raise _error(name, "Choose one of your own resources.", "invalid_reference") from None
        elif name in {"started_at", "ended_at"}:
            value = _instant(value, name, optional=name == "ended_at")
        elif name == "slot":
            if value == "":
                value = None
            if value is not None and (not isinstance(value, str) or len(value) > 80 or not re.fullmatch(r"[a-z0-9_]+", value)):
                raise _error(name, "Use a lowercase ASCII position key.", "invalid_slot")
        setattr(obj, name, value)


def _validate_temporal_cycle(owner, candidate):
    if candidate.parent_item_id is None:
        return
    edges = {}
    rows = scoped_inventory(owner, Installation).filter(parent_item__isnull=False).exclude(pk=candidate.pk)
    for item_id, parent_id, start, end in rows.values_list("item_id", "parent_item_id", "started_at", "ended_at"):
        edges.setdefault(item_id, []).append((parent_id, start, end))
    pending = [(candidate.parent_item_id, candidate.started_at, candidate.ended_at)]
    visited = set()
    while pending:
        node, lower, upper = pending.pop()
        state = (node, lower, upper)
        if state in visited:
            continue
        visited.add(state)
        if node == candidate.item_id:
            raise _error("parent_item", "These installations form a cycle during a common period.", "installation_cycle")
        for parent, start, end in edges.get(node, ()):
            intersection_start = max(lower, start)
            intersection_end = end if upper is None else upper if end is None else min(upper, end)
            if intersection_end is None or intersection_start < intersection_end:
                pending.append((parent, intersection_start, intersection_end))


def _validate(owner, obj):
    try:
        obj.full_clean(validate_constraints=False)
    except ValidationError as error:
        raise InventoryWriteError(error.error_dict) from error
    _validate_temporal_cycle(owner, obj)


def _create(owner, values):
    obj = Installation(owner=owner)
    _assign(owner, obj, values)
    _validate(owner, obj)
    obj.save(force_insert=True)
    return obj


def create_installation(actor, /, **values):
    return _mutate(actor, lambda owner: _create(owner, values))


def update_installation(actor, installation_id, /, **values):
    def operation(owner):
        obj = get_inventory(owner, Installation, installation_id)
        _assign(owner, obj, values)
        _validate(owner, obj)
        obj.save(force_update=True)
        return obj
    return _mutate(actor, operation)


def close_installation(actor, installation_id, *, at):
    def operation(owner):
        obj = get_inventory(owner, Installation, installation_id)
        end = _instant(at, "ended_at")
        if obj.ended_at is not None:
            if obj.ended_at == end:
                return obj
            raise _error("ended_at", "This installation is already closed; edit it explicitly to correct history.", "installation_closed")
        obj.ended_at = end
        _validate(owner, obj)
        obj.save(force_update=True)
        return obj
    return _mutate(actor, operation)


def delete_installation(actor, installation_id):
    def operation(owner):
        obj = get_inventory(owner, Installation, installation_id)
        obj.delete()
    return _mutate(actor, operation)


def _transition(owner, installation_id, *, at, incoming_item, bike, parent_item, slot, ended_at, notes):
    outgoing = get_inventory(owner, Installation, installation_id)
    instant = _instant(at, "started_at")
    if instant <= outgoing.started_at or (outgoing.ended_at is not None and instant >= outgoing.ended_at):
        raise _error("started_at", "Choose an instant strictly inside the outgoing installation.", "invalid_transition")
    original_end = outgoing.ended_at
    outgoing.ended_at = instant
    _validate(owner, outgoing)
    outgoing.save(force_update=True)
    values = {
        "item": outgoing.item_id if incoming_item is _UNCHANGED else incoming_item,
        "bike": outgoing.bike_id if bike is _UNCHANGED else bike,
        "parent_item": outgoing.parent_item_id if parent_item is _UNCHANGED else parent_item,
        "slot": outgoing.slot if slot is _UNCHANGED else slot,
        "started_at": instant,
        # A bounded outgoing period never becomes infinite by default.
        "ended_at": original_end if ended_at is _UNCHANGED else ended_at,
        "notes": notes,
    }
    incoming = _create(owner, values)
    return outgoing, incoming


def replace_installation(actor, installation_id, *, incoming_item, at, ended_at=_UNCHANGED, notes=""):
    return _mutate(actor, lambda owner: _transition(owner, installation_id, at=at, incoming_item=incoming_item,
        bike=_UNCHANGED, parent_item=_UNCHANGED, slot=_UNCHANGED, ended_at=ended_at, notes=notes))


def transfer_installation(actor, installation_id, *, at, bike=None, parent_item=None, slot=_UNCHANGED,
                          ended_at=_UNCHANGED, notes=""):
    return _mutate(actor, lambda owner: _transition(owner, installation_id, at=at, incoming_item=_UNCHANGED,
        bike=bike, parent_item=parent_item, slot=slot, ended_at=ended_at, notes=notes))


def _close_for_retirement(owner, resource, at):
    """Called only from inventory update, already holding its owner lock."""
    query = Q(bike_id=resource.pk) if isinstance(resource, Bike) else Q(item_id=resource.pk) | Q(parent_item_id=resource.pk)
    installations = list(scoped_inventory(owner, Installation).filter(query))
    # Validate the complete history before changing any open period. Closing at
    # its start would erase history; a future closed period needs explicit edit.
    if any(obj.started_at >= at or (obj.ended_at is not None and obj.ended_at > at) for obj in installations):
        raise _error("retired_at", "Correct later or empty installations explicitly before retiring this resource.",
                     "retirement_conflict")
    for obj in installations:
        if obj.ended_at is None:
            obj.ended_at = at
            obj.save(update_fields=("ended_at", "updated_at"))
