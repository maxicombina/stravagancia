"""A rule's alert from the phone: register the job or postpone it (garage-034)."""
from types import SimpleNamespace
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .models import SNOOZE_AMOUNTS, MaintenanceRule
from .presentation import thresholds, wear
from .services.lifespan import is_life
from .services.maintenance_due import maintenance_due
from .services.ownership import get_inventory
from .services.snoozes import end_snooze, snooze_rule
from .snooze_forms import SnoozeForm, presets
from .templatetags.garage_ui import item_icon, rule_name
from .timezones import user_time_zone


def target_url(rule):
    return reverse("garage:item-detail", args=[rule.item_id]) if rule.item_id else reverse("garage:bike-detail", args=[rule.bike_id])


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def snooze_edit(request, pk):
    rule = get_inventory(request.user, MaintenanceRule, pk)
    target = rule.item or rule.bike
    name = rule_name(rule)
    back = target_url(rule)
    options = presets(rule)
    form = SnoozeForm()
    if request.method == "POST" and request.POST.get("action") == "end":
        try:
            ended = end_snooze(request.user, rule)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            if ended:
                messages.success(request, f"{name} de {target.name} vuelve a avisar.")
        return redirect(back)
    errors = []  # not tied to the typed amounts (a shortcut, or the rule itself)
    if request.method == "POST":
        preset = request.POST.get("preset")
        amounts, notes = None, ""
        if preset is None:
            form = SnoozeForm(request.POST)
            if form.is_valid():
                amounts, notes = form.amounts, form.cleaned_data["notes"]
        elif preset in options:
            amounts = options[preset][1]
        else:
            errors.append("Elige uno de los atajos.")
        if amounts is not None:
            try:
                saved = snooze_rule(request.user, rule, notes=notes, **{key: amounts.get(key) for key in SNOOZE_AMOUNTS})
            except ValidationError as error:
                errors.extend(error.messages)
            else:
                messages.success(request, f"{name} de {target.name}: pospuesto {thresholds(saved, separator=' o ')}, lo primero que llegue.")
                return redirect(back)
    due = next((due for due in maintenance_due(request.user) if due.rule.pk == rule.pk), None)
    if due is None:  # deleted meanwhile
        raise Http404
    target_param = {"item" if rule.item_id else "bike": target.pk, "type": rule.service_type_id}
    edit_url = reverse("garage:item-lifespan", args=[rule.item_id]) if is_life(rule) else reverse("garage:maintenance-rule-edit", args=[rule.pk])
    return render(request, "garage/snooze.html", {
        "form": form, "errors": errors, "rule": rule, "target": target, "name": name, "w": wear(due),
        "presets": [(key, label, thresholds(SimpleNamespace(**{field: values.get(field) for field in SNOOZE_AMOUNTS}), separator=" o "))
                    for key, (label, values) in options.items()],
        "icon": item_icon(target) if rule.item_id else "bike", "title": f"Aviso: {name}", "back_url": back, "back_label": target.name,
        "event_url": reverse("garage:service-event-create") + "?" + urlencode(target_param), "edit_url": edit_url,
        "tab": "workshop", "user_tz": user_time_zone(request)})
