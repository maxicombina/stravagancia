"""Ride review from the phone (garage-031.4): bike, gear that counted, effect preview."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from .presentation import ride_speed, wear
from .services.lifespan import is_life
from .services.maintenance_due import maintenance_due
from .services.ride_review import NO_BIKE, UNCHANGED, review_ride, review_state


def _bike(data):
    value = data.get("bike")
    return UNCHANGED if value is None else (None if value == NO_BIKE else value)


def _messages(error):
    if hasattr(error, "message_dict"):
        return [message for values in error.message_dict.values() for message in values]
    return list(error.messages)


def _next(request):
    target = request.POST.get("next") or request.GET.get("next") or ""
    if target.startswith("/") and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()},
                                                                   require_https=request.is_secure()):
        return target
    return reverse("garage:index")


def _rows(state):
    names = {str(bike.pk): bike.name for bike in state.bikes}
    rows = []
    for candidate in state.candidates:
        usual = state.selected_key in candidate.usual
        if candidate.selected and usual:
            tag = f"Habitual en {names[state.selected_key]}" if state.selected_key in names else "Habitual"
        elif candidate.selected:
            tag = "Añadido sólo en esta salida"
        elif usual:
            tag = "Quitado sólo en esta salida"
        else:
            tag = ""
        rows.append({"candidate": candidate, "tag": tag, "exception": candidate.selected != usual,
                     "usual": " ".join(sorted(candidate.usual))})
    return rows


def _context(request, state, errors=(), notice=""):
    ride = state.ride
    speed = ride_speed(ride)
    target = _next(request)
    back_label = "Salidas" if target.startswith(reverse("garage:usage-ride-list")) else "Garaje" if target == reverse("garage:index") else "la página anterior"
    return {"state": state, "ride": ride, "rows": _rows(state), "errors": errors, "notice": notice, "speed": speed, "next": target,
            "title": ride.name or "Salida", "tab": "rides", "back_url": target, "back_label": back_label}


def _render_submitted(request, pk, bike, gear, errors):
    """Re-render what the person submitted; fall back to the saved state if it is invalid."""
    try:
        state = review_state(request.user, pk, bike=bike, gear=gear)
    except ValidationError:
        state = review_state(request.user, pk)
    return render(request, "garage/ride_review.html", _context(request, state, errors), status=400)


def _statuses(user):
    return {due.rule.pk: wear(due) for due in maintenance_due(user)}


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def ride_review(request, pk):
    if request.method == "POST":
        bike, gear = _bike(request.POST), request.POST.getlist("gear")
        shown = request.POST.get("shown_bike")
        # Without JavaScript the switches still show the previous bike's gear:
        # use the new bike's usual gear and ask for a second look before saving.
        bike_switched = shown is not None and request.POST.get("bike") not in (None, shown)
        if request.POST.get("action") == "preview" or bike_switched:
            try:
                state = review_state(request.user, pk, bike=bike, gear=None if bike_switched else gear)
            except ValidationError as error:
                return _render_submitted(request, pk, bike, gear, _messages(error))
            notice = "Material habitual de la nueva bici marcado. Revísalo y guarda." if bike_switched and request.POST.get("action") != "preview" else ""
            return render(request, "garage/ride_review.html", _context(request, state, notice=notice))
        else:
            before = _statuses(request.user)
            try:
                result = review_ride(request.user, pk, bike=bike, gear=gear)
            except ValidationError as error:
                return _render_submitted(request, pk, bike, gear, _messages(error))
            else:
                messages.success(request, "Salida revisada." if result.bike_changed or result.overrides_changed else "Sin cambios.")
                for rule_id, after in _statuses(request.user).items():
                    previous = before.get(rule_id)
                    if previous is not None and previous.state != after.state:
                        messages.info(request, f"{'Vida útil' if is_life(after.rule) else after.rule.service_type.name} · {after.target.name}: {previous.word} → {after.word}")
                return redirect(_next(request))
    return render(request, "garage/ride_review.html", _context(request, review_state(request.user, pk)))


@never_cache
@login_required
@require_GET
def ride_review_preview(request, pk):
    try:
        state = review_state(request.user, pk, bike=_bike(request.GET), gear=request.GET.getlist("gear"))
    except ValidationError as error:
        return render(request, "garage/_review_effects.html", {"errors": _messages(error)}, status=400)
    return render(request, "garage/_review_effects.html", {"state": state})
