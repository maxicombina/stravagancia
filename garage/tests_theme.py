"""garage-050 F1c: the theme is the browser's choice, kept in a cookie and painted by the server (spec §4.8, D5, D6)."""
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.template import Context, Template
from django.test import Client, RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse

from test_support import contrast

from .test_html import accessible_text, find_all, parse, visible_text

COOKIE = "garage_theme"
ONE_YEAR = 31536000
LIGHT_MEDIA, DARK_MEDIA = "(prefers-color-scheme: light)", "(prefers-color-scheme: dark)"


def bg_of(theme):
    with open(finders.find("garage/garage.css"), encoding="utf-8") as sheet:
        return contrast.theme_tokens(contrast.token_blocks(sheet.read()), theme)["--bg"].lower()


def html_of(response):
    return response.content.decode()


def root_of(html):
    found = find_all(parse(html), "html")
    assert len(found) == 1, f"{len(found)} <html> elements"
    return found[0]


def theme_metas(html):
    return find_all(parse(html), "meta", name="theme-color")


def color_scheme(html):
    found = find_all(parse(html), "meta", name="color-scheme")
    assert len(found) == 1, f"{len(found)} color-scheme metas"
    return found[0].attrs["content"]


class AppearanceViewTests(TestCase):
    """The form's target. It keeps nothing about the user, so it does not ask who the user is."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("theme-user", password="test-only-password")

    def setUp(self):
        self.url = reverse("garage:appearance")
        self.more = reverse("garage:more")

    def post(self, **data):
        return self.client.post(self.url, data)

    def test_choosing_a_theme_sets_the_cookie_and_goes_to_next(self):
        for theme in ("dark", "light"):
            with self.subTest(theme=theme):
                response = self.post(theme=theme, next="/garage/")
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.url, "/garage/")
                self.assertEqual(response.cookies[COOKIE].value, theme)

    def test_the_cookie_lasts_a_year_for_the_whole_site_and_stays_readable_by_the_script(self):
        morsel = self.post(theme="dark").cookies[COOKIE]
        self.assertEqual(morsel["max-age"], ONE_YEAR)
        self.assertEqual(morsel["path"], "/")
        self.assertEqual(morsel["samesite"], "Lax")
        self.assertFalse(morsel["httponly"])  # garage.js reads it for the offline page.
        self.assertFalse(morsel["secure"])

    def test_over_https_the_cookie_is_secure(self):
        response = self.client.post(self.url, {"theme": "dark", "next": "/garage/"}, secure=True)
        self.assertEqual(response.url, "/garage/")
        self.assertTrue(response.cookies[COOKIE]["secure"])

    def test_automatic_deletes_the_cookie(self):
        self.client.cookies[COOKIE] = "dark"
        response = self.post(theme="auto", next="/garage/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/garage/")
        morsel = response.cookies[COOKIE]
        self.assertEqual(morsel.value, "")
        self.assertEqual(morsel["max-age"], 0)
        self.assertEqual(morsel["path"], "/")  # Otherwise it would delete another cookie and leave this one.

    def test_sending_the_same_choice_again_gives_the_same_answer(self):
        for theme, value in (("dark", "dark"), ("dark", "dark"), ("auto", ""), ("auto", "")):
            with self.subTest(theme=theme):
                response = self.post(theme=theme, next="/garage/")
                self.assertEqual((response.status_code, response.url), (302, "/garage/"))
                self.assertEqual(response.cookies[COOKIE].value, value)

    def test_a_value_outside_the_list_is_refused_and_leaves_the_cookie_alone(self):
        self.client.cookies[COOKIE] = "dark"
        for data in ({"theme": "DARK"}, {"theme": "blue"}, {"theme": ""}, {"theme": "auto "}, {"theme": '"><x'}, {"theme": ["dark", "blue"]}, {}):
            with self.subTest(data=data):
                response = self.client.post(self.url, {"next": "/garage/", **data})
                self.assertEqual(response.status_code, 400)
                self.assertNotIn(COOKIE, response.cookies)

    def test_a_next_that_is_not_local_goes_to_the_menu_and_the_choice_still_counts(self):
        for target in ("https://evil.example/", "//evil.example/", "/\\evil.example/", "javascript:alert(1)", "garage/", ""):
            with self.subTest(target=target):
                response = self.post(theme="dark", next=target)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.url, self.more)
                self.assertEqual(response.cookies[COOKIE].value, "dark")

    def test_without_next_it_goes_to_the_menu(self):
        response = self.post(theme="dark")
        self.assertEqual((response.status_code, response.url), (302, self.more))

    def test_a_next_cannot_write_headers(self):
        response = self.post(theme="dark", next="/garage/\r\nSet-Cookie: injected=1")
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("\n", response["Location"])
        self.assertNotIn("injected", response.cookies)

    def test_opening_the_address_goes_to_the_menu_and_changes_nothing(self):
        # §4.8: never a 405, with a session or without one.
        for logged_in in (False, True):
            client = Client()
            if logged_in:
                client.force_login(self.user)
            for method in (client.get, client.head):
                with self.subTest(logged_in=logged_in, method=method.__name__):
                    response = method(self.url, {"theme": "dark", "next": "https://evil.example/"})
                    self.assertEqual((response.status_code, response.url), (302, self.more))
                    self.assertNotIn(COOKIE, response.cookies)

    def test_without_a_session_the_choice_counts_and_there_is_no_detour_through_the_login(self):
        response = self.post(theme="dark", next="/garage/")
        self.assertEqual((response.status_code, response.url), (302, "/garage/"))
        self.assertEqual(response.cookies[COOKIE].value, "dark")

    def test_it_keeps_nothing_on_the_account(self):
        self.client.force_login(self.user)
        before = dict(self.client.session)
        self.post(theme="dark")
        self.assertEqual(dict(self.client.session), before)

    def test_without_the_csrf_token_it_is_forbidden(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post(self.url, {"theme": "dark", "next": "/garage/"})
        self.assertEqual(response.status_code, 403)
        self.assertNotIn(COOKIE, response.cookies)

    def test_the_form_on_the_page_works_without_javascript(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        for theme, painted in (("dark", "dark"), ("light", "light"), ("auto", None)):
            with self.subTest(theme=theme):
                form = find_all(parse(html_of(client.get(self.more))), "form", action=self.url)[0]
                self.assertEqual(form.attrs["method"], "post")
                data = {field.attrs["name"]: field.attrs.get("value", "") for field in find_all(form, "input", type="hidden")}
                response = client.post(self.url, {**data, "theme": theme})
                self.assertEqual((response.status_code, response.url), (302, self.more))
                self.assertEqual(root_of(html_of(client.get(response.url))).attrs.get("data-theme"), painted)


class PaintedThemeTests(TestCase):
    """What the server writes, so that there is no flash on navigating and nothing depends on JavaScript."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("theme-user", password="test-only-password")

    def pages(self):
        self.client.force_login(self.user)
        for name in ("garage:index", "garage:more"):
            yield name, self.client.get(reverse(name))
        self.client.logout()

    def test_a_forced_theme_is_painted_with_a_single_theme_color(self):
        for theme in ("dark", "light"):
            self.client.cookies[COOKIE] = theme
            for name, response in self.pages():
                with self.subTest(theme=theme, page=name):
                    html = html_of(response)
                    self.assertEqual(root_of(html).attrs.get("data-theme"), theme)
                    metas = theme_metas(html)
                    self.assertEqual(len(metas), 1, metas)
                    self.assertEqual(metas[0].attrs["content"].lower(), bg_of(theme))
                    self.assertNotIn("media", metas[0].attrs)
                    self.assertEqual(color_scheme(html), theme)

    def test_the_login_page_follows_the_cookie_too(self):
        # A POST without a session sets the cookie: the page it lands on has to show it.
        self.client.cookies[COOKIE] = "dark"
        html = html_of(self.client.get(reverse("login")))
        self.assertEqual(root_of(html).attrs.get("data-theme"), "dark")

    def test_anything_else_in_the_cookie_follows_the_system(self):
        for value in (None, "DARK", "auto", '"><x', "", "dark light"):
            self.client.cookies.clear()
            if value is not None:
                self.client.cookies[COOKIE] = value
            for name, response in self.pages():
                with self.subTest(value=value, page=name):
                    html = html_of(response)
                    self.assertNotIn("data-theme", root_of(html).attrs)
                    metas = theme_metas(html)
                    self.assertEqual([meta.attrs.get("media") for meta in metas], [LIGHT_MEDIA, DARK_MEDIA])
                    self.assertEqual([meta.attrs["content"].lower() for meta in metas], [bg_of("light"), bg_of("dark")])
                    self.assertEqual(color_scheme(html), "light dark")
                    self.assertNotIn("<x", html)

    def test_the_offline_page_never_depends_on_the_cookie(self):
        # Public, stored by the service worker without credentials and cacheable for an hour.
        self.client.cookies[COOKIE] = "dark"
        response = self.client.get(reverse("garage:offline"))
        html = html_of(response)
        self.assertNotIn("data-theme", root_of(html).attrs)
        self.assertEqual([meta.attrs.get("media") for meta in theme_metas(html)], [LIGHT_MEDIA, DARK_MEDIA])
        self.assertEqual(color_scheme(html), "light dark")
        self.assertIn("max-age=3600", response["Cache-Control"])
        self.assertNotIn("Cookie", response.get("Vary", ""))


class ClientThemeTagTests(TestCase):
    def render(self, cookie=None, **context):
        request = RequestFactory().get("/garage/")
        if cookie is not None:
            request.COOKIES[COOKIE] = cookie
        return Template("{% load garage_ui %}{% client_theme %}").render(Context({"request": request, **context}))

    def test_only_a_closed_list_comes_out(self):
        for cookie, expected in (("dark", "dark"), ("light", "light"), (None, ""), ("auto", ""), ("DARK", ""), ("", ""),
                                 ('"><x', ""), (" dark", "")):
            with self.subTest(cookie=cookie):
                self.assertEqual(self.render(cookie), expected)

    def test_a_page_marked_automatic_ignores_the_cookie(self):
        self.assertEqual(self.render("dark", auto_theme=True), "")

    def test_without_a_request_it_is_automatic(self):
        self.assertEqual(Template("{% load garage_ui %}{% client_theme %}").render(Context({})), "")


class AppearanceSectionTests(TestCase):
    """Más → Apariencia."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("theme-user", password="test-only-password")

    def setUp(self):
        self.client.force_login(self.user)

    def page(self):
        return html_of(self.client.get(reverse("garage:more")))

    def form(self, html=None):
        found = find_all(parse(html or self.page()), "form", action=reverse("garage:appearance"))
        self.assertEqual(len(found), 1)
        return found[0]

    def test_it_offers_three_named_options_in_a_group(self):
        form = self.form()
        self.assertEqual(form.attrs["method"], "post")
        groups = find_all(form, "fieldset", cls="seg")
        self.assertEqual(len(groups), 1)
        self.assertEqual(accessible_text(find_all(groups[0], "legend")[0]), "Apariencia")
        radios = find_all(groups[0], "input", type="radio", name="theme")
        self.assertEqual([radio.attrs["value"] for radio in radios], ["auto", "light", "dark"])
        labels = [find_all(groups[0], "label", **{"for": radio.attrs["id"]}) for radio in radios]
        self.assertEqual([visible_text(found[0]) for found in labels], ["Automático", "Claro", "Oscuro"])

    def test_each_radio_shares_its_tile_with_its_own_label(self):
        # The stylesheet stretches each radio over its tile: together they have to be one option, not three radios on one spot.
        tiles = find_all(find_all(self.form(), "fieldset", cls="seg")[0], cls="tile")
        self.assertEqual(len(tiles), 3)
        for tile, value in zip(tiles, ("auto", "light", "dark")):
            with self.subTest(value=value):
                radios, labels = find_all(tile, "input", type="radio"), find_all(tile, "label")
                self.assertEqual([radio.attrs["value"] for radio in radios], [value])
                self.assertEqual([label.attrs["for"] for label in labels], [radios[0].attrs["id"]])

    def test_the_mark_is_on_the_option_the_cookie_says(self):
        for cookie, marked in ((None, "auto"), ("light", "light"), ("dark", "dark"), ("DARK", "auto"), ("auto", "auto")):
            self.client.cookies.pop(COOKIE, None)
            if cookie is not None:
                self.client.cookies[COOKIE] = cookie
            with self.subTest(cookie=cookie):
                radios = find_all(self.form(), "input", type="radio", name="theme")
                self.assertEqual([radio.attrs["value"] for radio in radios if "checked" in radio.attrs], [marked])

    def test_going_back_does_not_bring_back_the_old_mark(self):
        # On going back a browser puts the radios of that history entry over what the server painted, unless told not to.
        self.assertEqual(self.form().attrs.get("autocomplete"), "off")

    def test_it_comes_back_to_the_menu_and_saves_with_a_button(self):
        form = self.form()
        self.assertEqual(find_all(form, "input", type="hidden", name="next")[0].attrs["value"], reverse("garage:more"))
        self.assertEqual(find_all(form, "input", type="hidden", name="csrfmiddlewaretoken")[0].attrs["type"], "hidden")
        buttons = find_all(form, "button", type="submit")
        self.assertEqual([visible_text(button) for button in buttons], ["Guardar"])
        self.assertNotIn("hidden", buttons[0].attrs)  # Only garage.js hides it: without JavaScript it is the way to save.

    def test_the_note_says_where_the_choice_is_kept(self):
        text = accessible_text(parse(self.page()))
        self.assertIn("Automático sigue el ajuste del sistema. La elección se recuerda en este navegador "
                      "(en el iPhone, la app instalada y Safari la guardan por separado).", text)

    def test_it_adds_no_inline_style_nor_script(self):
        html = self.page()
        self.assertNotIn(' style="', html)
        self.assertEqual(len(find_all(parse(html), "script")), 1)


class ThemeScriptTests(SimpleTestCase):
    """The suite does not run JavaScript: these only keep in place what a browser was seen doing."""

    def setUp(self):
        with open(finders.find("garage/garage.js"), encoding="utf-8") as script:
            self.source = script.read()

    def test_a_choice_also_goes_through_the_server(self):
        # Safari caps a cookie written by a script to seven days, whatever its Max-Age; one set by the server keeps its year.
        # And a person who chooses and leaves at once still has it sent: hence keepalive.
        handler = self.source.partition("themeForm.addEventListener('change'")[2]
        self.assertIn("fetch(themeForm.action, { method: 'POST', body: new URLSearchParams(new FormData(themeForm)), keepalive: true })", handler)
