"""garage-031.1: mobile shell, installable-app plumbing, login and menu pages."""
import json
import re

from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse

from .assets import asset_version
from .models import Bike, Category, Item
from .services.ownership import create_inventory
from .templatetags.garage_ui import tab_for
from .timezones import DEFAULT_ZONE, parse_zone

ANDROID = "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Mobile Safari/537.36"
IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Mobile/15E148 Safari/604.1"


class ShellTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("shell-user", password="test-only-password")
        category = create_inventory(cls.user, Category, name="Cadenas")
        create_inventory(cls.user, Bike, name="Carretera")
        create_inventory(cls.user, Item, name="Cadena 11v", category=category)

    def setUp(self):
        self.client.force_login(self.user)

    def get(self, name, **headers):
        return self.client.get(reverse("garage:" + name), **headers)

    def current_tab(self, html):
        found = re.findall(r'<a class="tab" href="([^"]+)" aria-current="page">', html)
        self.assertEqual(len(found), 1, found)
        return found[0]

    def test_pages_use_the_garage_shell_not_the_legacy_strava_chrome(self):
        for name in ("index", "bike-list", "item-list", "maintenance", "statistics", "export", "more", "add",
                     "usage-ride-list", "history", "usage-profile-list", "category-list"):
            with self.subTest(name=name):
                response = self.get(name)
                self.assertEqual(response.status_code, 200)
                html = response.content.decode()
                self.assertNotIn("Strava Tools", html)
                self.assertIn('<link rel="manifest" href="/garage/manifest.webmanifest">', html)
                self.assertIn('viewport-fit=cover', html)
                self.assertIn(f"/static/garage/garage.css?v={asset_version()}", html)
                self.assertIn('class="tabbar"', html)
                # The only script is the deferred static file; no inline scripts.
                self.assertEqual(re.findall(r"<script[^>]*>", html), [f'<script src="/static/garage/garage.js?v={asset_version()}" defer>'])

    def test_active_tab_follows_the_section(self):
        expected = {"index": "/garage/", "item-list": "/garage/", "add": "/garage/", "usage-ride-list": "/garage/usage/rides/",
                    "history": "/garage/usage/rides/", "maintenance": "/garage/maintenance/", "statistics": "/garage/statistics/",
                    "more": "/garage/more/", "export": "/garage/more/", "category-list": "/garage/more/",
                    "usage-profile-list": "/garage/more/"}
        for name, href in expected.items():
            with self.subTest(name=name):
                self.assertEqual(self.current_tab(self.get(name).content.decode()), href)

    def test_tab_mapping_for_url_names(self):
        cases = {"photo-content": "garage", "bike-photo-create": "garage", "installation-create": "garage",
                 "service-event-photo-create": "workshop", "maintenance-rule-create": "workshop", "ride-review": "rides",
                 "history-run": "rides", "export-json": "more", None: "garage", "": "garage"}
        for url_name, tab in cases.items():
            with self.subTest(url_name=url_name):
                self.assertEqual(tab_for(url_name), tab)

    def test_android_fab_keeps_its_layout(self):
        # .only-android:not([hidden]) uses display:revert; the FAB rule must be more specific.
        css = open(finders.find("garage/garage.css"), encoding="utf-8").read()
        self.assertIn('html[data-os="android"] .fab.only-android:not([hidden]) { display: inline-flex !important; }', css)
        self.assertIn('class="fab only-android"', self.get("index", HTTP_USER_AGENT=ANDROID).content.decode())

    def test_index_is_get_only_and_uncached(self):
        response = self.get("index")
        self.assertIn("no-cache", response["Cache-Control"])
        self.assertEqual(self.client.post(reverse("garage:index")).status_code, 405)

    def test_platform_is_rendered_by_the_server(self):
        self.assertIn('data-os="android"', self.get("index", HTTP_USER_AGENT=ANDROID).content.decode())
        self.assertIn('data-os="ios"', self.get("index", HTTP_USER_AGENT=IPHONE).content.decode())
        self.assertIn('data-os="ios"', self.get("index").content.decode())

    def test_more_menu_links_and_logout_by_post(self):
        html = self.get("more").content.decode()
        for name in ("bike-list", "item-list", "category-list", "usage-profile-list", "export"):
            self.assertIn(f'href="{reverse("garage:" + name)}"', html)
        self.assertRegex(html, r'<form method="post" action="/accounts/logout/"><input type="hidden" name="csrfmiddlewaretoken"')
        self.assertIn("Añadir a pantalla de inicio", html)

    def test_add_menu_links(self):
        html = self.get("add").content.decode()
        for name in ("bike-create", "item-create", "item-used-create", "history-manual-create", "history",
                     "service-event-create", "category-create"):
            self.assertIn(f'href="{reverse("garage:" + name)}"', html)
        self.assertIn('class="back"', html)

    def test_menus_require_a_session_and_get(self):
        self.client.logout()
        for name in ("more", "add"):
            self.assertRedirects(self.get(name), f"/accounts/login/?next={reverse('garage:' + name)}", fetch_redirect_response=False)
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(reverse("garage:more")).status_code, 405)

    def test_login_page_uses_shell_without_tabs_and_keeps_its_contract(self):
        self.client.logout()
        html = self.client.get("/accounts/login/").content.decode()
        self.assertIn("Entrar en Garage", html)
        self.assertIn('autocomplete="username"', html)
        self.assertIn('autocomplete="current-password"', html)
        self.assertIn('name="next" value="/garage/"', html)
        self.assertNotIn('class="tabbar"', html)
        self.assertNotIn("Strava Tools", html)
        response = self.client.post("/accounts/login/", {"username": "shell-user", "password": "wrong", "next": "/garage/"})
        self.assertEqual(response.status_code, 200)
        self.assertIn('role="alert"', response.content.decode())


class InstallableAppTests(TestCase):
    """Public endpoints: no session needed and nothing personal in them."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("private-name-xyz", password="test-only-password")

    def test_manifest(self):
        response = self.client.get(reverse("garage:manifest"))
        self.assertEqual(response["Content-Type"], "application/manifest+json")
        data = json.loads(response.content)
        self.assertEqual((data["id"], data["start_url"], data["scope"], data["display"], data["lang"]),
                         ("/garage/", "/garage/", "/", "standalone", "es"))
        purposes = {(icon["sizes"], icon["purpose"]) for icon in data["icons"]}
        self.assertEqual(purposes, {("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")})
        for icon in data["icons"]:
            self.assertTrue(finders.find(icon["src"].removeprefix("/static/")), icon["src"])

    def test_public_endpoints_need_no_session(self):
        for name in ("manifest", "service-worker", "offline"):
            response = self.client.get(reverse("garage:" + name))
            self.assertEqual(response.status_code, 200, name)
        self.assertIn("User-Agent", self.client.get(reverse("garage:offline"))["Vary"])

    def test_service_worker_is_public_uncached_and_versioned(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("garage:service-worker"))
        body = response.content.decode()
        self.assertEqual(response["Content-Type"], "text/javascript; charset=utf-8")
        self.assertIn("no-cache", response["Cache-Control"])
        self.assertIn(f"const CACHE = 'garage-{asset_version()}';", body)
        self.assertIn(f"/static/garage/garage.css?v={asset_version()}", body)
        self.assertIn("credentials: 'omit'", body)
        self.assertIn("if (request.method !== 'GET') return;", body)
        self.assertIn("url.pathname.startsWith('/garage/export/')", body)
        self.assertNotIn("private-name-xyz", body)
        self.assertNotIn("csrf", body.lower())

    def test_offline_page_is_public_and_carries_no_session_data(self):
        self.client.force_login(self.user)
        html = self.client.get(reverse("garage:offline")).content.decode()
        self.assertIn("Sin conexión", html)
        self.assertNotIn("csrfmiddlewaretoken", html)
        self.assertNotIn("private-name-xyz", html)
        self.assertNotIn('class="tabbar"', html)

    def test_public_endpoints_reject_writes(self):
        for name in ("manifest", "service-worker", "offline"):
            self.assertEqual(self.client.post(reverse("garage:" + name)).status_code, 405)

    def test_icons_exist(self):
        for name in ("icon.svg", "favicon-32.png", "apple-touch-icon.png", "icon-192.png", "icon-512.png", "icon-maskable-512.png"):
            self.assertTrue(finders.find(f"garage/icons/{name}"), name)

    def test_asset_version_covers_precached_files(self):
        import hashlib
        from django.template.loader import get_template
        from .assets import TEMPLATES, VERSIONED
        digest = hashlib.sha256()
        for path in [finders.find(p) for p in VERSIONED] + [get_template(t).origin.name for t in TEMPLATES]:
            with open(path, "rb") as handle:
                digest.update(handle.read())
        self.assertEqual(asset_version(), digest.hexdigest()[:10])
        self.assertNotEqual(asset_version(), hashlib.sha256(b"").hexdigest()[:10])


class TimeZoneCookieTests(TestCase):
    """The browser zone reaches local dates on the page (raw or percent-encoded cookie)."""

    @classmethod
    def setUpTestData(cls):
        from datetime import datetime, timezone
        from .services.rides import create_manual_ride
        cls.user = get_user_model().objects.create_user("tz-user", password="test-only-password")
        # 01:30 UTC on 13 Oct: Tuesday in Madrid, still Monday 12 Oct in Buenos Aires.
        create_manual_ride(cls.user, started_at=datetime(2026, 10, 13, 1, 30, tzinfo=timezone.utc), name="Nocturna")

    def test_cookie_zone_changes_local_dates(self):
        self.client.force_login(self.user)
        self.assertIn("mar 13 oct 2026", self.client.get(reverse("garage:index")).content.decode())
        for value in ("America/Argentina/Buenos_Aires", "America%2FArgentina%2FBuenos_Aires"):
            self.client.cookies["garage_tz"] = value
            html = self.client.get(reverse("garage:index")).content.decode()
            self.assertIn("lun 12 oct 2026", html, value)
        self.client.cookies["garage_tz"] = "..%2Fetc%2Fpasswd"
        self.assertIn("mar 13 oct 2026", self.client.get(reverse("garage:index")).content.decode())


class TimeZoneTests(TestCase):
    def test_only_real_zones_are_accepted(self):
        self.assertEqual(str(parse_zone("America/Argentina/Buenos_Aires")), "America/Argentina/Buenos_Aires")
        for value in (None, "", "Mars/Olympus", "../etc/passwd", "/etc/localtime", "x" * 65, 12):
            self.assertIsNone(parse_zone(value))
        self.assertEqual(str(DEFAULT_ZONE), "Europe/Madrid")
