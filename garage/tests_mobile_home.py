"""garage-031.2: wear presentation (pure) and the mobile home screen."""
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .models import Bike, Category, Item, MaintenanceRule, Ride, ServiceType, UsageMaterializationState
from .presentation import SEVERITY, by_severity, number, quantity, ring, wear
from .services.home import home_snapshot
from .services.installations import create_installation
from .services.maintenance import save_maintenance
from .services.maintenance_due import MaintenanceDue, MaintenanceMetric
from .services.ownership import create_inventory
from .services.rides import create_manual_ride
from .services.usage import rebuild_usage
from .services.usage_profiles import create_profile_history

UTC = dt_timezone.utc
NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)


def metric(name="distance_m", threshold="3000000", value="2850000", status="unknown", coverage="partial", estimated=False):
    value = None if value is None else Decimal(value)
    threshold = Decimal(threshold)
    remaining = None if value is None else max(Decimal(0), threshold - value)
    return MaintenanceMetric(name, threshold, value, remaining, status, coverage, estimated)


def due(*metrics, item="Cadena", bike=None):
    rule = SimpleNamespace(pk=item, item=SimpleNamespace(name=item) if item else None, bike=bike, item_id=item, bike_id=None,
                           service_type=SimpleNamespace(name="Cambio"))
    return MaintenanceDue(rule, None, NOW, NOW, tuple(metrics), "unknown", 0, 0, True)


class TestPresentation:
    @pytest.mark.parametrize("args,state", [
        (dict(status="due", value="3100000"), "due"),
        (dict(status="unknown", value="2700000"), "review"),
        (dict(status="unknown", value="2699999"), "progress"),
        (dict(status="soon", coverage="complete", value="2800000"), "soon"),
        (dict(status="current", coverage="complete", value="100"), "current"),
        (dict(status="unknown", value=None, coverage="unknown"), "nodata"),
    ])
    def test_states(self, args, state):
        assert wear(due(metric(**args))).state == state

    def test_nodata_outranks_progress_and_current(self):
        result = wear(due(metric("calendar_days", "365", "30", "current", "complete"), metric(value=None, coverage="unknown")))
        assert result.state == "nodata" and result.word == "Sin datos"
        assert SEVERITY.index("nodata") < SEVERITY.index("progress") < SEVERITY.index("current")

    def test_headline_is_most_severe_then_highest_ratio(self):
        result = wear(due(metric("calendar_days", "365", "100", "current", "complete"), metric(value="2900000"),
                          metric("moving_time_s", "540000", "500000")))
        assert result.headline.name == "distance_m" and result.state == "review"

    def test_lower_bound_text_and_remaining(self):
        headline = wear(due(metric(value="2850000"))).headline
        assert headline.lower_bound and headline.percent_text == "≥ 95 %"
        assert (headline.big, headline.big_caption) == ("150", "km como máx.")

    def test_estimated_reading_is_never_a_lower_bound(self):
        result = wear(due(metric(value="2850000", estimated=True)))
        headline = result.headline
        assert not headline.lower_bound and result.estimated
        assert headline.percent_text == "≈ 95 %" and headline.big_caption == "km estimados"
        assert "≥" not in headline.percent_text

    def test_due_shows_overrun(self):
        headline = wear(due(metric("calendar_days", "365", "397.27", "due", "complete"))).headline
        assert (headline.big, headline.big_caption, headline.percent_text) == ("+32", "días de más", "108 %")
        assert headline.bar == "100.0%"

    def test_complete_soon_has_no_lower_bound_mark(self):
        headline = wear(due(metric(status="soon", coverage="complete"))).headline
        assert headline.percent_text == "95 %" and headline.big_caption == "km quedan"

    def test_nodata_figures(self):
        headline = wear(due(metric(value=None, coverage="unknown"))).headline
        assert (headline.big, headline.big_caption, headline.percent_text, headline.bar) == ("—", "sin datos", "?", "0%")

    def test_ring_is_capped(self):
        assert ring(Decimal("1.5"), 22) == ring(Decimal(1), 22)
        assert ring(None, 22).startswith("0.00 ")

    def test_spanish_numbers(self):
        assert [number(2840), number(Decimal("92.4"), decimals=1), number(1234567), number(Decimal("-0.04"), decimals=1)] == \
            ["2.840", "92,4", "1.234.567", "0"]
        assert quantity("distance_m", Decimal("92.44")) == "92,4"
        assert quantity("distance_m", Decimal("2840.6")) == "2.841"
        assert quantity("calendar_days", Decimal("227.9")) == "227"

    def test_sort_by_severity(self):
        wears = [wear(due(metric(status="current", coverage="complete", value="1"), item="c")),
                 wear(due(metric(status="due", value="3000001"), item="a")),
                 wear(due(metric(value="2000000"), item="p")),
                 wear(due(metric(value="2900000"), item="r"))]
        assert [w.state for w in by_severity(wears)] == ["due", "review", "progress", "current"]


def at(days):
    return NOW - timedelta(days=days)


@pytest.fixture
def garage(db):
    users = get_user_model().objects
    owner = users.create_user("home-owner", password="test-only-password")
    other = users.create_user("home-other", password="test-only-password")
    cats = {name: create_inventory(owner, Category, name=name) for name in ("Cadenas", "Cascos", "Zapatillas", "Calas", "Luces")}
    road = create_inventory(owner, Bike, name="Carretera")
    gravel = create_inventory(owner, Bike, name="Gravel")
    retired = create_inventory(owner, Bike, name="Vieja", retired_at=at(400))
    chain = create_inventory(owner, Item, name="Cadena 11v", category=cats["Cadenas"])
    shoes = create_inventory(owner, Item, name="Zapatillas", category=cats["Zapatillas"])
    cleats = create_inventory(owner, Item, name="Calas", category=cats["Calas"])
    helmet = create_inventory(owner, Item, name="Casco", category=cats["Cascos"])
    light = create_inventory(owner, Item, name="Luz", category=cats["Luces"])
    create_installation(owner, item=chain, bike=road, parent_item=None, started_at=at(200), ended_at=None, slot="chain")
    create_installation(owner, item=cleats, bike=None, parent_item=shoes, started_at=at(200), ended_at=None, slot=None)
    create_profile_history(owner, name="Ruta", bike=road, started_at=at(300), items=[shoes])
    create_profile_history(owner, name="Siempre", started_at=at(300), items=[helmet])
    for day in (150, 100, 50, 10):
        create_manual_ride(owner, started_at=at(day), bike=road, name=f"Ruta {day}", distance_m=Decimal(100000), moving_time_s=Decimal(14400))
    create_manual_ride(owner, started_at=at(20), bike=gravel, name="Pista", distance_m=Decimal(50000), moving_time_s=Decimal(9000))
    pending = create_manual_ride(owner, started_at=at(3), name="Sin bici", distance_m=Decimal(92400))
    create_manual_ride(owner, started_at=at(4), bike=None, name="Desconocida explícita", distance_m=Decimal(1000))
    kinds = {name: save_maintenance(owner, ServiceType, name=name) for name in ("Cambio de cadena", "Revisión", "Calas")}
    save_maintenance(owner, MaintenanceRule, item=chain, service_type=kinds["Cambio de cadena"], distance_m=Decimal(420000), anchor_at=at(200))
    save_maintenance(owner, MaintenanceRule, item=helmet, service_type=kinds["Revisión"], calendar_days=365)
    save_maintenance(owner, MaintenanceRule, item=cleats, service_type=kinds["Calas"], calendar_days=100, anchor_at=at(150))
    foreign_cat = create_inventory(other, Category, name="X")
    foreign = create_inventory(other, Item, name="SECRET item", category=foreign_cat)
    create_inventory(other, Bike, name="SECRET bike")
    save_maintenance(other, MaintenanceRule, item=foreign, service_type=save_maintenance(other, ServiceType, name="S"), calendar_days=1, anchor_at=at(10))
    rebuild_usage(owner)
    return SimpleNamespace(owner=owner, other=other, road=road, gravel=gravel, retired=retired, chain=chain, shoes=shoes,
                           cleats=cleats, helmet=helmet, light=light, pending=pending)


class TestHome:
    def test_snapshot(self, garage):
        home = home_snapshot(garage.owner, at=NOW)
        states = {alert.target.name: alert.wear.state for alert in home.attention}
        assert states == {"Cadena 11v": "review", "Calas": "due"}
        places = {alert.target.name: alert.place for alert in home.attention}
        assert places == {"Cadena 11v": "Carretera", "Calas": "en Zapatillas"}
        assert home.nodata == 1 and home.calm == 0 and home.rules == 3
        assert (home.pending_count, home.pending_first.pk, home.pending_distance_m) == (1, garage.pending.pk, Decimal(92400))
        bikes = {entry.bike.name: entry for entry in home.bikes}
        assert set(bikes) == {"Carretera", "Gravel"}
        assert bikes["Carretera"].distance_m == Decimal(400000) and bikes["Carretera"].alerts == 1
        assert bikes["Gravel"].distance_m == Decimal(50000) and bikes["Gravel"].alerts == 0
        gear = {entry.item.name: entry for entry in home.gear}
        assert list(gear) == ["Casco", "Zapatillas", "Luz"]
        assert gear["Casco"].contexts == ("Cualquier bici",) and gear["Zapatillas"].contexts == ("Carretera",)
        assert not gear["Luz"].in_use and gear["Luz"].distance_m == 0
        # garage-042: the same words as the Material list; never used is «Sin estrenar», no longer «Guardado».
        assert [gear[name].life.text for name in gear] == ["En uso · Cualquier bici", "En uso · Carretera", "Sin estrenar"]
        assert gear["Zapatillas"].distance_m == Decimal(400000)
        # A profile without bike applies to every ride, also those without a bike.
        assert gear["Casco"].distance_m == Decimal(543400)

    def test_nested_mount_counts_for_the_bike(self, garage):
        create_installation(garage.owner, item=garage.shoes, bike=garage.gravel, parent_item=None, started_at=at(1), ended_at=None, slot=None)
        home = home_snapshot(garage.owner, at=NOW)
        assert {entry.bike.name: entry.alerts for entry in home.bikes} == {"Carretera": 1, "Gravel": 1}
        assert [alert.place for alert in home.attention if alert.target.name == "Calas"] == ["Gravel"]

    def test_usage_not_rebuilt_is_pending(self, garage):
        UsageMaterializationState.objects.filter(owner=garage.owner).update(initialized_at=None)
        home = home_snapshot(garage.owner, at=NOW)
        assert home.usage_current is False
        assert all(entry.distance_m is None for entry in home.gear)

    def test_page(self, garage, client):
        client.force_login(garage.owner)
        with CaptureQueriesContext(connection) as queries:
            response = client.get(reverse("garage:index"))
        html = response.content.decode()
        assert response.status_code == 200
        assert not any(q["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"} for q in queries)
        assert len(queries) <= 28, len(queries)  # session + user + snapshot (savepoints included)
        assert "<script>" not in html and ' style="' not in html
        for text in ("Requiere atención", "Cadena 11v", "Revisar", "Vencido", "1 salida por revisar", "1 regla sin datos",
                     "Calas", "en Zapatillas", f'href="{reverse("garage:ride-review", args=[garage.pending.pk])}?next=/garage/"',
                     "Equipación y material sin montar", "En uso · Cualquier bici", "90 %", "km como máx.", 'class="fab only-android"',
                     f'href="{reverse("garage:item-detail", args=[garage.chain.pk])}"', "Carretera", "Sin estrenar"):
            assert text in html, text
        for secret in ("SECRET", "Vieja", "Desconocida explícita", "Guardado"):
            assert secret not in html

    def test_snapshot_query_budget(self, garage):
        with CaptureQueriesContext(connection) as queries:
            home_snapshot(garage.owner, at=NOW)
        assert len(queries) <= 26, len(queries)  # maintenance_due (<= 12) + home reads, savepoints included
        count = len(queries)
        for number in range(10):  # more rides, items, rules and mounts: the query count stays constant
            item = create_inventory(garage.owner, Item, name=f"Extra {number}", category=garage.helmet.category)
            create_installation(garage.owner, item=item, bike=garage.gravel, parent_item=None, started_at=at(5), ended_at=None, slot=f"s{number}")
            save_maintenance(garage.owner, MaintenanceRule, item=item, service_type=save_maintenance(garage.owner, ServiceType, name=f"T{number}"), calendar_days=10, anchor_at=at(30))
            create_manual_ride(garage.owner, started_at=at(2), name=f"P{number}", distance_m=Decimal(1000))
        with CaptureQueriesContext(connection) as queries:
            home = home_snapshot(garage.owner, at=NOW)
        assert len(queries) == count and home.attention_total == 12 and len(home.attention) == 6 and home.attention_hidden == 6
        assert home.pending_count == 11 and home.pending_distance_m == Decimal(92400 + 10000)

    def test_cap_link_and_exclusions(self, garage, client):
        kind = save_maintenance(garage.owner, ServiceType, name="Revisión anual")
        for number in range(6):
            item = create_inventory(garage.owner, Item, name=f"Vencido {number}", category=garage.helmet.category)
            save_maintenance(garage.owner, MaintenanceRule, item=item, service_type=kind, calendar_days=1, anchor_at=at(30))
        retired = create_inventory(garage.owner, Item, name="Retirado", category=garage.helmet.category, retired_at=at(1))
        save_maintenance(garage.owner, MaintenanceRule, item=retired, service_type=kind, calendar_days=1, anchor_at=at(30))
        future = create_inventory(garage.owner, Item, name="Se retira mañana", category=garage.helmet.category, retired_at=NOW + timedelta(days=1))
        create_manual_ride(garage.owner, name="Sin inicio", distance_m=Decimal(1), started_at=at(1))
        client.force_login(garage.owner)
        home = home_snapshot(garage.owner, at=NOW)
        assert "Retirado" not in {alert.target.name for alert in home.attention} and home.attention_hidden == 2
        assert future.pk in {entry.item.pk for entry in home.gear}
        html = client.get(reverse("garage:index")).content.decode()
        assert "Ver 2 más en Taller" in html and "Retirado" not in html

    def test_unknown_start_is_not_pending(self, garage):
        from .services.rides import import_fit_session, withdraw_source
        ride, source = import_fit_session(garage.owner, file_hash="e" * 64, session_index=0, parser_version="synthetic",
                                          observations={"started_at": at(2), "sport_type": "cycling"})
        withdraw_source(garage.owner, source.pk)
        assert home_snapshot(garage.owner, at=NOW).pending_count == 1

    def test_estimated_due_caption(self):
        headline = wear(due(metric(status="due", value="3100000", estimated=True))).headline
        assert headline.big_caption == "km de más (estimado)" and headline.percent_text == "≈ 103 %"
        partial = wear(due(metric(status="due", value="3100000"))).headline
        assert partial.big_caption == "km de más como mín." and partial.percent_text == "≥ 103 %"
        assert wear(due(metric(value="2999400"))).headline.remaining_text == "0,6"
        assert wear(due(metric(value="2899600"))).headline.remaining_text == "101"

    def test_empty_owner(self, db, client):
        owner = get_user_model().objects.create_user("empty-home", password="test-only-password")
        home = home_snapshot(owner, at=NOW)
        assert (home.attention, home.bikes, home.gear, home.pending_count, home.rules) == ((), (), (), 0, 0)
        client.force_login(owner)
        html = client.get(reverse("garage:index")).content.decode()
        assert "Aún no hay reglas de mantenimiento" in html and "Aún no tienes bicis" in html and "90 %" in html
