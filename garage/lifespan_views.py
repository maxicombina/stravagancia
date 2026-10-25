"""Useful life of a component from the phone (garage-033)."""
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .lifespan_forms import SUGGESTIONS, LifespanForm
from .local_forms import localize
from .models import Item
from .presentation import thresholds
from .services.lifespan import default_start, latest_replacement, lifespan_rule, remove_lifespan, set_lifespan
from .services.ownership import get_inventory
from .templatetags.garage_ui import item_icon
from .timezones import user_time_zone


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def lifespan_edit(request, pk):
    item = get_inventory(request.user, Item, pk)
    zone = user_time_zone(request)
    rule = lifespan_rule(request.user, item)
    back = reverse("garage:item-detail", args=[item.pk])
    if request.method == "POST" and request.POST.get("action") == "remove":
        if remove_lifespan(request.user, item):
            messages.success(request, "Vida útil quitada. Las intervenciones y el historial se conservan.")
        return redirect(back)
    form = LifespanForm(request.POST if request.method == "POST" else None, rule=rule,
                        start=default_start(request.user, item, zone=zone, at=timezone.now().replace(second=0, microsecond=0)))
    localize(form, zone)
    if request.method == "POST" and form.is_valid():
        try:
            saved = set_lifespan(request.user, item, start=form.cleaned_data["start"], **form.lifespan)
        except ValidationError as error:
            for message in error.messages:
                form.add_error(None, message)
        else:
            messages.success(request, f"Vida útil de {item.name}: {thresholds(saved)}, lo primero que llegue.")
            return redirect(back)
    # Also without a rule yet: a replacement registered earlier is where the life will count from.
    event = latest_replacement(request.user, item)
    icon = item_icon(item)
    return render(request, "garage/lifespan.html", {
        "form": form, "item": item, "rule": rule, "title": "Vida útil de " + item.name, "back_url": back, "back_label": item.name,
        "suggestion": SUGGESTIONS.get(icon), "reference_event": event, "suggestion_json": json.dumps(SUGGESTIONS[icon][0]) if icon in SUGGESTIONS else "",
        "icon": icon, "user_tz": zone})
