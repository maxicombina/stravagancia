"""Read-only snapshot for the Taller (workshop) tab. No rebuilds, no writes."""
from dataclasses import dataclass

from django.db import transaction
from django.db.models.functions import Lower
from django.utils import timezone

from garage.models import Bike, Item, ServiceEvent, ServiceType
from garage.presentation import by_severity, wear
from .baselines import _instant
from .home import HomeAlert, _retired, mount_resolver, open_installations, place_of
from .maintenance_due import maintenance_due
from .ownership import _lock_owner

EVENT_LIMIT = 20


@dataclass(frozen=True)
class Workshop:
    attention: tuple[HomeAlert, ...]
    snoozed: tuple[HomeAlert, ...]
    nodata: tuple[HomeAlert, ...]
    calm: tuple[HomeAlert, ...]
    rules: tuple
    events: tuple[ServiceEvent, ...]
    events_total: int
    types: tuple[ServiceType, ...]
    dues: tuple
    usage_current: bool


def nodata_reason(due):
    if due.reference_at is None:
        return "Falta una intervención o la fecha desde la que contar."
    if due.rule.item_id and not due.materialization_current:
        return "Uso pendiente de calcular."
    if any(getattr(metric, "unrecorded", False) for metric in due.metrics):
        # garage-030 phase 3 review: old sources have no elevation until re-imported.
        return "Ninguna salida desde la referencia registra desnivel: vuelve a importar sus FIT o el histórico de Strava."
    return "Sin datos de uso desde la referencia."


def workshop_snapshot(actor, *, at=None, all_events=False):
    at = _instant(timezone.now() if at is None else at, "at")
    with transaction.atomic():
        owner = _lock_owner(actor)
        dues = maintenance_due(owner, at=at)
        bikes = dict(Bike.objects.filter(owner=owner).values_list("id", "name"))
        items = dict(Item.objects.filter(owner=owner).values_list("id", "name"))
        open_now = open_installations(owner, at)
        events = ServiceEvent.objects.filter(owner=owner).select_related("item__category", "bike", "service_type") \
            .order_by("-performed_at", "-created_at", "-id")
        events_total = events.count()
        events = tuple(events if all_events else events[:EVENT_LIMIT])
        types = tuple(ServiceType.objects.filter(owner=owner).order_by(Lower("name"), "id"))

    mount_of = mount_resolver(open_now, bikes, items)
    groups = {"attention": [], "snoozed": [], "nodata": [], "calm": []}
    for item in by_severity([wear(due) for due in dues]):
        if _retired(item.target, at):
            continue
        group = "attention" if item.needs_attention else item.state if item.state in ("snoozed", "nodata") else "calm"
        groups[group].append(HomeAlert(item, place_of(item, mount_of)[1]))
    rules = tuple(sorted((due.rule for due in dues), key=lambda rule: (_retired(rule.item or rule.bike, at), rule.service_type.name.lower(),
                                                                         str(rule.item or rule.bike).lower(), str(rule.pk))))
    return Workshop(attention=tuple(groups["attention"]), snoozed=tuple(groups["snoozed"]), nodata=tuple(groups["nodata"]), calm=tuple(groups["calm"]), rules=rules,
                    events=events, events_total=events_total, types=types,
                    dues=tuple(due for due in dues if not _retired(due.rule.item or due.rule.bike, at)),
                    usage_current=all(due.materialization_current for due in dues))
