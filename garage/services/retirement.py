"""Retire a bike or component together with what is mounted in it (garage-038)."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from garage.models import Bike, Item
from .baselines import _instant
from .ownership import InventoryWriteError, _lock_owner, get_inventory, retire_inventory
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
