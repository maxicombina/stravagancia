"""Usage between interventions and how long each part of a category lasted (garage-036). Read-only.

Computed when shown, never stored: correcting rides or mounts changes the
figures coherently. Observed km, hours and rides are a minimum unless a reading
fixes them; days are exact.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from garage.models import Bike, Category, Installation, Item, Ride, ServiceEvent
from .baselines import _instant
from .lifecycle import ItemLifecycle, item_lifecycles
from .ownership import _lock_owner, get_inventory
from .statistics import StatisticMetric, _observed, _select, statistics


def _days(start, end):
    elapsed = end - start
    return (Decimal(elapsed.days * 86400 + elapsed.seconds) + Decimal(elapsed.microseconds) / Decimal(1000000)) / Decimal(86400)


@dataclass(frozen=True)
class Span:
    """Usage of one target over [start, end)."""
    start: object
    end: object
    metrics: tuple[StatisticMetric, ...]

    @property
    def days(self):
        return _days(self.start, self.end)

    def metric(self, name):
        return next(metric for metric in self.metrics if metric.name == name)


@dataclass(frozen=True)
class EventUsage:
    event: ServiceEvent
    previous: ServiceEvent | None
    next: ServiceEvent | None  # the next one up to `at`
    before: Span | None  # from the previous intervention of the same type to this one
    after: Span | None  # from this one to the next, or until `at`
    upcoming: ServiceEvent | None = None  # the next one when it is still to come (after `at`)
    future: bool = False  # registered with a date still to come: no usage yet
    retired_at: object = None  # the target was retired before `at`: «after» stops there


def _series_key(event):
    return event.performed_at, event.created_at, str(event.pk)


def bike_spans(rides, events, at):
    """{event id: Span} for a bike's interventions from its own rides: each one to the next of its type, or `at`."""
    series = defaultdict(list)
    for event in sorted((event for event in events if event.performed_at <= at), key=_series_key):
        series[event.service_type_id].append(event)
    spans = {}
    for chain in series.values():
        for index, event in enumerate(chain):
            upper = chain[index + 1].performed_at if index + 1 < len(chain) else at
            spans[event.pk] = Span(event.performed_at, upper, _observed(_select(rides, event.performed_at, upper), empty_complete=upper == event.performed_at))
    return spans


def item_spans(blocks):
    """{event id: Span} from the intervention blocks of `statistics` for one item."""
    return {block.reference.pk: Span(block.start, block.end, block.metrics) for block in blocks}


def previous_spans(spans, events):
    """{event id: Span of the previous intervention of its type up to this one}."""
    series = defaultdict(list)
    for event in sorted(events, key=_series_key):
        series[event.service_type_id].append(event)
    return {event.pk: spans[previous.pk] for chain in series.values() for previous, event in zip(chain, chain[1:]) if previous.pk in spans}


def event_spans(actor, target, *, at=None):
    """{event id: Span} from each intervention of the target to the next of its type (or `at`)."""
    at = _instant(timezone.now() if at is None else at, "at")
    if isinstance(target, Item):
        report = statistics(actor, item=target, started_to=at)
        return item_spans(report.rows[0].interventions if report.rows else ())
    with transaction.atomic():
        owner = _lock_owner(actor)
        bike = get_inventory(owner, Bike, target.pk)
        rides = list(Ride.objects.filter(owner=owner, bike=bike, started_at__isnull=False, started_at__lt=at)
                     .only("id", "started_at", "bike_id", "distance_m", "moving_time_s", "elevation_gain_m"))
        events = list(ServiceEvent.objects.filter(owner=owner, bike=bike, performed_at__lte=at))
    return bike_spans(rides, events, at)


def event_usage(actor, event, *, at=None):
    """The intervention with the usage since the previous one of its type and until the next (or `at`)."""
    at = _instant(timezone.now() if at is None else at, "at")
    event = get_inventory(actor, ServiceEvent, getattr(event, "pk", event))
    target = event.item or event.bike
    spans = event_spans(actor, target, at=at)
    everything = sorted(ServiceEvent.objects.filter(owner_id=event.owner_id, item_id=event.item_id, bike_id=event.bike_id,
                                                    service_type_id=event.service_type_id), key=_series_key)
    upcoming = next((other for other in everything if other.performed_at > at and other.pk != event.pk), None)
    if event.performed_at > at:  # registered ahead: no usage yet, and nothing links to it
        return EventUsage(event, None, None, None, None, None, future=True)
    series = [other for other in everything if other.performed_at <= at]
    index = next(position for position, other in enumerate(series) if other.pk == event.pk)
    previous = series[index - 1] if index else None
    following = series[index + 1] if index + 1 < len(series) else None
    after = spans.get(event.pk)
    retired = target.retired_at if target.retired_at is not None and target.retired_at <= at and following is None else None
    if after is not None and retired is not None:
        # No days after the retirement. An item gets no rides after it; a bike's rides still assigned after a
        # retroactive retirement are counted, as in its other figures.
        after = Span(after.start, max(after.start, retired), after.metrics)
    return EventUsage(event, previous, following, spans.get(previous.pk) if previous else None, after,
                      upcoming if following is None else None, retired_at=retired)


@dataclass(frozen=True)
class PartLife:
    item: Item
    state: str  # "mounted", "loose" or "retired"
    distance: StatisticMetric  # whole life with a lifetime reading, since acquisition with that reading, else observed
    reading: str  # "lifetime", "acquisition" or "" (only what Garage observed)
    days: Decimal | None
    days_kind: str  # "mounted", "use" (since the recorded start of use), "purchase" or "" (unknown)
    lifecycle: ItemLifecycle | None = None  # loose: «En uso · …», «Disponible» or «Sin estrenar», as in the Material list


def _mounted_days(mounts, end):
    """Days inside installation periods, each clipped to `end` (now or the retirement)."""
    total = Decimal(0)
    for mount in mounts:
        upper = min(mount.ended_at or end, end)
        if upper > mount.started_at:
            total += _days(mount.started_at, upper)
    return total


def category_comparison(actor, category, *, zone, at=None):
    """Each item of the category with its known distance and days of use, most used first.

    Days count the time mounted (clipped to the retirement or `at`); gear that is
    never mounted (it counts through usage profiles) uses the recorded start of
    use or the purchase date, and says which. What is not mounted nor retired
    carries its state from `item_lifecycles` (garage-042).
    """
    at = _instant(timezone.now() if at is None else at, "at")
    category = get_inventory(actor, Category, getattr(category, "pk", category))
    report = statistics(actor, category=category, started_to=at)
    with transaction.atomic():
        owner = _lock_owner(actor)
        mounts = defaultdict(list)
        for mount in Installation.objects.filter(owner=owner, item__category=category, started_at__lte=at).order_by("started_at", "id"):
            mounts[mount.item_id].append(mount)
        states = {row.target.pk: "retired" if row.target.retired_at is not None and row.target.retired_at <= at
                  else "mounted" if any(mount.ended_at is None or mount.ended_at > at for mount in mounts[row.target.pk]) else "loose"
                  for row in report.rows}
        # Same instant and transaction as the mounts above: none of the loose ones is mounted, so that read is skipped.
        lives = item_lifecycles(owner, [row.target for row in report.rows if states[row.target.pk] == "loose"], at=at, unmounted=True)
    parts = []
    for row in report.rows:
        item = row.target
        lifetime = row.totals[0].metrics[0] if row.totals else None
        acquisition = row.totals[1].metrics[0] if len(row.totals) > 1 else None
        if lifetime is not None and lifetime.value is not None:
            distance, reading = lifetime, "lifetime"
        elif acquisition is not None and acquisition.value is not None and acquisition.baseline is not None:
            distance, reading = acquisition, "acquisition"  # a used part: its reading since it was acquired
        else:
            distance, reading = row.observed[0], ""
        end = item.retired_at if states[item.pk] == "retired" else at
        if mounts[item.pk]:
            days, kind = _mounted_days(mounts[item.pk], end), "mounted"
        elif item.acquisition_anchor_at is not None and item.acquisition_anchor_at <= end:
            days, kind = _days(item.acquisition_anchor_at, end), "use"
        elif item.acquired_on is not None and datetime.combine(item.acquired_on, time(), tzinfo=zone) <= end:
            days, kind = _days(datetime.combine(item.acquired_on, time(), tzinfo=zone), end), "purchase"
        else:
            days, kind = None, ""
        parts.append(PartLife(item, states[item.pk], distance, reading, days, kind, lives.get(item.pk)))
    return sorted(parts, key=lambda part: (part.distance.value is None, -(part.distance.value or 0), part.item.name.lower(), str(part.item.pk)))
