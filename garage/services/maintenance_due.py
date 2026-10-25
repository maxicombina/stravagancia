"""Read-only maintenance snapshots serialized with all owned domain mutations.

Partial observed usage is a lower bound, never evidence that a rule is current.
No import/materialization claims complete coverage of real-world history.
"""
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, localcontext

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from garage.models import ItemUsage, MaintenanceRule, MaintenanceSnooze, Ride, ServiceEvent, UsageBaseline, UsageMaterializationState
from .baselines import _instant
from .ownership import _lock_owner

LABELS = {"due": "Vencido", "unknown": "Desconocido", "soon": "Próximo", "current": "Vigente"}
# Elevation (garage-030 phase 3) is last: the first reached still wins, whatever the order.
METRICS = ("distance_m", "moving_time_s", "ride_count", "calendar_days", "elevation_gain_m")


@dataclass(frozen=True)
class MaintenanceMetric:
    name: str
    threshold: Decimal
    value: Decimal | None
    remaining: Decimal | None
    status: str
    coverage: str
    is_estimated: bool = False
    missing_values: int = 0
    # Elevation only (garage-030 phase 3 review): every ride since the reference lacks it,
    # so the value is unknown, never an observed 0 that could not warn.
    unrecorded: bool = False

    @property
    def coverage_complete(self):
        return self.coverage == "complete"

    @property
    def label(self):
        return {"distance_m": "Distancia (km)", "moving_time_s": "Tiempo en movimiento (h)",
                "ride_count": "Salidas", "calendar_days": "Días de 24 horas", "elevation_gain_m": "Desnivel (m)"}[self.name]

    def _display(self, value):
        if value is None:
            return None
        with localcontext() as context:
            context.prec = 40
            if self.name == "distance_m":
                return value / Decimal(1000)
            if self.name == "moving_time_s":
                return value / Decimal(3600)
            return value

    @property
    def display_value(self):
        return self._display(self.value)

    @property
    def display_threshold(self):
        return self._display(self.threshold)

    @property
    def display_remaining(self):
        return self._display(self.remaining)

    @property
    def coverage_label(self):
        return {"complete": "Completo", "partial": "Histórico parcial: mínimo observado", "unknown": "Uso desconocido",
                "estimated": "Lectura estimada"}[self.coverage]


@dataclass(frozen=True)
class SnoozeState:
    """A postponed alert (garage-034): usage since the snooze started against each amount.

    Active only while every amount has a known value below it: unknown usage
    never hides an alert. A partial-history value is a lower bound, as in rules.
    Elevation is stricter (garage-030 phase 3): one ride in the interval without
    elevation leaves that amount unknown, so the snooze is «unknown» (to
    review), never active. Old sources often lack it: a minimum would hide too much.
    """
    snooze: MaintenanceSnooze
    metrics: tuple[MaintenanceMetric, ...]
    trusted: bool = True  # False: an item's usage is still to be calculated

    @property
    def status(self):
        if any(metric.value is not None and metric.value >= metric.threshold for metric in self.metrics):
            return "reached"
        if any(metric.value is None for metric in self.metrics):
            return "unknown"
        return "active"

    @property
    def active(self):
        return self.status == "active"

    @property
    def unknown_elevation(self):
        """«unknown» because a ride since the start has no elevation (not because usage is still to be calculated)."""
        return self.status == "unknown" and self.trusted and all(metric.value is not None or metric.name == "elevation_gain_m"
                                                                  for metric in self.metrics)


@dataclass(frozen=True)
class MaintenanceDue:
    rule: MaintenanceRule
    event: ServiceEvent | None
    reference_at: object
    at: object
    metrics: tuple[MaintenanceMetric, ...]
    status: str
    pending_started_rides: int
    unknown_bike_rides: int
    materialization_current: bool
    snooze: SnoozeState | None = None

    @property
    def label(self):
        return LABELS[self.status]

    @property
    def is_estimated(self):
        return any(metric.is_estimated for metric in self.metrics)


def _metric(name, threshold, value, complete, *, estimated=False, missing=0, unrecorded=False):
    threshold = Decimal(threshold)
    status = "due" if value is not None and value >= threshold else "unknown" if not complete else "soon" if value * 10 >= threshold * 9 else "current"
    return MaintenanceMetric(name, threshold, value, None if value is None else max(Decimal(0), threshold - value), status,
                             "complete" if complete else "partial" if value is not None else "unknown", estimated, missing, unrecorded)


def _elapsed_days(start, at):
    elapsed = at - start
    seconds = Decimal(elapsed.days * 86400 + elapsed.seconds) + Decimal(elapsed.microseconds) / Decimal(1000000)
    return seconds / Decimal(86400)


def _snooze_state(rule, snooze, at, rides, usages, current):
    """Usage observed over [snooze start, at), with the rule's own facts (no service readings)."""
    metrics = []
    start = snooze.started_at
    trusted = not rule.item_id or current or start == at
    for name in METRICS:
        amount = getattr(snooze, name)
        if amount is None:
            continue
        if name == "calendar_days":
            metrics.append(_metric(name, amount, _elapsed_days(start, at), True))
            continue
        rows = usages[rule.item_id] if rule.item_id else rides
        selected = [row for row in rows if row.started_at is not None and start <= row.started_at < at and (rule.item_id or row.bike_id == rule.bike_id)]
        values = [Decimal(1) if name == "ride_count" and not rule.item_id else getattr(row, name) for row in selected]
        value = sum((value for value in values if value is not None), Decimal(0)) if trusted else None
        if name == "elevation_gain_m" and any(value is None for value in values):
            value = None  # a ride without elevation: never a minimum that keeps the alert hidden
        metrics.append(_metric(name, amount, value, start == at, missing=sum(value is None for value in values)))
    return SnoozeState(snooze, tuple(metrics), trusted)


def maintenance_due(actor, *, at=None):
    """Evaluate every owned rule in one coherent, bounded-query snapshot.

    Owner locking intentionally also applies to reads: ordinary mutations use the
    same lock. The GET never materializes facts or updates timestamps.
    """
    at = _instant(timezone.now() if at is None else at, "at")
    with transaction.atomic():
        owner = _lock_owner(actor)
        rules = list(MaintenanceRule.objects.filter(owner=owner).select_related("item", "bike", "service_type").order_by("id"))
        if not rules:
            return ()
        events = {}
        for event in ServiceEvent.objects.filter(owner=owner, performed_at__lte=at).order_by("-performed_at", "-created_at", "id"):
            events.setdefault((event.item_id, event.bike_id, event.service_type_id), event)
        baselines = {}
        for baseline in UsageBaseline.objects.filter(owner=owner, scope="service", cut_at__lte=at).order_by("-cut_at", "id"):
            baselines.setdefault((baseline.service_event_id, baseline.metric), baseline)
        snoozes = {}
        for snooze in MaintenanceSnooze.objects.filter(owner=owner, started_at__lte=at).filter(Q(ended_at__isnull=True) | Q(ended_at__gt=at)) \
                .order_by("-started_at", "-created_at", "id"):
            snoozes.setdefault(snooze.rule_id, snooze)
        current = UsageMaterializationState.objects.filter(owner=owner, initialized_at__isnull=False).exists()
        rides = list(Ride.objects.filter(owner=owner).only("id", "started_at", "bike_id", "distance_m", "moving_time_s", "elevation_gain_m"))
        if not rides:
            current = True
        pending = sum(ride.started_at is None for ride in rides)
        usages = defaultdict(list)
        for usage in ItemUsage.objects.filter(owner=owner, started_at__lt=at).only("item_id", "started_at", "distance_m", "moving_time_s", "ride_count",
                                                                                   "elevation_gain_m"):
            usages[usage.item_id].append(usage)
        results = []
        with localcontext() as context:
            context.prec = 40
            for rule in rules:
                event = events.get((rule.item_id, rule.bike_id, rule.service_type_id))
                reference = event.performed_at if event else rule.anchor_at
                if reference is not None and reference > at:
                    reference = None
                unknown_bikes = sum(ride.bike_id is None and ride.started_at is not None and reference is not None and reference <= ride.started_at < at for ride in rides)
                metrics = []
                for name in METRICS:
                    threshold = getattr(rule, name)
                    if threshold is None:
                        continue
                    if reference is None:
                        metrics.append(_metric(name, threshold, None, False))
                        continue
                    if name == "calendar_days":
                        elapsed = at - reference
                        # Never construct reference + timedelta(days=threshold):
                        # SQL permits intervals larger than Python datetime's range.
                        seconds = Decimal(elapsed.days * 86400 + elapsed.seconds) + Decimal(elapsed.microseconds) / Decimal(1000000)
                        metrics.append(_metric(name, threshold, seconds / Decimal(86400), True))
                        continue
                    baseline = baselines.get((event.pk, name)) if event and rule.item_id else None
                    cut = baseline.cut_at if baseline else reference
                    exact = cut == at
                    rows = usages[rule.item_id] if rule.item_id else rides
                    selected = [row for row in rows if row.started_at is not None and cut <= row.started_at < at and (rule.item_id or row.bike_id == rule.bike_id)]
                    values = [Decimal(1) if name == "ride_count" and not rule.item_id else getattr(row, name) for row in selected]
                    missing = sum(value is None for value in values)
                    trusted = not rule.item_id or current or exact
                    value = (baseline.value if baseline else Decimal(0)) + sum((value for value in values if value is not None), Decimal(0)) if trusted else None
                    # Rides without elevation count as a minimum, as for distance; but when none since the
                    # reference has it (old sources, before phase 3) it is unknown, as in statistics.
                    unrecorded = name == "elevation_gain_m" and trusted and baseline is None and bool(values) and missing == len(values)
                    if unrecorded:
                        value = None
                    # A nonempty observed interval cannot certify missing real rides.
                    complete = exact and (baseline is not None or reference == at)
                    metrics.append(_metric(name, threshold, value, complete, estimated=bool(baseline and baseline.is_estimated), missing=missing,
                                           unrecorded=unrecorded))
                status = next((state for state in ("due", "unknown", "soon", "current") if any(metric.status == state for metric in metrics)), "unknown")
                snooze = snoozes.get(rule.pk)
                # Any other reference than the one postponed (a new, edited or backdated intervention, another
                # anchor) restarted the count: that snooze no longer applies.
                same = snooze is not None and reference is not None and (snooze.reference_at, snooze.reference_event_id) == (reference, event.pk if event else None)
                state = _snooze_state(rule, snooze, at, rides, usages, current) if same else None
                results.append(MaintenanceDue(rule, event, reference, at, tuple(metrics), status, pending, unknown_bikes, current, state))
        return tuple(sorted(results, key=lambda result: (("due", "unknown", "soon", "current").index(result.status), result.rule.service_type.name, str(result.rule.pk))))
