"""Installable-app plumbing and menu pages. Manifest, service worker and the
offline page are public and carry no user data; menus require a session."""
import json

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.cache import cache_control, never_cache
from django.views.decorators.vary import vary_on_headers
from django.views.decorators.http import require_GET

from .assets import asset_url, asset_version

STATIC_ASSETS = ("garage/garage.css", "garage/garage.js", "garage/icons/icon.svg", "garage/icons/favicon-32.png",
                 "garage/icons/apple-touch-icon.png", "garage/icons/icon-192.png")


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
        "background_color": "#f1f2f5",
        "theme_color": "#f1f2f5",
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
               "static_prefix": json.dumps(static("garage/")), "assets": json.dumps([asset_url(path) for path in STATIC_ASSETS])}
    return render(request, "garage/sw.js", context, content_type="text/javascript; charset=utf-8")


@require_GET
@cache_control(max_age=3600)
@vary_on_headers("User-Agent")
def offline(request):
    return render(request, "garage/offline.html", {"title": "Sin conexión"})


@never_cache
@login_required
@require_GET
def more(request):
    return render(request, "garage/more.html", {"title": "Más", "tab": "more"})


@never_cache
@login_required
@require_GET
def add(request):
    return render(request, "garage/add.html", {"title": "Añadir", "tab": "garage", "back_url": reverse("garage:index"),
                                               "back_label": "Garaje"})
