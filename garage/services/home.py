"""Read-only snapshot for the mobile home screen. No rebuilds, no writes."""
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from garage.models import Bike, Installation, Item, ItemUsage, Ride, UsageMaterializationState
from garage.presentation import by_severity, wear
from .baselines import _instant
from .lifecycle import IN_USE, ItemLifecycle, item_lifecycles, mount_resolver  # mount_resolver re-exported: workshop, bike screen
from .maintenance_due import maintenance_due
from .ownership import _lock_owner

ATTENTION_LIMIT = 6


def pending_rides(owner):
    """Rides with a known start and no bike that nobody has decided yet: «por revisar»."""
    return Ride.objects.filter(owner=owner, started_at__isnull=False, bike__isnull=True).exclude(manual_overrides__has_key="bike")


@dataclass(frozen=True)
class HomeAlert:
    wear: object
    place: str

    @property
    def target(self):
        return self.wear.target


@dataclass(frozen=True)
class HomeBike:
    bike: Bike
    distance_m: Decimal | None
    moving_time_s: Decimal | None
    alerts: int
    elevation_gain_m: Decimal | None = None  # None while no ride of the bike has elevation (garage-030 phase 3)
    no_elevation: int = 0  # rides of the bike without elevation: the figure is a minimum («↑ ≥»)


@dataclass(frozen=True)
class HomeGear:
    item: Item
    in_use: bool
    contexts: tuple[str, ...]
    distance_m: Decimal | None
    life: ItemLifecycle | None = None  # «En uso · …», «Disponible» or «Sin estrenar» (garage-042)


@dataclass(frozen=True)
class Home:
    attention: tuple[HomeAlert, ...]
    attention_total: int
    nodata: int
    calm: int
    snoozed: int
    pending_count: int
    pending_distance_m: Decimal | None
    pending_first: Ride | None
    bikes: tuple[HomeBike, ...]
    gear: tuple[HomeGear, ...]
    usage_current: bool
    rules: int

    @property
    def attention_hidden(self):
        return self.attention_total - len(self.attention)


def _retired(obj, at):
    return obj.retired_at is not None and obj.retired_at <= at


def open_installations(owner, at):
    """(item, bike, parent item) of every mount open at `at`."""
    return list(Installation.objects.filter(owner=owner, started_at__lte=at)
                .filter(Q(ended_at__isnull=True) | Q(ended_at__gt=at)).values_list("item_id", "bike_id", "parent_item_id"))


def place_of(item_wear, mount_of):
    """(bike id or None, place text) for one rule's target."""
    if item_wear.rule.item_id:
        return mount_of(item_wear.rule.item_id)
    return item_wear.rule.bike_id, "bici"


def home_snapshot(actor, *, at=None):
    at = _instant(timezone.now() if at is None else at, "at")
    with transaction.atomic():
        owner = _lock_owner(actor)
        # Same transaction and lock as the reads below: one coherent snapshot.
        dues = maintenance_due(owner, at=at)
        all_bikes = list(Bike.objects.filter(owner=owner).order_by("name", "id"))
        totals = {row["bike"]: row for row in Ride.objects.filter(owner=owner, bike__isnull=False, started_at__lt=at)
                  .values("bike").annotate(distance=Sum("distance_m"), moving=Sum("moving_time_s"), elevation=Sum("elevation_gain_m"),
                                            no_elevation=Count("id", filter=Q(elevation_gain_m__isnull=True)))}
        open_now = open_installations(owner, at)
        all_items = list(Item.objects.filter(owner=owner).select_related("category").order_by("name", "id"))
        usage_current = not Ride.objects.filter(owner=owner).exists() or \
            UsageMaterializationState.objects.filter(owner=owner, initialized_at__isnull=False).exists()
        pending = pending_rides(owner).aggregate(count=Count("id"), distance=Sum("distance_m"))
        pending_first = pending_rides(owner).order_by("-started_at", "-id").only("id", "name", "started_at", "distance_m").first() \
            if pending["count"] else None
        mounted = {item_id for item_id, _, _ in open_now}
        loose = [item for item in all_items if item.pk not in mounted and not _retired(item, at)]
        # In use, available or never used, with the words of the Material list; `loose` are not mounted at `at`.
        lives = item_lifecycles(owner, loose, at=at, unmounted=True)
        distances = {}
        if usage_current and loose:
            distances = dict(ItemUsage.objects.filter(owner=owner, item_id__in=[item.pk for item in loose])
                             .values("item_id").annotate(total=Sum("distance_m")).values_list("item_id", "total"))

    bikes = [bike for bike in all_bikes if not _retired(bike, at)]
    mount_of = mount_resolver(open_now, {bike.pk: bike.name for bike in all_bikes}, {item.pk: item.name for item in all_items})
    wears = [item for item in by_severity([wear(due) for due in dues]) if not _retired(item.target, at)]
    alerts = []
    per_bike = Counter()
    for item in wears:
        bike_id, place = place_of(item, mount_of)
        if item.needs_attention:
            if bike_id is not None:
                per_bike[bike_id] += 1
            alerts.append(HomeAlert(item, place))

    gear = [HomeGear(item, lives[item.pk].state == IN_USE, lives[item.pk].contexts,
                     (distances.get(item.pk) or Decimal(0)) if usage_current else None, lives[item.pk]) for item in loose]
    gear.sort(key=lambda entry: (not entry.in_use, entry.item.name.lower(), str(entry.item.pk)))
    return Home(
        attention=tuple(alerts[:ATTENTION_LIMIT]),
        attention_total=len(alerts),
        nodata=sum(item.state == "nodata" for item in wears),
        calm=sum(item.state in {"progress", "current"} for item in wears),
        snoozed=sum(item.state == "snoozed" for item in wears),
        pending_count=pending["count"],
        pending_distance_m=pending["distance"],
        pending_first=pending_first,
        bikes=tuple(HomeBike(bike, totals.get(bike.pk, {}).get("distance", Decimal(0)), totals.get(bike.pk, {}).get("moving", Decimal(0)),
                             per_bike[bike.pk], totals.get(bike.pk, {}).get("elevation"), totals.get(bike.pk, {}).get("no_elevation", 0))
                    for bike in bikes),
        gear=tuple(gear),
        usage_current=usage_current,
        rules=len(wears),
    )
