"""Private interventions and independent rules; due-date alerts belong to garage-018."""
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from garage.models import Bike, Item, MaintenanceRule, ServiceEvent, ServiceType, UsageBaseline
from .baselines import _instant
from .ownership import InventoryNotFound, InventoryWriteError, _lock_owner, get_inventory, scoped_inventory

MODELS = (ServiceType, ServiceEvent, MaintenanceRule)


def save_maintenance(actor, model, resource_id=None, **values):
    if model not in MODELS:
        raise TypeError("Unsupported maintenance resource.")
    try:
        with transaction.atomic():
            owner = _lock_owner(actor)
            obj = get_inventory(owner, model, resource_id) if resource_id else model(owner=owner)
            alert = (obj.item_id, obj.bike_id, obj.service_type_id) if resource_id and model is MaintenanceRule else None
            allowed = {f.name for f in model._meta.fields if f.editable and not f.primary_key}
            for field, value in values.items():
                if field not in allowed:
                    raise InventoryWriteError({field: "This field cannot be written."})
                related = {"item": Item, "bike": Bike, "service_type": ServiceType}.get(field)
                if related and value is not None:
                    try:
                        value = get_inventory(owner, related, getattr(value, "pk", value))
                    except InventoryNotFound:
                        raise InventoryWriteError({field: "Choose one of your own resources."}) from None
                if field in ("performed_at", "anchor_at") and value is not None:
                    value = _instant(value, field)
                if field == "amount" and isinstance(value, (float, bool)):
                    raise InventoryWriteError({field: "Use an exact decimal amount."})
                setattr(obj, field, value)
            try:
                obj.full_clean()
            except ValidationError as error:
                raise InventoryWriteError(error.error_dict) from error
            obj.save()
            if alert is not None and alert != (obj.item_id, obj.bike_id, obj.service_type_id):
                # Another target or type is another alert: a snooze of the old one must not hide it (garage-034).
                from .snoozes import close_moved
                close_moved(owner, obj, timezone.now())
            return obj
    except IntegrityError as error:
        name = getattr(getattr(error.__cause__, "diag", None), "constraint_name", "") or ""
        if name in ("garage_servicetype_owner_name_unique", "garage_rule_item_type_unique", "garage_rule_bike_type_unique"):
            raise InventoryWriteError({"__all__": "This type or rule already exists."}) from error
        raise


def delete_maintenance(actor, model, resource_id):
    if model not in MODELS:
        raise TypeError("Unsupported maintenance resource.")
    try:
        with transaction.atomic():
            get_inventory(_lock_owner(actor), model, resource_id).delete()
    except ProtectedError:
        raise InventoryWriteError("This resource has interventions, readings or photos.", code="resource_protected") from None


def maintenance_reference(actor, rule_id, *, at):
    """Latest same-target/same-type event <= cutoff, else explicit initial anchor.

    Returns (event, instant). Missing reference remains None; inventory purchase,
    retirement and installations never participate in this selection.
    """
    rule = get_inventory(actor, MaintenanceRule, getattr(rule_id, "pk", rule_id))
    at = _instant(at, "at")
    event = scoped_inventory(actor, ServiceEvent).filter(item_id=rule.item_id, bike_id=rule.bike_id,
        service_type_id=rule.service_type_id, performed_at__lte=at).order_by("-performed_at", "-created_at", "id").first()
    anchor = event.performed_at if event else rule.anchor_at
    return event, anchor if anchor is not None and anchor <= at else None
