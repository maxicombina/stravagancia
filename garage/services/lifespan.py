"""Useful life of a component (garage-033): km, moving hours and time, whichever comes first.

A useful life is the item's maintenance rule of the owner's «Sustitución»
service type, shown as «Vida útil». Nothing new is stored: thresholds, the
first-reached semantics, 90 % warnings and lower bounds are the existing
maintenance rules. Registering a «Sustitución» intervention restarts it.
"""
from datetime import datetime, time

from django.db import transaction
from django.utils import timezone

from garage.models import Installation, Item, MaintenanceRule, ServiceEvent, ServiceType
from .baselines import _instant
from .maintenance import delete_maintenance, save_maintenance
from .ownership import InventoryWriteError, _lock_owner, get_inventory

LIFE_TYPE = "Sustitución"
# Written by the useful-life form; elevation (metres) since garage-030 phase 3. A ride-count threshold is kept.
THRESHOLDS = ("distance_m", "moving_time_s", "calendar_days", "elevation_gain_m")


def is_life(rule):
    """A component's useful life: an item rule of the «Sustitución» type (bike rules of that type are ordinary)."""
    return rule is not None and rule.item_id is not None and rule.service_type.name.strip().lower() == LIFE_TYPE.lower()


def latest_replacement(actor, item, *, at=None):
    """The item's latest «Sustitución» intervention up to `at`, which the useful life counts from."""
    at = _instant(timezone.now() if at is None else at, "at")
    item = get_inventory(actor, Item, getattr(item, "pk", item))
    return ServiceEvent.objects.filter(owner_id=item.owner_id, item=item, service_type__name__iexact=LIFE_TYPE, performed_at__lte=at) \
        .select_related("service_type").order_by("-performed_at", "-created_at", "id").first()


def _life_type(owner, *, create):
    kind = ServiceType.objects.filter(owner=owner, name__iexact=LIFE_TYPE).order_by("created_at", "id").first()
    if kind is None and create:
        kind = save_maintenance(owner, ServiceType, name=LIFE_TYPE,
                               notes="Vida útil de cada componente: registrar una sustitución la reinicia.")
    return kind


def _rule(owner, item):
    kind = _life_type(owner, create=False)
    if kind is None:
        return None
    return MaintenanceRule.objects.filter(owner=owner, item=item, service_type=kind).select_related("service_type").first()


def lifespan_rule(actor, item):
    with transaction.atomic():
        owner = _lock_owner(actor)
        return _rule(owner, get_inventory(owner, Item, getattr(item, "pk", item)))


def default_start(actor, item, *, zone, at=None):
    """When the useful life starts counting if the person says nothing else.

    Recorded start of use, else the purchase date (local midnight), else the
    first mount, else `at` (now). Never in the future.
    """
    at = _instant(timezone.now() if at is None else at, "at")
    item = get_inventory(actor, Item, getattr(item, "pk", item))
    candidates = []
    if item.acquisition_anchor_at is not None:
        candidates.append(item.acquisition_anchor_at)
    elif item.acquired_on is not None:
        candidates.append(datetime.combine(item.acquired_on, time(), tzinfo=zone))
    else:
        first = Installation.objects.filter(owner_id=item.owner_id, item=item).order_by("started_at", "id").values_list("started_at", flat=True).first()
        if first is not None:
            candidates.append(first)
    return min(candidates[0], at) if candidates else at


def remove_lifespan(actor, item):
    """Delete the item's useful life (the rule only; interventions and history stay)."""
    with transaction.atomic():
        owner = _lock_owner(actor)
        rule = _rule(owner, get_inventory(owner, Item, getattr(item, "pk", item)))
        if rule is not None:
            delete_maintenance(owner, MaintenanceRule, rule.pk)
        return rule is not None


def set_lifespan(actor, item, *, distance_m=None, moving_time_s=None, calendar_days=None, elevation_gain_m=None, start):
    """Create or update the useful life of one owned item.

    km, hours and days are written; a ride-count threshold set on the rules page
    is kept. Without any threshold left it is an error: removing is explicit.
    """
    with transaction.atomic():
        owner = _lock_owner(actor)
        item = get_inventory(owner, Item, getattr(item, "pk", item))
        rule = _rule(owner, item)
        values = {"distance_m": distance_m, "moving_time_s": moving_time_s, "calendar_days": calendar_days,
                  "elevation_gain_m": elevation_gain_m}
        if all(value is None for value in values.values()) and (rule is None or rule.ride_count is None):
            raise InventoryWriteError({"__all__": "Indica km, horas, desnivel o tiempo, o quita la vida útil."})
        kind = _life_type(owner, create=True)
        return save_maintenance(owner, MaintenanceRule, rule.pk if rule else None, item=item, service_type=kind,
                                anchor_at=start, **values)


def inherit_lifespan(actor, *, outgoing, incoming, at):
    """The replacement part gets the outgoing part's useful life, counted from `at`.

    Returns the new rule, or None when there is nothing to copy or the incoming
    part already has its own useful life.
    """
    with transaction.atomic():
        owner = _lock_owner(actor)
        outgoing = get_inventory(owner, Item, getattr(outgoing, "pk", outgoing))
        incoming = get_inventory(owner, Item, getattr(incoming, "pk", incoming))
        source = _rule(owner, outgoing)
        if source is None or _rule(owner, incoming) is not None:
            return None
        rule = save_maintenance(owner, MaintenanceRule, item=incoming, service_type=source.service_type, anchor_at=at,
                                **{name: getattr(source, name) for name in (*THRESHOLDS, "ride_count")})
        if ServiceEvent.objects.filter(owner=owner, item=incoming, service_type=source.service_type, performed_at__lt=at).exists():
            # An earlier «Sustitución» of this part would win over the anchor: record this one so it counts from now.
            save_maintenance(owner, ServiceEvent, item=incoming, service_type=source.service_type, performed_at=at,
                             notes=f"Montada en sustitución de {outgoing.name}.")
        return rule
