"""Private read-only statistics. Period facts never distribute cumulative readings.

Totals use a full lifetime/acquisition/service scope at the upper cut, irrespective
of the selected bike/period. Materialization initialization is not real coverage.
"""
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, localcontext

from django.db import transaction
from django.utils import timezone

from garage.models import Bike, Category, Installation, Item, ItemUsage, Ride, ServiceEvent, UsageBaseline, UsageMaterializationState
from .baselines import _instant
from .ownership import InventoryWriteError, _lock_owner, get_inventory

# Elevation is last (garage-030 phase 3): screens and costs keep indexing distance, time and rides as 0, 1 and 2.
# No reading (UsageBaseline) holds elevation, so its lifetime and acquisition totals stay unknown.
# Average power is not additive over a period and is left out.
METRICS = ("distance_m", "moving_time_s", "ride_count", "elevation_gain_m")
SCALES = {"distance_m": Decimal(1000), "moving_time_s": Decimal(3600), "ride_count": Decimal(1), "elevation_gain_m": Decimal(1)}


@dataclass(frozen=True)
class StatisticMetric:
    name: str
    value: Decimal | None
    missing_values: int = 0
    complete: bool = False
    baseline: UsageBaseline | None = None

    @property
    def estimated(self):
        return bool(self.baseline and self.baseline.is_estimated)

    @property
    def display_value(self):
        if self.value is None:
            return None
        with localcontext() as ctx:
            ctx.prec = 50
            return self.value / SCALES[self.name]

    @property
    def label(self):
        return {"distance_m": "Km", "moving_time_s": "Horas en movimiento", "ride_count": "Salidas",
                "elevation_gain_m": "Desnivel (m)"}[self.name]


@dataclass(frozen=True)
class UsageBlock:
    label: str
    start: object
    end: object
    metrics: tuple[StatisticMetric, ...]
    reference: object = None


@dataclass(frozen=True)
class CostStatistic:
    currency: str
    amount: Decimal
    per_km: Decimal | None
    reason: str
    scope: str


@dataclass(frozen=True)
class TargetStatistics:
    target: object
    kind: str
    observed: tuple[StatisticMetric, ...]
    totals: tuple[UsageBlock, ...]
    bikes: tuple[UsageBlock, ...]
    installations: tuple[UsageBlock, ...]
    interventions: tuple[UsageBlock, ...]
    costs: tuple[CostStatistic, ...]
    unknown_costs: int


@dataclass(frozen=True)
class StatisticsReport:
    start: object
    end: object
    rows: tuple[TargetStatistics, ...]
    materialization_current: bool
    pending_started_rides: int
    unknown_bike_rides: int
    # Every ride with a known start in the period, and those without a bike (garage-032).
    overall: tuple[StatisticMetric, ...] = ()
    no_bike: tuple[StatisticMetric, ...] = ()


def _select(rows, start, end, bike_id=None):
    return [row for row in rows if row.started_at is not None and (start is None or row.started_at >= start)
            and row.started_at < end and (bike_id is None or row.bike_id == bike_id)]


def _observed(rows, *, trusted=True, empty_complete=False):
    result = []
    for name in METRICS:
        values = [Decimal(1) if name == "ride_count" else getattr(row, name) for row in rows]
        missing = sum(value is None for value in values)
        # All-null contributions are unknown; a real empty set is observed zero.
        value = sum((value for value in values if value is not None), Decimal(0)) if trusted and (not values or missing < len(values)) else None
        result.append(StatisticMetric(name, value, missing, trusted and empty_complete))
    return tuple(result)


def _total(rows, baselines, *, scope, start, end, trusted, event=None):
    selected = _select(rows, start, end)
    empty_service = scope == "service" and start == end
    result = []
    for name in METRICS:
        readings = [b for b in baselines if b.scope == scope and b.metric == name and b.service_event_id == (event.pk if event else None) and b.cut_at <= end]
        baseline = max(readings, key=lambda b: (b.cut_at, str(b.pk)), default=None)
        if scope == "acquisition" and start is None:
            baseline = None
            value = None
            missing = 0
        else:
            contributions = _select(selected, baseline.cut_at if baseline else start, end)
            metric = _observed(contributions, trusted=trusted)[METRICS.index(name)]
            missing = metric.missing_values
            value = None
            if baseline and (trusted or baseline.cut_at == end):
                values = [Decimal(1) if name == "ride_count" else getattr(row, name) for row in contributions]
                value = baseline.value + sum((value for value in values if value is not None), Decimal(0))
            if scope == "service" and baseline is None:
                value = Decimal(0) if empty_service else metric.value
        complete = bool(baseline and baseline.cut_at == end) or empty_service
        result.append(StatisticMetric(name, value, missing, complete, baseline))
    return tuple(result)


def _costs(events, distance, *, scope, purchase=None):
    grouped = defaultdict(lambda: Decimal(0))
    unknown = 0
    for event in events:
        if event.amount is None or not event.currency:
            unknown += 1
        else:
            grouped[event.currency] += event.amount
    if purchase is not None:
        if purchase.purchase_amount is None or not purchase.purchase_currency:
            unknown += 1
        else:
            grouped[purchase.purchase_currency] += purchase.purchase_amount
    reason = "" if distance.complete and not distance.estimated and distance.value is not None and distance.value > 0 and not unknown else (
        "Costes sin importe o moneda" if unknown else "Distancia desconocida" if distance.value is None else
        "Distancia cero" if distance.value == 0 else "Lectura estimada" if distance.estimated else "Histórico parcial: no acredita el denominador completo")
    return tuple(CostStatistic(currency, amount, None if reason else amount * Decimal(1000) / distance.value, reason, scope)
                 for currency, amount in sorted(grouped.items())), unknown


def statistics(actor, *, started_from=None, started_to=None, bike=None, category=None, item=None):
    """One coherent bounded-query snapshot, no rebuild or persistent writes.

    A bike filter limits period facts only. Cumulative totals, interventions and
    purchase costs retain their full target scope, explicitly labelled in HTML.
    """
    end = _instant(timezone.now() if started_to is None else started_to, "started_to")
    start = _instant(started_from, "started_from") if started_from is not None else None
    if start is not None and start >= end:
        raise InventoryWriteError({"started_to": "El final debe seguir al inicio."})
    with transaction.atomic(), localcontext() as ctx:
        ctx.prec = 50
        owner = _lock_owner(actor)
        filters = {name: get_inventory(owner, model, getattr(value, "pk", value)) if value is not None else None
                   for name, model, value in (("bike", Bike, bike), ("category", Category, category), ("item", Item, item))}
        bikes = list(Bike.objects.filter(owner=owner).order_by("name", "id"))
        items = list(Item.objects.filter(owner=owner).select_related("category").order_by("name", "id"))
        items = [obj for obj in items if (not filters["item"] or obj.pk == filters["item"].pk) and (not filters["category"] or obj.category_id == filters["category"].pk)]
        rides = list(Ride.objects.filter(owner=owner).only("id", "started_at", "bike_id", "distance_m", "moving_time_s", "elevation_gain_m"))
        current = not rides or UsageMaterializationState.objects.filter(owner=owner, initialized_at__isnull=False).exists()
        usages, baselines, events, installations = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
        # One item requested: only its own rows are ever read below, so load only those.
        only = {"item": filters["item"]} if filters["item"] else {}
        for row in ItemUsage.objects.filter(owner=owner, started_at__lt=end, **only):
            usages[row.item_id].append(row)
        for row in UsageBaseline.objects.filter(owner=owner, cut_at__lte=end, **only):
            baselines[row.item_id].append(row)
        for row in ServiceEvent.objects.filter(owner=owner, performed_at__lte=end, **only).select_related("service_type").order_by("performed_at", "created_at", "id"):
            events[(row.item_id, row.bike_id)].append(row)
        for row in Installation.objects.filter(owner=owner, started_at__lt=end, **only).select_related("bike", "parent_item"):
            installations[row.item_id].append(row)
        bike_id = filters["bike"].pk if filters["bike"] else None
        names = {obj.pk: obj.name for obj in bikes}
        targets = [(obj, "bike") for obj in bikes if (bike_id is None or obj.pk == bike_id) and not filters["item"] and not filters["category"]] + [(obj, "item") for obj in items]
        results = []
        for target, kind in targets:
            is_item = kind == "item"
            rows = usages[target.pk] if is_item else [ride for ride in rides if ride.bike_id == target.pk]
            trusted = current if is_item else True
            selected = _select(rows, start, end, bike_id)
            observed = _observed(selected, trusted=trusted)
            totals = []
            if is_item:
                for scope, label, anchor in (("lifetime", "Toda la vida", None), ("acquisition", "Desde adquisición", target.acquisition_anchor_at)):
                    totals.append(UsageBlock(label, anchor, end, _total(rows, baselines[target.pk], scope=scope, start=anchor, end=end, trusted=trusted)))
            if not is_item and target.acquisition_anchor_at is not None and target.acquisition_anchor_at <= end:
                totals.append(UsageBlock("Desde adquisición (observado)", target.acquisition_anchor_at, end, _observed(_select(rows, target.acquisition_anchor_at, end), empty_complete=target.acquisition_anchor_at == end)))
            distribution = []
            if is_item and trusted:
                for destination in sorted({row.bike_id for row in selected}, key=str):
                    distribution.append(UsageBlock(names.get(destination, "Bici desconocida"), start, end, _observed([row for row in selected if row.bike_id == destination], trusted=trusted)))
            mounts = []
            for mount in installations[target.pk] if is_item else []:
                lower = max(mount.started_at, start) if start else mount.started_at
                upper = min(mount.ended_at, end) if mount.ended_at else end
                if lower >= upper:
                    continue
                label = "Montaje en " + mount.bike.name if mount.bike_id else "Uso durante montaje en " + mount.parent_item.name
                mounted_rows = _select(rows, lower, upper, bike_id)
                if mount.bike_id:
                    mounted_rows = [row for row in mounted_rows if row.bike_id == mount.bike_id]
                mounts.append(UsageBlock(label, lower, upper, _observed(mounted_rows, trusted=trusted), mount))
            own_events = events[(target.pk, None) if is_item else (None, target.pk)]
            by_type = defaultdict(list)
            for event in own_events:
                by_type[event.service_type_id].append(event)
            periods = []
            for series in by_type.values():
                for index, event in enumerate(series):
                    upper = series[index + 1].performed_at if index + 1 < len(series) else end
                    metrics = _total(rows, baselines[target.pk], scope="service", start=event.performed_at, end=upper, trusted=trusted, event=event) if is_item else _observed(_select(rows, event.performed_at, upper), empty_complete=upper == event.performed_at)
                    block = UsageBlock(event.service_type.name, event.performed_at, upper, metrics, event)
                    periods.append(block)
                if is_item:
                    latest = series[-1]
                    totals.append(UsageBlock("Desde última " + latest.service_type.name, latest.performed_at, end, _total(rows, baselines[target.pk], scope="service", start=latest.performed_at, end=end, trusted=trusted, event=latest), latest))
            period_events = [event for event in own_events if (start is None or event.performed_at >= start) and event.performed_at < end]
            costs, unknown = _costs(period_events, observed[0], scope="Intervenciones del período; distancia observada del período" + (" en bici filtrada" if bike_id and is_item else ""))
            # Acquisition costs are never assigned to a bike or selected month.
            unknown_entries = {("event", event.pk) for event in period_events if event.amount is None or not event.currency}
            if target.acquisition_anchor_at is not None and target.acquisition_anchor_at <= end:
                acquisition_events = [event for event in own_events if target.acquisition_anchor_at <= event.performed_at < end]
                acquisition_distance = totals[1 if is_item else 0].metrics[0]
                acquisition_costs, _ = _costs(acquisition_events, acquisition_distance, scope="Compra e intervenciones registradas desde adquisición; " + ("uso total adquisición, todas las bicis" if is_item else "uso observado directo de la bici desde adquisición"), purchase=target)
                costs += acquisition_costs
                unknown_entries.update(("event", event.pk) for event in acquisition_events if event.amount is None or not event.currency)
                if target.purchase_amount is None or not target.purchase_currency:
                    unknown_entries.add(("purchase", target.pk))
            unknown = len(unknown_entries)
            results.append(TargetStatistics(target, kind, observed, tuple(totals), tuple(distribution), tuple(mounts), tuple(periods), costs, unknown))
        known = _select(rides, start, end)
        return StatisticsReport(start, end, tuple(results), current, sum(row.started_at is None for row in rides), sum(row.bike_id is None for row in known),
                                overall=_observed(known), no_bike=_observed([row for row in known if row.bike_id is None]))
