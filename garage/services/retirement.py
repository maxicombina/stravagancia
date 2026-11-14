"""Retire a bike or component together with what is mounted in it (garage-038)."""
from dataclasses import dataclass
from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from garage.models import Bike, Installation, Item
from .baselines import _instant
from .ownership import InventoryWriteError, _lock_owner, get_inventory, retire_inventory, scoped_inventory
from .parts import _scope


class PartsChanged(InventoryWriteError):
    """What is mounted at the chosen date differs from the list shown: nothing was retired."""

    def __init__(self, message, ids):
        super().__init__({"__all__": message})
        self.ids = ids


def mounted_in(actor, target, *, at=None):
    """Items mounted in the bike or item at `at`, directly or nested, parents first (the target excluded)."""
    at = _instant(timezone.now() if at is None else at, "at")
    with transaction.atomic():
        owner = _lock_owner(actor)
        target = get_inventory(owner, Bike if isinstance(target, Bike) else Item, target.pk)
        return [obj for obj, _ in _scope(owner, target, at)[1:]]


def direct_parts(actor, item, *, at=None):
    """Items mounted directly inside `item` at `at`: retiring it unmounts these (their own parts stay in them)."""
    at = _instant(timezone.now() if at is None else at, "at")
    with transaction.atomic():
        owner = _lock_owner(actor)
        item = get_inventory(owner, Item, getattr(item, "pk", item))
        return [obj for obj, parent in _scope(owner, item, at)[1:] if parent is not None and parent.pk == item.pk]


@dataclass(frozen=True)
class RetirementPreview:
    """What retiring would close and the earliest instant its mounts allow (garage-047 F04)."""
    mount: Installation | None  # an item's own open mount; a bike has none
    closes_others: bool  # open mounts of what is mounted in it close too
    limit: datetime | None  # retiring needs an instant after this one
    limit_with_parts: datetime | None  # the same when the parts given are retired with it
    ends_later: bool = False  # without an open mount, mounted at that instant until a later end: retiring closes none of it


def _checked(objects):
    """The mounts that retiring each of `objects` checks before closing any (_close_for_retirement)."""
    query = Q(pk__in=())
    for obj in objects:
        query |= Q(bike_id=obj.pk) if isinstance(obj, Bike) else Q(item_id=obj.pk) | Q(parent_item_id=obj.pk)
    return query


def _limit(owner, objects):
    bounds = scoped_inventory(owner, Installation).filter(_checked(objects)).aggregate(start=Max("started_at"), end=Max("ended_at"))
    return max((value for value in bounds.values() if value is not None), default=None)


def retirement_preview(actor, target, *, parts=(), at=None):
    """Read only. Each mount that retiring checks must start before the instant and not end after it, so
    the latest of their starts and ends bounds it. With `parts` (what the page offers to retire with it),
    the same over them too: each part checks its own mounts and those of what is mounted in it.

    The limit is necessary, not sufficient: a recorded inactivity period refuses with another rule, and
    the history may change before saving. The server's error on saving is what counts.

    `at` (default now) is the instant whose state `ends_later` reads, as the item's screen does: a mount
    that started by then and ends after it, like those of a bike whose retirement is already set.
    """
    at = _instant(timezone.now() if at is None else at, "at")
    model = Bike if isinstance(target, Bike) else Item
    with transaction.atomic():
        owner = _lock_owner(actor)
        target = get_inventory(owner, model, target.pk)
        mounts = scoped_inventory(owner, Installation)
        open_mounts = mounts.filter(_checked([target]), ended_at__isnull=True)
        mount = None if model is Bike else open_mounts.filter(item_id=target.pk).select_related("bike", "parent_item").first()
        others = open_mounts if model is Bike else open_mounts.exclude(item_id=target.pk)
        ends_later = model is Item and mount is None and mounts.filter(item_id=target.pk, started_at__lte=at, ended_at__gt=at).exists()
        return RetirementPreview(mount=mount, closes_others=others.exists(), limit=_limit(owner, [target]),
                                 limit_with_parts=_limit(owner, [target, *parts]) if parts else None, ends_later=ends_later)


MESSAGES = {
    "retirement_conflict": "tiene montajes que empiezan o terminan después. Corrígelos en su historial o elige una fecha posterior.",
    "retirement_overlap": "se solapa con un período inactivo ya registrado. Elige otra fecha.",
}


def retire_one(actor, obj, *, at):
    """retire_inventory with a Spanish message that names what blocks it."""
    try:
        return retire_inventory(actor, type(obj), obj.pk, at=at)
    except ValidationError as error:
        groups = error.error_dict.values() if hasattr(error, "error_dict") else [error.error_list]
        code = next((entry.code for entries in groups for entry in entries if getattr(entry, "code", None) in MESSAGES), None)
        if code:
            raise InventoryWriteError({"__all__": f"No se puede retirar {obj.name} en esa fecha: {MESSAGES[code]}"}) from error
        raise


def retire_with_parts(actor, target, *, at, parts=False, expected=None):
    """Retire the target and, with `parts`, everything mounted in it at `at`; all or nothing.

    The list is taken before anything closes: retiring the target closes the
    mounts of its direct parts, which would hide them from a later look. With
    `expected` (the ids the person saw), a different list at that date stops it.
    """
    at = _instant(at, "retired_at")
    model = Bike if isinstance(target, Bike) else Item
    with transaction.atomic():
        owner = _lock_owner(actor)
        target = get_inventory(owner, model, target.pk)
        inside = [obj for obj, _ in _scope(owner, target, at)[1:]] if parts else []
        if parts and expected is not None and {obj.pk for obj in inside} != set(expected):
            names = ", ".join(obj.name for obj in inside) or "nada"
            raise PartsChanged(f"En esa fecha lo montado es: {names}. Revísalo y vuelve a guardar.", [obj.pk for obj in inside])
        retire_one(owner, target, at=at)
        for item in inside:
            retire_one(owner, item, at=at)
        return inside
