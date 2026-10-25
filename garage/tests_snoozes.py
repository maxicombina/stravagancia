"""garage-034: postpone a rule's alert by km, hours, rides or days, whichever comes first."""
import io
import json
import re
from datetime import timedelta
from decimal import Decimal
from zipfile import ZipFile

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .models import MaintenanceRule, MaintenanceSnooze, ServiceEvent, ServiceType, UsageMaterializationState
from .presentation import SEVERITY, wear
from .services.export import ExportError, TABLES, csv_zip, export_snapshot
from .services.home import home_snapshot
from .services.lifespan import set_lifespan
from .services.maintenance import delete_maintenance, save_maintenance
from .services.maintenance_due import maintenance_due
from .services.ownership import InventoryNotFound, InventoryWriteError
from .services.rides import create_manual_ride
from .services.snoozes import end_snooze, open_snooze, snooze_rule
from .services.usage import rebuild_usage
from .services.workshop import workshop_snapshot
from .snooze_forms import SnoozeForm, presets
from .tests_mobile_home import NOW, at, garage  # noqa: F401 (fixture)

WRITES = {"INSERT", "UPDATE", "DELETE"}


@pytest.fixture
def now(monkeypatch):
    monkeypatch.setattr("django.utils.timezone.now", lambda: NOW)
    return NOW


def rule_of(garage, name):
    item = {"chain": garage.chain, "cleats": garage.cleats, "helmet": garage.helmet}[name]
    return MaintenanceRule.objects.get(owner=garage.owner, item=item)


def due_of(owner, rule, when=NOW):
    return next(due for due in maintenance_due(owner, at=when) if due.rule.pk == rule.pk)


def bike_rule(garage, **values):
    kind = save_maintenance(garage.owner, ServiceType, name="Revisión general")
    return save_maintenance(garage.owner, MaintenanceRule, bike=garage.road, service_type=kind, anchor_at=at(200), **values)


def writes(queries):
    return [q["sql"] for q in queries if q["sql"].lstrip().split()[0].upper() in WRITES]


class TestModel:
    def test_constraints(self, garage):
        rule = rule_of(garage, "cleats")
        base = {"owner": garage.owner, "rule": rule, "started_at": at(2), "reference_at": at(150)}
        for values in ({}, {"calendar_days": 0}, {"distance_m": Decimal("-1")}, {"calendar_days": 1, "ended_at": at(3)}):
            with pytest.raises(IntegrityError), transaction.atomic():
                MaintenanceSnooze.objects.create(**base, **values)
        MaintenanceSnooze.objects.create(**base, calendar_days=1)
        with pytest.raises(IntegrityError), transaction.atomic():  # one open snooze per rule
            MaintenanceSnooze.objects.create(**{**base, "started_at": at(1)}, calendar_days=1)
        MaintenanceSnooze.objects.create(**{**base, "started_at": at(5), "ended_at": at(5)}, calendar_days=1)

    def test_clean(self, garage):
        foreign = MaintenanceRule.objects.get(owner=garage.other)
        snooze = MaintenanceSnooze(owner=garage.owner, rule=foreign, started_at=at(1), reference_at=at(9), calendar_days=1)
        with pytest.raises(ValidationError) as error:
            snooze.full_clean()
        assert "rule" in error.value.error_dict
        snooze = MaintenanceSnooze(owner=garage.owner, rule=rule_of(garage, "cleats"), started_at=at(1).replace(tzinfo=None),
                                   reference_at=at(9), distance_m=Decimal("0.0001"))
        with pytest.raises(ValidationError) as error:
            snooze.full_clean()
        assert {"started_at", "distance_m"} <= set(error.value.error_dict)

    def test_deleting_the_rule_deletes_its_snoozes(self, garage):
        rule = rule_of(garage, "cleats")
        snooze_rule(garage.owner, rule, calendar_days=3, at=at(2))
        delete_maintenance(garage.owner, MaintenanceRule, rule.pk)
        assert not MaintenanceSnooze.objects.filter(owner=garage.owner).exists()


class TestService:
    def test_create_replace_and_end(self, garage):
        rule = rule_of(garage, "cleats")
        first = snooze_rule(garage.owner, rule, calendar_days=7, at=at(5))
        assert (first.started_at, first.ended_at, first.calendar_days, first.reference_at, first.reference_event_id) == (at(5), None, 7, at(150), None)
        second = snooze_rule(garage.owner, rule.pk, distance_m=Decimal("1500.5"), at=at(2))
        first.refresh_from_db()
        assert first.ended_at == at(2) and open_snooze(garage.owner, rule) == second
        assert end_snooze(garage.owner, rule, at=at(1)) is True
        second.refresh_from_db()
        assert second.ended_at == at(1) and open_snooze(garage.owner, rule) is None
        assert end_snooze(garage.owner, rule, at=at(1)) is False

    def test_double_tap_is_harmless(self, garage):
        rule = rule_of(garage, "cleats")
        first = snooze_rule(garage.owner, rule, calendar_days=7, at=at(2))
        second = snooze_rule(garage.owner, rule, calendar_days=7, at=at(2))
        first.refresh_from_db()
        assert first.ended_at == first.started_at and open_snooze(garage.owner, rule) == second

    def test_reference_is_remembered(self, garage):
        rule = rule_of(garage, "cleats")
        event = save_maintenance(garage.owner, ServiceEvent, item=garage.cleats, service_type=rule.service_type, performed_at=at(120))
        snooze = snooze_rule(garage.owner, rule, calendar_days=7, at=at(2))
        assert (snooze.reference_at, snooze.reference_event_id) == (at(120), event.pk)

    @pytest.mark.parametrize("call,text", [
        (lambda g: snooze_rule(g.owner, rule_of(g, "cleats")), "Indica cuántos"),
        (lambda g: snooze_rule(g.owner, rule_of(g, "cleats"), distance_m=Decimal("0.0001")), ""),
        (lambda g: snooze_rule(g.owner, rule_of(g, "helmet"), calendar_days=3), "no hay aviso que posponer"),
        (lambda g: snooze_rule(g.owner, rule_of(g, "cleats"), calendar_days=3, at=NOW + timedelta(days=400)), "futuro"),
    ])
    def test_errors(self, garage, call, text):
        with pytest.raises(InventoryWriteError) as error:
            call(garage)
        assert text in " ".join(error.value.messages)
        assert not MaintenanceSnooze.objects.exists()

    def test_never_overlaps_earlier_history(self, garage):
        rule = rule_of(garage, "cleats")
        snooze_rule(garage.owner, rule, calendar_days=3, at=at(5))
        end_snooze(garage.owner, rule, at=at(3))
        with pytest.raises(InventoryWriteError):
            snooze_rule(garage.owner, rule, calendar_days=3, at=at(4))  # before the last end
        snooze_rule(garage.owner, rule, calendar_days=3, at=at(2))
        with pytest.raises(InventoryWriteError):
            end_snooze(garage.owner, rule, at=at(3))  # before its start

    def test_foreign(self, garage):
        foreign = MaintenanceRule.objects.get(owner=garage.other)
        for call in (lambda: snooze_rule(garage.owner, foreign, calendar_days=1), lambda: end_snooze(garage.owner, foreign),
                     lambda: open_snooze(garage.owner, foreign)):
            with pytest.raises(InventoryNotFound):
                call()

    def test_moving_the_rule_ends_its_snooze(self, garage):
        rule = rule_of(garage, "chain")
        snooze_rule(garage.owner, rule, calendar_days=30, at=at(5))
        save_maintenance(garage.owner, MaintenanceRule, rule.pk, distance_m=Decimal(500000))  # same alert: kept
        assert open_snooze(garage.owner, rule) is not None
        save_maintenance(garage.owner, MaintenanceRule, rule.pk, item=garage.light)  # another alert
        assert open_snooze(garage.owner, rule) is None and MaintenanceSnooze.objects.get().ended_at is not None


class TestDue:
    def test_days_active_then_reached(self, garage):
        rule = rule_of(garage, "cleats")  # due: 150 days of 100
        snooze_rule(garage.owner, rule, calendar_days=7, at=at(2))
        w = wear(due_of(garage.owner, rule))
        assert (w.real_state, w.state, w.word, w.icon, w.needs_attention) == ("due", "snoozed", "Pospuesto", "clock", False)
        assert w.snooze_left == "5 días"
        later = wear(due_of(garage.owner, rule, NOW + timedelta(days=5)))
        assert later.due.snooze.status == "reached" and later.state == "due" and later.needs_attention

    def test_km_lower_bound_and_first_amount_wins(self, garage):
        rule = rule_of(garage, "chain")  # review: at least 400 km of 420
        snooze_rule(garage.owner, rule, distance_m=Decimal(150000), calendar_days=60, at=at(30))  # 100 km since
        w = wear(due_of(garage.owner, rule))
        assert w.state == "snoozed" and w.real_state == "review"
        assert w.snooze_left == "como máx. 50 km o 30 días"  # observed km are a minimum, days are exact
        snooze_rule(garage.owner, rule, distance_m=Decimal(150000), calendar_days=5, at=at(30))
        assert wear(due_of(garage.owner, rule)).state == "review"  # 30 days > 5: time came first
        snooze_rule(garage.owner, rule, distance_m=Decimal(100000), calendar_days=60, at=at(30))
        assert due_of(garage.owner, rule).snooze.status == "reached"

    def test_unknown_usage_never_hides_an_alert(self, garage):
        rule = rule_of(garage, "cleats")  # due by days: always known
        snooze_rule(garage.owner, rule, distance_m=Decimal(500000), calendar_days=60, at=at(30))
        assert wear(due_of(garage.owner, rule)).state == "snoozed"
        UsageMaterializationState.objects.filter(owner=garage.owner).update(initialized_at=None)
        due = due_of(garage.owner, rule)
        assert due.snooze.status == "unknown" and wear(due).state == "due"

    def test_any_other_reference_restarts(self, garage):
        rule = rule_of(garage, "cleats")
        snooze_rule(garage.owner, rule, calendar_days=30, at=at(2))
        # Registered right after postponing, with the form's minute-rounded time: before the snooze start.
        event = save_maintenance(garage.owner, ServiceEvent, item=garage.cleats, service_type=rule.service_type,
                                 performed_at=at(2) - timedelta(seconds=30))
        due = due_of(garage.owner, rule)
        assert due.snooze is None and wear(due).state != "snoozed"
        delete_maintenance(garage.owner, ServiceEvent, event.pk)
        assert wear(due_of(garage.owner, rule)).state == "snoozed"  # deleting it brings the snooze back
        save_maintenance(garage.owner, MaintenanceRule, rule.pk, anchor_at=at(149))
        assert due_of(garage.owner, rule).snooze is None  # another anchor: the count restarted

    def test_an_older_intervention_keeps_it(self, garage):
        rule = rule_of(garage, "cleats")
        save_maintenance(garage.owner, ServiceEvent, item=garage.cleats, service_type=rule.service_type, performed_at=at(120))
        snooze_rule(garage.owner, rule, calendar_days=30, at=at(2))
        save_maintenance(garage.owner, ServiceEvent, item=garage.cleats, service_type=rule.service_type, performed_at=at(130))
        assert wear(due_of(garage.owner, rule)).state == "snoozed"  # still counted from at(120)

    def test_instant_window(self, garage):
        rule = rule_of(garage, "cleats")
        snooze_rule(garage.owner, rule, calendar_days=30, at=at(10))
        end_snooze(garage.owner, rule, at=at(5))
        assert due_of(garage.owner, rule, at(11)).snooze is None  # before it started
        assert wear(due_of(garage.owner, rule, at(7))).state == "snoozed"  # while it was open
        assert due_of(garage.owner, rule).snooze is None  # stopped by hand

    def test_bike_rule_counts_its_rides(self, garage):
        rule = bike_rule(garage, ride_count=3)  # 4 rides since at(200): due
        snooze_rule(garage.owner, rule, ride_count=2, calendar_days=90, at=at(60))  # rides at(50) and at(10)
        assert wear(due_of(garage.owner, rule)).state == "due"
        snooze_rule(garage.owner, rule, ride_count=2, calendar_days=60, at=at(30))
        w = wear(due_of(garage.owner, rule))
        assert w.state == "snoozed" and w.snooze_left == "como máx. 1 salida o 30 días"

    def test_useful_life_can_be_postponed(self, garage):
        life = set_lifespan(garage.owner, garage.light, calendar_days=10, start=at(20))
        snooze_rule(garage.owner, life, calendar_days=3, at=at(1))
        assert wear(due_of(garage.owner, life)).state == "snoozed"

    def test_same_queries_without_writes(self, garage):
        with CaptureQueriesContext(connection) as before:
            maintenance_due(garage.owner, at=NOW)
        snooze_rule(garage.owner, rule_of(garage, "cleats"), calendar_days=3, at=at(1))
        with CaptureQueriesContext(connection) as after:
            maintenance_due(garage.owner, at=NOW)
        assert len(after) == len(before) and not writes(after)


class TestPresentation:
    def test_order(self):
        assert SEVERITY.index("soon") < SEVERITY.index("snoozed") < SEVERITY.index("nodata")

    def test_no_snooze_is_unchanged(self, garage):
        w = wear(due_of(garage.owner, rule_of(garage, "cleats")))
        assert (w.state, w.real_state, w.snoozed, w.snooze_metrics, w.snooze_left) == ("due", "due", False, (), "")

    def test_snapshots(self, garage):
        snooze_rule(garage.owner, rule_of(garage, "chain"), distance_m=Decimal(150000), calendar_days=60, at=at(30))
        home = home_snapshot(garage.owner, at=NOW)
        assert [alert.target.name for alert in home.attention] == ["Calas"]
        assert home.snoozed == 1 and {entry.bike.name: entry.alerts for entry in home.bikes}["Carretera"] == 0
        shop = workshop_snapshot(garage.owner, at=NOW)
        assert [alert.target.name for alert in shop.snoozed] == ["Cadena 11v"]
        assert [alert.target.name for alert in shop.attention] == ["Calas"]


class TestForm:
    def test_amounts_are_exact(self):
        form = SnoozeForm({"distance_km": "0,5", "moving_time_h": "1,25", "ride_count": "2", "calendar_days": "7", "notes": "viaje"})
        assert form.is_valid(), form.errors
        assert form.amounts == {"distance_m": Decimal("500"), "moving_time_s": Decimal("4500"), "ride_count": 2, "calendar_days": 7,
                            "elevation_gain_m": None}
        assert SnoozeForm().fields["calendar_days"].initial == 30

    @pytest.mark.parametrize("data,field,text", [
        ({}, "calendar_days", "máximo de días"),
        ({"distance_km": "3.000", "calendar_days": "30"}, "distance_km", "¿Miles o decimales?"),
        ({"distance_km": "0", "calendar_days": "30"}, "distance_km", "mayor que cero"),
        ({"moving_time_h": "0,0000001", "calendar_days": "30"}, "moving_time_h", "6 decimales"),
        ({"calendar_days": "1,5"}, "calendar_days", "entero"),
        ({"calendar_days": "40000"}, "calendar_days", "36.500"),
        ({"ride_count": "0", "calendar_days": "30"}, "ride_count", "al menos 1"),
    ])
    def test_errors(self, data, field, text):
        form = SnoozeForm(data)
        assert not form.is_valid() and text in " ".join(form.errors[field])

    def test_presets(self, garage):
        options = presets(rule_of(garage, "chain"))
        assert [label for label, _ in options.values()] == ["1 semana", "2 semanas", "1 mes", "10 % de la regla"]
        assert options["month"][1] == {"calendar_days": 30}
        assert options["tenth"][1] == {"distance_m": Decimal("42000.000"), "calendar_days": 30}  # no days threshold: 30-day maximum
        rule = bike_rule(garage, distance_m=Decimal("30000000.5"), moving_time_s=Decimal(5), ride_count=1, calendar_days=365)
        assert presets(rule)["tenth"][1] == {"distance_m": Decimal("3000000.050"), "moving_time_s": Decimal("0.500"), "ride_count": 1,
                                             "calendar_days": 37}


def snooze_url(rule):
    return reverse("garage:maintenance-rule-snooze", args=[rule.pk])


class TestScreens:
    def test_page_get_has_no_writes(self, garage, client, now):
        rule = rule_of(garage, "cleats")
        client.force_login(garage.owner)
        with CaptureQueriesContext(connection) as queries:
            response = client.get(snooze_url(rule))
        html = response.content.decode()
        assert response.status_code == 200 and not writes(queries)
        assert "<script>" not in html and ' style="' not in html
        for text in ("<h1>Calas</h1>", "100 días, lo primero que llegue", "Vencido", "Registrar calas", "Posponer el aviso",
                     'name="preset" value="week"', "10 % de la regla", 'name="calendar_days"', 'value="30"', "Editar la regla"):
            assert text in html, text
        assert f"?item={garage.cleats.pk}&amp;type={rule.service_type_id}" in html
        assert "Dejar de posponer" not in html

    def test_post_create_change_and_end(self, garage, client, now):
        rule = rule_of(garage, "cleats")
        client.force_login(garage.owner)
        response = client.post(snooze_url(rule), {"calendar_days": "7", "distance_km": "0,5", "notes": "Tras el viaje"}, follow=True)
        assert response.redirect_chain[-1][0] == reverse("garage:item-detail", args=[garage.cleats.pk])
        html = response.content.decode()
        assert "Calas de Calas: pospuesto 0,5 km o 7 días, lo primero que llegue." in html
        assert "Pospuesto (vencido): quedan 0,5 km o 7 días; después vuelve a avisar." in html
        assert "Cambiar o dejar de posponer" in html
        snooze = MaintenanceSnooze.objects.get(owner=garage.owner)
        assert (snooze.started_at, snooze.distance_m, snooze.calendar_days, snooze.notes) == (NOW, Decimal(500), 7, "Tras el viaje")
        page = client.get(snooze_url(rule)).content.decode()
        assert "Dejar de posponer" in page and "Quedan <b>0,5 km o 7 días</b>" in page and "(Tras el viaje)" in page
        assert "Volver a posponer desde ahora" in page
        response = client.post(snooze_url(rule), {"action": "end"}, follow=True)
        assert "Calas de Calas vuelve a avisar." in response.content.decode()
        snooze.refresh_from_db()
        assert snooze.ended_at == NOW

    def test_preset_works_without_javascript(self, garage, client, now):
        client.force_login(garage.owner)
        response = client.post(snooze_url(rule_of(garage, "cleats")), {"preset": "week"})
        assert response.status_code == 302 and MaintenanceSnooze.objects.get().calendar_days == 7
        response = client.post(snooze_url(rule_of(garage, "cleats")), {"preset": "tenth"})
        assert response.status_code == 302 and MaintenanceSnooze.objects.get(ended_at__isnull=True).calendar_days == 10

    def test_post_errors_keep_the_page(self, garage, client, now):
        client.force_login(garage.owner)
        url = snooze_url(rule_of(garage, "cleats"))
        for data, text in (({"distance_km": "3.000", "calendar_days": "30"}, "¿Miles o decimales?"), ({"calendar_days": ""}, "máximo de días"),
                           ({"preset": "forever"}, "Elige uno de los atajos.")):
            response = client.post(url, data)
            assert response.status_code == 200 and text in response.content.decode(), text
        response = client.post(snooze_url(rule_of(garage, "helmet")), {"preset": "week"})
        assert "no hay aviso que posponer" in response.content.decode()
        assert not MaintenanceSnooze.objects.exists()

    def test_foreign_and_anonymous(self, garage, client):
        foreign = MaintenanceRule.objects.get(owner=garage.other)
        assert client.get(snooze_url(foreign)).status_code == 302  # login first
        client.force_login(garage.owner)
        assert client.get(snooze_url(foreign)).status_code == 404
        assert client.post(snooze_url(foreign), {"calendar_days": "1"}).status_code == 404
        assert client.post(snooze_url(foreign), {"action": "end"}).status_code == 404
        assert not MaintenanceSnooze.objects.exists()

    def test_item_home_and_workshop(self, garage, client, now):
        client.force_login(garage.owner)
        item = client.get(reverse("garage:item-detail", args=[garage.cleats.pk])).content.decode()
        assert "Posponer aviso" in item and snooze_url(rule_of(garage, "cleats")) in item
        snooze_rule(garage.owner, rule_of(garage, "cleats"), calendar_days=7, at=at(2))
        home = client.get(reverse("garage:index")).content.decode()
        assert "1 aviso pospuesto" in home and reverse("garage:maintenance") + "#snoozed" in home
        shop = client.get(reverse("garage:maintenance")).content.decode()
        assert 'id="snoozed"' in shop and "Vencido · quedan 5 días de aplazamiento" in shop
        assert "Aplazamiento desde el" in shop and "activo" in shop  # technical details

    def test_bike_rule_row_on_its_own_page(self, garage, client, now):
        rule = bike_rule(garage, ride_count=3)
        client.force_login(garage.owner)
        page = client.get(reverse("garage:bike-detail", args=[garage.road.pk])).content.decode()
        assert snooze_url(rule) in page
        snooze_rule(garage.owner, rule, ride_count=2, calendar_days=60, at=at(30))
        page = client.get(reverse("garage:bike-detail", args=[garage.road.pk])).content.decode()
        assert '<h3 class="sub-h">Pospuestos</h3>' in page and snooze_url(rule) in page

    def test_life_links_to_its_own_editor(self, garage, client, now):
        life = set_lifespan(garage.owner, garage.light, calendar_days=10, start=at(20))
        client.force_login(garage.owner)
        page = client.get(snooze_url(life)).content.decode()
        assert "<h1>Vida útil</h1>" in page and reverse("garage:item-lifespan", args=[garage.light.pk]) in page and "Editar vida útil" in page

    def test_event_form_preselects_the_type(self, garage, client):
        rule = rule_of(garage, "cleats")
        client.force_login(garage.owner)
        html = client.get(reverse("garage:service-event-create") + f"?item={garage.cleats.pk}&type={rule.service_type_id}").content.decode()
        assert re.search(rf'<option value="{rule.service_type_id}" selected>', html)
        foreign_type = ServiceType.objects.get(owner=garage.other)
        assert client.get(reverse("garage:service-event-create") + f"?type={foreign_type.pk}").status_code == 404
        assert client.get(reverse("garage:service-event-create") + "?type=nope").status_code == 404

    def test_ride_review_reports_the_snooze_running_out(self, garage, client, now):
        rule = rule_of(garage, "cleats")
        snooze_rule(garage.owner, rule, ride_count=2, calendar_days=60, at=at(30))  # the shoes (and their cleats) rode at(10)
        ride = create_manual_ride(garage.owner, started_at=at(1), name="Nueva", distance_m=Decimal(1000))
        rebuild_usage(garage.owner)
        client.force_login(garage.owner)
        response = client.post(reverse("garage:ride-review", args=[ride.pk]),
                               {"bike": str(garage.road.pk), "shown_bike": str(garage.road.pk), "gear": [str(garage.shoes.pk)]}, follow=True)
        assert "Calas · Calas: Pospuesto → Vencido" in response.content.decode()


class TestExport:
    def test_exported_and_foreign_rule_rejected(self, garage):
        snooze_rule(garage.owner, rule_of(garage, "cleats"), calendar_days=7, distance_m=Decimal("1.5"), at=at(2))
        rows = export_snapshot(garage.owner)["tables"]["snoozes"]
        assert len(rows) == 1
        assert (rows[0]["calendar_days"], rows[0]["distance_m"], rows[0]["ended_at"], rows[0]["reference_event_id"]) == (7, "1.500", None, None)
        MaintenanceSnooze.objects.create(owner=garage.owner, rule=MaintenanceRule.objects.get(owner=garage.other), started_at=at(1),
                                         reference_at=at(9), calendar_days=1)
        with pytest.raises(ExportError):
            export_snapshot(garage.owner)


class TestReviewFixes:
    def test_postponed_in_advance_is_shown_and_can_be_ended(self, garage, client, now):
        kind = save_maintenance(garage.owner, ServiceType, name="Revisión anual")
        rule = save_maintenance(garage.owner, MaintenanceRule, item=garage.light, service_type=kind, calendar_days=1000, anchor_at=at(10))
        snooze_rule(garage.owner, rule, calendar_days=30, at=at(1))
        w = wear(due_of(garage.owner, rule))
        assert w.real_state in ("current", "progress") and w.state == w.real_state and w.snooze.active
        client.force_login(garage.owner)
        page = client.get(snooze_url(rule)).content.decode()
        assert "Ahora no requiere atención; si vence antes, no avisará." in page and "Dejar de posponer" in page
        assert "El uso desde entonces está pendiente de calcular" not in page
        item = client.get(reverse("garage:item-detail", args=[garage.light.pk])).content.decode()
        assert "Pospuesto por adelantado: quedan 29 días" in item
        client.post(snooze_url(rule), {"action": "end"})
        assert MaintenanceSnooze.objects.get().ended_at == NOW

    def test_reached_names_only_what_ran_out(self, garage, client, now):
        rule = rule_of(garage, "cleats")
        snooze_rule(garage.owner, rule, distance_m=Decimal(500000), calendar_days=2, at=at(5))
        w = wear(due_of(garage.owner, rule))
        assert w.snooze.status == "reached" and w.snooze_reached == "2 días" and w.state == "due"
        client.force_login(garage.owner)
        page = client.get(snooze_url(rule)).content.decode()
        assert "Se llegó a 2 días: el aviso se muestra." in page and "Cerrar el aplazamiento" in page

    def test_days_left_round_up(self, garage):
        rule = rule_of(garage, "cleats")
        snooze_rule(garage.owner, rule, calendar_days=1, at=NOW - timedelta(hours=12))
        w = wear(due_of(garage.owner, rule))
        assert w.state == "snoozed" and (w.snooze_verb, w.snooze_left) == ("queda", "1 día")

    def test_unknown_page_and_bike_links(self, garage, client, now):
        rule = rule_of(garage, "cleats")
        snooze_rule(garage.owner, rule, distance_m=Decimal(500000), calendar_days=60, at=at(30))
        UsageMaterializationState.objects.filter(owner=garage.owner).update(initialized_at=None)
        client.force_login(garage.owner)
        page = client.get(snooze_url(rule)).content.decode()
        assert "Aplazamiento sin calcular" in page and "pendiente de calcular: el aviso se sigue mostrando." in page
        bike = bike_rule(garage, ride_count=100)  # far from due
        snooze_rule(garage.owner, bike, ride_count=5, calendar_days=60, at=at(30))
        html = client.get(reverse("garage:bike-detail", args=[garage.road.pk])).content.decode()
        assert snooze_url(bike) in html  # its in-advance snooze stays reachable
        shop = client.get(reverse("garage:maintenance")).content.decode()
        assert "Ver el aplazamiento" in shop and "Posponer el aviso" in shop

    def test_reference_event_moved_elsewhere(self, garage):
        rule = rule_of(garage, "cleats")
        event = save_maintenance(garage.owner, ServiceEvent, item=garage.cleats, service_type=rule.service_type, performed_at=at(120))
        snooze_rule(garage.owner, rule, calendar_days=30, at=at(2))
        assert wear(due_of(garage.owner, rule)).state == "snoozed"
        save_maintenance(garage.owner, ServiceEvent, event.pk, item=garage.chain)
        assert due_of(garage.owner, rule).snooze is None  # its reference is the anchor again

    def test_rides_without_bike_do_not_count_for_a_bike_rule(self, garage):
        rule = bike_rule(garage, ride_count=3)
        snooze_rule(garage.owner, rule, ride_count=2, calendar_days=60, at=at(30))
        create_manual_ride(garage.owner, started_at=at(2), name="Sin bici", distance_m=Decimal(1000))
        assert wear(due_of(garage.owner, rule)).snooze_left == "como máx. 1 salida o 30 días"

    def test_csrf_and_methods(self, garage, client):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(garage.owner)
        url = snooze_url(rule_of(garage, "cleats"))
        assert strict.post(url, {"preset": "week"}).status_code == 403
        client.force_login(garage.owner)
        assert client.put(url).status_code == 405 and client.delete(url).status_code == 405
        assert not MaintenanceSnooze.objects.exists()

    def test_preset_cap_and_zip_columns(self, garage):
        rule = bike_rule(garage, calendar_days=2147483647)
        assert presets(rule)["tenth"][1]["calendar_days"] == 36500
        snooze_rule(garage.owner, rule_of(garage, "cleats"), calendar_days=7, at=at(2))
        with ZipFile(io.BytesIO(csv_zip(export_snapshot(garage.owner)))) as archive:
            header = archive.read("snoozes.csv").decode().splitlines()[0]
            manifest = json.loads(archive.read("manifest.json"))
        assert header == ",".join(f'"{column}"' for column in ("id", "created_at", "updated_at", *TABLES["snoozes"][1]))
        assert manifest["csv"]["tables"]["snoozes"]["rows"] == 1
