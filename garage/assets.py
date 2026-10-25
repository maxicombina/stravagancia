"""Version token for Garage's unhashed static files (STATICFILES_STORAGE is ignored
by Django 5.2, so names carry no hash). Shared by templates and the service worker,
it also covers what the worker precaches: icons and the offline page templates."""
import hashlib
from functools import cache

from django.contrib.staticfiles import finders
from django.template.loader import get_template
from django.templatetags.static import static

VERSIONED = ("garage/garage.css", "garage/garage.js", "garage/icons/icon.svg", "garage/icons/favicon-32.png",
             "garage/icons/apple-touch-icon.png", "garage/icons/icon-192.png", "garage/icons/icon-512.png",
             "garage/icons/icon-maskable-512.png")
TEMPLATES = ("garage/offline.html", "garage/shell.html", "garage/_icons.html")


@cache
def asset_version():
    digest = hashlib.sha256()
    sources = [finders.find(path) for path in VERSIONED] + [get_template(name).origin.name for name in TEMPLATES]
    for found in sources:
        if not found:
            raise FileNotFoundError("A Garage asset is missing; run tools/garage_icons.py or restore the file.")
        with open(found, "rb") as handle:
            digest.update(handle.read())
    return digest.hexdigest()[:10]


def asset_url(path):
    return f"{static(path)}?v={asset_version()}"
