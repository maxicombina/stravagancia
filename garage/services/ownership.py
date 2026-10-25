"""Authorized inventory writes and scoped reads for forms, admin and future APIs.

Actors come from authentication, never from client data. Raw model save/update,
bulk operations and SQL are outside this API and do not enforce ownership.
Every write locks the owner first; lifecycle changes validate and close temporal
installations inside that same transaction.
"""
from datetime import datetime

from garage.ride_values import aware_instant

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Value
from django.db.models.deletion import ProtectedError
from django.db.models.functions import Lower
from django.http import Http404
from django.utils import timezone

from garage.models import ActivitySource, Bike, Category, ImportRun, Installation, Item, ItemUsage, Ride, RetirementInterval, UsageBaseline, UsageOverride, UsageProfile, UsageProfileItem, ServiceType, ServiceEvent, MaintenanceRule, MaintenanceSnooze, StravaAccount, StravaGear

INVENTORY_MODELS = (Bike, Category, Item)
CATEGORY_NAME_CONSTRAINT = "garage_category_owner_name_ci_unique"


class InventoryNotFound(Http404):
    code = "resource_not_found"

    def __init__(self):
        super().__init__("Inventory resource not found.")


class InventoryWriteError(ValidationError):
    """An expected domain error that a bound form may display after rollback."""


class CategoryNameConflict(InventoryWriteError):
    def __init__(self):
        super().__init__({"name": ValidationError("You already have a category with this name.",
                                               code="category_name_conflict")})


def require_actor(actor):
    user_model = get_user_model()
    if (not isinstance(actor, user_model) or not actor.is_authenticated or not actor.is_active
            or actor.pk is None or actor._state.adding):
        raise PermissionDenied("An authenticated active user is required.")
    user = user_model.objects.filter(pk=actor.pk, is_active=True).first()
    if user is None:
        raise PermissionDenied("An authenticated active user is required.")
    return user


def _require_model(model):
    if model not in INVENTORY_MODELS:
        raise TypeError("Unsupported inventory model.")


def scoped_inventory(actor, model):
    """Read queryset; callers must use services below for writes."""
    owner = require_actor(actor)
    if model not in (*INVENTORY_MODELS, Installation, UsageBaseline, Ride, ActivitySource, ImportRun, UsageProfile, UsageProfileItem, UsageOverride, RetirementInterval, ItemUsage, ServiceType, ServiceEvent, MaintenanceRule, MaintenanceSnooze, StravaAccount, StravaGear):
        raise TypeError("Unsupported owned resource model.")
    return model.objects.filter(owner_id=owner.pk)


def get_inventory(actor, model, resource_id):
    queryset = scoped_inventory(actor, model)
    try:
        return queryset.get(pk=resource_id)
    except (model.DoesNotExist, ValidationError, ValueError, TypeError):
        raise InventoryNotFound() from None


def _lock_owner(actor):
    owner = require_actor(actor)
    # Recheck active under the lock rather than trusting a stale auth object.
    owner = get_user_model().objects.select_for_update().filter(pk=owner.pk, is_active=True).first()
    if owner is None:
        raise PermissionDenied("An authenticated active user is required.")
    return owner


def _assign_values(owner, obj, values):
    allowed = {field.name for field in obj._meta.fields if field.editable and not field.primary_key}
    errors = {}
    for name in values:
        if name not in allowed:
            code = "immutable_field" if name in {"id", "pk", "owner", "owner_id", "created_at", "updated_at"} else "invalid_field"
            errors[name] = ValidationError("This field cannot be written.", code=code)
    if errors:
        raise ValidationError(errors)
    for name, value in values.items():
        if name in {"retired_at", "acquisition_anchor_at"} and value is not None:
            if not isinstance(value, datetime) or timezone.is_naive(value):
                raise ValidationError({name: ValidationError("Enter an instant with an explicit time zone.",
                                                            code="invalid_instant")})
        if name == "purchase_amount" and isinstance(value, (float, bool)):
            raise ValidationError({"purchase_amount": ValidationError("Use a decimal amount, never a float.",
                                                                      code="invalid_amount")})
        if name == "category":
            category_id = value.pk if isinstance(value, Category) else value
            try:
                value = get_inventory(owner, Category, category_id)
            except InventoryNotFound:
                raise ValidationError({"category": ValidationError("Choose one of your own categories.",
                                                                   code="invalid_reference")}) from None
        setattr(obj, name, value)


def validate_category_name(actor, name, *, resource_id=None):
    duplicates = scoped_inventory(actor, Category).annotate(canonical_name=Lower("name"))
    duplicates = duplicates.filter(canonical_name=Lower(Value(name)))
    if resource_id is not None:
        duplicates = duplicates.exclude(pk=resource_id)
    if duplicates.exists():
        raise CategoryNameConflict()


def _validate_inventory(obj):
    obj.full_clean(validate_constraints=False)
    if isinstance(obj, Category):
        validate_category_name(obj.owner, obj.name, resource_id=None if obj._state.adding else obj.pk)
    obj.validate_constraints()


def _translate_integrity_error(error):
    cause = error.__cause__
    constraint_name = getattr(getattr(cause, "diag", None), "constraint_name", None)
    if constraint_name == CATEGORY_NAME_CONSTRAINT:
        raise CategoryNameConflict() from error
    # Unrecognized constraints and programming errors must remain visible.
    raise error


def create_inventory(actor, model, /, **values):
    _require_model(model)
    try:
        with transaction.atomic():
            owner = _lock_owner(actor)
            obj = model(owner=owner)
            _assign_values(owner, obj, values)
            _validate_inventory(obj)
            obj.save(force_insert=True)
            return obj
    except IntegrityError as error:
        _translate_integrity_error(error)


def update_inventory(actor, model, resource_id, /, **values):
    _require_model(model)
    try:
        with transaction.atomic():
            owner = _lock_owner(actor)
            obj = get_inventory(owner, model, resource_id)
            original_retired_at = getattr(obj, "retired_at", None)
            original_acquisition_anchor = getattr(obj, "acquisition_anchor_at", None)
            _assign_values(owner, obj, values)
            _validate_inventory(obj)
            if isinstance(obj, Item) and obj.acquisition_anchor_at != original_acquisition_anchor:
                from .baselines import _validate_acquisition_anchor
                _validate_acquisition_anchor(owner, obj)
            if isinstance(obj, (Bike, Item)) and obj.retired_at is not None and obj.retired_at != original_retired_at:
                from .installations import _close_for_retirement
                _close_for_retirement(owner, obj, obj.retired_at)
            obj.save(force_update=True)
            if isinstance(obj, (Bike, Item)) and obj.retired_at != original_retired_at:
                from .usage import _rebuild_all_locked
                _rebuild_all_locked(owner)
            return obj
    except IntegrityError as error:
        _translate_integrity_error(error)


def delete_inventory(actor, model, resource_id):
    _require_model(model)
    try:
        with transaction.atomic():
            owner = _lock_owner(actor)
            obj = get_inventory(owner, model, resource_id)
            obj.delete()
    except ProtectedError:
        raise ValidationError("This resource is referenced by inventory or history.", code="resource_protected") from None


def retire_inventory(actor, model, resource_id, *, at):
    """Retain identity and close eligible open installations atomically."""
    require_actor(actor)
    if model not in (Bike, Item):
        raise TypeError("Only physical inventory can be retired.")
    if not isinstance(at, datetime) or timezone.is_naive(at):
        raise ValidationError({"retired_at": ValidationError("Enter an instant with an explicit time zone.",
                                                             code="invalid_instant")})
    return update_inventory(actor, model, resource_id, retired_at=at)


def correct_retirement(actor, model, resource_id, *, retired_at):
    """Explicit historical correction of the current flag, not a real resume.

    Direct retired_at edits through update_inventory/forms have this same
    correction meaning. Recorded closed inactivity intervals remain intact.
    """
    if model not in (Bike, Item):
        raise TypeError("Only physical inventory has retirement dates.")
    return update_inventory(actor, model, resource_id, retired_at=retired_at)


def reactivate_inventory(actor, model, resource_id, *, at=None):
    """Resume now (or at an explicit past instant), preserving real inactivity."""
    if model not in (Bike, Item):
        raise TypeError("Only physical inventory can be reactivated.")
    try:
        with transaction.atomic():
            owner = _lock_owner(actor)
            obj = get_inventory(owner, model, resource_id)
            now = timezone.now()
            try:
                resumed_at = aware_instant(now if at is None else at)
            except ValidationError as error:
                raise InventoryWriteError({"retired_at": error}) from error
            if resumed_at > now:
                raise InventoryWriteError({"retired_at": ValidationError("Reactivation cannot be scheduled in the future.", code="future_reactivation")})
            if obj.retired_at is None:
                return obj
            if obj.retired_at <= now:
                if resumed_at < obj.retired_at:
                    raise InventoryWriteError({"retired_at": ValidationError("Reactivation cannot precede retirement.", code="invalid_interval")})
                if resumed_at > obj.retired_at:
                    values = {"item": obj} if model is Item else {"bike": obj}
                    interval = RetirementInterval(owner=owner, started_at=obj.retired_at, ended_at=resumed_at, **values)
                    try:
                        interval.full_clean(validate_constraints=False)
                    except ValidationError as error:
                        raise InventoryWriteError(error.error_dict) from error
                    interval.save(force_insert=True)
            # An unapplied future retirement is cancelled without inventing a gap.
            obj.retired_at = None
            _validate_inventory(obj)
            obj.save(force_update=True)
            from .usage import _rebuild_all_locked
            _rebuild_all_locked(owner)
            return obj
    except IntegrityError as error:
        name = getattr(getattr(error.__cause__, "diag", None), "constraint_name", None)
        if name in {"garage_retirementinterval_item_no_overlap", "garage_retirementinterval_bike_no_overlap"}:
            raise InventoryWriteError({"retired_at": ValidationError("Inactivity periods cannot overlap.", code="retirement_overlap")}) from error
        raise
