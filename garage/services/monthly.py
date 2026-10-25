"""Owner-scoped usage per calendar month in the user's time zone. Read-only."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from garage.models import Bike, Item, ItemUsage, Ride, UsageMaterializationState
from .baselines import _instant
from .ownership import InventoryWriteError, _lock_owner, get_inventory

# Elevation metres per month (garage-030 phase 3); average power is not additive and is not offered.
METRICS = ("distance_m", "moving_time_s", "ride_count", "elevation_gain_m")
SHORT_MONTHS = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
MONTHS = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
          "noviembre", "diciembre")


@dataclass(frozen=True)
class MonthlySeries:
    buckets: tuple
    trusted: bool


@dataclass(frozen=True)
class MonthBucket:
    start: datetime
    end: datetime
    label: str
    name: str
    value: Decimal | None
    missing: int
    partial: bool


def _months_back(year, month, count):
    keys = []
    for _ in range(count):
        keys.append((year, month))
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return keys[::-1]


def _next(year, month):
    return (year + 1, 1) if month == 12 else (year, month + 1)


def monthly_usage(actor, /, *, item=None, bike=None, all_rides=False, metric="distance_m", months=12, tz, at=None, through=None):
    """Sum one metric per local calendar month, oldest first, ending with `through` (default: the month of `at`).

    A bucket is in progress (partial) when it contains `at`. all_rides=True sums
    every ride of the owner with a known start, with or without a bike.

    Month bounds are local midnights converted to aware instants, so DST changes
    keep [start, end) exact. Known values are summed; a month whose rows all lack
    the value is None, and a month without rows is zero. Item usage is only
    trusted once the owner's materialization is initialized; otherwise every
    month is None and trusted is False.
    """
    if (item is not None) + (bike is not None) + bool(all_rides) != 1:
        raise InventoryWriteError({"item": "Elige un objeto, una bici o todas las salidas."})
    if metric not in METRICS:
        raise InventoryWriteError({"metric": "Elige distancia, tiempo en movimiento, salidas o desnivel."})
    if isinstance(months, bool) or not isinstance(months, int) or not 1 <= months <= 60:
        raise InventoryWriteError({"months": "Elige entre 1 y 60 meses."})
    zone = tz if isinstance(tz, ZoneInfo) else ZoneInfo(tz)
    at = _instant(timezone.now() if at is None else at, "at")
    local = at.astimezone(zone)
    if through is None:
        through = (local.year, local.month)
    if (not isinstance(through, tuple) or len(through) != 2 or not all(isinstance(part, int) and not isinstance(part, bool) for part in through)
            or not 1 <= through[1] <= 12 or not 1900 <= through[0] <= 9998 or through > (local.year, local.month)):
        raise InventoryWriteError({"through": "Elige un mes que no sea posterior al actual."})
    keys = _months_back(*through, months)
    bounds = [datetime(year, month, 1, tzinfo=zone) for year, month in keys]
    bounds.append(datetime(*_next(*keys[-1]), 1, tzinfo=zone))
    with transaction.atomic():
        owner = _lock_owner(actor)
        trusted = True
        if item is not None:
            target = get_inventory(owner, Item, getattr(item, "pk", item))
            rows = ItemUsage.objects.filter(owner=owner, item=target)
            trusted = (UsageMaterializationState.objects.filter(owner=owner, initialized_at__isnull=False).exists()
                       or not Ride.objects.filter(owner=owner).exists())
        elif bike is not None:
            target = get_inventory(owner, Bike, getattr(bike, "pk", bike))
            rows = Ride.objects.filter(owner=owner, bike=target)
        else:
            rows = Ride.objects.filter(owner=owner)
        field = "id" if metric == "ride_count" else metric
        facts = list(rows.filter(started_at__gte=bounds[0], started_at__lt=min(bounds[-1], at))
                     .values_list("started_at", field)) if trusted else []
    buckets = []
    for index, (year, month) in enumerate(keys):
        start, end = bounds[index], bounds[index + 1]
        values = [Decimal(1) if metric == "ride_count" else value for started, value in facts if start <= started < end]
        missing = sum(value is None for value in values)
        value = None if not trusted or (values and missing == len(values)) else sum((v for v in values if v is not None), Decimal(0))
        buckets.append(MonthBucket(start, end, SHORT_MONTHS[month - 1], f"{MONTHS[month - 1]} {year}", value, missing,
                                   start <= at < end))
    return MonthlySeries(tuple(buckets), trusted)
