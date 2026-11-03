"""Installable-app plumbing and menu pages. Manifest, service worker and the
offline page are public and carry no user data; menus require a session."""
import json

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import cache_control, never_cache
from django.views.decorators.vary import vary_on_headers
from django.views.decorators.http import require_GET

from .assets import asset_url, asset_version
from .templatetags.garage_ui import FORCED_THEMES, THEME_COOKIE

STATIC_ASSETS = ("garage/garage.css", "garage/garage.js", "garage/icons/icon.svg", "garage/icons/favicon-32.png",
                 "garage/icons/apple-touch-icon.png", "garage/icons/icon-192.png")
# garage.css asks for these without ?v= and the worker matches the whole URL, so they are precached as they are asked for.
STATIC_FONTS = ("garage/fonts/figtree-latin-wght-v1.woff2", "garage/fonts/outfit-latin-wght-v1.woff2")
THEME_MAX_AGE = 31536000  # One year, like garage_tz in garage.js.


@require_GET
@cache_control(max_age=3600)
def manifest(request):
    data = {
        "id": reverse("garage:index"),
        "name": "Garage",
        "short_name": "Garage",
        "description": "Bicis, material y mantenimiento.",
        "lang": "es",
        "start_url": reverse("garage:index"),
        "scope": "/",
        "display": "standalone",
        "background_color": "#F5F3EF",
        "theme_color": "#F5F3EF",
        "icons": [
            {"src": static("garage/icons/icon-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": static("garage/icons/icon-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": static("garage/icons/icon-maskable-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }
    return HttpResponse(json.dumps(data, ensure_ascii=False), content_type="application/manifest+json")


@require_GET
@cache_control(no_cache=True)
def service_worker(request):
    # Server-generated paths only, serialized as JS literals (the file is JavaScript, not HTML).
    context = {"version": asset_version(), "offline_url": json.dumps(reverse("garage:offline")),
               "static_prefix": json.dumps(static("garage/")),
               "assets": json.dumps([asset_url(path) for path in STATIC_ASSETS] + [static(path) for path in STATIC_FONTS])}
    return render(request, "garage/sw.js", context, content_type="text/javascript; charset=utf-8")


@require_GET
@cache_control(max_age=3600)
@vary_on_headers("User-Agent")
def offline(request):
    # The worker stores it without credentials and it is cacheable: it cannot vary by cookie, garage.js applies the theme.
    return render(request, "garage/offline.html", {"title": "Sin conexión", "auto_theme": True})


@never_cache
@login_required
@require_GET
def more(request):
    return render(request, "garage/more.html", {"title": "Más", "tab": "more"})


@never_cache
def appearance(request):
    """The theme is this browser's, not the account's: no session needed, and a POST whose session expired still counts."""
    if request.method != "POST":
        return redirect("garage:more")
    theme = request.POST.get("theme")
    if theme != "auto" and theme not in FORCED_THEMES:
        return HttpResponseBadRequest("Tema no válido.")
    target = request.POST.get("next", "")
    if not (target.startswith("/") and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()},
                                                                       require_https=request.is_secure())):
        target = reverse("garage:more")
    response = HttpResponseRedirect(target)
    if theme == "auto":
        response.delete_cookie(THEME_COOKIE, path="/", samesite="Lax")
    else:
        response.set_cookie(THEME_COOKIE, theme, max_age=THEME_MAX_AGE, path="/", samesite="Lax", secure=request.is_secure())
    return response


@never_cache
@login_required
@require_GET
def add(request):
    return render(request, "garage/add.html", {"title": "Añadir", "tab": "garage", "back_url": reverse("garage:index"),
                                               "back_label": "Garaje"})
