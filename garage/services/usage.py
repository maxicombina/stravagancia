"""Transactional set materialization, explicit reconstruction and honest totals.

Mutations hold owner first, then Ride rows in UUID order. Temporal/profile writes
conservatively rebuild all that owner's rides in this personal phase; this costs
O(owner history), and is deliberately explicit rather than hidden in signals.
Resolution is reused directly under the existing lock, never through a public
service that would recursively trigger reconstruction. Unknown-start rides have
no ItemUsage facts. Baselines remain independent query-time readings.
"""
from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from garage.models import ActivitySource, Item, ItemUsage, Ride, UsageBaseline, UsageMaterializationState
from garage.ride_values import SOURCE_PROVENANCE, USAGE_METRICS, aware_instant, validate_provenance
from .baselines import UsageObservation, UsageReading, summarize_usage
from .ownership import InventoryNotFound, InventoryWriteError, _lock_owner, get_inventory, scoped_inventory
from .usage_profiles import _load_context, _resolve
from garage.validators import exact_usage_value


@dataclass(frozen=True)
class RideUsagePlan:
    ride_id: object
    create_item_ids: frozenset
    update_item_ids: frozenset
    delete_item_ids: frozenset
    unchanged_item_ids: frozenset
    unknown_started_at: bool


@dataclass(frozen=True)
class UsageRebuildResult:
    plans: tuple[RideUsagePlan, ...]
    dry_run: bool

    @property
    def created(self):
        return sum(len(plan.create_item_ids) for plan in self.plans)

    @property
    def updated(self):
        return sum(len(plan.update_item_ids) for plan in self.plans)

    @property
    def deleted(self):
        return sum(len(plan.delete_item_ids) for plan in self.plans)

    @property
    def unchanged(self):
        return sum(len(plan.unchanged_item_ids) for plan in self.plans)


@dataclass(frozen=True)
class ItemUsageSummary:
    reading: UsageReading
    owner_pending_started_rides: int
    owner_unknown_bike_rides: int
    materialization_current: bool


def _error(field, message, code):
    return InventoryWriteError({field: ValidationError(message, code=code)})


def _instant(value, field):
    try:
        return aware_instant(value)
    except ValidationError as error:
        raise InventoryWriteError({field: error}) from error


def _values(ride, reasons):
    resolution = [{"kind": reason.kind, "resource_id": str(reason.resource_id), "root_item_id": str(reason.root_item_id)}
                  for reason in sorted(reasons, key=lambda reason: (reason.kind, reason.resource_id, reason.root_item_id))]
    return {"started_at": ride.started_at, "bike_id": ride.bike_id, "ride_count": 1, "resolution": resolution,
            "field_provenance": ride.field_provenance, **{field: getattr(ride, field) for field in USAGE_METRICS}}


def _validate_canonical_ride(owner, ride, context, sources):
    """Validate trusted typed facts once per ride, without FK checks per item."""
    if ride.owner_id != owner.pk or (ride.bike_id is not None and ride.bike_id not in context.bikes):
        raise _error("ride", "Use an owned ride and bike.", "invalid_reference")
    if ride.started_at is not None:
        _instant(ride.started_at, "started_at")
    for field in USAGE_METRICS:
        value = getattr(ride, field)
        if value is not None:
            try:
                exact_usage_value(value)
            except ValidationError as error:
                raise InventoryWriteError({field: error}) from error
    try:
        validate_provenance(ride.field_provenance)
    except ValidationError as error:
        raise InventoryWriteError({"field_provenance": error}) from error
    for entry in ride.field_provenance.values():
        if entry["kind"] in SOURCE_PROVENANCE:
            source = sources.get(entry["source_id"])
            if source is None or source[0] != ride.pk or source[1] is not None or source[2] != entry["kind"]:
                raise _error("field_provenance", "Use an active own source of this ride.", "invalid_reference")


def _plan_ride(owner, ride, context, sources, existing):
    _validate_canonical_ride(owner, ride, context, sources)
    resolved = _resolve(owner, ride, context=context)
    created, updated, unchanged = set(), set(), set()
    deleted = set(existing) - set(resolved.item_ids)
    inserts, updates = [], []
    for item_id in sorted(resolved.item_ids):
        values = _values(ride, resolved.provenance[item_id])
        usage = existing.get(item_id)
        if usage is None:
            created.add(item_id)
            inserts.append(ItemUsage(owner=owner, ride=ride, item_id=item_id, **values))
        elif any(getattr(usage, field) != value for field, value in values.items()):
            updated.add(item_id)
            for field, value in values.items():
                setattr(usage, field, value)
            updates.append(usage)
        else:
            unchanged.add(item_id)
    plan = RideUsagePlan(ride.pk, frozenset(created), frozenset(updated), frozenset(deleted), frozenset(unchanged), resolved.unknown_started_at)
    return plan, inserts, updates, [existing[item_id].pk for item_id in deleted]


def _rebuild_locked(owner, rides, *, dry_run=False):
    """Private batch path: owner/Ride locks and canonical snapshot are mandatory.

    Bulk writes are internal implementation only, never a public free-form API.
    Fields/IDs derive from the owned resolver and the validated canonical Ride;
    no user payload or unchecked FK enters these batches. SQL constraints remain
    active, and any failure rolls back the enclosing domain mutation as well.
    """
    if not rides:
        return ()
    context = _load_context(owner)
    ride_ids = [ride.pk for ride in rides]
    existing = {}
    for usage in ItemUsage.objects.filter(owner_id=owner.pk, ride_id__in=ride_ids):
        existing.setdefault(usage.ride_id, {})[usage.item_id] = usage
    sources = {str(pk): (ride_id, withdrawn, kind) for pk, ride_id, withdrawn, kind in
               ActivitySource.objects.filter(owner_id=owner.pk, ride_id__in=ride_ids).values_list("pk", "ride_id", "withdrawn_at", "source_kind")}
    plans, inserts, updates, deletes = [], [], [], []
    for ride in rides:
        plan, add, change, remove = _plan_ride(owner, ride, context, sources, existing.get(ride.pk, {}))
        plans.append(plan)
        inserts.extend(add)
        updates.extend(change)
        deletes.extend(remove)
    if not dry_run:
        if deletes:
            ItemUsage.objects.filter(owner_id=owner.pk, pk__in=deletes).delete()
        if inserts:
            ItemUsage.objects.bulk_create(inserts, batch_size=500)
        if updates:
            now = timezone.now()
            for usage in updates:
                usage.updated_at = now
            ItemUsage.objects.bulk_update(updates, ["started_at", "bike", "ride_count", "resolution", "field_provenance",
                                                   *USAGE_METRICS, "updated_at"], batch_size=200)
    return tuple(plans)


def _rebuild_ride_locked(owner, ride, *, dry_run=False):
    """Caller already holds owner; re-read and lock the canonical Ride."""
    try:
        canonical = Ride.objects.filter(owner_id=owner.pk).select_for_update().get(pk=ride.pk)
    except Ride.DoesNotExist:
        raise InventoryNotFound() from None
    plan = _rebuild_locked(owner, [canonical], dry_run=dry_run)[0]
    if not dry_run and Ride.objects.filter(owner_id=owner.pk).count() == 1:
        _mark_initialized_locked(owner)
    return plan


def _mark_initialized_locked(owner):
    state, _ = UsageMaterializationState.objects.get_or_create(owner=owner)
    if state.initialized_at is None:
        state.initialized_at = timezone.now()
        state.save(update_fields=["initialized_at", "updated_at"])


def _rebuild_all_locked(owner):
    """Authorized service hook, after its complete domain mutation, inside atomic."""
    rides = list(Ride.objects.filter(owner_id=owner.pk).select_for_update().order_by("pk"))
    plans = _rebuild_locked(owner, rides)
    _mark_initialized_locked(owner)
    return plans


def rebuild_ride_usage(actor, ride_id, /, *, dry_run=False):
    if type(dry_run) is not bool:
        raise _error("dry_run", "Use an explicit boolean.", "invalid_value")
    with transaction.atomic():
        owner = _lock_owner(actor)
        ride = get_inventory(owner, Ride, ride_id)
        return _rebuild_ride_locked(owner, ride, dry_run=dry_run)


def rebuild_usage(actor, /, *, started_from=None, started_to=None, dry_run=False):
    """Rebuild complete rides selected by current OR previously stored start.

    A moved ride selected through an old usage start is fully reconstructed even
    when its new start is outside the requested [from,to). Pending rides with
    residual usages are always cleaned; their unknown start cannot be bucketed.
    Dry runs produce the same delta plan without saving/deleting any rows.
    """
    if type(dry_run) is not bool:
        raise _error("dry_run", "Use an explicit boolean.", "invalid_value")
    lower = _instant(started_from, "started_from") if started_from is not None else None
    upper = _instant(started_to, "started_to") if started_to is not None else None
    if lower is not None and upper is not None and lower >= upper:
        raise _error("started_to", "Choose a positive reconstruction interval.", "invalid_interval")
    with transaction.atomic():
        owner = _lock_owner(actor)
        rides = scoped_inventory(owner, Ride)
        usages = scoped_inventory(owner, ItemUsage)
        current = Q()
        stored = Q()
        if lower is not None:
            current &= Q(started_at__gte=lower)
            stored &= Q(started_at__gte=lower)
        if upper is not None:
            current &= Q(started_at__lt=upper)
            stored &= Q(started_at__lt=upper)
        selected = rides.filter(current).values_list("pk", flat=True)
        stored_rides = usages.filter(stored).values_list("ride_id", flat=True)
        pending = usages.filter(ride__started_at__isnull=True).values_list("ride_id", flat=True)
        ids = set(selected) | set(stored_rides) | set(pending)
        selected_rides = list(rides.filter(pk__in=ids).select_for_update().order_by("pk"))
        plans = _rebuild_locked(owner, selected_rides, dry_run=dry_run)
        if not dry_run and lower is None and upper is None:
            _mark_initialized_locked(owner)
        return UsageRebuildResult(plans, dry_run)


def summarize_item_usage(actor, item_id, /, *, metric, scope, at, service_event=None):
    """Observed/materialized facts plus the latest eligible independent baseline.

    Coverage is conservatively unknown: neither an upload nor a materialized row
    certifies all real rides have been entered. Only the exact baseline cut can
    establish an empty complete contribution window. Ambiguous ride counts are
    owner-wide context, not inferred item usages or fabricated zero metrics.
    """
    if not isinstance(metric, str) or metric not in {"distance_m", "moving_time_s", "ride_count"}:
        raise _error("metric", "Choose a supported metric.", "invalid_metric")
    at = _instant(at, "at")
    with transaction.atomic():
        owner = _lock_owner(actor)
        item = get_inventory(owner, Item, item_id)
        usages = scoped_inventory(owner, ItemUsage).filter(item=item, started_at__lt=at).only("id", "started_at", metric).order_by("started_at", "pk")
        observations = tuple(UsageObservation(owner.pk, item.pk, metric, usage.started_at,
                             Decimal(usage.ride_count) if metric == "ride_count" else getattr(usage, metric)) for usage in usages)
        reading = summarize_usage(owner, item.pk, metric=metric, scope=scope, at=at, observations=observations,
                                  observations_complete=False, service_event=service_event)
        known_rides = scoped_inventory(owner, Ride).filter(started_at__lt=at)
        if scope == UsageBaseline.Scope.ACQUISITION and item.acquisition_anchor_at is not None:
            known_rides = known_rides.filter(started_at__gte=item.acquisition_anchor_at)
        if scope == UsageBaseline.Scope.SERVICE:
            from .baselines import _service_event
            event = _service_event(owner, item, scope, service_event)
            known_rides = known_rides.filter(started_at__gte=event.performed_at)
        pending = scoped_inventory(owner, Ride).filter(started_at__isnull=True).count()
        # An explicit full reconstruction initializes pre-existing Garage rides;
        # trusted write hooks maintain them afterwards. This O(1) marker avoids
        # repeating an O(history) resolver plan for each item/metric counter.
        current = UsageMaterializationState.objects.filter(owner=owner, initialized_at__isnull=False).exists()
        if not current and not scoped_inventory(owner, Ride).exists():
            current = True
        if not current:
            exact_cut = reading.baseline is not None and at == reading.baseline.cut_at
            reading = UsageReading(None, reading.baseline.value if exact_cut else None, reading.baseline,
                                   reading.observed_missing_values, reading.missing_values, exact_cut)
        return ItemUsageSummary(reading, pending, known_rides.filter(bike__isnull=True).count(), current)
