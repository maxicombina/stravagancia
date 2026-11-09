"""garage-031.2: wear presentation (pure) and the mobile home screen."""
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from .models import Bike, Category, Item, MaintenanceRule, Ride, ServiceType, UsageMaterializationState
from .presentation import SEVERITY, STATES, by_severity, number, quantity, ring, wear
from .services.home import home_snapshot
from .services.installations import create_installation
from .services.maintenance import save_maintenance
from .services.maintenance_due import MaintenanceDue, MaintenanceMetric, maintenance_due
from .services.ownership import create_inventory
from .services.rides import create_manual_ride
from .services.snoozes import snooze_rule
from .services.usage import rebuild_usage
from .services.usage_profiles import create_profile_history
from .test_html import accessible_text, find_all, parse, row_by_href, visible_text

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


def days_ago(days):
    """Against the real clock, as the page reads it: `at()` is fixed, so a calendar rule built on it would change state as days go by."""
    return timezone.now() - timedelta(days=days)


def on_bike(g, bike, state, name="Regla"):
    """A rule of `bike` in `state`, by what the domain computes from it. Gravel has one ride: 50 km, 20 days before NOW."""
    amounts = {"due": dict(calendar_days=10, anchor_at=days_ago(30)),
               "soon": dict(calendar_days=100, anchor_at=days_ago(95)),
               "review": dict(distance_m=Decimal(52000), anchor_at=at(30)),
               "current": dict(calendar_days=1000, anchor_at=days_ago(1)),
               "nodata": dict(calendar_days=1000)}[state]
    rule = save_maintenance(g.owner, MaintenanceRule, bike=bike, service_type=save_maintenance(g.owner, ServiceType, name=f"{name} {state}"), **amounts)
    rebuild_usage(g.owner)
    built = wear(next(entry for entry in maintenance_due(g.owner) if entry.rule.pk == rule.pk))
    assert built.state == state, (built.state, state)  # Otherwise the test would not be about what it says.
    return rule


class TestBikeWorst:
    """Spec D17: `worst` is the gravest state among what needs attention on a bike; what `alerts` counts, nothing else."""

    def entry(self, g, bike):
        return next(entry for entry in home_snapshot(g.owner).bikes if entry.bike == bike)

    def test_due_and_soon_is_due(self, garage):
        on_bike(garage, garage.gravel, "soon")
        on_bike(garage, garage.gravel, "due")
        entry = self.entry(garage, garage.gravel)
        assert (entry.worst, entry.alerts) == ("due", 2)

    def test_only_soon_is_soon(self, garage):
        on_bike(garage, garage.gravel, "soon")
        assert self.entry(garage, garage.gravel).worst == "soon"

    def test_review_and_soon_is_review(self, garage):
        on_bike(garage, garage.gravel, "soon")
        on_bike(garage, garage.gravel, "review")
        assert self.entry(garage, garage.gravel).worst == "review"

    def test_no_alerts_is_none(self, garage):
        entry = self.entry(garage, garage.gravel)
        assert (entry.worst, entry.alerts) == (None, 0)

    def test_a_snoozed_rule_does_not_count_even_if_it_is_due(self, garage):
        snooze_rule(garage.owner, on_bike(garage, garage.gravel, "due"), calendar_days=3)
        entry = self.entry(garage, garage.gravel)
        assert (entry.worst, entry.alerts) == (None, 0)
        on_bike(garage, garage.gravel, "soon")
        entry = self.entry(garage, garage.gravel)
        assert (entry.worst, entry.alerts) == ("soon", 1)

    def test_no_data_and_calm_rules_do_not_count(self, garage):
        on_bike(garage, garage.gravel, "nodata")
        on_bike(garage, garage.gravel, "current")
        entry = self.entry(garage, garage.gravel)
        assert (entry.worst, entry.alerts) == (None, 0)

    def test_a_bike_past_the_cap_of_the_attention_list_keeps_it(self, garage):
        for number in range(7):
            on_bike(garage, garage.road, "due", name=f"Regla {number}")
        on_bike(garage, garage.gravel, "soon")
        home = home_snapshot(garage.owner)
        assert garage.gravel not in {alert.target for alert in home.attention}
        assert {entry.bike: entry.worst for entry in home.bikes} == {garage.road: "due", garage.gravel: "soon"}

    def test_each_bike_has_its_own_and_a_piece_on_no_bike_counts_for_none(self, garage):
        # The cleats are due, inside shoes mounted on no bike.
        home = home_snapshot(garage.owner)
        assert "due" in {alert.wear.state for alert in home.attention}
        assert {entry.bike: entry.worst for entry in home.bikes} == {garage.road: "review", garage.gravel: None}

    def test_a_piece_inside_a_mounted_piece_counts_for_the_bike(self, garage):
        create_installation(garage.owner, item=garage.shoes, bike=garage.gravel, parent_item=None, started_at=at(1), ended_at=None, slot=None)
        assert self.entry(garage, garage.gravel).worst == "due"


def classes(node):
    return node.attrs.get("class", "").split()


class TestGarageScreen:
    """Spec F3a: the sections in cards and, on each bike, the badge of D17."""

    def html(self, g, client):
        client.force_login(g.owner)
        response = client.get(reverse("garage:index"))
        assert response.status_code == 200
        return response.content.decode()

    def row(self, html, bike):
        """Its row in «Bicis»: a rule of the bike also links to it, from «Requiere atención»."""
        section = find_all(parse(html), "section", aria_labelledby="bikes-title")[0]
        rows = find_all(section, "a", cls="entry", href=reverse("garage:bike-detail", args=[bike.pk]))
        assert len(rows) == 1, rows
        return rows[0]

    def badge(self, html, bike):
        chips = find_all(self.row(html, bike), "span", cls="chip")
        assert len(chips) == 1, chips
        return chips[0]

    def test_the_badge_counts_with_the_icon_of_the_gravest(self, garage, client):
        on_bike(garage, garage.gravel, "soon")
        on_bike(garage, garage.gravel, "due")
        badge = self.badge(self.html(garage, client), garage.gravel)
        assert visible_text(badge) == "2 avisos" and "st-due" in classes(badge)
        assert [use.attrs["href"] for use in find_all(badge, "use")] == ["#i-octagon"]
        assert len(find_all(badge, "svg", aria_hidden="true")) == 1

    def test_the_gravest_is_heard_and_not_seen(self, garage, client):
        on_bike(garage, garage.gravel, "soon")
        on_bike(garage, garage.gravel, "due")
        html = self.html(garage, client)
        assert accessible_text(self.badge(html, garage.gravel)) == "2 avisos, el más grave: Vencido"
        assert "el más grave" not in visible_text(self.row(html, garage.gravel))

    @pytest.mark.parametrize("gravest,others", [("soon", "soon"), ("review", "soon")])
    def test_the_badge_takes_icon_and_word_from_states(self, garage, client, gravest, others):
        on_bike(garage, garage.gravel, others)
        on_bike(garage, garage.gravel, gravest, name="Otra")
        badge = self.badge(self.html(garage, client), garage.gravel)
        word, icon = STATES[gravest]
        assert f"st-{gravest}" in classes(badge) and [use.attrs["href"] for use in find_all(badge, "use")] == [f"#i-{icon}"]
        assert accessible_text(badge) == f"2 avisos, el más grave: {word}"

    def test_one_alert_has_nothing_to_be_the_gravest_of(self, garage, client):
        on_bike(garage, garage.gravel, "due")
        badge = self.badge(self.html(garage, client), garage.gravel)
        assert visible_text(badge) == "1 aviso" and accessible_text(badge) == "1 aviso: Vencido"

    def test_no_alerts_is_a_neutral_chip(self, garage, client):
        row = self.row(self.html(garage, client), garage.gravel)
        badge = find_all(row, "span", cls="chip")[0]
        assert visible_text(badge) == accessible_text(badge) == "Sin avisos"
        assert not [name for element in [row, badge] + find_all(row) for name in classes(element) if name.startswith("st-")]

    def test_the_alerts_leave_the_second_line(self, garage, client):
        on_bike(garage, garage.gravel, "due")
        on_bike(garage, garage.gravel, "soon")
        row = self.row(self.html(garage, client), garage.gravel)
        figures = visible_text(find_all(row, cls="entry-sub")[0])
        assert figures.endswith(" h") and "aviso" not in figures, figures
        assert visible_text(row).count("aviso") == 1, "said once, in the badge"

    def test_the_bike_row_keeps_its_tile_name_and_kilometres(self, garage, client):
        row = self.row(self.html(garage, client), garage.gravel)
        tile = find_all(row, cls="glyph")
        assert len(tile) == 1 and [use.attrs["href"] for use in find_all(tile[0], "use")] == ["#i-bike"]
        assert visible_text(find_all(row, cls="entry-name")[0]) == "Gravel"
        assert visible_text(find_all(row, cls="big")[0]) == "50km registrados"

    def test_the_name_of_a_bike_is_written_as_a_title(self, garage, client):
        names = find_all(self.row(self.html(garage, client), garage.gravel), cls="entry-name")
        assert len(names) == 1 and "bike-name" in classes(names[0])

    def test_every_row_of_the_attention_card_has_its_name_in_the_same_column(self, garage, client):
        # «compact» is 48 px against the 52 of a row with a ring: in one card, the names of «1 regla sin datos» and «1 aviso pospuesto» stood 4 px further left.
        snooze_rule(garage.owner, on_bike(garage, garage.gravel, "due"), calendar_days=30)
        on_bike(garage, garage.gravel, "soon", name="Otra")
        section = find_all(parse(self.html(garage, client)), "section", aria_labelledby="attention-title")[0]
        rows = find_all(section, "a", cls="entry")
        hrefs = [row.attrs["href"] for row in rows]
        assert reverse("garage:maintenance") in hrefs and f'{reverse("garage:maintenance")}#snoozed' in hrefs, hrefs  # Otherwise the test would not be about them.
        assert [row.attrs["href"] for row in rows if "compact" in classes(row)] == []

    def test_the_three_sections_are_cards_with_the_same_titles(self, garage, client):
        cards = find_all(parse(self.html(garage, client)), "section", cls="sec card")
        assert [visible_text(find_all(card, "h2")[0]) for card in cards] == ["Requiere atención", "Bicis", "Equipación y material sin montar"]
        for card in cards:
            assert find_all(card, "h2")[0].attrs["id"] == card.attrs["aria-labelledby"]

    def test_the_headings_are_read_in_the_same_order_as_before(self, garage, client):
        """Spec F4b: the columns are only wrappers."""
        headings = [(heading.tag, visible_text(heading)) for heading in find_all(find_all(parse(self.html(garage, client)), "main")[0]) if heading.tag in ("h1", "h2")]
        assert headings == [("h1", "Garaje"), ("h2", "Requiere atención"), ("h2", "Bicis"), ("h2", "Equipación y material sin montar")]

    def test_the_columns_take_the_three_sections_and_nothing_else(self, garage, client):
        main = find_all(parse(self.html(garage, client)), "main")[0]
        elements = [child for child in main.children if not isinstance(child, str)]
        columns = [element for element in elements if "cols" in classes(element)]
        assert len(columns) == 1, columns
        assert [child.tag for child in columns[0].children if not isinstance(child, str)] == ["section"] * 3
        assert [visible_text(find_all(section, "h2")[0]) for section in find_all(columns[0], "section", cls="sec card")] == ["Requiere atención", "Bicis", "Equipación y material sin montar"]
        # The title and the notice to install stay above them, across the page.
        assert [element.tag for element in elements[:3]] == ["h1", "aside", "div"] and elements[2] is columns[0]

    def test_the_rides_to_review_keep_their_circle(self, garage, client):
        href = f'{reverse("garage:ride-review", args=[garage.pending.pk])}?next=/garage/'
        row = row_by_href(self.html(garage, client), href)
        circles = find_all(row, cls="ring-ic")
        assert "st-review" in classes(row) and len(circles) == 1
        assert [use.attrs["href"] for use in find_all(circles[0], "use")] == ["#i-route"]
