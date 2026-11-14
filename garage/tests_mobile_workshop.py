"""garage-032.1: local time in forms, rules in km/h, Taller and the intervention screens."""
import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.contrib.messages import get_messages
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .forms import UsageBaselineForm
from .local_forms import LocalDateTimeInput, localize
from .maintenance_forms import MaintenanceRuleWebForm as MaintenanceRuleForm, ServiceEventWebForm as ServiceEventForm
from .models import Bike, Category, Installation, Item, MaintenanceRule, ServiceEvent, ServiceType
from .presentation import ring, thresholds
from .services import workshop as workshop_module
from .services.baselines import record_baseline
from .services.lifespan import set_lifespan
from .services.maintenance import save_maintenance
from .services.ownership import create_inventory
from .services.parts import scope_rules
from .services.snoozes import snooze_rule
from .services.workshop import EVENT_LIMIT, workshop_snapshot
from .test_html import Node, accessible_text, find_all, parse, row_by_href, visible_text
from .tests_mobile_home import NOW, at, days_ago, garage  # noqa: F401 (fixture)
from .web_forms import TemporalActionForm

UTC = dt_timezone.utc
MADRID = ZoneInfo("Europe/Madrid")
WRITES = {"INSERT", "UPDATE", "DELETE"}


FROZEN = datetime(2026, 10, 17, 10, 7, 30, tzinfo=UTC)  # far from any summer-time change


@pytest.fixture
def frozen(monkeypatch):
    monkeypatch.setattr("django.utils.timezone.now", lambda: FROZEN)
    return FROZEN


def writes(queries):
    return [q["sql"] for q in queries if q["sql"].lstrip().split()[0].upper() in WRITES]


def value_of(html, name):
    match = re.search(rf'<input[^>]*name="{name}"[^>]*>', html)
    assert match, name
    found = re.search(r'value="([^"]*)"', match.group(0))
    return found.group(1) if found else ""


def render(form, name):
    return str(form[name])


def zone_fold(html):
    """The one `details.zone` of a page, and the elements of the form that holds it, in their order."""
    root = parse(html)
    folds = find_all(root, "details", cls="zone")
    assert len(folds) == 1, f"{len(folds)} time zone folds"
    form = next(form for form in find_all(root, "form") if any(fold is folds[0] for fold in find_all(form, "details")))
    return folds[0], [child for child in form.children if isinstance(child, Node)]


def zone_summary(html):
    fold, _ = zone_fold(html)
    return visible_text(find_all(fold, "summary")[0])


def control_names(node):
    """Names of the controls a person fills in inside `node`."""
    return {found.attrs.get("name") for tag in ("input", "select", "textarea") for found in find_all(node, tag)
            if found.attrs.get("type") != "hidden"}


class TestLocalDateTimeInput:
    @pytest.mark.parametrize("value,kind,step", [
        (datetime(2026, 1, 2, 10, 30), "datetime-local", False),
        (datetime(2026, 1, 2, 10, 30, 5), "datetime-local", True),
        (datetime(2026, 1, 2, 10, 30, 5, 123456), "text", False),
        ("2026-01-02T10:30", "datetime-local", False),
        ("2026-01-02T10:30:00.5", "text", False),
        ("", "datetime-local", False),
    ])
    def test_picker_only_without_fraction(self, value, kind, step):
        html = LocalDateTimeInput().render("at", value)
        assert f'type="{kind}"' in html
        assert ('step="1"' in html) is step
        if isinstance(value, datetime) and value.microsecond:
            assert 'value="2026-01-02T10:30:05.123456"' in html


class TestLocalize:
    def test_unbound_form_shows_the_viewer_zone(self, garage):
        form = TemporalActionForm(user=garage.owner, initial={"at": datetime(2026, 7, 1, 10, 0)})  # naive UTC wall time
        localize(form, MADRID)
        assert form.initial["time_zone"] == "Europe/Madrid" and form.initial["at"] == datetime(2026, 7, 1, 12, 0)
        assert 'type="datetime-local"' in render(form, "at") and 'value="2026-07-01T12:00"' in render(form, "at")

    def test_instance_values_round_trip(self, garage):
        kind = save_maintenance(garage.owner, ServiceType, name="Engrase")
        anchor = datetime(2026, 3, 29, 0, 30, tzinfo=UTC)  # 01:30 in Madrid, before the DST jump
        rule = save_maintenance(garage.owner, MaintenanceRule, item=garage.light, service_type=kind, calendar_days=30, anchor_at=anchor)
        shown = localize(MaintenanceRuleForm(user=garage.owner, instance=rule), MADRID)
        assert value_of(render(shown, "anchor_at"), "anchor_at") == "2026-03-29T01:30"
        posted = MaintenanceRuleForm({"item": garage.light.pk, "service_type": kind.pk, "calendar_days": "30",
                                      "anchor_at": "2026-03-29T01:30", "time_zone": "Europe/Madrid"}, user=garage.owner, instance=rule)
        assert posted.is_valid(), posted.errors
        assert posted.save().anchor_at == anchor

    @pytest.mark.parametrize("instant", [datetime(2026, 10, 25, 0, 30, tzinfo=UTC), datetime(2026, 10, 25, 1, 30, tzinfo=UTC)])
    def test_repeated_hour_keeps_utc(self, garage, instant):
        kind = save_maintenance(garage.owner, ServiceType, name="Engrase")
        event = save_maintenance(garage.owner, ServiceEvent, bike=garage.road, service_type=kind, performed_at=instant)
        form = localize(ServiceEventForm(user=garage.owner, instance=event), MADRID)
        assert form["time_zone"].value() == "UTC" and value_of(render(form, "performed_at"), "performed_at") == instant.strftime("%Y-%m-%dT%H:%M")
        posted = ServiceEventForm({"bike": garage.road.pk, "service_type": kind.pk, "performed_at": instant.strftime("%Y-%m-%dT%H:%M"),
                                   "time_zone": form["time_zone"].value()}, user=garage.owner, instance=event)
        assert posted.is_valid(), posted.errors
        assert posted.save().performed_at == instant

    def test_bound_and_explicit_zones_are_untouched(self, garage):
        bound = localize(TemporalActionForm({"time_zone": "UTC", "at": "2026-01-01T10:00"}, user=garage.owner), MADRID)
        assert bound.is_valid() and bound.cleaned_data["at"] == datetime(2026, 1, 1, 10, tzinfo=UTC)
        cut = datetime(2026, 1, 1, 15, tzinfo=UTC)
        reading = record_baseline(garage.owner, item=garage.light, metric="ride_count", scope="lifetime", cut_at=cut, value=Decimal(0), source="manual")
        form = localize(UsageBaselineForm(user=garage.owner, instance=reading, time_zone="America/Argentina/Buenos_Aires"), MADRID)
        assert form.initial["time_zone"] == "America/Argentina/Buenos_Aires" and form.initial["cut_at"] == datetime(2026, 1, 1, 12)

    def test_pages_preselect_the_cookie_zone(self, garage, client, frozen):
        client.force_login(garage.owner)
        client.cookies["garage_tz"] = "America/Argentina/Buenos_Aires"
        html = client.get(reverse("garage:installation-create", args=[garage.light.pk])).content.decode()
        assert value_of(html, "time_zone") == "America/Argentina/Buenos_Aires" and 'type="datetime-local"' in html
        assert "<details class=\"zone\">" in html
        assert zone_summary(html) == "Horas en America/Argentina/Buenos_Aires · Cambiar"  # garage-047 F01
        del client.cookies["garage_tz"]
        html = client.get(reverse("garage:item-retire", args=[garage.light.pk])).content.decode()
        assert value_of(html, "time_zone") == "Europe/Madrid"

    def test_zone_error_opens_the_fold_and_messages_are_spanish(self, garage, client):
        client.force_login(garage.owner)
        response = client.post(reverse("garage:item-retire", args=[garage.light.pk]), {"time_zone": "Mars/Base", "at": "2026-03-29T02:30"})
        html = response.content.decode()
        assert response.status_code == 200 and '<details class="zone" open>' in html and "Elige una zona horaria IANA válida." in html
        response = client.post(reverse("garage:item-retire", args=[garage.light.pk]), {"time_zone": "Europe/Madrid", "at": "2026-03-29T02:30"})
        assert "Esa hora local no existe (cambio de hora): elige otra." in response.content.decode()


class TestRuleUnits:
    @pytest.fixture
    def kind(self, garage):
        return save_maintenance(garage.owner, ServiceType, name="Cambio")

    def post(self, garage, kind, **data):
        return MaintenanceRuleForm({"item": garage.light.pk, "service_type": kind.pk, "time_zone": "UTC", **data}, user=garage.owner)

    def test_km_and_hours_are_stored_exactly(self, garage, kind):
        form = self.post(garage, kind, distance_km="2700.000001", moving_time_h="1.5")
        assert form.is_valid(), form.errors
        rule = form.save()
        rule.refresh_from_db()
        assert (rule.distance_m, rule.moving_time_s) == (Decimal("2700000.001"), Decimal("5400"))
        shown = MaintenanceRuleForm(user=garage.owner, instance=rule)
        assert (shown.initial["distance_km"], shown.initial["moving_time_h"]) == (Decimal("2700.000001"), Decimal("1.5"))
        assert str(shown.initial["distance_km"]) == "2700.000001" and "E" not in str(shown.initial["moving_time_h"])

    @pytest.mark.parametrize("data,field,message", [
        ({"distance_km": "1.0000001"}, "distance_km", "Como máximo 6 decimales."),
        ({"moving_time_h": "0.000001"}, "moving_time_h", "Ese tiempo no se puede guardar exacto"),
        ({"distance_km": "0"}, "distance_km", "Debe ser mayor que cero"),
        ({"distance_km": "-1"}, "distance_km", "Debe ser mayor que cero."),
        ({"distance_km": "abc"}, "distance_km", "Introduce un número."),
        ({"distance_km": "1" * 19}, "distance_km", "Valor fuera del intervalo admitido."),
    ])
    def test_never_rounds_silently(self, garage, kind, data, field, message):
        form = self.post(garage, kind, **data)
        assert not form.is_valid() and message in " ".join(form.errors[field])

    def test_model_errors_land_on_the_shown_field(self, garage, kind, client):
        client.force_login(garage.owner)
        url = reverse("garage:maintenance-rule-create")
        response = client.post(url, {"item": garage.light.pk, "service_type": kind.pk, "time_zone": "UTC"})
        html = response.content.decode()
        assert response.status_code == 200 and "Indica al menos un umbral: distancia, tiempo, salidas, días o desnivel." in html
        response = client.post(url, {"item": garage.light.pk, "bike": garage.road.pk, "service_type": kind.pk, "distance_km": "0,5", "time_zone": "UTC"})
        assert response.status_code == 200 and "Elige un objeto o una bici, no ambos." in response.content.decode()
        assert not MaintenanceRule.objects.filter(service_type=kind).exists()

    def test_decimal_comma(self, garage, kind, client):
        client.force_login(garage.owner)
        html = client.get(reverse("garage:maintenance-rule-create")).content.decode()
        assert re.search(r'<input type="text" name="distance_km"[^>]*inputmode="decimal"', html) and 'type="number" name="distance_km"' not in html
        response = client.post(reverse("garage:maintenance-rule-create"), {"item": garage.light.pk, "service_type": kind.pk,
                                                                          "distance_km": "2.700,5", "moving_time_h": "1,25", "time_zone": "UTC"})
        assert response.status_code == 302
        rule = MaintenanceRule.objects.get(service_type=kind)
        assert (rule.distance_m, rule.moving_time_s) == (Decimal("2700500"), Decimal("4500"))

    @pytest.mark.parametrize("text,expected", [("3,5", Decimal("3500")), ("0.500", Decimal("500")), ("-0,5", None), ("2.700,5", Decimal("2700500")), ("2700.5", Decimal("2700500")),
                                               (" 1\u00a0234,5 ", Decimal("1234500")), ("0.5", Decimal("500")), ("1e3", Decimal("1000000"))])
    def test_decimal_formats(self, garage, kind, text, expected):
        form = self.post(garage, kind, distance_km=text)
        if expected is None:
            assert form.errors["distance_km"][0] == "Debe ser mayor que cero."
            return
        assert form.is_valid(), form.errors
        assert form.cleaned_data["distance_m"] == expected

    @pytest.mark.parametrize("text,message", [("3.000", "¿Miles o decimales?"), ("1.234.567", "¿Miles o decimales?"),
                                              ("1,234.5", "Introduce un número."), ("1.5,3", "Introduce un número."), ("1,2,3", "Introduce un número."),
                                              ("0.500,5", "Introduce un número.")])
    def test_ambiguous_or_mixed_separators_are_rejected(self, garage, kind, text, message):
        form = self.post(garage, kind, distance_km=text)
        assert not form.is_valid() and message in " ".join(form.errors["distance_km"])

    def test_exact_field_errors_and_remap(self, garage, kind, client):
        client.force_login(garage.owner)
        response = client.post(reverse("garage:maintenance-rule-create"), {"item": garage.light.pk, "service_type": kind.pk,
                                                                          "moving_time_s": "0", "time_zone": "UTC"})
        assert response.status_code == 200 and "Debe ser mayor que cero." in response.content.decode()
        form = self.post(garage, kind, distance_km="1")
        form.is_valid()
        form.add_error("distance_m", "x")
        assert form.errors["distance_km"] == ["x"]

    def test_duplicates_in_spanish(self, garage, kind, client):
        save_maintenance(garage.owner, MaintenanceRule, item=garage.light, service_type=kind, calendar_days=10)
        client.force_login(garage.owner)
        html = client.post(reverse("garage:maintenance-rule-create"), {"item": garage.light.pk, "service_type": kind.pk, "calendar_days": "5",
                                                                       "time_zone": "UTC"}).content.decode()
        assert "Ya hay una regla de ese tipo para este objeto" in html and "Constraint" not in html
        html = client.post(reverse("garage:service-type-create"), {"name": "cambio"}).content.decode()
        assert "Ya tienes un tipo con ese nombre." in html and "Constraint" not in html
        html = client.post(reverse("garage:maintenance-rule-create"), {"service_type": kind.pk, "time_zone": "UTC"}).content.decode()
        assert "This field is required" not in html

    def test_delete_from_edit_and_foreign_404(self, garage, kind, client):
        rule = save_maintenance(garage.owner, MaintenanceRule, item=garage.light, service_type=kind, calendar_days=10)
        client.force_login(garage.owner)
        edit = client.get(reverse("garage:maintenance-rule-edit", args=[rule.pk])).content.decode()
        assert "Se eliminará «Cambio · Luz»." in edit
        assert client.post(reverse("garage:maintenance-rule-delete", args=[rule.pk])).status_code == 302
        assert not MaintenanceRule.objects.filter(pk=rule.pk).exists()
        foreign = MaintenanceRule.objects.get(owner=garage.other)
        assert client.post(reverse("garage:maintenance-rule-delete", args=[foreign.pk])).status_code == 404
        assert client.get(reverse("garage:maintenance-rule-edit", args=[foreign.pk])).status_code == 404
        assert MaintenanceRule.objects.filter(pk=foreign.pk).exists()

    def test_clearing_a_threshold_keeps_the_others(self, garage, kind):
        rule = save_maintenance(garage.owner, MaintenanceRule, item=garage.light, service_type=kind, distance_m=Decimal(3000000), calendar_days=365)
        form = MaintenanceRuleForm({"item": garage.light.pk, "service_type": kind.pk, "distance_km": "", "calendar_days": "365", "time_zone": "UTC"},
                                   user=garage.owner, instance=rule)
        assert form.is_valid(), form.errors
        form.save()
        rule.refresh_from_db()
        assert (rule.distance_m, rule.calendar_days) == (None, 365)

    def test_web_form_shows_km_and_keeps_inexact_seconds(self, garage, kind):
        rule = save_maintenance(garage.owner, MaintenanceRule, item=garage.light, service_type=kind, distance_m=Decimal("123.456"),
                                moving_time_s=Decimal("1.001"))
        shown = MaintenanceRuleForm(user=garage.owner, instance=rule)
        assert "distance_m" not in shown.fields and shown.initial["distance_km"] == Decimal("0.123456")
        assert shown.fields["moving_time_s"].label == "Tiempo en movimiento (segundos)" and "moving_time_h" not in shown.fields
        posted = MaintenanceRuleForm({"item": garage.light.pk, "service_type": kind.pk, "distance_km": "0.123456", "moving_time_s": "1.001",
                                      "time_zone": "UTC"}, user=garage.owner, instance=rule)
        assert posted.is_valid(), posted.errors
        posted.save()
        rule.refresh_from_db()
        assert (rule.distance_m, rule.moving_time_s) == (Decimal("123.456"), Decimal("1.001"))
        from .maintenance_forms import MaintenanceRuleForm as AdminForm
        assert "distance_m" in AdminForm(user=garage.owner, instance=rule).fields  # the admin keeps exact units

    def test_thresholds_text(self, garage, kind):
        rule = MaintenanceRule(distance_m=Decimal(3000000), moving_time_s=Decimal(360000), ride_count=1, calendar_days=365)
        assert thresholds(rule) == "3.000 km · 100 h · 1 salida · 365 días"
        assert thresholds(MaintenanceRule(distance_m=Decimal(50), calendar_days=1)) == "0,05 km · 1 día"
        assert thresholds(MaintenanceRule(distance_m=Decimal("2700500"), moving_time_s=Decimal(1))) == "2.700,5 km · 1 s"
        assert thresholds(MaintenanceRule(moving_time_s=Decimal(5400))) == "1,5 h"


class TestEventForm:
    def test_defaults_and_prefill(self, garage, client, frozen):
        kind = save_maintenance(garage.owner, ServiceType, name="Lavado")
        save_maintenance(garage.owner, ServiceEvent, bike=garage.road, service_type=kind, performed_at=at(30), amount=Decimal(5), currency="USD")
        client.force_login(garage.owner)
        html = client.get(reverse("garage:service-event-create") + f"?bike={garage.road.pk}").content.decode()
        assert re.search(rf'<option value="{garage.road.pk}" selected>', html)
        assert value_of(html, "currency") == "USD" and value_of(html, "time_zone") == "Europe/Madrid"
        assert value_of(html, "performed_at") == "2026-10-17T12:07"
        assert f'href="{reverse("garage:bike-detail", args=[garage.road.pk])}"' in html
        foreign = create_inventory(garage.other, Item, name="X", category=create_inventory(garage.other, __import__("garage.models", fromlist=["Category"]).Category, name="Y"))
        assert client.get(reverse("garage:service-event-create") + f"?item={foreign.pk}").status_code == 404
        assert client.get(reverse("garage:maintenance-rule-create") + "?bike=nope").status_code == 404
        assert client.get(reverse("garage:maintenance-rule-create") + f"?bike={garage.gravel.pk}").status_code == 200

    def test_amount_with_comma(self, garage):
        kind = save_maintenance(garage.owner, ServiceType, name="Lavado")
        form = ServiceEventForm({"bike": garage.road.pk, "service_type": kind.pk, "performed_at": "2026-10-01T10:00", "time_zone": "UTC",
                                 "amount": "32,9", "currency": "EUR"}, user=garage.owner)
        assert form.is_valid(), form.errors
        assert form.save().amount == Decimal("32.90")
        bad = ServiceEventForm({"bike": garage.road.pk, "service_type": kind.pk, "performed_at": "2026-10-01T10:00", "time_zone": "UTC",
                                "amount": "1,234", "currency": "EUR"}, user=garage.owner)
        assert not bad.is_valid() and bad.errors["amount"] == ["Como máximo 2 decimales."]

    def test_untouched_currency_needs_no_amount(self, garage, client, frozen):
        kind = save_maintenance(garage.owner, ServiceType, name="Lavado")
        save_maintenance(garage.owner, ServiceEvent, bike=garage.gravel, service_type=kind, performed_at=at(9), amount=Decimal(5), currency="EUR")
        client.force_login(garage.owner)
        page = client.get(reverse("garage:service-event-create")).content.decode()
        assert value_of(page, "initial-currency") == "EUR" and value_of(page, "currency") == "EUR"
        data = {"bike": garage.road.pk, "service_type": kind.pk, "performed_at": "2026-10-01T10:00", "time_zone": "Europe/Madrid",
                "currency": "EUR", "initial-currency": "EUR", "amount": ""}
        response = client.post(reverse("garage:service-event-create"), data)
        assert response.status_code == 302
        event = ServiceEvent.objects.get(bike=garage.road)
        assert (event.amount, event.currency, event.performed_at) == (None, None, datetime(2026, 10, 1, 8, tzinfo=UTC))
        typed = client.post(reverse("garage:service-event-create"), {**data, "initial-currency": ""})
        assert typed.status_code == 200 and "Indica importe y moneda, o ninguno de los dos." in typed.content.decode()

    def test_admin_forms_keep_their_messages(self, garage):
        from .maintenance_forms import MaintenanceRuleForm as AdminRuleForm, ServiceEventForm as AdminEventForm
        assert AdminRuleForm({}, user=garage.owner).errors["service_type"] == ["This field is required."]
        assert AdminEventForm({"amount": "abc"}, user=garage.owner).errors["amount"] == ["Enter a number."]

    def test_invalid_currency_once_in_spanish(self, garage):
        kind = save_maintenance(garage.owner, ServiceType, name="Lavado")
        form = ServiceEventForm({"bike": garage.road.pk, "service_type": kind.pk, "performed_at": "2026-10-01T10:00", "time_zone": "UTC",
                                 "amount": "1", "currency": "EURO"}, user=garage.owner)
        assert not form.is_valid() and list(form.errors["currency"]).count("Como máximo 3 caracteres.") == 1
        form = ServiceEventForm({"bike": garage.road.pk, "service_type": kind.pk, "performed_at": "2026-10-01T10:00", "time_zone": "UTC",
                                 "amount": "1", "currency": "XYZ"}, user=garage.owner)
        assert not form.is_valid() and form.errors["currency"][0] == "Usa un código de moneda ISO 4217, por ejemplo EUR."

    def test_amount_and_currency_checks(self, garage):
        kind = save_maintenance(garage.owner, ServiceType, name="Lavado")
        base = {"bike": garage.road.pk, "service_type": kind.pk, "performed_at": "2026-10-01T10:00", "time_zone": "UTC"}
        negative = ServiceEventForm({**base, "amount": "-1", "currency": "EUR"}, user=garage.owner)
        assert not negative.is_valid() and negative.errors["amount"] == ["El importe no puede ser negativo."]
        lower = ServiceEventForm({**base, "amount": "1,5", "currency": "eur"}, user=garage.owner)
        assert lower.is_valid(), lower.errors
        assert lower.save().currency == "EUR"

    def test_detail_and_delete_from_edit(self, garage, client):
        kind = save_maintenance(garage.owner, ServiceType, name="Cadena nueva")
        event = save_maintenance(garage.owner, ServiceEvent, item=garage.chain, service_type=kind, performed_at=datetime(2026, 3, 3, 7, tzinfo=UTC),
                                 amount=Decimal("32.9"), currency="EUR", notes="Compra y montaje")
        record_baseline(garage.owner, item=garage.chain, metric="distance_m", scope="service", service_event=event,
                        cut_at=datetime(2026, 3, 4, tzinfo=UTC), value=Decimal("12345.678"), source="manual")
        client.force_login(garage.owner)
        html = client.get(reverse("garage:service-event-detail", args=[event.pk])).content.decode()
        for text in ("Cadena nueva", "Cadena 11v", "mar 3 mar 2026, 8:00", "32,90", "EUR", "Compra y montaje", "12,3 km", "Lecturas desde aquí",
                     f'href="{reverse("garage:item-detail", args=[garage.chain.pk])}"', "Fotos privadas"):
            assert text in html, text
        assert "Eliminar intervención" not in html
        assert client.get(reverse("garage:service-event-detail", args=[ServiceEvent.objects.create(owner=garage.other, bike=Bike.objects.get(name="SECRET bike"),
                          service_type=ServiceType.objects.get(owner=garage.other), performed_at=at(1)).pk])).status_code == 404
        edit = client.get(reverse("garage:service-event-edit", args=[event.pk])).content.decode()
        assert f'action="{reverse("garage:service-event-delete", args=[event.pk])}"' in edit and "Eliminar intervención" in edit
        assert value_of(edit, "performed_at") == "2026-03-03T08:00"
        response = client.post(reverse("garage:service-event-delete", args=[event.pk]))
        assert response.status_code == 409 and "elimínalas antes" in response.content.decode()
        assert ServiceEvent.objects.filter(pk=event.pk).exists()


class TestWorkshop:
    def test_snapshot_groups(self, garage):
        kind = save_maintenance(garage.owner, ServiceType, name="Lavado")
        save_maintenance(garage.owner, MaintenanceRule, bike=garage.gravel, service_type=kind, calendar_days=365, anchor_at=at(10))
        retired = create_inventory(garage.owner, Item, name="Retirado", category=garage.helmet.category, retired_at=at(1))
        save_maintenance(garage.owner, MaintenanceRule, item=retired, service_type=kind, calendar_days=1, anchor_at=at(30))
        shop = workshop_snapshot(garage.owner, at=NOW)
        assert [(a.target.name, a.wear.state, a.place) for a in shop.attention] == [("Calas", "due", "en Zapatillas"), ("Cadena 11v", "review", "Carretera")]
        assert [a.target.name for a in shop.nodata] == ["Casco"]
        assert [(a.target.name, a.place) for a in shop.calm] == [("Gravel", "bici")]
        assert "Retirado" in {str(rule.item) for rule in shop.rules} and len(shop.rules) == 5
        assert shop.events == () and shop.events_total == 0 and [t.name for t in shop.types][:1] == ["Calas"]

    def test_page(self, garage, client):
        client.force_login(garage.owner)
        with CaptureQueriesContext(connection) as queries:
            response = client.get(reverse("garage:maintenance"))
        html = response.content.decode()
        assert response.status_code == 200 and not writes(queries)
        assert len(queries) <= 24, len(queries)
        assert "<script>" not in html and ' style="' not in html and "SECRET" not in html
        for text in ("<h1>Taller</h1>", "Requiere atención", "Sin datos", "Últimas intervenciones", "Reglas", "Tipos de intervención",
                     "420 km", "365 días", "Falta una intervención o la fecha desde la que contar.", "90 %",
                     "Detalles técnicos de los avisos", 'class="fab only-android"', 'aria-current="page"'):
            assert text in html, text
        assert 'href="/garage/maintenance/" aria-current="page"' in html or re.search(r'href="/garage/maintenance/"[^>]*aria-current="page"', html)

    def test_the_links_of_a_technical_alert_take_a_finger(self, garage, client):
        # «Editar regla» and «Posponer el aviso» measured 19 px, 2 px under the block before them. As plain links right in an `.actions` row
        # they get the 44 px of `.page .actions > a:not([class])`; as a block of the card, its 12 px.
        client.force_login(garage.owner)
        sections = find_all(parse(client.get(reverse("garage:maintenance")).content.decode()), "section", aria_labelledby="maintenance-alerts-title")
        assert len(sections) == 1
        cards = find_all(sections[0], "article", cls="card")
        assert cards
        for card in cards:
            rows = [child for child in card.children if not isinstance(child, str) and "actions" in child.attrs.get("class", "").split()]
            assert len(rows) == 1
            links = [child for child in rows[0].children if not isinstance(child, str)]
            assert [(link.tag, "class" in link.attrs) for link in links] == [("a", False), ("a", False)]
            assert visible_text(links[0]) == "Editar regla" and visible_text(links[1]) in ("Posponer el aviso", "Ver el aplazamiento")

    def test_events_capped_and_query_count_constant(self, garage, client):
        kind = save_maintenance(garage.owner, ServiceType, name="Lavado")
        client.force_login(garage.owner)
        client.get(reverse("garage:maintenance"))
        with CaptureQueriesContext(connection) as before:
            client.get(reverse("garage:maintenance"))
        for day in range(EVENT_LIMIT + 3):
            save_maintenance(garage.owner, ServiceEvent, bike=garage.road, service_type=kind, performed_at=at(day + 1))
            other = save_maintenance(garage.owner, ServiceType, name=f"Tipo {day}")
            save_maintenance(garage.owner, MaintenanceRule, item=garage.light, service_type=other, calendar_days=10, anchor_at=at(5))
        with CaptureQueriesContext(connection) as after:
            html = client.get(reverse("garage:maintenance")).content.decode()
        assert len(after) == len(before), (len(before), len(after))
        assert html.count('href="/garage/maintenance/events/') == EVENT_LIMIT and f"Ver todas ({EVENT_LIMIT + 3})" in html
        full = client.get(reverse("garage:maintenance") + "?all=1").content.decode()
        assert full.count('href="/garage/maintenance/events/') == EVENT_LIMIT + 3 and "Ver todas" not in full

    def test_empty_owner_and_login(self, db, client):
        from django.contrib.auth import get_user_model
        assert client.get(reverse("garage:maintenance")).status_code == 302
        owner = get_user_model().objects.create_user("empty-shop", password="test-only-password")
        client.force_login(owner)
        html = client.get(reverse("garage:maintenance")).content.decode()
        assert "Aún no hay reglas de mantenimiento" in html and "Sin intervenciones registradas." in html
        create = client.get(reverse("garage:service-event-create")).content.decode()
        assert "Primero crea un tipo de intervención" in create

    def test_csrf_and_methods(self, garage, client):
        client.force_login(garage.owner)
        assert client.post(reverse("garage:maintenance")).status_code == 405
        secured = Client(enforce_csrf_checks=True)
        secured.force_login(garage.owner)
        kind = save_maintenance(garage.owner, ServiceType, name="Nada")
        assert secured.post(reverse("garage:service-type-delete", args=[kind.pk])).status_code == 403
        assert ServiceType.objects.filter(pk=kind.pk).exists()


def workshop_page(client, owner):
    client.force_login(owner)
    response = client.get(reverse("garage:maintenance"))
    assert response.status_code == 200
    return response.content.decode()


def uses(node):
    return [use.attrs["href"] for use in find_all(node, "use")]


def classes(node):
    return node.attrs.get("class", "").split()


def rule_of(garage, item):
    return MaintenanceRule.objects.get(owner=garage.owner, item=item)


class TestGroupsInCards:
    """Spec F3d, D10: the groups of Taller, in the order they had, each in a card of its own."""

    GROUPS = ["Requiere atención", "Pospuestos", "Sin datos", "En curso y al día"]
    TITLES = [*GROUPS, "Últimas intervenciones", "Reglas", "Tipos de intervención"]

    def sections(self, html):
        """Those of the screen: the technical details, folded at its end, are another phase's (F4c)."""
        return [section for section in find_all(parse(html), "section", aria_labelledby=True) if section.attrs["aria-labelledby"] != "maintenance-alerts-title"]

    def titles(self, html):
        return [visible_text(find_all(section, "h2")[0]) for section in self.sections(html)]

    def one_in_each_group(self, garage):
        kind = save_maintenance(garage.owner, ServiceType, name="Lavado")
        save_maintenance(garage.owner, MaintenanceRule, bike=garage.gravel, service_type=kind, calendar_days=365, anchor_at=days_ago(10))
        snooze_rule(garage.owner, rule_of(garage, garage.cleats), calendar_days=3)

    def test_the_groups_keep_their_order(self, garage, client):
        self.one_in_each_group(garage)
        assert self.titles(workshop_page(client, garage.owner)) == self.TITLES

    def test_each_group_is_a_card(self, garage, client):
        self.one_in_each_group(garage)
        for section in self.sections(workshop_page(client, garage.owner)):
            assert "card" in classes(section), classes(section)

    def test_each_rule_stays_in_its_group(self, garage, client):
        self.one_in_each_group(garage)
        sections = dict(zip(self.TITLES, self.sections(workshop_page(client, garage.owner))))
        names = {title: [visible_text(find_all(row, cls="entry-name")[0]) for row in find_all(sections[title], "a", cls="entry")] for title in self.GROUPS}
        assert names == {"Requiere atención": ["Cadena 11v"], "Pospuestos": ["Calas · Calas"], "Sin datos": ["Casco · Revisión"], "En curso y al día": ["Gravel"]}

    def test_a_group_with_nothing_has_no_card(self, garage, client):
        assert self.titles(workshop_page(client, garage.owner)) == ["Requiere atención", "Sin datos", "Últimas intervenciones", "Reglas", "Tipos de intervención"]

    def test_with_nothing_at_all_the_messages_stay_in_their_cards(self, db, client):
        from django.contrib.auth import get_user_model
        html = workshop_page(client, get_user_model().objects.create_user("empty-cards", password="test-only-password"))
        sections = self.sections(html)
        assert self.titles(html) == ["Requiere atención", "Últimas intervenciones", "Reglas", "Tipos de intervención"]
        for section in sections:
            assert "card" in classes(section) and len(find_all(section, "li", cls="empty")) == 1

    def test_the_rest_of_the_calm_rules_fold_inside_their_card(self, garage, client):
        kind = save_maintenance(garage.owner, ServiceType, name="Lavado")
        for number in range(8):
            piece = create_inventory(garage.owner, Item, name=f"Pieza {number}", category=garage.helmet.category)
            save_maintenance(garage.owner, MaintenanceRule, item=piece, service_type=kind, calendar_days=365, anchor_at=days_ago(10))
        section = find_all(parse(workshop_page(client, garage.owner)), "section", aria_labelledby="calm-title")[0]
        fold = find_all(section, "details", cls="more")
        assert "card" in classes(section) and len(fold) == 1 and visible_text(find_all(fold[0], "summary")[0]) == "Ver 2 más"
        assert len(find_all(fold[0], "a", cls="entry")) == 2 and len(find_all(section, "a", cls="entry")) == 8

    def test_the_date_of_an_intervention_stays_whole(self, garage, client):
        """A card takes 32 px off the row: at 390 px «27 sep 2025», after the name of the piece, left the year alone on a line."""
        kind = save_maintenance(garage.owner, ServiceType, name="Lavado")
        event = save_maintenance(garage.owner, ServiceEvent, item=garage.chain, service_type=kind, performed_at=at(30))
        row = row_by_href(workshop_page(client, garage.owner), reverse("garage:service-event-detail", args=[event.pk]))
        sub = find_all(row, cls="entry-sub")[0]
        assert visible_text(sub) == "Cadena 11v · 16 sep 2026"
        assert [visible_text(span) for span in find_all(sub, "span", cls="nowrap")] == ["16 sep 2026"]


class TestPostponedAndNoDataRows:
    """Spec F3d, §4.1, §7.1.5: the ring with the icon of the piece, and a chip, for what their old tile was the only icon of the state."""

    @pytest.fixture
    def bottle(self, garage):
        """The pieces of the fixture wear an icon of their own, neither the clock nor the question mark nor what a name would suggest."""
        Category.objects.filter(owner=garage.owner).update(icon="bottle")

    def postponed(self, garage, client, item=None, **amounts):
        rule = rule_of(garage, item or garage.cleats)
        snooze_rule(garage.owner, rule, **(amounts or {"calendar_days": 3}))
        return row_by_href(workshop_page(client, garage.owner), reverse("garage:maintenance-rule-snooze", args=[rule.pk]))

    def row_without_data(self, garage, client, href):
        """In its group: «Reglas» links to the same editor."""
        section = find_all(parse(workshop_page(client, garage.owner)), "section", aria_labelledby="nodata-title")[0]
        rows = find_all(section, "a", cls="entry", href=href)
        assert len(rows) == 1, rows
        return rows[0]

    def without_data(self, garage, client):
        return self.row_without_data(garage, client, reverse("garage:maintenance-rule-edit", args=[rule_of(garage, garage.helmet).pk]))

    def assert_ring_of_the_bottle(self, row):
        rings = find_all(row, "svg", cls="ring", aria_hidden="true")
        assert len(rings) == 1 and uses(rings[0]) == ["#i-bottle"]
        assert len(find_all(rings[0], "use", cls="ring-glyph")) == 1
        assert not find_all(row, cls="glyph")

    def test_a_postponed_row_has_the_ring_with_its_piece(self, garage, client, bottle):
        self.assert_ring_of_the_bottle(self.postponed(garage, client))

    def test_a_row_without_data_has_the_ring_with_its_piece(self, garage, client, bottle):
        self.assert_ring_of_the_bottle(self.without_data(garage, client))

    @pytest.mark.parametrize("build,state,icon,word,rest", [("postponed", "snoozed", "#i-clock", "Pospuesto", r" · \d+ %"), ("without_data", "nodata", "#i-help", "Sin datos", "")])
    def test_the_chip_says_the_state_without_color(self, garage, client, build, state, icon, word, rest):
        row = getattr(self, build)(garage, client)
        chips = find_all(row, "span", cls="chip")
        assert len(chips) == 1 and uses(chips[0]) == [icon]
        assert re.fullmatch(word + rest, visible_text(chips[0])), visible_text(chips[0])
        assert classes(chips[0]) == ["chip", f"st-{state}"] and f"st-{state}" in classes(row)
        assert find_all(chips[0], "svg", cls="ic xs", aria_hidden="true")
        assert word in accessible_text(row)

    def test_every_ring_of_the_screen_goes_with_its_chip(self, garage, client):
        snooze_rule(garage.owner, rule_of(garage, garage.cleats), calendar_days=3)
        rows = [row for row in find_all(parse(workshop_page(client, garage.owner)), "a", cls="entry") if find_all(row, "svg", cls="ring")]
        assert len(rows) == 3  # review, postponed and without data
        for row in rows:
            chip = find_all(row, "span", cls="chip")
            assert len(chip) == 1 and len(uses(chip[0])) == 1 and visible_text(chip[0]), visible_text(row)

    def test_the_lines_of_text_do_not_change(self, garage, client):
        postponed = self.postponed(garage, client)
        assert visible_text(find_all(postponed, cls="entry-name")[0]) == "Calas · Calas"
        assert visible_text(find_all(postponed, cls="entry-sub")[0]) == "Vencido · quedan 3 días de aplazamiento"
        row = self.without_data(garage, client)
        assert visible_text(find_all(row, cls="entry-name")[0]) == "Casco · Revisión"
        assert visible_text(find_all(row, cls="entry-sub")[0]) == "Falta una intervención o la fecha desde la que contar."

    @pytest.mark.parametrize("build", ["postponed", "without_data"])
    def test_they_go_on_being_rows_that_navigate(self, garage, client, build):
        assert uses(getattr(self, build)(garage, client))[-1] == "#i-chev-right"

    def test_a_row_without_data_paints_no_arc(self, garage, client):
        row = self.without_data(garage, client)
        assert find_all(row, "circle", cls="arc") == [] and len(find_all(row, "circle", cls="trk")) == 1

    def test_a_rule_without_metrics_does_not_break_the_row(self, garage, client, monkeypatch):
        """No rule of the base has none today: `wear` already provides for it, and the row must not depend on a headline."""
        rule = rule_of(garage, garage.helmet)
        real = workshop_module.maintenance_due
        monkeypatch.setattr(workshop_module, "maintenance_due", lambda owner, at: tuple(replace(due, metrics=()) if due.rule.pk == rule.pk else due for due in real(owner, at=at)))
        row = self.without_data(garage, client)
        assert find_all(row, "circle", cls="arc") == [] and len(find_all(row, "circle", cls="trk")) == 1
        assert "st-nodata" in classes(row) and visible_text(find_all(row, "span", cls="chip st-nodata")[0]) == "Sin datos"

    def overdue_snoozed(self, garage, frozen):
        """Ten days of a rule, eleven gone by: 110 %, whatever the ring can paint."""
        kind = save_maintenance(garage.owner, ServiceType, name="Engrase")
        rule = save_maintenance(garage.owner, MaintenanceRule, item=garage.light, service_type=kind, calendar_days=10, anchor_at=frozen - timedelta(days=11))
        snooze_rule(garage.owner, rule, calendar_days=3)
        return rule

    def snooze_row(self, garage, client, rule):
        return row_by_href(workshop_page(client, garage.owner), reverse("garage:maintenance-rule-snooze", args=[rule.pk]))

    def test_a_postponed_chip_says_the_proportion_the_ring_only_draws(self, garage, client, frozen):
        """Spec §4.1: the ring is decorative, «el porcentaje pasa a leerse en el chip»; the ring of a rule at 110 % is simply full."""
        row = self.snooze_row(garage, client, self.overdue_snoozed(garage, frozen))
        assert visible_text(find_all(row, "span", cls="chip")[0]) == "Pospuesto · 110 %"
        assert "Pospuesto · 110 %" in accessible_text(row)

    def test_a_postponed_chip_says_when_its_figure_is_a_minimum(self, garage, client, frozen, monkeypatch):
        """Spec §4.1, row «≥»: the same figure as the rest of the app, not a bare number that promises more than is known."""
        rule = self.overdue_snoozed(garage, frozen)
        real = workshop_module.maintenance_due
        monkeypatch.setattr(workshop_module, "maintenance_due", lambda owner, at: tuple(replace(due, metrics=tuple(replace(metric, coverage="partial") for metric in due.metrics)) if due.rule.pk == rule.pk else due for due in real(owner, at=at)))
        assert visible_text(find_all(self.snooze_row(garage, client, rule), "span", cls="chip")[0]) == "Pospuesto · ≥ 110 %"

    def test_a_postponed_ring_shows_the_real_proportion(self, garage, client, frozen):
        kind = save_maintenance(garage.owner, ServiceType, name="Engrase")
        rule = save_maintenance(garage.owner, MaintenanceRule, item=garage.light, service_type=kind, calendar_days=10, anchor_at=frozen - timedelta(days=9, hours=12))
        snooze_rule(garage.owner, rule, calendar_days=3)
        row = row_by_href(workshop_page(client, garage.owner), reverse("garage:maintenance-rule-snooze", args=[rule.pk]))
        assert [arc.attrs["stroke-dasharray"] for arc in find_all(row, "circle", cls="arc")] == [ring(Decimal("0.95"), 22)]

    def test_a_postponed_row_never_carries_the_excess(self, garage, client):
        """However far past its threshold: «Pospuesto» is grey, and its ring only shows that it is full."""
        kind = save_maintenance(garage.owner, ServiceType, name="Engrase")
        rule = save_maintenance(garage.owner, MaintenanceRule, item=garage.light, service_type=kind, calendar_days=10, anchor_at=days_ago(30))
        snooze_rule(garage.owner, rule, calendar_days=3)
        row = row_by_href(workshop_page(client, garage.owner), reverse("garage:maintenance-rule-snooze", args=[rule.pk]))
        assert classes(row) == ["entry", "compact", "st-snoozed"]
        assert classes(find_all(row, "span", cls="chip")[0]) == ["chip", "st-snoozed"]
        assert [arc.attrs["stroke-dasharray"] for arc in find_all(row, "circle", cls="arc")] == [ring(Decimal(1), 22)]

    def test_the_rule_of_a_bike_has_the_bike_in_its_ring(self, garage, client):
        kind = save_maintenance(garage.owner, ServiceType, name="Lavado")
        rule = save_maintenance(garage.owner, MaintenanceRule, bike=garage.road, service_type=kind, calendar_days=10)
        row = self.row_without_data(garage, client, reverse("garage:maintenance-rule-edit", args=[rule.pk]))
        assert uses(find_all(row, "svg", cls="ring")[0]) == ["#i-bike"]
        MaintenanceRule.objects.filter(pk=rule.pk).update(anchor_at=days_ago(30))
        snooze_rule(garage.owner, rule, calendar_days=3)
        row = row_by_href(workshop_page(client, garage.owner), reverse("garage:maintenance-rule-snooze", args=[rule.pk]))
        assert uses(find_all(row, "svg", cls="ring")[0]) == ["#i-bike"]

    def test_a_postponed_row_goes_on_to_postpone(self, garage, client):
        rule = rule_of(garage, garage.cleats)
        row = self.postponed(garage, client)
        assert row.attrs["href"] == reverse("garage:maintenance-rule-snooze", args=[rule.pk])

    def test_a_row_without_data_goes_on_to_edit_its_rule(self, garage, client):
        assert self.without_data(garage, client).attrs["href"] == reverse("garage:maintenance-rule-edit", args=[rule_of(garage, garage.helmet).pk])

    def test_a_useful_life_without_data_goes_on_to_edit_the_life(self, garage, client):
        life = set_lifespan(garage.owner, garage.light, calendar_days=10, start=days_ago(1))
        MaintenanceRule.objects.filter(pk=life.pk).update(anchor_at=None)
        row = self.row_without_data(garage, client, reverse("garage:item-lifespan", args=[garage.light.pk]))
        assert visible_text(find_all(row, "span", cls="chip st-nodata")[0]) == "Sin datos"

    def test_the_rings_do_not_add_a_query_per_row(self, garage, client):
        """The icon of the ring reads the category of the piece: `maintenance_due` has to bring it along, and with the rows of these two groups too."""
        client.force_login(garage.owner)
        url = reverse("garage:maintenance")
        client.get(url)
        snooze_rule(garage.owner, rule_of(garage, garage.cleats), calendar_days=3)
        with CaptureQueriesContext(connection) as before:
            assert client.get(url).status_code == 200
        kind = save_maintenance(garage.owner, ServiceType, name="Engrase")
        for number in range(4):
            category = create_inventory(garage.owner, Category, name=f"Tipo {number}", icon="bottle")
            quiet = create_inventory(garage.owner, Item, name=f"Sin datos {number}", category=category)
            save_maintenance(garage.owner, MaintenanceRule, item=quiet, service_type=kind, calendar_days=10)
            late = create_inventory(garage.owner, Item, name=f"Pospuesta {number}", category=category)
            rule = save_maintenance(garage.owner, MaintenanceRule, item=late, service_type=kind, calendar_days=10, anchor_at=days_ago(30))
            snooze_rule(garage.owner, rule, calendar_days=3)
        with CaptureQueriesContext(connection) as after:
            html = client.get(url).content.decode()
        assert len(find_all(parse(html), "section", aria_labelledby="snoozed-title")) == 1 and html.count('class="entry compact st-snoozed"') == 5
        assert len(after) == len(before), (len(before), len(after))


class TestSpanishWorkshopForms:
    """garage-047 F07 and F13: the type form speaks Spanish and the currency box is empty until something was used."""

    def field(self, html, name):
        wrappers = [w for w in find_all(parse(html), "div", cls="field") if find_all(w, "input", name=name) or find_all(w, "textarea", name=name)]
        assert len(wrappers) == 1, name
        return wrappers[0]

    def test_service_type_labels_are_spanish(self, garage, client):
        client.force_login(garage.owner)
        html = client.get(reverse("garage:service-type-create")).content.decode()
        for name, label in (("name", "Nombre"), ("notes", "Notas")):
            assert [visible_text(found) for found in find_all(self.field(html, name), "label")] == [label], name

    def test_admin_type_form_keeps_its_labels(self, garage):
        from .maintenance_forms import ServiceTypeForm as AdminTypeForm
        form = AdminTypeForm(user=garage.owner)
        assert (form.fields["name"].label, form.fields["notes"].label) == ("Name", "Notes")

    def test_an_empty_type_name_says_so_once_in_spanish(self, garage, client):
        client.force_login(garage.owner)
        html = client.post(reverse("garage:service-type-create"), {"name": " "}).content.decode()
        errors = [visible_text(li) for li in find_all(self.field(html, "name"), "li")]
        assert errors == ["Este campo es obligatorio."]
        assert not ServiceType.objects.filter(owner=garage.owner, name="").exists()

    def test_currency_has_no_placeholder(self, garage, client):
        """«EUR» in grey looked like a value already typed (F13); the help says the example."""
        client.force_login(garage.owner)
        assert not ServiceEvent.objects.filter(owner=garage.owner, currency__isnull=False).exists()
        box = find_all(parse(client.get(reverse("garage:service-event-create")).content.decode()), "input", name="currency")
        assert len(box) == 1 and "placeholder" not in box[0].attrs and box[0].attrs.get("value", "") == ""
        assert "Código ISO, por ejemplo EUR." in visible_text(self.field(client.get(reverse("garage:service-event-create")).content.decode(), "currency"))

    def test_currency_still_preloads_the_last_one_used(self, garage, client):
        kind = save_maintenance(garage.owner, ServiceType, name="Lavado")
        save_maintenance(garage.owner, ServiceEvent, bike=garage.road, service_type=kind, performed_at=at(9), amount=Decimal(5), currency="USD")
        save_maintenance(garage.owner, ServiceEvent, bike=garage.road, service_type=kind, performed_at=at(2), amount=Decimal(5), currency="GBP")
        client.force_login(garage.owner)
        page = client.get(reverse("garage:service-event-create")).content.decode()
        assert value_of(page, "currency") == "GBP"

    def test_an_amount_with_too_many_decimals_says_only_that(self, garage, client):
        """An amount was typed: «Indica importe y moneda» under the currency would be false (garage-047 F07, D4)."""
        kind = save_maintenance(garage.owner, ServiceType, name="Lavado")
        client.force_login(garage.owner)
        html = client.post(reverse("garage:service-event-create"), {"bike": garage.road.pk, "service_type": kind.pk, "time_zone": "UTC",
                                                                   "performed_at": "2026-10-01T10:00", "amount": "1,234", "currency": "EUR"}).content.decode()
        assert [visible_text(li) for ul in find_all(parse(html), "ul", cls="errorlist") for li in find_all(ul, "li")] == ["Como máximo 2 decimales."]
        assert not ServiceEvent.objects.filter(owner=garage.owner).exists()

    def test_a_wrong_currency_is_said_even_when_the_amount_is_wrong_too(self, garage, client):
        """Two mistakes, two messages: only «importe y moneda» follows from the rejected amount."""
        kind = save_maintenance(garage.owner, ServiceType, name="Lavado")
        client.force_login(garage.owner)
        html = client.post(reverse("garage:service-event-create"), {"bike": garage.road.pk, "service_type": kind.pk, "time_zone": "UTC",
                                                                   "performed_at": "2026-10-01T10:00", "amount": "mucho", "currency": "xyz"}).content.decode()
        assert [visible_text(li) for li in find_all(self.field(html, "amount"), "li")] == ["Introduce un importe, por ejemplo 32,90."]
        assert [visible_text(li) for li in find_all(self.field(html, "currency"), "li")] == ["Usa un código de moneda ISO 4217, por ejemplo EUR."]
        assert len([li for ul in find_all(parse(html), "ul", cls="errorlist") for li in find_all(ul, "li")]) == 2
        assert not ServiceEvent.objects.filter(owner=garage.owner).exists()

    @pytest.mark.parametrize("data,field,message", [
        ({"distance_km": "mucho"}, "distance_km", "Introduce un número."),
        ({"moving_time_h": "1,2,3"}, "moving_time_h", "Introduce un número."),
        ({"ride_count": "1,5"}, "ride_count", "Introduce un número entero."),
        ({"calendar_days": "diez"}, "calendar_days", "Introduce un número entero."),
        ({"elevation_gain_m": "1,5"}, "elevation_gain_m", "Introduce metros enteros, sin decimales (1500 o 1.500)."),
        ({"moving_time_s": "mucho"}, "moving_time_s", "Introduce un número."),  # the exact field, still accepted when posted
    ])
    def test_a_threshold_typed_wrong_says_only_that(self, garage, client, data, field, message):
        """A threshold was typed: «Indica al menos un umbral» would be false, and under Distancia a second error (F07, D4)."""
        kind = save_maintenance(garage.owner, ServiceType, name="Lavado")
        client.force_login(garage.owner)
        html = client.post(reverse("garage:maintenance-rule-create"),
                           {"item": garage.light.pk, "service_type": kind.pk, "time_zone": "UTC", **data}).content.decode()
        assert [visible_text(li) for li in find_all(self.field(html, field), "li")] == [message]
        assert [visible_text(li) for ul in find_all(parse(html), "ul", cls="errorlist") for li in find_all(ul, "li")] == [message]
        assert not MaintenanceRule.objects.filter(service_type=kind).exists()

    def test_no_threshold_at_all_is_still_said(self, garage, client):
        """The other side: nothing typed, or only a field that is no threshold rejected, still asks for one."""
        kind = save_maintenance(garage.owner, ServiceType, name="Lavado")
        client.force_login(garage.owner)
        url, wanted = reverse("garage:maintenance-rule-create"), "Indica al menos un umbral: distancia, tiempo, salidas, días o desnivel."
        html = client.post(url, {"item": garage.light.pk, "service_type": kind.pk, "time_zone": "UTC"}).content.decode()
        assert [visible_text(li) for li in find_all(self.field(html, "distance_km"), "li")] == [wanted]
        assert [visible_text(li) for ul in find_all(parse(html), "ul", cls="errorlist") for li in find_all(ul, "li")] == [wanted]
        html = client.post(url, {"item": garage.light.pk, "service_type": kind.pk, "time_zone": "UTC",
                                 "anchor_at": "mañana"}).content.decode()
        assert [visible_text(li) for li in find_all(self.field(html, "distance_km"), "li")] == [wanted]
        assert not MaintenanceRule.objects.filter(service_type=kind).exists()

    def test_a_bad_zone_says_only_that(self, garage, client):
        """The date stays naive without a valid zone: «con su zona horaria» under it would be false."""
        kind = save_maintenance(garage.owner, ServiceType, name="Lavado")
        client.force_login(garage.owner)
        for zone, message in (("Marte/Olimpo", "Elige una zona horaria IANA válida."), ("", "Este campo es obligatorio.")):
            html = client.post(reverse("garage:service-event-create"), {"bike": garage.road.pk, "service_type": kind.pk, "time_zone": zone,
                                                                       "performed_at": "2026-10-01T10:00"}).content.decode()
            assert [visible_text(li) for ul in find_all(parse(html), "ul", cls="errorlist") for li in find_all(ul, "li")] == [message], zone
        assert not ServiceEvent.objects.filter(owner=garage.owner).exists()


def status_line(response):
    """What the page after a save says in its status line, one entry per message."""
    return [visible_text(p) for box in find_all(parse(response.content.decode()), "div", cls="messages") for p in find_all(box, "p")]


def pending(response):
    """The messages a response leaves for the next page (none were shown)."""
    return [str(message) for message in get_messages(response.wsgi_request)]


EVENT = {"performed_at": "2026-10-15T10:00", "time_zone": "UTC", "notes": "", "amount": "", "currency": ""}


class TestSaveMessages:
    """garage-047 F08 (D7): every save of a type, a rule or an intervention says what was saved, also when editing."""

    def test_saving_a_service_type_confirms_it(self, garage, client):
        client.force_login(garage.owner)
        created = client.post(reverse("garage:service-type-create"), {"name": "Purgar frenos"}, follow=True)
        assert created.redirect_chain == [(reverse("garage:maintenance"), 302)]
        assert status_line(created) == ["Tipo de intervención guardado."]
        kind = ServiceType.objects.get(owner=garage.owner, name="Purgar frenos")
        edited = client.post(reverse("garage:service-type-edit", args=[kind.pk]), {"name": "Purgar frenos", "notes": "Cada año"}, follow=True)
        assert status_line(edited) == ["Tipo de intervención guardado."]
        assert ServiceType.objects.get(pk=kind.pk).notes == "Cada año"
        assert status_line(client.get(reverse("garage:maintenance"))) == []  # said once, not on every visit

    def test_saving_a_rule_confirms_it(self, garage, client):
        kind = ServiceType.objects.get(owner=garage.owner, name="Revisión")
        client.force_login(garage.owner)
        for target in ({"item": garage.light.pk}, {"bike": garage.road.pk}):
            created = client.post(reverse("garage:maintenance-rule-create"),
                                  {**target, "service_type": kind.pk, "calendar_days": "30", "time_zone": "UTC"}, follow=True)
            assert created.redirect_chain == [(reverse("garage:maintenance"), 302)], target
            assert status_line(created) == ["Regla guardada."], target
        rule = MaintenanceRule.objects.get(owner=garage.owner, item=garage.light, service_type=kind)
        edited = client.post(reverse("garage:maintenance-rule-edit", args=[rule.pk]),
                             {"item": garage.light.pk, "service_type": kind.pk, "calendar_days": "60", "time_zone": "UTC"}, follow=True)
        assert status_line(edited) == ["Regla guardada."]
        rule.refresh_from_db()
        assert rule.calendar_days == 60

    def test_saving_an_intervention_confirms_it(self, garage, client, frozen):
        kind = ServiceType.objects.get(owner=garage.owner, name="Revisión")
        client.force_login(garage.owner)
        created = client.post(reverse("garage:service-event-create"), {**EVENT, "bike": garage.road.pk, "service_type": kind.pk}, follow=True)
        event = ServiceEvent.objects.get(owner=garage.owner, bike=garage.road, service_type=kind)
        assert created.redirect_chain == [(reverse("garage:service-event-detail", args=[event.pk]), 302)]
        assert status_line(created) == ["Intervención guardada."]
        edited = client.post(reverse("garage:service-event-edit", args=[event.pk]),
                             {**EVENT, "bike": garage.road.pk, "service_type": kind.pk, "notes": "Rodamientos"}, follow=True)
        assert status_line(edited) == ["Intervención guardada."]
        assert ServiceEvent.objects.get(pk=event.pk).notes == "Rodamientos"
        # From the bike's screen, with its parts offered and none ticked: the same message, nothing about the others.
        chain_rule = MaintenanceRule.objects.get(owner=garage.owner, item=garage.chain)
        shown = [str(rule.pk) for rule, _ in scope_rules(garage.owner, garage.road, at=datetime(2026, 10, 14, 10, tzinfo=UTC))]
        assert str(chain_rule.pk) in shown
        alone = client.post(reverse("garage:service-event-create") + f"?bike={garage.road.pk}",
                            {**EVENT, "performed_at": "2026-10-14T10:00", "service_type": kind.pk, "together": "1", "shown_rules": shown}, follow=True)
        assert status_line(alone) == ["Intervención guardada."]
        assert not ServiceEvent.objects.filter(owner=garage.owner, item=garage.chain).exists()

    def test_one_message_with_the_others_registered(self, garage, client, frozen):
        """The intervention and the others of the same visit: one message, the main one first."""
        kind = ServiceType.objects.get(owner=garage.owner, name="Revisión")
        chain_rule = MaintenanceRule.objects.get(owner=garage.owner, item=garage.chain)
        performed = datetime(2026, 10, 15, 10, tzinfo=UTC)
        shown = [str(rule.pk) for rule, _ in scope_rules(garage.owner, garage.road, at=performed)]
        client.force_login(garage.owner)
        response = client.post(reverse("garage:service-event-create") + f"?bike={garage.road.pk}",
                               {**EVENT, "service_type": kind.pk, "together": "1", "shown_rules": shown, "also": [str(chain_rule.pk)]}, follow=True)
        assert status_line(response) == ["Intervención guardada. Registradas también: Cambio de cadena de Cadena 11v."]
        assert ServiceEvent.objects.filter(owner=garage.owner, item=garage.chain, service_type=chain_rule.service_type, performed_at=performed).exists()

    def test_a_rejected_save_leaves_no_message(self, garage, client, frozen):
        """Guard: nothing saved, nothing confirmed; the form comes back with its error."""
        kind = ServiceType.objects.get(owner=garage.owner, name="Revisión")
        chain_rule = MaintenanceRule.objects.get(owner=garage.owner, item=garage.chain)
        counts = lambda: (ServiceType.objects.count(), MaintenanceRule.objects.count(), ServiceEvent.objects.count())  # noqa: E731
        before = counts()
        client.force_login(garage.owner)
        rejected = (
            ("garage:service-type-create", {"name": "revisión"}, "Ya tienes un tipo con ese nombre."),  # refused when saving
            ("garage:maintenance-rule-create", {"item": garage.helmet.pk, "service_type": kind.pk, "calendar_days": "30", "time_zone": "UTC"},
             "Ya hay una regla de ese tipo para este objeto"),  # the helmet has one already
            ("garage:service-event-create", {**EVENT, "service_type": kind.pk}, "Elige un objeto o una bici, no ambos."),  # no target
        )
        for name, data, error in rejected:
            response = client.post(reverse(name), data)
            assert response.status_code == 200 and error in response.content.decode(), name
            assert status_line(response) == [] and pending(response) == [], name
        # A valid form the service refuses: the parts mounted at that date are not the list that was shown.
        response = client.post(reverse("garage:service-event-create") + f"?bike={garage.road.pk}",
                               {**EVENT, "service_type": kind.pk, "together": "1", "shown_rules": [], "also": [str(chain_rule.pk)]})
        assert response.status_code == 200 and "Con esa fecha cambian las piezas montadas" in response.content.decode()
        assert status_line(response) == [] and pending(response) == []
        assert counts() == before


class TestZoneFold:
    """garage-047 F01: the time zone sits right after the dates it reads, and its summary says which zone that is."""

    @pytest.mark.parametrize("page,date_field", [
        ("installation-create", "ended_at"),  # Montar: after «Final», its last date
        ("service-event-create", "performed_at"),  # Registrar mantenimiento: after «Fecha y hora»
        ("maintenance-rule-create", "anchor_at"),  # Nueva regla: after «Contar desde»
        ("item-create", "acquisition_anchor_at"),  # Crear material: after «Inicio del uso desde adquisición»
    ])
    def test_the_zone_follows_the_last_date_field(self, garage, client, page, date_field):
        client.force_login(garage.owner)
        url = reverse(f"garage:{page}", args=[garage.light.pk] if page == "installation-create" else [])
        response = client.get(url)
        assert response.status_code == 200
        fold, elements = zone_fold(response.content.decode())
        before = elements[elements.index(fold) - 1]
        assert "field" in before.attrs.get("class", "").split() and control_names(before) == {date_field}

    def test_the_zone_summary_says_what_it_changes(self, garage, client):
        client.force_login(garage.owner)
        client.cookies["garage_tz"] = "Europe/Madrid"
        for url in (reverse("garage:installation-create", args=[garage.light.pk]), reverse("garage:item-retire", args=[garage.light.pk]),
                    reverse("garage:item-lifespan", args=[garage.chain.pk])):  # Vida útil draws its own fold
            html = client.get(url).content.decode()
            assert zone_summary(html) == "Horas en Europe/Madrid · Cambiar", url
            fold, _ = zone_fold(html)
            # What the script keeps up to date while another zone is typed: the name alone.
            assert [visible_text(name) for name in find_all(fold, data_zone_name=True)] == ["Europe/Madrid"], url

    def test_a_bound_invalid_zone_is_repeated_escaped(self, garage, client):
        client.force_login(garage.owner)
        typed = "<b>Mars</b>"
        posts = ((reverse("garage:item-retire", args=[garage.light.pk]), {"at": "2026-10-01T10:00"}),
                 (reverse("garage:item-lifespan", args=[garage.chain.pk]), {"distance_km": "3000", "start": "2026-01-01T00:00", "time_unit": "days"}))
        for url, data in posts:
            response = client.post(url, {**data, "time_zone": typed})
            html = response.content.decode()
            assert response.status_code == 200, url
            fold, _ = zone_fold(html)
            assert "open" in fold.attrs and zone_summary(html) == f"Horas en {typed} · Cambiar", url
            assert typed not in html, url  # shown as text, never as markup
        assert Item.objects.get(pk=garage.light.pk).retired_at is None

    @pytest.mark.parametrize("typed", ["", "   "])
    def test_an_empty_zone_reads_as_a_dash(self, garage, client, typed):
        """No zone was given: the summary does not claim one (the script writes «—» too while it stays empty)."""
        client.force_login(garage.owner)
        for url, data in ((reverse("garage:item-retire", args=[garage.light.pk]), {"at": "2026-10-01T10:00"}),
                          (reverse("garage:item-lifespan", args=[garage.chain.pk]), {"distance_km": "3000", "start": "2026-01-01T00:00", "time_unit": "days"})):
            html = client.post(url, {**data, "time_zone": typed}).content.decode()
            assert zone_summary(html) == "Horas en — · Cambiar", url

    def test_the_lifespan_zone_stays_after_its_start(self, garage, client):
        """Guard: Vida útil already has it after «Cuenta desde» and the notes about that date; nothing moves there."""
        client.force_login(garage.owner)
        fold, elements = zone_fold(client.get(reverse("garage:item-lifespan", args=[garage.chain.pk])).content.decode())
        index = elements.index(fold)
        start = next(position for position, element in enumerate(elements) if control_names(element) == {"start"})
        assert start < index
        assert [control_names(element) for element in elements[start + 1:index] if control_names(element)] == []  # only notes between
        assert [control_names(element) for element in elements[index + 1:] if control_names(element)] == []  # no field after it


NOW_HELP = "Por defecto, ahora. Si fue antes, cámbialo."
HALF_PAST = datetime(2026, 10, 17, 10, 31, 27, tzinfo=UTC)  # 12:31:27 in Madrid


def open_mount(garage):
    return Installation.objects.get(item=garage.chain, ended_at__isnull=True).pk


# The pages that start from «now»: (url name, the date field, its arguments).
NOW_PAGES = [
    ("item-retire", "at", lambda garage: [garage.light.pk]),  # Retirar
    ("bike-retire", "at", lambda garage: [garage.gravel.pk]),
    ("installation-close", "at", lambda garage: [open_mount(garage)]),  # Desmontar
    ("installation-replace", "at", lambda garage: [open_mount(garage)]),  # Reemplazar
    ("installation-transfer", "at", lambda garage: [open_mount(garage)]),  # Transferir
    ("installation-create", "started_at", lambda garage: [garage.light.pk]),  # Montar
    ("item-part-create", "at", lambda garage: [garage.shoes.pk]),  # Añadir pieza: already to the minute, and the help is the same
]


def date_control(html, name):
    controls = find_all(parse(html), "input", name=name)
    assert len(controls) == 1, name
    return controls[0]


def help_of(html, name):
    wrappers = [wrapper for wrapper in find_all(parse(html), "div", cls="field") if find_all(wrapper, "input", name=name)]
    assert len(wrappers) == 1, name
    return [visible_text(found) for found in find_all(wrappers[0], "div", cls="help")]


class TestNowToTheMinute:
    """garage-047 F03: «now» is offered to the minute, and the field says it is only a default."""

    @pytest.fixture
    def half_past(self, monkeypatch):
        monkeypatch.setattr("django.utils.timezone.now", lambda: HALF_PAST)
        return HALF_PAST

    @pytest.mark.parametrize("page,name,args", NOW_PAGES, ids=[page for page, *_ in NOW_PAGES])
    def test_now_is_offered_to_the_minute(self, garage, client, half_past, page, name, args):
        client.force_login(garage.owner)
        client.cookies["garage_tz"] = "Europe/Madrid"
        response = client.get(reverse(f"garage:{page}", args=args(garage)))
        assert response.status_code == 200
        control = date_control(response.content.decode(), name)
        assert (control.attrs.get("type"), control.attrs.get("value")) == ("datetime-local", "2026-10-17T12:31")
        assert "step" not in control.attrs  # no seconds to pick

    @pytest.mark.parametrize("page,name,args", NOW_PAGES, ids=[page for page, *_ in NOW_PAGES])
    def test_the_default_says_it_is_now(self, garage, client, half_past, page, name, args):
        client.force_login(garage.owner)
        assert help_of(client.get(reverse(f"garage:{page}", args=args(garage))).content.decode(), name) == [NOW_HELP]

    def test_a_new_mount_sent_with_errors_still_says_it(self, garage, client, half_past):
        client.force_login(garage.owner)
        response = client.post(reverse("garage:installation-create", args=[garage.light.pk]),
                               {"time_zone": "Europe/Madrid", "started_at": "2026-10-01T10:00"})  # no destination
        html = response.content.decode()
        assert response.status_code == 200 and "Elige exactamente una bici o un objeto de destino." in html
        assert help_of(html, "started_at") == [NOW_HELP]
        assert not Installation.objects.filter(item=garage.light).exists()

    # Guards: they pass before the change and must keep passing.

    def test_a_repeated_hour_keeps_now_in_utc(self, garage, client, monkeypatch):
        """02:31 happens twice in Madrid on 25 Oct 2026: the form stays in UTC, where the instant is not ambiguous."""
        monkeypatch.setattr("django.utils.timezone.now", lambda: datetime(2026, 10, 25, 0, 31, 27, tzinfo=UTC))
        client.force_login(garage.owner)
        client.cookies["garage_tz"] = "Europe/Madrid"
        html = client.get(reverse("garage:item-retire", args=[garage.light.pk])).content.decode()
        assert value_of(html, "time_zone") == "UTC" and value_of(html, "at").startswith("2026-10-25T00:31")

    def test_a_bound_form_keeps_its_seconds(self, garage, client, half_past):
        client.force_login(garage.owner)
        response = client.post(reverse("garage:item-retire", args=[garage.light.pk]), {"time_zone": "Mars/Base", "at": "2026-01-01T10:00:15"})
        assert response.status_code == 200 and value_of(response.content.decode(), "at") == "2026-01-01T10:00:15"

    def test_editing_a_mount_keeps_its_seconds(self, garage, client, half_past):
        from .services.installations import create_installation
        mount = create_installation(garage.owner, item=garage.light, bike=garage.gravel, started_at=datetime(2026, 1, 1, 10, 0, 15, tzinfo=UTC))
        client.force_login(garage.owner)
        client.cookies["garage_tz"] = "Europe/Madrid"
        html = client.get(reverse("garage:installation-edit", args=[mount.pk])).content.decode()
        assert value_of(html, "started_at") == "2026-01-01T11:00:15"

    def test_editing_a_mount_does_not_say_now(self, garage, client, half_past):
        """Its start comes from the saved period, not from «now» (R2-06)."""
        from .services.installations import create_installation
        mount = create_installation(garage.owner, item=garage.light, bike=garage.gravel, started_at=datetime(2026, 1, 1, 10, tzinfo=UTC))
        client.force_login(garage.owner)
        url = reverse("garage:installation-edit", args=[mount.pk])
        shown = client.get(url).content.decode()
        rejected = client.post(url, {"time_zone": "UTC", "bike": garage.gravel.pk, "started_at": "2026-01-02T10:00", "ended_at": "2026-01-01T10:00"})
        assert rejected.status_code == 200 and "El final debe ser posterior al inicio." in rejected.content.decode()
        for html in (shown, rejected.content.decode()):
            assert NOW_HELP not in visible_text(parse(html))
            assert help_of(html, "started_at") == []


def drawn_layout(html):
    """How the one `form.form` of a page draws what a person fills in, in order: per element of the form that holds
    controls, what it is (`row` for a `.field-row`, `zone` for the time zone fold, else `field`) and its control names."""
    forms = find_all(parse(html), "form", cls="form")
    assert len(forms) == 1, f"{len(forms)} forms"
    layout = []
    for element in (child for child in forms[0].children if isinstance(child, Node)):
        names = [found.attrs.get("name") for found in find_all(element) if found.tag in ("input", "select", "textarea")
                 and found.attrs.get("type") != "hidden"]
        if names:
            classes = element.attrs.get("class", "").split()
            layout.append(("row" if "field-row" in classes else "zone" if element.tag == "details" else "field", names))
    return layout


def row_holding(html, name):
    """The `.field-row` that holds the control `name`, and that control's own `.field` box."""
    rows = [row for row in find_all(parse(html), "div", cls="field-row") if find_all(row, name=name)]
    assert len(rows) == 1, f"{len(rows)} rows hold {name}"
    boxes = [box for box in find_all(rows[0], "div", cls="field") if find_all(box, name=name)]
    assert len(boxes) == 1, name
    return rows[0], boxes[0]


RULE_LAYOUT = [("field", ["item"]), ("field", ["bike"]), ("field", ["service_type"]),
               ("row", ["distance_km", "moving_time_h"]), ("row", ["ride_count", "calendar_days"]),
               ("field", ["elevation_gain_m"]), ("field", ["anchor_at"]), ("zone", ["time_zone"]), ("field", ["notes"])]


class TestRuleRows:
    """garage-047 F20: Nueva regla is shorter. Its thresholds go two by two, so «Contar desde» comes up the page."""

    def test_rule_thresholds_go_two_by_two(self, garage, client):
        client.force_login(garage.owner)
        kind = save_maintenance(garage.owner, ServiceType, name="Engrase")
        rule = save_maintenance(garage.owner, MaintenanceRule, item=garage.light, service_type=kind, distance_m=Decimal(500000),
                                moving_time_s=Decimal(36000), ride_count=20, calendar_days=90, elevation_gain_m=Decimal(10000))
        for url in (reverse("garage:maintenance-rule-create"), reverse("garage:maintenance-rule-edit", args=[rule.pk])):
            html = client.get(url).content.decode()
            assert drawn_layout(html) == RULE_LAYOUT, url
            for name in ("distance_km", "ride_count"):
                row, _ = row_holding(html, name)
                assert len([box for box in row.children if isinstance(box, Node) and "field" in box.attrs.get("class", "").split()]) == 2

    def test_rides_need_no_help(self, garage, client):
        """«Salidas» says it all: its help «Número de salidas.» only made the row taller. Días keeps what it explains."""
        client.force_login(garage.owner)
        html = client.get(reverse("garage:maintenance-rule-create")).content.decode()
        assert help_of(html, "ride_count") == [] and "Número de salidas." not in html
        assert help_of(html, "calendar_days") == ["Días de 24 horas, aunque no se use."]  # guard
        from .maintenance_forms import MaintenanceRuleForm as AdminForm
        assert AdminForm(user=garage.owner).fields["ride_count"].help_text == "Número de salidas."  # guard: the admin keeps its own

    @pytest.mark.parametrize("name,typed,message,partner", [
        ("calendar_days", "1,5", "Introduce un número entero.", "ride_count"),  # right half of the second row
        ("ride_count", "muchas", "Introduce un número entero.", "calendar_days"),  # left half of the second row
        ("distance_km", "abc", "Introduce un número.", "moving_time_h"),  # left half of the first row
        ("moving_time_h", "-1", "Debe ser mayor que cero.", "distance_km"),  # right half of the first row
    ])
    def test_a_row_keeps_its_errors(self, garage, client, name, typed, message, partner):
        client.force_login(garage.owner)
        kind = save_maintenance(garage.owner, ServiceType, name="Engrase")
        data = {"item": garage.light.pk, "service_type": kind.pk, "time_zone": "UTC", "distance_km": "3000", "ride_count": "20", name: typed}
        response = client.post(reverse("garage:maintenance-rule-create"), data)
        html = response.content.decode()
        assert response.status_code == 200 and drawn_layout(html) == RULE_LAYOUT
        row, box = row_holding(html, name)
        assert "has-error" in box.attrs["class"].split()
        assert [visible_text(found) for found in find_all(box, "ul", cls="errorlist")] == [message]
        others = [other for other in find_all(row, "div", cls="field") if find_all(other, name=partner)]  # same row, no error
        assert len(others) == 1 and "has-error" not in others[0].attrs["class"].split() and not find_all(others[0], "ul", cls="errorlist")
        assert visible_text(parse(html)).count(message) == 1  # once, under its own field
        assert value_of(html, name) == typed  # what was typed stays, to correct it
        assert not MaintenanceRule.objects.filter(service_type=kind).exists()

    # Guards: they pass before the change and must keep passing.

    @pytest.mark.parametrize("stored", [
        {"distance_m": Decimal("123.456"), "moving_time_s": Decimal("1.001")},
        {"moving_time_s": Decimal("1.001"), "calendar_days": 5},  # no distance: its field is still offered, in km
    ])
    def test_an_exact_field_goes_alone(self, garage, client, stored):
        """Seconds that are no exact hours keep their own field: it and the other one of its pair each go on their own line.

        Stored metres are always exact km (3 decimals of a metre are 6 of a km): only a POST keeps metres (next test).
        """
        alone = ["moving_time_s", "distance_km"]
        client.force_login(garage.owner)
        kind = save_maintenance(garage.owner, ServiceType, name="Engrase")
        rule = save_maintenance(garage.owner, MaintenanceRule, item=garage.light, service_type=kind, **stored)
        layout = drawn_layout(client.get(reverse("garage:maintenance-rule-edit", args=[rule.pk])).content.decode())
        for name in alone:
            assert ("field", [name]) in layout, (name, layout)

    @pytest.mark.parametrize("posted,alone", [
        ({"distance_m": "1500", "moving_time_h": "2"}, ["distance_m", "moving_time_h"]),
        ({"distance_m": "1500", "moving_time_s": "7200"}, ["distance_m", "moving_time_s"]),
    ])
    def test_an_exact_field_posted_goes_alone(self, garage, client, posted, alone):
        """Posting metres or seconds stays supported; sent back with an error, each value of the pair keeps its own line."""
        client.force_login(garage.owner)
        response = client.post(reverse("garage:maintenance-rule-create"), {"item": garage.light.pk, "time_zone": "UTC", **posted})  # no type
        layout = drawn_layout(response.content.decode())
        assert response.status_code == 200
        for name in alone:
            assert ("field", [name]) in layout, (name, layout)

    @pytest.mark.parametrize("page", ["service-event-create", "service-type-create", "item-create", "installation-create"])
    def test_other_forms_keep_one_field_per_line(self, garage, client, page):
        client.force_login(garage.owner)
        url = reverse(f"garage:{page}", args=[garage.light.pk] if page == "installation-create" else [])
        layout = drawn_layout(client.get(url).content.decode())
        assert layout and all(kind != "row" and len(names) == 1 for kind, names in layout), layout
