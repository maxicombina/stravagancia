from uuid import UUID

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from .local_forms import localize
from .maintenance_forms import MaintenanceRuleWebForm, ServiceEventWebForm, ServiceTypeWebForm
from .models import Bike, Item, MaintenanceRule, ServiceEvent, ServiceType, UsageBaseline
from .services.maintenance import delete_maintenance
from .services.ownership import InventoryWriteError, get_inventory, scoped_inventory
from .services.lifespan import LIFE_TYPE
from .services.parts import ScopeChanged, register_together
from .services.photos import owned_photos
from .timezones import user_time_zone

KINDS = {"service-type": (ServiceType, ServiceTypeWebForm), "service-event": (ServiceEvent, ServiceEventWebForm), "maintenance-rule": (MaintenanceRule, MaintenanceRuleWebForm)}


@login_required
@never_cache
@require_http_methods(["GET"])
def maintenance_list(request):
    from .services.workshop import workshop_snapshot
    shop = workshop_snapshot(request.user, all_events=request.GET.get("all") == "1")
    return render(request, "garage/maintenance.html", {"shop": shop, "title": "Taller", "tab": "workshop", "user_tz": user_time_zone(request)})


TITLES = {"service-event": ("Registrar mantenimiento", "Editar intervención"), "maintenance-rule": ("Nueva regla", "Editar regla"),
          "service-type": ("Nuevo tipo de intervención", "Editar tipo de intervención")}
EXPLANATIONS = {
    "service-event": "Lo que hiciste y cuándo. Reinicia las reglas de ese tipo para ese objeto o bici; comprar o montar no las reinicia.",
    "maintenance-rule": "Avisa al llegar al 90 % de cualquier umbral y vence con el primero. Deja vacío lo que no uses.",
    "service-type": "Por ejemplo «Lubricar cadena» o «Cambiar pastillas». Se usa en intervenciones y reglas.",
}
DELETE_LABELS = {"service-event": "Eliminar intervención", "maintenance-rule": "Eliminar regla", "service-type": "Eliminar tipo"}


def _prefill(request):
    """Own item or bike from ?item= / ?bike=, and type from ?type= (404 for foreign or malformed ids)."""
    initial, target = {}, None
    for name, target_model in (("item", Item), ("bike", Bike)):
        if name in request.GET:
            try:
                target = get_inventory(request.user, target_model, UUID(request.GET[name]))
            except ValueError:
                raise Http404 from None
            initial = {name: target.pk}
            break
    if "type" in request.GET:
        try:
            initial["service_type"] = get_inventory(request.user, ServiceType, UUID(request.GET["type"])).pk
        except ValueError:
            raise Http404 from None
    return initial, target


def _target_page(target):
    route = "garage:item-detail" if isinstance(target, Item) else "garage:bike-detail"
    return reverse(route, args=[target.pk]), target.name


def _uuids(values):
    try:
        return [UUID(value) for value in values]
    except (TypeError, ValueError):
        raise InventoryWriteError({"__all__": "Elige una opción válida."}) from None


def _together(user, target, *, at, type_id=None, checked=()):
    """Rules of the target and of its mounted parts at `at` that the same visit can also cover (garage-035).

    `groups` is empty when there is nothing to offer; `shown` lists every rule in
    the scope (also one hidden below), which is what a later submission compares.
    The rule of the target with the chosen type is not offered: the main
    intervention covers it.
    """
    from .presentation import wear
    from .services.lifespan import is_life
    from .services.maintenance_due import maintenance_due
    from .services.parts import scope_rules
    rules = scope_rules(user, target, at=at)
    wears = {due.rule.pk: wear(due) for due in maintenance_due(user, at=at)}
    groups, index = [], {}
    for rule, parent in rules:
        place = rule.item or rule.bike
        if place.pk == target.pk and rule.service_type_id == type_id:
            continue
        if place.pk not in index:
            index[place.pk] = len(groups)
            groups.append({"target": place, "parent": parent, "rows": [], "open": place.pk == target.pk})
        group = groups[index[place.pk]]
        item_wear = wears.get(rule.pk)
        group["rows"].append({"rule": rule, "wear": item_wear, "checked": str(rule.pk) in checked,
                              "label": f"Sustitución de {place.name} (misma ficha: reinicia su vida útil)" if is_life(rule) else rule.service_type.name,
                              "life": is_life(rule)})
        if str(rule.pk) in checked or (item_wear is not None and (item_wear.needs_attention or item_wear.snoozed)):
            group["open"] = True
    other = reverse("garage:service-event-create") + (f"?type={type_id}" if type_id else "")
    return {"groups": groups, "shown": [rule.pk for rule, _ in rules], "other_url": other}


def _together_message(events):
    parts = []
    for event in events:
        target = event.item or event.bike
        text = f"Sustitución de {target.name} (reinicia su vida útil)" if event.item_id and event.service_type.name.strip().lower() == LIFE_TYPE.lower() \
            else f"{event.service_type.name} de {target.name}"
        if ServiceEvent.objects.filter(owner_id=event.owner_id, item_id=event.item_id, bike_id=event.bike_id, service_type_id=event.service_type_id,
                                       performed_at__gt=event.performed_at).exists():
            text += " (hay una posterior: no reinicia la cuenta)"
        parts.append(text)
    return "Registradas también: " + "; ".join(parts) + "."


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def maintenance_edit(request, kind, pk=None):
    model, form_class = KINDS[kind]
    obj = get_inventory(request.user, model, pk) if pk else None
    posted = request.method == "POST"
    initial, origin = {}, None
    if obj is None and model is not ServiceType and (not posted or model is ServiceEvent):
        # An intervention also on POST: a target fixed by the page stays fixed (garage-035).
        initial, origin = _prefill(request)
    shown_at = timezone.now().replace(second=0, microsecond=0)
    if obj is None and model is ServiceEvent and not posted:
        initial["performed_at"] = shown_at
        last = scoped_inventory(request.user, ServiceEvent).filter(currency__isnull=False).order_by("-performed_at", "-created_at").values_list("currency", flat=True).first()
        if last:
            initial["currency"] = last
    form = form_class(request.POST if posted else None, user=request.user, initial=initial,
                      **({"instance": obj} if obj else {}))
    # The same visit can also cover rules of the target's parts: offered only when creating from a target's screen.
    grouped = obj is None and model is ServiceEvent and origin is not None
    checked = set(request.POST.getlist("also")) if posted else set()
    together = _together(request.user, origin, at=shown_at, type_id=initial.get("service_type")) if grouped and not posted else None
    fixed = grouped and (request.POST.get("together") == "1" if posted else bool(together and together["groups"]))
    if fixed:
        for name in ("item", "bike"):
            form.fields[name].disabled = True  # the list belongs to this target
        unused = "bike" if isinstance(origin, Item) else "item"
        form.fields[unused].widget = forms.HiddenInput()  # an empty, fixed second target only adds noise
        form.fields["bike" if unused == "item" else "item"].help_text = "Fijo: el de la pantalla de la que vienes. Para otro, «Registrar en otro destino»."
    localize(form, user_time_zone(request))
    if posted and form.is_valid():
        try:
            with transaction.atomic():  # the main intervention and the others, or none
                saved = form.save()
                extras = register_together(request.user, saved, _uuids(request.POST.getlist("also")),
                                           shown=_uuids(request.POST.getlist("shown_rules"))) if fixed else []
        except ScopeChanged as error:
            form.add_error(None, error.messages)
        except ValidationError as error:
            form._update_errors(error)
        else:
            if extras:
                messages.success(request, _together_message(extras))
            return redirect("garage:service-event-detail", pk=saved.pk) if model is ServiceEvent else redirect("garage:maintenance")
    if fixed and posted:
        # Always kept once shown: the target stays fixed even if that date offers nothing else.
        cleaned = getattr(form, "cleaned_data", {})
        at, chosen = cleaned.get("performed_at"), cleaned.get("service_type")
        together = _together(request.user, origin, at=at if at is not None and timezone.is_aware(at) else shown_at,
                             type_id=chosen.pk if chosen is not None else initial.get("service_type"), checked=checked)
    if obj is None and posted and hasattr(form, "cleaned_data") and not fixed:
        # A rejected submission keeps the way back to the screen it came from.
        origin = form.cleaned_data.get("item") or form.cleaned_data.get("bike") or origin
    if obj is not None and model is ServiceEvent:
        back, back_label = reverse("garage:service-event-detail", args=[obj.pk]), "Intervención"
    elif origin is not None:
        back, back_label = _target_page(origin)
    else:
        back, back_label = reverse("garage:maintenance"), "Taller"
    context = {"form": form, "title": TITLES[kind][obj is not None], "explanation": EXPLANATIONS[kind], "back": back, "back_url": back,
               "back_label": back_label, "tab": "workshop", "submit_label": "Guardar", "together": together if fixed else None}
    if obj is not None:
        context.update(delete_url=reverse(f"garage:{kind}-delete", args=[obj.pk]), delete_label=DELETE_LABELS[kind], delete_text=_describe(obj))
    if model is not ServiceType and not scoped_inventory(request.user, ServiceType).exists():
        context["missing_types"] = True
    return render(request, "garage/form.html", context)


def _describe(obj):
    if isinstance(obj, ServiceType):
        return obj.name
    target = obj.item or obj.bike
    return f"{obj.service_type.name} · {target.name}"


@login_required
@never_cache
@require_http_methods(["GET"])
def event_detail(request, pk):
    event = get_inventory(request.user, ServiceEvent, pk)
    target = event.item or event.bike
    back = reverse("garage:item-detail" if event.item_id else "garage:bike-detail", args=[target.pk])
    from .services.service_usage import event_usage
    return render(request, "garage/service_event.html", {"event": event, "object": event, "kind": "service-event", "target": target,
        "usage": event_usage(request.user, event),
        "photos": owned_photos(request.user).filter(service_event=event).select_related("storage_object"),
        "readings": scoped_inventory(request.user, UsageBaseline).filter(service_event=event).order_by("metric", "cut_at", "pk"),
        "title": event.service_type.name, "tab": "workshop", "back_url": back, "back_label": target.name, "user_tz": user_time_zone(request)})


@login_required
@never_cache
@require_POST
def maintenance_delete(request, kind, pk):
    model, _ = KINDS[kind]
    obj = get_inventory(request.user, model, pk)
    try:
        delete_maintenance(request.user, model, pk)
    except ValidationError as error:
        protected = any(getattr(item, "code", None) == "resource_protected" for item in error.error_list) if hasattr(error, "error_list") else False
        explanation = "Tiene intervenciones, reglas, lecturas o fotos que dependen de esto: elimínalas antes." if protected else " ".join(error.messages)
        back = reverse("garage:service-event-detail" if model is ServiceEvent else f"garage:{kind}-edit", args=[obj.pk])
        return render(request, "garage/form.html", {"title": "No se puede eliminar", "explanation": explanation, "back": back,
                                                    "back_url": back, "back_label": _describe(obj), "tab": "workshop"}, status=409)
    return redirect("garage:maintenance")
