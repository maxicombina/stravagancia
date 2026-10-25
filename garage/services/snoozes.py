"""Postpone a rule's alert by km, hours, rides, days or elevation, whichever comes first (garage-034, garage-030 phase 3).

A snooze starts now and never rewrites history. It remembers the rule's
reference at that moment: when the reference changes (an intervention, also a
backdated one, or another anchor) the count restarted and the snooze no longer
applies. It also ends when its first amount is reached (both computed in
services.maintenance_due), by hand, when another snooze of the rule replaces it,
or when the rule moves to another target or type.
"""
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from garage.models import SNOOZE_AMOUNTS, MaintenanceRule, MaintenanceSnooze
from .baselines import _instant
from .maintenance import maintenance_reference
from .ownership import InventoryWriteError, _lock_owner, get_inventory


def _open(owner, rule):
    return MaintenanceSnooze.objects.filter(owner=owner, rule=rule, ended_at__isnull=True).first()


def _close(snooze, at):
    snooze.ended_at = at
    snooze.full_clean()
    snooze.save(update_fields=["ended_at", "updated_at"])


def _when(at):
    """`at` or now, read after taking the owner lock: a request that waited for it never goes back in time."""
    now = timezone.now()
    at = now if at is None else _instant(at, "at")
    if at > now:
        raise InventoryWriteError({"__all__": "Un aplazamiento empieza ahora: no puede ser futuro."})
    return at


def open_snooze(actor, rule):
    """The rule's open record (it may already be used up or no longer apply), or None."""
    with transaction.atomic():
        owner = _lock_owner(actor)
        return _open(owner, get_inventory(owner, MaintenanceRule, getattr(rule, "pk", rule)))


def snooze_rule(actor, rule, *, distance_m=None, moving_time_s=None, ride_count=None, calendar_days=None, elevation_gain_m=None,
                at=None, notes=""):
    """Postpone one owned rule from `at` (now). An open snooze of the rule ends at that instant."""
    if at is not None:
        _instant(at, "at")
    amounts = {"distance_m": distance_m, "moving_time_s": moving_time_s, "ride_count": ride_count, "calendar_days": calendar_days,
               "elevation_gain_m": elevation_gain_m}
    if all(value is None for value in amounts.values()):
        raise InventoryWriteError({"__all__": "Indica cuántos km, horas, salidas, días o metros de desnivel quieres posponer."})
    try:
        with transaction.atomic():
            owner = _lock_owner(actor)
            at = _when(at)
            rule = get_inventory(owner, MaintenanceRule, getattr(rule, "pk", rule))
            event, reference = maintenance_reference(owner, rule, at=at)
            if reference is None:
                raise InventoryWriteError({"__all__": "La regla aún no cuenta desde ninguna fecha: no hay aviso que posponer."})
            history = MaintenanceSnooze.objects.filter(owner=owner, rule=rule).aggregate(start=Max("started_at"), end=Max("ended_at"))
            latest = max((value for value in history.values() if value is not None), default=None)
            if latest is not None and at < latest:
                raise InventoryWriteError({"__all__": "Ya hay un aplazamiento posterior: un aplazamiento nuevo empieza después."})
            previous = _open(owner, rule)
            if previous is not None:
                _close(previous, at)
            snooze = MaintenanceSnooze(owner=owner, rule=rule, started_at=at, notes=notes, reference_at=reference,
                                       reference_event_id=event.pk if event else None, **amounts)
            try:
                snooze.full_clean()
            except ValidationError as error:
                raise InventoryWriteError(error.error_dict) from error
            snooze.save()
            return snooze
    except IntegrityError as error:
        name = getattr(getattr(error.__cause__, "diag", None), "constraint_name", "") or ""
        if name.startswith("garage_snooze_"):
            raise InventoryWriteError({"__all__": "No se pudo posponer: vuelve a intentarlo."}) from error
        raise


def end_snooze(actor, rule, *, at=None):
    """Stop postponing: the alert is shown again. Returns whether a snooze was open."""
    if at is not None:
        _instant(at, "at")
    with transaction.atomic():
        owner = _lock_owner(actor)
        at = _when(at)
        snooze = _open(owner, get_inventory(owner, MaintenanceRule, getattr(rule, "pk", rule)))
        if snooze is None:
            return False
        if at < snooze.started_at:
            raise InventoryWriteError({"__all__": "No puede terminar antes de empezar."})
        _close(snooze, at)
        return True


def close_moved(owner, rule, at):
    """A rule moved to another target or type: its open snooze belonged to the old alert. Caller holds the lock."""
    snooze = _open(owner, rule)
    if snooze is not None:
        _close(snooze, max(at, snooze.started_at))


__all__ = ["SNOOZE_AMOUNTS", "close_moved", "end_snooze", "open_snooze", "snooze_rule"]
