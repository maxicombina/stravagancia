"""garage-033: a component's useful life by km, hours and time, whichever comes first."""
import json
import re
from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.urls import reverse

from .lifespan_forms import LifespanForm, split_days
from .models import Installation, Item, MaintenanceRule, ServiceEvent, ServiceType
from .presentation import wear
from .services.installations import create_installation
from .services.lifespan import LIFE_TYPE, default_start, inherit_lifespan, is_life, lifespan_rule, remove_lifespan, set_lifespan
from .services.maintenance import save_maintenance
from .services.maintenance_due import maintenance_due
from .services.ownership import InventoryNotFound, InventoryWriteError, create_inventory, update_inventory
from .tests_mobile_home import NOW, at, garage  # noqa: F401 (fixture)

UTC = dt_timezone.utc
MADRID = ZoneInfo("Europe/Madrid")


def life(owner, item):
    return MaintenanceRule.objects.filter(owner=owner, item=item, service_type__name=LIFE_TYPE).first()


class TestService:
    def test_create_update_and_first_threshold_wins(self, garage):
        rule = set_lifespan(garage.owner, garage.chain, distance_m=Decimal(3000000), calendar_days=30, start=at(200))
        assert is_life(rule) and rule.anchor_at == at(200)
        assert ServiceType.objects.filter(owner=garage.owner, name=LIFE_TYPE).count() == 1
        due = next(d for d in maintenance_due(garage.owner, at=NOW) if d.rule.pk == rule.pk)
        assert due.status == "due" and wear(due).headline.name == "calendar_days"  # 200 days > 30: time came first
        same = set_lifespan(garage.owner, garage.chain, distance_m=Decimal(1000), calendar_days=None, start=at(1))
        assert same.pk == rule.pk and (same.distance_m, same.calendar_days, same.anchor_at) == (Decimal(1000), None, at(1))

    def test_existing_type_is_reused_case_insensitively(self, garage):
        kind = save_maintenance(garage.owner, ServiceType, name="sustitución")
        rule = set_lifespan(garage.owner, garage.light, calendar_days=365, start=at(10))
        assert rule.service_type_id == kind.pk and lifespan_rule(garage.owner, garage.light).pk == rule.pk

    def test_needs_a_threshold_and_keeps_ride_count(self, garage):
        with pytest.raises(InventoryWriteError):
            set_lifespan(garage.owner, garage.light, start=at(1))
        rule = set_lifespan(garage.owner, garage.light, calendar_days=10, start=at(1))
        save_maintenance(garage.owner, MaintenanceRule, rule.pk, ride_count=50)
        kept = set_lifespan(garage.owner, garage.light, start=at(1))
        assert (kept.calendar_days, kept.ride_count) == (None, 50)
        assert remove_lifespan(garage.owner, garage.light) and lifespan_rule(garage.owner, garage.light) is None
        assert remove_lifespan(garage.owner, garage.light) is False

    def test_ownership(self, garage):
        foreign = Item.objects.get(name="SECRET item")
        with pytest.raises(InventoryNotFound):
            set_lifespan(garage.owner, foreign, calendar_days=1, start=at(1))
        with pytest.raises(InventoryNotFound):
            inherit_lifespan(garage.owner, outgoing=garage.chain, incoming=foreign, at=at(1))

    def test_default_start(self, garage):
        assert default_start(garage.owner, garage.chain, zone=MADRID, at=NOW) == at(200)  # first mount
        assert default_start(garage.owner, garage.light, zone=MADRID, at=NOW) == NOW  # nothing known
        update_inventory(garage.owner, Item, garage.light.pk, acquired_on=date(2026, 3, 1))
        assert default_start(garage.owner, garage.light, zone=MADRID, at=NOW) == datetime(2026, 3, 1, tzinfo=MADRID)
        update_inventory(garage.owner, Item, garage.light.pk, acquisition_anchor_at=at(5))
        assert default_start(garage.owner, garage.light, zone=MADRID, at=NOW) == at(5)
        update_inventory(garage.owner, Item, garage.light.pk, acquisition_anchor_at=NOW + timedelta(days=3))
        assert default_start(garage.owner, garage.light, zone=MADRID, at=NOW) == NOW  # never in the future

    def test_inherit(self, garage):
        spare = create_inventory(garage.owner, Item, name="Cadena nueva", category=garage.chain.category)
        assert inherit_lifespan(garage.owner, outgoing=garage.chain, incoming=spare, at=at(1)) is None
        set_lifespan(garage.owner, garage.chain, distance_m=Decimal(3000000), calendar_days=365, start=at(200))
        copied = inherit_lifespan(garage.owner, outgoing=garage.chain, incoming=spare, at=at(1))
        assert (copied.item_id, copied.distance_m, copied.calendar_days, copied.anchor_at) == (spare.pk, Decimal(3000000), 365, at(1))
        assert inherit_lifespan(garage.owner, outgoing=garage.chain, incoming=spare, at=at(0)) is None  # already has its own

    def test_replacement_event_restarts_the_life(self, garage):
        rule = set_lifespan(garage.owner, garage.chain, calendar_days=30, start=at(200))
        save_maintenance(garage.owner, ServiceEvent, item=garage.chain, service_type=rule.service_type, performed_at=at(2))
        due = next(d for d in maintenance_due(garage.owner, at=NOW) if d.rule.pk == rule.pk)
        assert due.reference_at == at(2) and due.status == "current"


class TestForm:
    def bound(self, **data):
        return LifespanForm({"start": "2026-01-01T00:00", "time_zone": "Europe/Madrid", "time_unit": "days", **data})

    @pytest.mark.parametrize("value,unit,days", [("2", "years", 730), ("6", "months", 180), ("45", "days", 45)])
    def test_time_units(self, value, unit, days):
        form = self.bound(time_value=value, time_unit=unit)
        assert form.is_valid(), form.errors
        assert form.lifespan["calendar_days"] == days and split_days(days) == (int(value), unit)

    def test_km_hours_and_local_start(self):
        form = self.bound(distance_km="2.700,5", moving_time_h="1,5")
        assert form.is_valid(), form.errors
        assert form.lifespan == {"distance_m": Decimal("2700500"), "moving_time_s": Decimal("5400"), "calendar_days": None,
                                 "elevation_gain_m": None}
        assert form.cleaned_data["start"] == datetime(2025, 12, 31, 23, tzinfo=UTC)

    @pytest.mark.parametrize("data,field", [({"distance_km": "3.000"}, "distance_km"), ({"distance_km": "0"}, "distance_km"),
                                            ({"moving_time_h": "0,000001"}, "moving_time_h"), ({"time_value": "0"}, "time_value"),
                                            ({"time_value": "101", "time_unit": "years"}, "time_value")])
    def test_rejects(self, data, field):
        form = self.bound(**data)
        assert not form.is_valid() and field in form.errors

    def test_messages_are_spanish_and_specific(self):
        form = self.bound(distance_km="abc", time_value="x")
        assert not form.is_valid()
        assert form.errors["distance_km"] == ["Introduce un número."] and form.errors["time_value"] == ["Introduce un número entero."]
        assert self.bound(distance_km="0.500").is_valid()

    def test_inexact_hours_are_kept(self, garage):
        rule = set_lifespan(garage.owner, garage.light, moving_time_s=Decimal("1.001"), calendar_days=10, start=at(1))
        shown = LifespanForm(rule=rule, start=at(1))
        assert "moving_time_h" not in shown.fields
        form = LifespanForm({"start": "2026-01-01T00:00", "time_zone": "UTC", "time_value": "10", "time_unit": "days"}, rule=rule, start=at(1))
        assert form.is_valid(), form.errors
        assert form.lifespan["moving_time_s"] == Decimal("1.001")


class TestPage:
    def url(self, item):
        return reverse("garage:item-lifespan", args=[item.pk])

    def test_create_from_suggestion_and_edit(self, garage, client):
        client.force_login(garage.owner)
        html = client.get(self.url(garage.chain)).content.decode()
        assert "Orientativo para una cadena: <b>unos 3.000 km</b>" in html and json.loads(re.search(r'data-fill="([^"]+)"', html).group(1).replace("&quot;", '"')) == {"distance_km": "3000"}
        assert 'name="time_zone" value="Europe/Madrid"' in html and "Quitar vida útil" not in html
        response = client.post(self.url(garage.chain), {"distance_km": "3000", "time_value": "1", "time_unit": "years",
                                                         "start": "2026-03-30T12:00", "time_zone": "Europe/Madrid"})
        assert response.status_code == 302 and response.url == reverse("garage:item-detail", args=[garage.chain.pk])
        rule = life(garage.owner, garage.chain)
        assert (rule.distance_m, rule.calendar_days, rule.anchor_at) == (Decimal(3000000), 365, datetime(2026, 3, 30, 10, tzinfo=UTC))
        edit = client.get(self.url(garage.chain)).content.decode()
        assert 'value="3000"' in edit and '<option value="years" selected>' in edit and "Quitar vida útil" in edit

    def test_remove_and_errors(self, garage, client):
        set_lifespan(garage.owner, garage.chain, calendar_days=30, start=at(1))
        client.force_login(garage.owner)
        empty = client.post(self.url(garage.chain), {"start": "2026-01-01T00:00", "time_zone": "UTC", "time_unit": "days"})
        assert empty.status_code == 200 and "Indica km, horas, desnivel o tiempo, o quita la vida útil." in empty.content.decode()
        assert client.post(self.url(garage.chain), {"action": "remove"}).status_code == 302
        assert life(garage.owner, garage.chain) is None

    def test_foreign_and_login(self, garage, client):
        assert client.get(self.url(garage.chain)).status_code == 302
        client.force_login(garage.owner)
        foreign = Item.objects.get(name="SECRET item")
        assert client.get(self.url(foreign)).status_code == 404
        assert client.post(self.url(foreign), {"action": "remove"}).status_code == 404

    @pytest.mark.parametrize("inherit", [True, False])
    def test_replacement_inherits_on_request(self, garage, client, inherit):
        set_lifespan(garage.owner, garage.chain, distance_m=Decimal(3000000), start=at(200))
        spare = create_inventory(garage.owner, Item, name="Cadena nueva", category=garage.chain.category)
        period = Installation.objects.get(item=garage.chain, ended_at__isnull=True)
        client.force_login(garage.owner)
        url = reverse("garage:installation-replace", args=[period.pk])
        assert "La pieza nueva hereda la vida útil" in client.get(url).content.decode()
        data = {"time_zone": "UTC", "at": "2026-10-15T08:00", "incoming_item": spare.pk, **({"inherit_lifespan": "on"} if inherit else {})}
        response = client.post(url, data, follow=True)
        copied = life(garage.owner, spare)
        assert response.status_code == 200
        if inherit:
            assert copied.distance_m == Decimal(3000000) and copied.anchor_at == datetime(2026, 10, 15, 8, tzinfo=UTC)
            assert "Cadena nueva hereda la vida útil: 3.000 km, desde el reemplazo." in response.content.decode()
        else:
            assert copied is None

    def test_no_life_no_checkbox(self, garage, client):
        period = Installation.objects.get(item=garage.chain, ended_at__isnull=True)
        client.force_login(garage.owner)
        assert "hereda la vida útil" not in client.get(reverse("garage:installation-replace", args=[period.pk])).content.decode()


class TestScreens:
    def test_item_home_and_workshop_say_vida_util(self, garage, client):
        client.force_login(garage.owner)
        html = client.get(reverse("garage:item-detail", args=[garage.chain.pk])).content.decode()
        assert "Definir vida útil" in html and f'href="{reverse("garage:item-lifespan", args=[garage.chain.pk])}"' in html
        set_lifespan(garage.owner, garage.chain, distance_m=Decimal(3000000), calendar_days=30, start=at(200))
        html = client.get(reverse("garage:item-detail", args=[garage.chain.pk])).content.decode()
        assert "Definir vida útil" not in html and "Editar vida útil" in html
        first_panel = html.index('<span class="gauge-title">')
        assert html[first_panel:first_panel + 60].startswith('<span class="gauge-title">Vida útil</span>')
        assert "Vence con lo primero que llegue: 3.000 km o 30 días." in html
        home = client.get(reverse("garage:index")).content.decode()
        assert re.search(r'Cadena 11v</span>\s*<span class="entry-sub">Vida útil · Carretera', home)
        shop = client.get(reverse("garage:maintenance")).content.decode()
        assert "Vida útil · Cadena 11v" in shop and "Sustitución · Cadena 11v" not in shop


class TestReviewFixes:
    def test_an_earlier_replacement_wins_and_the_page_says_so(self, garage, client):
        rule = set_lifespan(garage.owner, garage.chain, calendar_days=365, start=at(5))
        save_maintenance(garage.owner, ServiceEvent, item=garage.chain, service_type=rule.service_type, performed_at=at(100))
        due = next(d for d in maintenance_due(garage.owner, at=NOW) if d.rule.pk == rule.pk)
        assert due.reference_at == at(100)
        client.force_login(garage.owner)
        html = client.get(reverse("garage:item-lifespan", args=[garage.chain.pk])).content.decode()
        assert "Ahora cuenta desde la última sustitución registrada" in html

    def test_inherit_counts_from_the_swap_despite_older_replacements(self, garage):
        set_lifespan(garage.owner, garage.chain, calendar_days=30, start=at(200))
        spare = create_inventory(garage.owner, Item, name="Cadena usada", category=garage.chain.category)
        kind = lifespan_rule(garage.owner, garage.chain).service_type
        save_maintenance(garage.owner, ServiceEvent, item=spare, service_type=kind, performed_at=at(300))
        copied = inherit_lifespan(garage.owner, outgoing=garage.chain, incoming=spare, at=at(1))
        due = next(d for d in maintenance_due(garage.owner, at=NOW) if d.rule.pk == copied.pk)
        assert due.reference_at == at(1) and due.status == "current"

    def test_bike_rules_of_that_type_are_not_a_useful_life(self, garage, client):
        rule = set_lifespan(garage.owner, garage.chain, calendar_days=30, start=at(1))
        bike_rule = save_maintenance(garage.owner, MaintenanceRule, bike=garage.road, service_type=rule.service_type, calendar_days=1, anchor_at=at(5))
        assert is_life(rule) and not is_life(bike_rule)
        client.force_login(garage.owner)
        shop = client.get(reverse("garage:maintenance")).content.decode()
        assert "Sustitución · Carretera" in shop and "Vida útil · Cadena 11v" in shop

    def test_the_life_type_cannot_be_renamed_while_used(self, garage, client):
        rule = set_lifespan(garage.owner, garage.chain, calendar_days=30, start=at(1))
        client.force_login(garage.owner)
        url = reverse("garage:service-type-edit", args=[rule.service_type_id])
        html = client.post(url, {"name": "Cambio"}).content.decode()
        assert "guarda la vida útil de tus componentes" in html
        assert ServiceType.objects.get(pk=rule.service_type_id).name == LIFE_TYPE
        remove_lifespan(garage.owner, garage.chain)
        assert client.post(url, {"name": "Cambio"}).status_code == 302

    def test_future_start_is_rejected(self, garage):
        form = LifespanForm({"start": "2999-01-01T00:00", "time_zone": "UTC", "time_value": "1", "time_unit": "years"})
        assert not form.is_valid() and "No puede ser una fecha futura" in form.errors["start"][0]

    def test_get_writes_nothing_and_ride_count_is_visible(self, garage, client):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        rule = set_lifespan(garage.owner, garage.chain, calendar_days=30, start=at(1))
        save_maintenance(garage.owner, MaintenanceRule, rule.pk, ride_count=50)
        client.force_login(garage.owner)
        with CaptureQueriesContext(connection) as queries:
            html = client.get(reverse("garage:item-lifespan", args=[garage.chain.pk])).content.decode()
        assert not [q for q in queries if q["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}]
        assert "También vence a 50 salidas" in html and "= 30 días." in html

    def test_failed_inheritance_rolls_back_the_replacement(self, garage, client, monkeypatch):
        set_lifespan(garage.owner, garage.chain, distance_m=Decimal(3000000), start=at(200))
        spare = create_inventory(garage.owner, Item, name="Cadena nueva", category=garage.chain.category)
        period = Installation.objects.get(item=garage.chain, ended_at__isnull=True)

        def broken(*args, **kwargs):
            raise InventoryWriteError({"__all__": "Fallo simulado."})
        monkeypatch.setattr("garage.services.lifespan.inherit_lifespan", broken)
        client.force_login(garage.owner)
        response = client.post(reverse("garage:installation-replace", args=[period.pk]),
                               {"time_zone": "UTC", "at": "2026-10-15T08:00", "incoming_item": spare.pk, "inherit_lifespan": "on"})
        assert response.status_code == 200 and "Fallo simulado." in response.content.decode()
        period.refresh_from_db()
        assert period.ended_at is None and not Installation.objects.filter(item=spare).exists()

    @pytest.mark.parametrize("zone", ["Mars/Base", ""])
    def test_invalid_zone_is_a_form_error(self, garage, client, zone):
        client.force_login(garage.owner)
        response = client.post(reverse("garage:item-lifespan", args=[garage.chain.pk]),
                               {"distance_km": "3000", "start": "2026-01-01T00:00", "time_zone": zone, "time_unit": "days"})
        assert response.status_code == 200 and life(garage.owner, garage.chain) is None

    def test_earlier_replacement_is_announced_before_the_life_exists(self, garage, client):
        kind = save_maintenance(garage.owner, ServiceType, name=LIFE_TYPE)
        save_maintenance(garage.owner, ServiceEvent, item=garage.chain, service_type=kind, performed_at=at(40))
        client.force_login(garage.owner)
        html = client.get(reverse("garage:item-lifespan", args=[garage.chain.pk])).content.decode()
        assert "Ahora cuenta desde la última sustitución registrada" in html

    def test_no_duplicate_replacement_at_the_same_instant(self, garage):
        set_lifespan(garage.owner, garage.chain, calendar_days=30, start=at(200))
        spare = create_inventory(garage.owner, Item, name="Cadena usada", category=garage.chain.category)
        kind = lifespan_rule(garage.owner, garage.chain).service_type
        save_maintenance(garage.owner, ServiceEvent, item=spare, service_type=kind, performed_at=at(1))
        inherit_lifespan(garage.owner, outgoing=garage.chain, incoming=spare, at=at(1))
        assert ServiceEvent.objects.filter(item=spare, service_type=kind).count() == 1

    def test_future_replacement_does_not_inherit_and_days_warning(self, garage, client):
        set_lifespan(garage.owner, garage.chain, distance_m=Decimal(3000000), start=at(200))
        spare = create_inventory(garage.owner, Item, name="Cadena nueva", category=garage.chain.category)
        period = Installation.objects.get(item=garage.chain, ended_at__isnull=True)
        client.force_login(garage.owner)
        html = client.post(reverse("garage:installation-replace", args=[period.pk]),
                           {"time_zone": "UTC", "at": "2999-01-01T08:00", "incoming_item": spare.pk, "inherit_lifespan": "on"}, follow=True).content.decode()
        assert "Reemplazo futuro: la vida útil no se hereda." in html and life(garage.owner, spare) is None
        assert "sigue contando días" not in html  # the outgoing life has no time threshold

    def test_outgoing_part_with_days_is_flagged(self, garage, client):
        set_lifespan(garage.owner, garage.chain, calendar_days=365, start=at(200))
        spare = create_inventory(garage.owner, Item, name="Cadena nueva", category=garage.chain.category)
        period = Installation.objects.get(item=garage.chain, ended_at__isnull=True)
        client.force_login(garage.owner)
        html = client.post(reverse("garage:installation-replace", args=[period.pk]),
                           {"time_zone": "UTC", "at": "2026-10-15T08:00", "incoming_item": spare.pk, "inherit_lifespan": "on"}, follow=True).content.decode()
        assert "La pieza que sale (Cadena 11v) sigue contando días" in html and life(garage.owner, spare).calendar_days == 365
