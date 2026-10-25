"""Where each item is in its life (garage-042): mounted, in use, available or retired. Read-only.

Nothing is stored: the state comes from the mounts, the usage profiles, the
readings, the usage exceptions of the rides, the start of use and the
retirement, at one instant. This module is the only source of the state and of
its words; the Material list, the item screen, the category screen and the home
screen show what it returns.
"""
from dataclasses import dataclass
from datetime import datetime

from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from garage.models import Installation, Item, UsageBaseline, UsageOverride, UsageProfileItem
from garage.sports import sport_label
from .baselines import _instant
from .ownership import InventoryWriteError

MOUNTED, IN_USE, AVAILABLE, RETIRED = "mounted", "in_use", "available", "retired"
# Material list chips, in order; «Todos» (all) is the default and `active` stays as an alias without chip.
CHIPS = ((MOUNTED, "Montados"), (AVAILABLE, "Disponibles"), (IN_USE, "En uso"), (RETIRED, "Retirados"), ("all", "Todos"))
FILTERS = (MOUNTED, AVAILABLE, IN_USE, RETIRED, "active")

AVAILABLE_TEXT = "Disponible"
UNUSED_TEXT = "Sin estrenar"
IN_USE_TEXT = "En uso"
RETIRED_TEXT = "Retirado el"
RETIRES_TEXT = "se retira el"  # a retirement still to come: the item keeps its state until then
ANY_BIKE = "Cualquier bici"


@dataclass(frozen=True)
class ItemLifecycle:
    """`text` is followed, when `since` is set, by that date in the viewer's zone, and by «· se retira el …»
    when `retires` is set (tag `life_text`)."""
    state: str  # MOUNTED, IN_USE, AVAILABLE or RETIRED
    text: str
    since: datetime | None = None  # the retirement or the start of the open mount
    unused: bool = False  # available and never mounted, in a profile, read or started up to then: «Sin estrenar»
    bike: str = ""  # the bike it is on, directly or through the items it is mounted inside
    parent: str = ""  # the item it is mounted inside, when it is a part
    contexts: tuple[str, ...] = ()  # in use: the current profiles, as on the home screen
    retires: datetime | None = None  # not retired yet, with a retirement scheduled after the instant


def context_label(bike_name, sport_type):
    """«Gravel», «Cualquier bici» or «Gravel · MTB»: one current usage profile, as the home screen shows it."""
    label = bike_name or ANY_BIKE
    return f"{label} · {sport_label(sport_type)}" if sport_type else label


def _open_at(at, prefix=""):
    """Open at `at`: started by then and not ended (an end at `at` is already closed)."""
    return Q(**{prefix + "started_at__lte": at}) & (Q(**{prefix + "ended_at__isnull": True}) | Q(**{prefix + "ended_at__gt": at}))


def _not_retired(at):
    return Q(retired_at__isnull=True) | Q(retired_at__gt=at)


def filter_state(items, state, *, at):
    """The items of `items` (an owned Item queryset) in `state` at `at`, filtered in the database.

    `active` means not retired; `all` or any other value leaves the queryset as it is.
    """
    at = _instant(at, "at")
    # Same rows as `item_lifecycles`: the owner's open mounts and current profiles.
    mounted = Exists(Installation.objects.filter(owner_id=OuterRef("owner_id"), item=OuterRef("pk")).filter(_open_at(at)))
    in_use = Exists(UsageProfileItem.objects.filter(owner_id=OuterRef("owner_id"), item=OuterRef("pk")).filter(_open_at(at, "profile__")))
    if state == RETIRED:
        return items.filter(retired_at__isnull=False, retired_at__lte=at)
    if state == "active":
        return items.filter(_not_retired(at))
    if state == MOUNTED:
        return items.filter(_not_retired(at)).filter(mounted)
    if state == IN_USE:
        return items.filter(_not_retired(at)).filter(~mounted).filter(in_use)
    if state == AVAILABLE:
        return items.filter(_not_retired(at)).filter(~mounted).filter(~in_use)
    return items


def mount_resolver(open_now, bike_names, item_names):
    """item id -> (bike id or None, place text), following nested mounts up to a bike.

    The one walk from a part to the bike above it: the home and workshop alert
    rows, the bike screen and the state of a nested part use it.
    """
    parent = {item_id: (bike_id, parent_id) for item_id, bike_id, parent_id in open_now}

    def mount_of(item_id):
        seen, first_parent = set(), None
        while item_id in parent and item_id not in seen:
            seen.add(item_id)
            bike_id, parent_id = parent[item_id]
            if bike_id is not None:
                return bike_id, bike_names.get(bike_id, "")
            first_parent = first_parent or parent_id
            item_id = parent_id
        return None, (f"en {item_names[first_parent]}" if first_parent in item_names else "sin montar")
    return mount_of


def item_lifecycles(owner, items, *, at=None, unmounted=False):
    """{item id: ItemLifecycle} at `at` for the owner's `items`, in at most three queries whatever their number.

    A display read of already owned items, like the other blocks of their screens:
    no owner lock, so the home snapshot can call it inside its own transaction.
    `unmounted=True` says the caller already found none of them mounted at `at`
    (same instant, same transaction): the read of the open mounts is skipped.
    """
    at = _instant(timezone.now() if at is None else at, "at")
    items = list(items)
    owner_id = getattr(owner, "pk", owner)
    if owner_id is None or any(item.owner_id != owner_id for item in items):
        raise InventoryWriteError({"__all__": "Elige un objeto propio."})
    result = {}
    for item in items:
        if item.retired_at is not None and item.retired_at <= at:
            result[item.pk] = ItemLifecycle(RETIRED, RETIRED_TEXT, since=item.retired_at)
    pending = [item for item in items if item.pk not in result]
    if not pending:
        return result
    # Every open mount of the owner: a part's bike can be several items above it.
    mounts = {}
    for mount in (() if unmounted else Installation.objects.filter(owner_id=owner_id).filter(_open_at(at)).order_by("started_at", "id")
                  .values("item_id", "bike_id", "parent_item_id", "started_at", "bike__name", "parent_item__name")):
        mounts.setdefault(mount["item_id"], mount)
    mount_of = mount_resolver([(mount["item_id"], mount["bike_id"], mount["parent_item_id"]) for mount in mounts.values()],
                              {mount["bike_id"]: mount["bike__name"] for mount in mounts.values() if mount["bike_id"] is not None}, {})
    retires = {item.pk: item.retired_at for item in pending if item.retired_at is not None}  # all after `at` here
    for item in pending:
        mount = mounts.get(item.pk)
        if mount is None:
            continue
        if mount["bike_id"] is not None:
            bike = mount["bike__name"]
            result[item.pk] = ItemLifecycle(MOUNTED, f"En {bike} desde el", since=mount["started_at"], bike=bike, retires=retires.get(item.pk))
            continue
        bike_id, place = mount_of(item.pk)
        parent, bike = mount["parent_item__name"], place if bike_id is not None else ""  # no bike above: just the parent
        where = f"{parent} · {bike}" if bike else parent
        result[item.pk] = ItemLifecycle(MOUNTED, f"Sobre {where} desde el", since=mount["started_at"], bike=bike, parent=parent,
                                        retires=retires.get(item.pk))
    loose = [item.pk for item in pending if item.pk not in result]
    if not loose:
        return result
    contexts = {}
    for item_id, bike_name, sport_type in (UsageProfileItem.objects.filter(owner_id=owner_id, item_id__in=loose)
                                           .filter(_open_at(at, "profile__")).values_list("item_id", "profile__bike__name", "profile__sport_type")):
        contexts.setdefault(item_id, set()).add(context_label(bike_name, sport_type))
    for item_id, labels in contexts.items():
        ordered = tuple(sorted(labels))
        result[item_id] = ItemLifecycle(IN_USE, f"{IN_USE_TEXT} · " + ", ".join(ordered), contexts=ordered, retires=retires.get(item_id))
    available = [item for item in pending if item.pk not in result]
    candidates = {item.pk for item in available if item.acquisition_anchor_at is None or item.acquisition_anchor_at > at}
    used = set()
    if candidates:
        # Used before (up to `at`): any mount, any profile version, any reading, or a ride that includes it by
        # exception (the ride screen offers any item). Those are every way an item gets usage; unmounting never
        # makes it new again. An intervention alone does not: a new chain can be waxed before its first ride.
        mine = {"owner_id": owner_id, "item": OuterRef("pk")}
        used = set(Item.objects.filter(owner_id=owner_id, pk__in=candidates).filter(
            Exists(Installation.objects.filter(**mine, started_at__lte=at))
            | Exists(UsageProfileItem.objects.filter(**mine, profile__started_at__lte=at))
            | Exists(UsageBaseline.objects.filter(**mine, cut_at__lte=at))
            | Exists(UsageOverride.objects.filter(**mine, action=UsageOverride.Action.INCLUDE, ride__started_at__lte=at)))
            .values_list("pk", flat=True))
    for item in available:
        unused = item.pk in candidates and item.pk not in used
        result[item.pk] = ItemLifecycle(AVAILABLE, UNUSED_TEXT if unused else AVAILABLE_TEXT, unused=unused, retires=retires.get(item.pk))
    return result
