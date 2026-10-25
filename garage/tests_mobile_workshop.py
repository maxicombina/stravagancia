"""garage-032.1: local time in forms, rules in km/h, Taller and the intervention screens."""
import re
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .forms import UsageBaselineForm
from .local_forms import LocalDateTimeInput, localize
from .maintenance_forms import MaintenanceRuleWebForm as MaintenanceRuleForm, ServiceEventWebForm as ServiceEventForm
from .models import Bike, Item, MaintenanceRule, ServiceEvent, ServiceType
from .presentation import thresholds
from .services.baselines import record_baseline
from .services.maintenance import save_maintenance
from .services.ownership import create_inventory
from .services.workshop import EVENT_LIMIT, workshop_snapshot
from .tests_mobile_home import NOW, at, garage  # noqa: F401 (fixture)
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
        assert "<details class=\"zone\">" in html and "Zona horaria: America/Argentina/Buenos_Aires" in html
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
