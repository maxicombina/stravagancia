"""Independent readings, explicit acquisition anchors and cutoff-aware summaries.

UsageObservation is internal normalized input for a single item's metric, not
a Ride/import endpoint. Its caller guarantees unique observations; ItemUsage
deduplication and import coverage will be integrated in garage-016.
"""
from dataclasses import dataclass
from datetime import datetime, timezone as datetime_timezone
from decimal import Decimal, localcontext
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from garage.models import Item, ServiceEvent, UsageBaseline
from garage.validators import exact_usage_value
from .ownership import InventoryNotFound, InventoryWriteError, _lock_owner, get_inventory, scoped_inventory, update_inventory


def _error(field, message, code):
    return InventoryWriteError({field: ValidationError(message, code=code)})


def _instant(value, field):
    if not isinstance(value, datetime) or timezone.is_naive(value):
        raise _error(field, "Enter an instant with an explicit time zone.", "invalid_instant")
    return value.astimezone(datetime_timezone.utc)


def _metric_scope(metric, scope):
    if metric not in UsageBaseline.Metric.values:
        raise _error("metric", "Choose a supported metric.", "invalid_metric")
    if scope not in UsageBaseline.Scope.values:
        raise _error("scope", "Choose lifetime, acquisition or an explicit intervention.", "invalid_scope")


def _mutate(actor, operation):
    try:
        with transaction.atomic():
            owner = _lock_owner(actor)
            return operation(owner)
    except IntegrityError as error:
        name = getattr(getattr(error.__cause__, "diag", None), "constraint_name", None)
        if name in {"garage_baseline_unique_reading", "garage_baseline_service_unique"}:
            raise _error("cut_at", "Correct the existing reading at this cut instead of creating another.", "baseline_conflict") from error
        raise


def _assign(owner, obj, values):
    allowed = {"item", "metric", "scope", "cut_at", "value", "source", "is_estimated", "notes", "service_event"}
    for field in values:
        if field not in allowed:
            code = "immutable_field" if field in {"id", "pk", "owner", "owner_id", "created_at", "updated_at"} else "invalid_field"
            raise _error(field, "This field cannot be written.", code)
    for field, value in values.items():
        if field == "item":
            resource_id = value.pk if isinstance(value, Item) else value
            try:
                value = get_inventory(owner, Item, resource_id)
            except InventoryNotFound:
                raise _error(field, "Choose one of your own items.", "invalid_reference") from None
        elif field == "service_event" and value is not None:
            try:
                value = get_inventory(owner, ServiceEvent, getattr(value, "pk", value))
            except InventoryNotFound:
                raise _error(field, "Choose one of your own interventions.", "invalid_reference") from None
        elif field == "cut_at":
            value = _instant(value, field)
        elif field == "value":
            try:
                value = exact_usage_value(value, metric=values.get("metric", obj.metric))
            except ValidationError as error:
                raise InventoryWriteError({"value": error}) from error
        setattr(obj, field, value)


def _validate(obj):
    try:
        obj.full_clean(validate_constraints=False)
    except ValidationError as error:
        raise InventoryWriteError(error.error_dict) from error


def record_baseline(actor, /, **values):
    """Create a reading or correct the same item/metric/scope/cut, keeping UUID."""
    def operation(owner):
        candidate = UsageBaseline(owner=owner)
        _assign(owner, candidate, values)
        _validate(candidate)
        existing = scoped_inventory(owner, UsageBaseline).filter(item_id=candidate.item_id, metric=candidate.metric,
            scope=candidate.scope, cut_at=candidate.cut_at, service_event_id=candidate.service_event_id).first()
        if existing is not None:
            _assign(owner, existing, values)
            _validate(existing)
            existing.save(force_update=True)
            return existing
        candidate.save(force_insert=True)
        return candidate
    return _mutate(actor, operation)


def update_baseline(actor, baseline_id, /, **values):
    def operation(owner):
        obj = get_inventory(owner, UsageBaseline, baseline_id)
        _assign(owner, obj, values)
        _validate(obj)
        obj.save(force_update=True)
        return obj
    return _mutate(actor, operation)


def delete_baseline(actor, baseline_id):
    return _mutate(actor, lambda owner: get_inventory(owner, UsageBaseline, baseline_id).delete())


def _latest(owner, item, metric, scope, at, service_event=None):
    if scope == UsageBaseline.Scope.ACQUISITION and item.acquisition_anchor_at is None:
        return None
    rows = scoped_inventory(owner, UsageBaseline).filter(item=item, metric=metric, scope=scope, cut_at__lte=at, service_event=service_event)
    return rows.order_by("-cut_at", "id").first()


def latest_baseline(actor, item_id, *, metric, scope, at, service_event=None):
    item = get_inventory(actor, Item, item_id.pk if isinstance(item_id, Item) else item_id)
    _metric_scope(metric, scope)
    event = _service_event(actor, item, scope, service_event)
    return _latest(actor, item, metric, scope, _instant(at, "at"), event)


def _validate_acquisition_anchor(owner, item):
    """Inventory update holds the owner lock and passes the proposed item state."""
    readings = scoped_inventory(owner, UsageBaseline).filter(item=item, scope=UsageBaseline.Scope.ACQUISITION)
    if item.acquisition_anchor_at is None:
        if readings.exists():
            raise _error("acquisition_anchor_at", "Correct acquisition readings before removing their anchor.", "acquisition_anchor_in_use")
    elif readings.filter(cut_at__lt=item.acquisition_anchor_at).exists():
        raise _error("acquisition_anchor_at", "The acquisition anchor cannot follow an existing acquisition reading.", "baseline_before_anchor")


def correct_acquisition_anchor(actor, item_id, *, at):
    """Explicit correction; purchase date, lifetime and installations stay independent."""
    return update_inventory(actor, Item, item_id, acquisition_anchor_at=at)


@dataclass(frozen=True)
class UsageObservation:
    owner_id: int
    item_id: UUID
    metric: str
    started_at: datetime
    value: Decimal | None


@dataclass(frozen=True)
class UsageReading:
    observed: Decimal | None
    total: Decimal | None
    baseline: UsageBaseline | None
    observed_missing_values: int
    missing_values: int
    coverage_complete: bool

    @property
    def known(self):
        return self.total is not None

    @property
    def is_estimated(self):
        return self.baseline is not None and self.baseline.is_estimated


def summarize_usage(actor, item_id, *, metric, scope, at, observations=(), observations_complete=False, service_event=None):
    """Observed history and baseline plus [C,T), with explicit coverage.

missing_values counts unknown contributions since the chosen cut (or the whole
observed scope without a reading). observed_missing_values counts the complete
observed window. A computable total can still have partial coverage; known does
not promise complete history or that an estimated baseline is exact.
"""
    item = get_inventory(actor, Item, item_id.pk if isinstance(item_id, Item) else item_id)
    _metric_scope(metric, scope)
    at = _instant(at, "at")
    event = _service_event(actor, item, scope, service_event)
    if event is not None and at < event.performed_at:
        return UsageReading(None, None, None, 0, 0, False)
    if not isinstance(observations_complete, bool):
        raise _error("observations_complete", "Declare coverage explicitly.", "invalid_coverage")
    entries = []
    for observation in observations:
        if not isinstance(observation, UsageObservation):
            raise _error("observations", "Use canonical usage observations.", "invalid_observation")
        if observation.owner_id != item.owner_id or observation.item_id != item.pk:
            raise PermissionDenied("Only this owner's item observations are allowed.")
        if observation.metric != metric:
            raise _error("observations", "Do not mix different metrics.", "invalid_observation")
        start = _instant(observation.started_at, "observations")
        try:
            value = exact_usage_value(observation.value, metric=metric) if observation.value is not None else None
        except ValidationError as error:
            raise InventoryWriteError({"observations": error}) from error
        if start < at:
            entries.append((start, value))
    if scope == UsageBaseline.Scope.ACQUISITION:
        if item.acquisition_anchor_at is None:
            return UsageReading(None, None, None, 0, 0, False)
        entries = [(start, value) for start, value in entries if start >= item.acquisition_anchor_at]
    if event is not None:
        entries = [(start, value) for start, value in entries if start >= event.performed_at]
    baseline = _latest(actor, item, metric, scope, at, event)
    contributions = [(start, value) for start, value in entries if baseline is None or start >= baseline.cut_at]
    with localcontext() as context:
        context.prec = max(28, 24 + len(str(len(entries) + 1)))
        observed = sum((value for _, value in entries if value is not None), Decimal("0.000"))
        total = None if baseline is None else baseline.value + sum(
            (value for _, value in contributions if value is not None), Decimal("0.000"))
    if event is not None and baseline is None and observations_complete:
        total = observed
    missing = sum(value is None for _, value in contributions)
    observed_missing = sum(value is None for _, value in entries)
    complete = baseline is not None and missing == 0 and (observations_complete or at == baseline.cut_at)
    if event is not None and baseline is None:
        complete = observations_complete and missing == 0
    return UsageReading(observed, total, baseline, observed_missing, missing, complete)


def _service_event(actor, item, scope, event):
    if scope != UsageBaseline.Scope.SERVICE:
        if event is not None:
            raise _error("service_event", "Only service scope accepts an intervention.", "invalid_reference")
        return None
    if event is None:
        raise _error("service_event", "Choose an explicit intervention.", "service_event_required")
    event = get_inventory(actor, ServiceEvent, getattr(event, "pk", event))
    if event.item_id != item.pk:
        raise _error("service_event", "Choose an intervention on this item.", "invalid_reference")
    return event
