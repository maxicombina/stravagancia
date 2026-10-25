"""Más → Strava (garage-030, token mode), the daily sync endpoint and the separate/join pages of a source.

GET never writes nor calls Strava. Strava is only called when the person
presses «Sincronizar ahora» or «Importar», or when the daily sync
(POST strava/sync-all/ with X-Sync-Token) runs. Messages carry codes turned
into Spanish text, never Strava responses or tokens.
"""
import hmac

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponseForbidden, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.debug import sensitive_variables
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .history_forms import FIELD_LABELS
from .models import ActivitySource, ImportRun, StravaGear
from .services.ownership import get_inventory, scoped_inventory
from .services.strava_client import StravaError
from .services.strava_sources import (dismiss_duplicate, link_gear, merge_candidates, merge_effects, merge_source,
                                      remove_strava_data, separate_source)
from .services.strava_sync import STEP_BUDGET, default_after, purge_date, start_strava_import, strava_status, sync_now
from .services.strava_sync import sync_all as run_sync_all
from .strava_forms import ConfirmForm, GearLinkForm, MergeForm, StravaImportForm, StravaRemoveForm, owner_bikes
from .templatetags.garage_ui import datetime_text
from .timezones import user_time_zone
from .views import form_page, local, show_errors

ERROR_LABELS = {
    "not_configured": "Strava no está configurado para tu usuario de Garage (GARAGE_STRAVA_USER).",
    "unauthorized": "Strava rechazó el token de Stravagancia. Renueva el token y vuelve a intentarlo.",
    "rate_limited": "Strava pide esperar: se alcanzó su límite de peticiones. Reintenta en 15 minutos; lo ya guardado se conserva.",
    "network": "No se pudo hablar con Strava. Reintenta más tarde; lo ya guardado se conserva.",
    "invalid_response": "Strava devolvió una respuesta inesperada. No se guardó nada de esa respuesta.",
    "athlete_taken": "Ese atleta de Strava ya está vinculado a otro usuario de Garage.",
    "not_found": "Strava no encontró lo pedido.",
    "unexpected_failure": "Algo falló al sincronizar. Lo ya guardado se conserva.",
}
STATUS_LABELS = {"ok": "correcta", "partial": "con actividades omitidas por datos no válidos", "failed": "con error", "": ""}
SYNC_TOKEN_MIN = 32  # a shorter GARAGE_SYNC_TOKEN leaves the daily sync disabled (404)


def error_label(code):
    return ERROR_LABELS.get(code, ERROR_LABELS["unexpected_failure"])


def _page(request, *, import_form=None, remove_form=None, status=200):
    user = request.user
    state = strava_status(user)
    zone = user_time_zone(request)
    gear = list(scoped_inventory(user, StravaGear).select_related("bike").order_by("retired", "name", "gear_id"))
    bikes = owner_bikes(user)
    rows = [{"gear": item, "form": GearLinkForm(bikes=bikes, gear_name=item.name or item.gear_id, prefix=str(item.pk),
                                                initial={"bike": str(item.bike_id) if item.bike_id else ""})} for item in gear]
    if import_form is None:
        import_form = StravaImportForm(zone=zone, initial={"after": default_after(user).astimezone(zone).date()})
    sources = scoped_inventory(user, ActivitySource).filter(source_kind="strava", withdrawn_at__isnull=True)
    account = state.account
    # Revoked (phase 4): its own paragraph with the purge date replaces the generic «unauthorized» text.
    # Only the configured owner's account is purged by the daily sync, so only then is the date true; the
    # date is the Madrid day the daily run purges from (purge_date), promised as automatic only with a token.
    revoked_at = account.revoked_at if state.is_owner and account else None
    code = account.last_error_code if account else ""
    context = {"title": "Strava", "tab": "more", "back_url": reverse("garage:more"), "back_label": "Más", "state": state,
               "account": account, "error": error_label(code) if code and not (revoked_at and code == "unauthorized") else "",
               "auto_sync": sync_token_configured(), "revoked_at": revoked_at,
               "purge_on": purge_date(revoked_at) if revoked_at else None,
               "sync_status": STATUS_LABELS.get(account.last_sync_status, "") if account else "",
               "gear_rows": rows, "import_form": import_form, "remove_form": remove_form or StravaRemoveForm(),
               "strava_rides": sources.values("ride_id").distinct().count(),
               "duplicates": sources.filter(possible_duplicate=True).count(),
               "runs": scoped_inventory(user, ImportRun).filter(source_kind="strava").order_by("-created_at", "-pk")[:5]}
    return render(request, "garage/strava.html", context, status=status)


@never_cache
@login_required
@require_GET
def strava_page(request):
    return _page(request)


def _not_owner(request):
    if not strava_status(request.user).is_owner:
        messages.error(request, error_label("not_configured"))
        return True
    return False


@login_required
@require_POST
def strava_sync(request):
    if _not_owner(request):
        return redirect("garage:strava")
    result = sync_now(request.user)
    if result.error:
        messages.error(request, error_label(result.error))
    else:
        messages.success(request, f"Sincronizado con Strava: {result.imported} salidas nuevas, {result.updated} ya conocidas, "
                                  f"{result.skipped} omitidas (otros deportes, retiradas o datos no válidos), {result.events} avisos procesados.")
    if result.pending:
        count = "Queda 1 aviso" if result.pending == 1 else f"Quedan {result.pending} avisos"
        messages.info(request, f"{count} del webhook por confirmar: se confirman solos o al volver a pulsar.")
    if not result.complete:
        messages.info(request, "No se leyó toda la semana (límite de tiempo o más de 100 actividades): vuelve a pulsar o usa «Importar histórico».")
    return redirect("garage:strava")


def sync_token_configured():
    token = getattr(settings, "GARAGE_SYNC_TOKEN", "")
    return isinstance(token, str) and len(token) >= SYNC_TOKEN_MIN


@sensitive_variables("given")
def _sync_token_matches(request):
    """X-Sync-Token against GARAGE_SYNC_TOKEN in constant time, in its own frame.

    The given value never becomes a local of the view: a DEBUG 500 page prints
    the locals of every frame and Django's filter (sensitive_variables) only
    acts with DEBUG off. This frame has returned before the sync runs.
    """
    given = request.headers.get("X-Sync-Token", "")
    return hmac.compare_digest(given.encode("utf-8", "replace"), settings.GARAGE_SYNC_TOKEN.encode("utf-8"))


@csrf_exempt
@never_cache
def sync_all(request):
    """POST from the Cloudflare Worker: X-Sync-Token, no session; the body is ignored.

    Disabled (no or a short GARAGE_SYNC_TOKEN) it is a 404 like any unknown
    URL, whatever the method; then POST only (405) and a bare 403 for a missing
    or different token, compared in constant time. The JSON (200 also when the
    run failed) carries counters and codes only; the token is never logged,
    echoed nor stored.
    """
    if not sync_token_configured():
        raise Http404
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    if not _sync_token_matches(request):
        return HttpResponseForbidden()
    return JsonResponse(run_sync_all().as_json())


@login_required
@require_POST
def strava_import(request):
    if _not_owner(request):
        return redirect("garage:strava")
    form = StravaImportForm(request.POST, zone=user_time_zone(request))
    if form.is_valid():
        try:
            run = start_strava_import(request.user, after=form.cleaned_data["after"], budget=STEP_BUDGET)
        except StravaError as error:
            messages.error(request, error_label(error.code))
        except ValidationError as error:
            show_errors(form, error)
            return _page(request, import_form=form, status=400)
        else:
            return redirect("garage:history-run", pk=run.pk)
        return redirect("garage:strava")
    return _page(request, import_form=form, status=400)


@login_required
@require_POST
def gear_link(request, pk):
    gear = get_inventory(request.user, StravaGear, pk)
    form = GearLinkForm(request.POST, bikes=owner_bikes(request.user), prefix=str(gear.pk))
    if form.is_valid():
        try:
            link_gear(request.user, gear.pk, form.cleaned_data["bike"])
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            bike = form.cleaned_data["bike"]
            messages.success(request, f"«{gear.name or gear.gear_id}» " + (f"cuenta ahora como {bike.name}." if bike else "queda sin vincular.")
                             + " Sus salidas y contadores se recalcularon.")
    else:
        messages.error(request, "Elige una de tus bicis.")
    return redirect("garage:strava")


@login_required
@require_POST
def strava_remove(request):
    form = StravaRemoveForm(request.POST)
    if not form.is_valid():
        return _page(request, remove_form=form, status=400)
    result = remove_strava_data(request.user)
    messages.success(request, f"Quitado lo sincronizado desde Strava: {result.sources} fuentes, {result.deleted_rides} salidas "
                              f"borradas, {result.kept_rides} conservadas por otras fuentes o correcciones y {result.gear} bicis de Strava. "
                              "Volverá a llegar si pulsas «Sincronizar ahora» o «Importar».")
    return redirect("garage:strava")


@login_required
@require_http_methods(["GET", "POST"])
def source_separate(request, pk):
    source = get_inventory(request.user, ActivitySource, pk)
    form = ConfirmForm(request.POST if request.method == "POST" else None,
                       label="Confirmo separar esta fuente en una salida nueva; las correcciones manuales se quedan en la actual.")
    if request.method == "POST" and form.is_valid():
        try:
            ride = separate_source(request.user, pk)
        except ValidationError as error:
            show_errors(form, error)
        else:
            messages.success(request, "Fuente separada en una salida nueva. Las dos salidas y sus contadores se recalcularon.")
            return redirect("garage:usage-ride-detail", pk=ride.pk)
    return form_page(request, form, "Separar fuente", reverse("garage:usage-ride-detail", args=[source.ride_id]),
                     "La fuente pasa a una salida propia, con su bici y su material resueltos de nuevo. Úsalo cuando dos salidas distintas se unieron por error.")


def merge_warnings(effects):
    """What «Unir con…» does to the ride the source leaves, in Spanish, before the POST."""
    lines = ["La salida elegida recalcula sus datos, su bici y su material con esta fuente; sus correcciones manuales prevalecen."]
    if effects.deletes_ride:
        lines.append("La salida actual se queda sin fuentes ni correcciones: se borrará con su uso.")
        return lines
    if effects.corrections:
        fields = ", ".join(FIELD_LABELS.get(field, field) for field in effects.corrections)
        lines.append(f"La salida actual tiene correcciones manuales ({fields}): se conserva con ellas; no se copian a la elegida.")
    if effects.overrides:
        count = "una excepción" if effects.overrides == 1 else f"{effects.overrides} excepciones"
        lines.append(f"La salida actual tiene {count} de material: se conserva con ella.")
    if effects.other_sources:
        lines.append("La salida actual conserva sus otras fuentes.")
    if effects.loses_start:
        lines.append("Se quedará sin inicio confirmado (pendiente, sin contador) hasta que lo corrijas o la borres.")
    return lines


@login_required
@require_http_methods(["GET", "POST"])
def source_merge(request, pk):
    source = get_inventory(request.user, ActivitySource, pk)
    zone = user_time_zone(request)
    candidates = merge_candidates(request.user, pk)
    choices = [(str(row.ride.pk), f"{datetime_text(row.ride.started_at, zone)} · {row.ride.name or 'Sin nombre'}"
                + (" · coincide" if row.matches else "")) for row in candidates]
    form = MergeForm(request.POST if request.method == "POST" else None, choices=choices)
    if request.method == "POST" and choices and form.is_valid():
        try:
            ride = merge_source(request.user, pk, form.cleaned_data["ride"])
        except ValidationError as error:
            show_errors(form, error)
        else:
            messages.success(request, "Fuente unida; los contadores se recalcularon. La salida anterior sólo se borró si no le quedaban "
                                      "fuentes, correcciones ni excepciones.")
            return redirect("garage:usage-ride-detail", pk=ride.pk)
    back = reverse("garage:usage-ride-detail", args=[source.ride_id])
    # GET never writes: an empty list is shown here, not stored as a session message.
    return render(request, "garage/source_merge.html", {
        "title": "Unir con…", "back": back, "back_url": back, "back_label": "la salida", "form": local(request, form) if choices else None,
        "warnings": merge_warnings(merge_effects(request.user, pk)) if choices else []},
        status=400 if request.method == "POST" else 200)


@login_required
@require_POST
def source_keep(request, pk):
    source = get_inventory(request.user, ActivitySource, pk)
    dismiss_duplicate(request.user, pk)
    messages.success(request, "Marcada como salida distinta: deja de aparecer como posible duplicado.")
    return redirect("garage:usage-ride-detail", pk=source.ride_id)
