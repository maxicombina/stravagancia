"""Parts mounted inside other items (garage-035): what is mounted where, and servicing them together.

Nothing new is stored: parts are installations with a parent item. Servicing
together records one ordinary intervention per chosen rule; nothing is reset
implicitly, because each intervention restarts one specific rule. Gear that only
counts through usage profiles (helmet, shoes) is not mounted and never a part.
"""
from collections import defaultdict

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from garage.models import Bike, Installation, Item, MaintenanceRule, ServiceEvent
from .baselines import _instant
from .installations import create_installation
from .maintenance import save_maintenance
from .ownership import InventoryWriteError, _lock_owner, get_inventory

SPANISH = {
    "installation_cycle": "Esa pieza ya contiene a este objeto en esas fechas: se formaría un ciclo.",
    "installation_overlap": "Esa pieza ya está montada en esas fechas. Desmóntala o muévela desde su ficha.",
    "slot_occupied": "Esa posición ya está ocupada en esas fechas.",
    "resource_retired": "Uno de los dos está retirado o inactivo en esas fechas.",
    "invalid_reference": "Elige un objeto propio.",
    "invalid_instant": "Indica una fecha válida.",
}


class ScopeChanged(InventoryWriteError):
    """What is mounted at the chosen date differs from the list the person saw: nothing is saved."""


def _open(owner, at):
    return list(Installation.objects.filter(owner=owner, started_at__lte=at).filter(Q(ended_at__isnull=True) | Q(ended_at__gt=at))
                .select_related("item__category", "parent_item", "bike").order_by("started_at", "id"))


def _active(obj, at):
    return obj.retired_at is None or obj.retired_at > at


def _scope(owner, target, at):
    children = defaultdict(list)
    for mount in _open(owner, at):
        children[("bike", mount.bike_id) if mount.bike_id else ("item", mount.parent_item_id)].append(mount)
    if not _active(target, at):
        return []
    result, seen = [(target, None)], {target.pk}

    def walk(key, parent):
        for mount in sorted(children.get(key, ()), key=lambda m: (m.item.name.lower(), str(m.item_id))):
            if mount.item_id in seen or not _active(mount.item, at):
                continue  # inconsistent data or a retired part: never followed
            seen.add(mount.item_id)
            result.append((mount.item, parent))
            walk(("item", mount.item_id), mount.item)
    walk(("bike" if isinstance(target, Bike) else "item", target.pk), target if isinstance(target, Item) else None)
    return result


def _rules(owner, places):
    order = {obj.pk: index for index, (obj, _) in enumerate(places)}
    parents = {obj.pk: parent for obj, parent in places}
    rules = MaintenanceRule.objects.filter(owner=owner).filter(
        Q(item_id__in=[obj.pk for obj, _ in places if isinstance(obj, Item)]) |
        Q(bike_id__in=[obj.pk for obj, _ in places if isinstance(obj, Bike)])).select_related("item__category", "bike", "service_type")
    return sorted(((rule, parents[rule.item_id or rule.bike_id]) for rule in rules),
                  key=lambda pair: (order[pair[0].item_id or pair[0].bike_id], pair[0].service_type.name.lower(), str(pair[0].pk)))


def scope(actor, target, *, at=None):
    """[(target, None), (part, parent item or None), ...]: the target and what is mounted in it at `at`.

    Any depth, parents before their parts. For a bike, what is mounted on it
    directly (parent None) and nested. Retired objects are left out.
    """
    at = _instant(timezone.now() if at is None else at, "at")
    with transaction.atomic():
        owner = _lock_owner(actor)
        target = get_inventory(owner, Bike if isinstance(target, Bike) else Item, target.pk)
        return _scope(owner, target, at)


def scope_rules(actor, target, *, at=None):
    """[(rule, part's parent or None)] for every rule of the target and of what is mounted in it at `at`."""
    at = _instant(timezone.now() if at is None else at, "at")
    with transaction.atomic():
        owner = _lock_owner(actor)
        target = get_inventory(owner, Bike if isinstance(target, Bike) else Item, target.pk)
        return _rules(owner, _scope(owner, target, at))


def register_together(actor, main, rule_ids, *, shown):
    """One more intervention per chosen rule: same date and notes as `main`, no amount.

    Call inside the transaction that saved `main`, so that an error undoes all.
    The scope is what was mounted in main's target at its date; if it differs
    from the rules the person saw (`shown`), ScopeChanged is raised. A rule with
    main's own target and type is skipped. Returns the interventions created.
    """
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("register_together must run inside the transaction that saved the main intervention.")
    owner = _lock_owner(actor)
    rule_ids = list(dict.fromkeys(rule_ids))
    if rule_ids and main.performed_at > timezone.now():
        raise InventoryWriteError({"__all__": "Para registrar también en las piezas, la fecha no puede ser futura."})
    if not rule_ids:
        return []  # only the main intervention: nothing to compare
    target = main.item or main.bike
    in_scope = {rule.pk: rule for rule, _ in _rules(owner, _scope(owner, target, main.performed_at))}
    if set(in_scope) != set(shown):
        raise ScopeChanged({"__all__": "Con esa fecha cambian las piezas montadas: revisa la lista y vuelve a guardar."})
    created = []
    for rule_id in rule_ids:
        rule = in_scope.get(rule_id)
        if rule is None:
            raise InventoryWriteError({"__all__": "Elige una opción válida."})
        if (rule.item_id, rule.bike_id, rule.service_type_id) == (main.item_id, main.bike_id, main.service_type_id):
            continue
        created.append(save_maintenance(owner, ServiceEvent, item=rule.item, bike=rule.bike, service_type=rule.service_type,
                                        performed_at=main.performed_at, notes=main.notes))
    return created


def ancestors(actor, item, *, at=None):
    """Item ids that contain `item` at `at`, from its parent up."""
    at = _instant(timezone.now() if at is None else at, "at")
    with transaction.atomic():
        owner = _lock_owner(actor)
        item = get_inventory(owner, Item, getattr(item, "pk", item))
        parent = {mount.item_id: mount.parent_item_id for mount in _open(owner, at) if mount.parent_item_id}
    result, current = [], item.pk
    while current in parent and parent[current] not in result and parent[current] != item.pk:
        current = parent[current]
        result.append(current)
    return result


def placement(actor, item, *, at=None):
    """(direct parts of `item`, the bike it is on through its parents or None) at `at`, in one query.

    A display read of an already owned item, like the other blocks of its screen:
    one query, without the owner lock that writes and due snapshots take.
    """
    at = _instant(timezone.now() if at is None else at, "at")
    if item.owner_id != getattr(actor, "pk", None):  # the caller already resolved `item` for this authenticated actor
        raise InventoryWriteError({"__all__": "Elige un objeto propio."})
    mounts = _open(item.owner_id, at)
    parts = [mount for mount in mounts if mount.parent_item_id == item.pk]
    by_item = {mount.item_id: mount for mount in mounts}
    seen, current, bike = set(), item.pk, None
    while current in by_item and current not in seen:
        seen.add(current)
        if by_item[current].bike_id:
            bike = by_item[current].bike
            break
        current = by_item[current].parent_item_id
    return parts, bike


def part_candidates(actor, parent, *, at=None):
    """Own active items not mounted at `at`, without the parent itself or what contains it."""
    at = _instant(timezone.now() if at is None else at, "at")
    excluded = {getattr(parent, "pk", parent), *ancestors(actor, parent, at=at)}
    with transaction.atomic():
        owner = _lock_owner(actor)
        mounted = {mount.item_id for mount in _open(owner, at)}
        return Item.objects.filter(owner=owner).filter(Q(retired_at__isnull=True) | Q(retired_at__gt=at)) \
            .exclude(pk__in=excluded | mounted).select_related("category").order_by("name", "id")


def add_part(actor, parent, item, *, at, slot=None, notes=""):
    """Mount `item` inside `parent` from `at`; installation errors come back in Spanish by code."""
    parent = get_inventory(actor, Item, getattr(parent, "pk", parent))
    child = get_inventory(actor, Item, getattr(item, "pk", item))
    try:
        return create_installation(actor, item=child, bike=None, parent_item=parent, started_at=at, ended_at=None,
                                   slot=slot or None, notes=notes)
    except ValidationError as error:
        groups = error.error_dict.values() if hasattr(error, "error_dict") else [error.error_list]
        codes = [getattr(entry, "code", None) for entries in groups for entry in entries]
        messages = [SPANISH[code] for code in dict.fromkeys(codes) if code in SPANISH] or ["No se pudo montar la pieza: revisa las fechas."]
        raise InventoryWriteError({"__all__": messages}) from error
