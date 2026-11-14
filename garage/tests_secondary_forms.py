"""garage-050 F4c: the forms of the secondary screens draw their fields and their buttons as the rest of the app."""
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from test_support import contrast

from .models import ImportRun
from .services.import_history import preview_fit, start_fit_import
from .test_html import find_all, parse, visible_text
from .tests_fit_import import activity, session
from .tests_ui_guards import stylesheet

TEMPLATES = Path(__file__).parent / "templates"
CONTROLS = ("input", "select", "textarea")
PERIOD = {"requested_from": "Desde (incluido)", "requested_to": "Hasta (excluido)", "time_zone": "Zona IANA"}


def controls(root, name):
    return [found for tag in CONTROLS for found in find_all(root, tag, name=name)]


def field_of(root, name):
    """The one `div.field` that holds the control `name`."""
    wrappers = [wrapper for wrapper in find_all(root, "div", cls="field") if controls(wrapper, name)]
    assert len(wrappers) == 1, f"{len(wrappers)} div.field hold {name!r}"
    return wrappers[0]


def errors_in(root):
    return [visible_text(found) for found in find_all(root, "ul", cls="errorlist")]


def upload(raw=None):
    return SimpleUploadedFile("ride.fit", activity() if raw is None else raw)


class FieldAssertions:
    def assert_fields(self, root, expected):
        """Each one in a `div.field` of its own, with a label tied to its control."""
        for name, label in expected.items():
            with self.subTest(field=name):
                wrapper = field_of(root, name)
                control = controls(wrapper, name)[0]
                self.assertEqual([visible_text(found) for found in find_all(wrapper, "label", **{"for": control.attrs["id"]})], [label])

    def assert_error_on(self, root, name):
        wrapper = field_of(root, name)
        self.assertIn("has-error", wrapper.attrs["class"].split())
        self.assertEqual(len(errors_in(wrapper)), 1)


class SecondaryFormTests(FieldAssertions, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user("forms-owner")

    def setUp(self):
        self.client.force_login(self.owner)

    def page(self, response):
        self.assertEqual(response.status_code, 200)
        return parse(response.content.decode())

    def preview(self, **data):
        return self.page(self.client.post(reverse("garage:history-preview"), {"time_zone": "UTC", **data}))

    def resumable_run(self):
        raw = activity(session(), session(start=1_100_010_000))
        preview = preview_fit(self.owner, raw, session_indices=[0, 1])
        return start_fit_import(self.owner, raw, preview.token, budget=1)

    def test_history_filter(self):
        self.assert_fields(self.page(self.client.get(reverse("garage:history"))),
                           {**PERIOD, "pending": "Solo pendientes o campos desconocidos"})

    def test_history_filter_error_stays_on_its_field(self):
        self.assert_error_on(self.page(self.client.get(reverse("garage:history"), {"requested_from": "mañana"})), "requested_from")

    def test_statistics_filter(self):
        self.assert_fields(self.page(self.client.get(reverse("garage:statistics"))),
                           {"bike": "Bici (uso observado)", "category": "Categoría", "item": "Objeto",
                            "started_from": "Desde (incluido)", "started_to": "Hasta (excluido; vacío: ahora)", "time_zone": "Zona IANA"})

    def test_statistics_filter_error_stays_on_its_field(self):
        self.assert_error_on(self.page(self.client.get(reverse("garage:statistics"), {"time_zone": "Marte/Olympus"})), "time_zone")

    def test_fit_preview(self):
        self.assert_fields(self.page(self.client.get(reverse("garage:history-preview"))),
                           {**PERIOD, "file": "Archivo FIT original propio", "session_indices": "Índices de sesiones a importar"})

    def test_fit_preview_errors_stay_on_their_fields(self):
        page = self.preview(session_indices="dos")
        self.assert_error_on(page, "file")
        self.assert_error_on(page, "session_indices")

    def test_fit_preview_error_of_the_file_itself_is_still_shown(self):
        """One that belongs to no field, or to the whole form: `form.as_p` printed them above the fields."""
        page = self.preview(file=upload(activity()[:-1]))
        self.assertTrue(errors_in(page))
        self.assertEqual(find_all(page, "h2"), [])  # No session was shown as previewed.

    def test_execute_form_inside_the_preview(self):
        page = self.preview(file=upload())
        form = find_all(page, "form", action=reverse("garage:history-execute"))[0]
        self.assert_fields(form, {"file": "Reenvía el mismo FIT (no lo conservamos)"})

    def test_execute_form_keeps_its_token_hidden(self):
        """A hidden field drawn as the rest would come with a box and a label, and without the token nothing can be imported."""
        form = find_all(self.preview(file=upload()), "form", action=reverse("garage:history-execute"))[0]
        token = controls(form, "preview_token")
        self.assertEqual([found.attrs["type"] for found in token], ["hidden"])
        self.assertTrue(token[0].attrs["value"])
        self.assertEqual([wrapper for wrapper in find_all(form, "div", cls="field") if controls(wrapper, "preview_token")], [])

    def test_each_form_of_the_preview_labels_its_own_file(self):
        """Both ask for a file: with one `id` for the two, the label of the form that imports names the file of the other."""
        page = self.preview(file=upload())
        ids = [found.attrs["id"] for found in find_all(page, id=True)]
        self.assertEqual([name for name in set(ids) if ids.count(name) > 1], [])
        for form in find_all(page, "form", enctype="multipart/form-data"):
            with self.subTest(action=form.attrs.get("action", "preview")):
                file_input = controls(form, "file")[0]
                labels = find_all(page, "label", **{"for": file_input.attrs["id"]})
                self.assertEqual(len(labels), 1)
                self.assertEqual(len(find_all(form, "label", **{"for": file_input.attrs["id"]})), 1)

    def test_execute_page(self):
        page = self.page(self.client.post(reverse("garage:history-execute"), {}))
        self.assert_fields(page, {"file": "Reenvía el mismo FIT (no lo conservamos)"})
        self.assert_error_on(page, "file")

    def test_execute_page_still_says_when_the_hidden_token_is_missing(self):
        """`form.as_p` printed the errors of hidden fields above the form; nobody else can tell that the token is gone."""
        page = self.page(self.client.post(reverse("garage:history-execute"), {"file": upload()}))
        self.assertEqual(len(errors_in(page)), 1)
        self.assertEqual(find_all(field_of(page, "file"), "ul", cls="errorlist"), [])

    def test_resume_form_of_a_run(self):
        run = self.resumable_run()
        self.assert_fields(self.page(self.client.get(reverse("garage:history-run", args=[run.pk]))),
                           {"file": "Reenvía el FIT original para continuar"})

    def test_resume_form_error_stays_on_its_field(self):
        run = self.resumable_run()
        self.assert_error_on(self.page(self.client.post(reverse("garage:history-run", args=[run.pk]), {})), "file")

    def assert_way_back_takes_a_finger(self, page, text):
        """Alone on its line, with nothing around it for a finger to land on: the 44 px of `.link.solo`. They measured 19 and 23."""
        alone = [paragraph for paragraph in find_all(page, "p") if visible_text(paragraph) == text]
        self.assertEqual(len(alone), 1, f"{text!r}, alone in a paragraph")
        self.assertEqual(len(find_all(alone[0], "a", cls="link solo")), 1)

    def test_the_way_back_from_the_execute_page_takes_a_finger(self):
        self.assert_way_back_takes_a_finger(self.page(self.client.post(reverse("garage:history-execute"), {})), "Volver a previsualizar")

    def test_the_way_back_from_a_fit_run_takes_a_finger(self):
        run = self.resumable_run()
        self.assert_way_back_takes_a_finger(self.page(self.client.get(reverse("garage:history-run", args=[run.pk]))), "Volver al histórico")

    def test_the_way_back_from_a_strava_run_takes_a_finger(self):
        run = ImportRun.objects.create(owner=self.owner, source_kind="strava", items_imported=0, items_skipped=0)
        self.assert_way_back_takes_a_finger(self.page(self.client.get(reverse("garage:history-run", args=[run.pk]))), "Volver a Strava")


class EmptyOptionTests(TestCase):
    """garage-047 F09: no select offers Django's «---------»; an empty option says what it means."""

    @classmethod
    def setUpTestData(cls):
        from datetime import datetime, timezone as dt_timezone
        from decimal import Decimal

        from .models import Bike, Category, Item
        from .services.installations import create_installation
        from .services.ownership import create_inventory
        from .services.rides import create_manual_ride
        cls.owner = get_user_model().objects.create_user("empty-options")
        category = create_inventory(cls.owner, Category, name="Sillines")
        cls.bike = create_inventory(cls.owner, Bike, name="Carretera")
        cls.item = create_inventory(cls.owner, Item, name="Sillín", category=category)
        create_inventory(cls.owner, Item, name="Otro sillín", category=category)
        cls.period = create_installation(cls.owner, item=cls.item, bike=cls.bike,
                                         started_at=datetime(2026, 1, 1, 10, tzinfo=dt_timezone.utc))
        cls.ride = create_manual_ride(cls.owner, started_at=datetime(2026, 2, 1, 10, tzinfo=dt_timezone.utc), bike=cls.bike,
                                      name="Ruta", distance_m=Decimal(1000))

    def setUp(self):
        self.client.force_login(self.owner)

    def page(self, name, *args):
        response = self.client.get(reverse("garage:" + name, args=args))
        self.assertEqual(response.status_code, 200)
        return parse(response.content.decode())

    def first_option(self, root, name):
        selects = find_all(root, "select", name=name)
        self.assertEqual(len(selects), 1, name)
        option = find_all(selects[0], "option")[0]
        return option.attrs.get("value"), visible_text(option)

    def test_no_django_empty_option_is_shown(self):
        pages = [("item-create", ()), ("item-used-create", ()), ("installation-create", (self.item.pk,)),
                 ("installation-transfer", (self.period.pk,)), ("installation-replace", (self.period.pk,)),
                 ("baseline-create", (self.item.pk,)), ("maintenance-rule-create", ()), ("service-event-create", ()),
                 ("statistics", ()), ("usage-ride-detail", (self.ride.pk,))]
        for name, args in pages:
            with self.subTest(page=name):
                root = self.page(name, *args)
                self.assertTrue(find_all(root, "select"), "a page without selects proves nothing")
                self.assertEqual([visible_text(option) for option in find_all(root, "option") if "---" in visible_text(option)], [])

    def test_empty_options_say_what_they_mean(self):
        cases = [("item-create", (), "category", "Elige una categoría"), ("item-used-create", (), "category", "Elige una categoría"),
                 ("installation-create", (self.item.pk,), "bike", "—"), ("installation-create", (self.item.pk,), "parent_item", "—"),
                 ("installation-transfer", (self.period.pk,), "bike", "—"), ("installation-transfer", (self.period.pk,), "parent_item", "—"),
                 ("installation-replace", (self.period.pk,), "incoming_item", "Elige un objeto"),
                 ("baseline-create", (self.item.pk,), "item", "—"), ("baseline-create", (self.item.pk,), "service_event", "—"),
                 ("usage-ride-detail", (self.ride.pk,), "item", "—")]
        for name, args, field, text in cases:
            with self.subTest(page=name, field=field):
                self.assertEqual(self.first_option(self.page(name, *args), field), ("", text))

    def test_statistics_filters_say_all(self):
        """Empty there means «no filter»."""
        root = self.page("statistics")
        for field, text in (("bike", "Todas"), ("category", "Todas"), ("item", "Todos")):
            with self.subTest(field=field):
                self.assertEqual(self.first_option(root, field), ("", text))


class ZoneFoldTests(SimpleTestCase):
    def test_without_date_fields_the_zone_goes_last(self):
        """Guard, garage-047 F01: the zone follows the last date field; with none it stays the last field, before the buttons."""
        from django import forms
        from django.contrib.auth.models import AnonymousUser
        from django.template.loader import render_to_string
        from django.test import RequestFactory

        from .test_html import Node

        class NoDates(forms.Form):
            name = forms.CharField()
            time_zone = forms.CharField(initial="UTC")
            notes = forms.CharField(required=False)

        request = RequestFactory().get("/garage/")
        request.user = AnonymousUser()
        root = parse(render_to_string("garage/form.html", {"form": NoDates(), "title": "Sin fechas", "back": "/garage/"}, request=request))
        form = find_all(root, "form", cls="form")[0]
        drawn = [(child.tag, child.attrs.get("class", ""), sorted(found.attrs["name"] for tag in CONTROLS for found in find_all(child, tag)))
                 for child in form.children if isinstance(child, Node) and child.attrs.get("type") != "hidden"]
        self.assertEqual(drawn, [("div", "field", ["name"]), ("div", "field", ["notes"]), ("details", "zone", ["time_zone"]),
                                 ("div", "actionbar", [])])


class FormColumnTests(SimpleTestCase):
    def test_a_date_box_does_not_widen_the_form_or_its_field(self):
        """F4-r1: in an `auto` column a date and time with seconds asks for 306 px, and at 320 px the card has 254. No document overflow tells."""
        css = stylesheet()
        for selector in (".form", ".page .field"):
            with self.subTest(selector=selector):
                self.assertEqual(contrast.declared(css, selector).get("grid-template-columns"), "minmax(0, 1fr)")


class ButtonGuardTests(SimpleTestCase):
    def test_no_template_draws_a_button_without_a_class(self):
        """Spec garage-050 F4c. `.btn.ghost`, or `.btn.danger` if it deletes: a bare button has no style of the app."""
        bare = [f"{path.relative_to(TEMPLATES)}: {visible_text(button)}"
                for path in sorted(TEMPLATES.rglob("*.html"))
                for button in find_all(parse(path.read_text(encoding="utf-8")), "button")
                if not button.attrs.get("class", "").strip()]
        self.assertEqual(bare, [])
