"""garage-031.3: monthly usage, line chart and the component screen."""
import re
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .charts import line_chart
from .models import Bike, Category, Item, MaintenanceRule, ServiceEvent, ServiceType, UsageMaterializationState
from .services.baselines import record_baseline
from .services.installations import create_installation
from .services.maintenance import save_maintenance
from .services.monthly import MonthBucket, monthly_usage
from .services.ownership import InventoryNotFound, InventoryWriteError, create_inventory
from .services.rides import create_manual_ride
from .services.usage import rebuild_usage
from .test_html import find_all, parse, visible_text

UTC = dt_timezone.utc
MADRID = ZoneInfo("Europe/Madrid")
BUENOS_AIRES = ZoneInfo("America/Argentina/Buenos_Aires")
AT = datetime(2026, 11, 15, 12, tzinfo=UTC)


@pytest.fixture
def garage(db):
    users = get_user_model().objects
    owner = users.create_user("item-owner", password="test-only-password")
    other = users.create_user("item-other", password="test-only-password")
    category = create_inventory(owner, Category, name="Cadenas")
    road = create_inventory(owner, Bike, name="Carretera")
    gravel = create_inventory(owner, Bike, name="Gravel")
    chain = create_inventory(owner, Item, name="Cadena 11v", category=category)
    create_installation(owner, item=chain, bike=gravel, parent_item=None, started_at=datetime(2026, 1, 1, tzinfo=UTC),
                        ended_at=datetime(2026, 6, 1, tzinfo=UTC), slot="chain")
    create_installation(owner, item=chain, bike=road, parent_item=None, started_at=datetime(2026, 6, 1, tzinfo=UTC), ended_at=None, slot="chain")

    def ride(when, bike, km, **values):
        return create_manual_ride(owner, started_at=when, bike=bike, name="Salida", distance_m=None if km is None else Decimal(km) * 1000,
                                  moving_time_s=Decimal(3600), **values)
    # 22:30 UTC on 31 March is 00:30 on 1 April in Madrid (CEST) but still March in Buenos Aires.
    ride(datetime(2026, 3, 31, 22, 30, tzinfo=UTC), gravel, 10)
    ride(datetime(2026, 3, 15, 10, tzinfo=UTC), gravel, 20)
    # 23:30 UTC on 31 October is 00:30 on 1 November in Madrid (CET, after the DST change).
    ride(datetime(2026, 10, 31, 23, 30, tzinfo=UTC), road, 30)
    ride(datetime(2026, 7, 10, 8, tzinfo=UTC), road, None)
    ride(datetime(2026, 11, 14, 8, tzinfo=UTC), road, 5)
    ride(datetime(2026, 11, 20, 8, tzinfo=UTC), road, 99)  # after AT: never counted
    kind = save_maintenance(owner, ServiceType, name="Cambio de cadena")
    save_maintenance(owner, ServiceEvent, item=chain, service_type=kind, performed_at=datetime(2026, 1, 1, tzinfo=UTC),
                     amount=Decimal("32.9"), currency="EUR", notes="Compra y montaje")
    save_maintenance(owner, MaintenanceRule, item=chain, service_type=kind, distance_m=Decimal(60000), calendar_days=365)
    foreign = create_inventory(other, Item, name="SECRET", category=create_inventory(other, Category, name="X"))
    rebuild_usage(owner)
    return SimpleNamespace(owner=owner, other=other, chain=chain, road=road, gravel=gravel, foreign=foreign, kind=kind)


def values(series):
    return {bucket.label + str(bucket.start.year): bucket.value for bucket in series.buckets}


class TestMonthly:
    def test_local_month_bounds_madrid(self, garage):
        series = monthly_usage(garage.owner, item=garage.chain, tz=MADRID, months=12, at=AT)
        assert series.trusted and len(series.buckets) == 12
        # Instants, not wall clocks: local midnights converted to UTC (CET in winter, CEST in April).
        assert series.buckets[0].start == datetime(2025, 11, 30, 23, tzinfo=UTC)
        assert series.buckets[4].start == datetime(2026, 3, 31, 22, tzinfo=UTC) and series.buckets[4].label == "abr"
        assert series.buckets[-1].partial and not any(b.partial for b in series.buckets[:-1])
        by_month = values(series)
        assert by_month["mar2026"] == Decimal(20000) and by_month["abr2026"] == Decimal(10000)
        assert by_month["oct2026"] == 0 and by_month["nov2026"] == Decimal(35000)
        assert by_month["jul2026"] is None  # every row of the month lacks distance
        assert by_month["ago2026"] == 0

    def test_local_month_bounds_buenos_aires(self, garage):
        by_month = values(monthly_usage(garage.owner, item=garage.chain, tz=BUENOS_AIRES, at=AT))
        assert by_month["mar2026"] == Decimal(30000) and by_month["abr2026"] == 0
        assert by_month["oct2026"] == Decimal(30000) and by_month["nov2026"] == Decimal(5000)

    def test_bike_mode_and_other_metrics(self, garage):
        series = monthly_usage(garage.owner, bike=garage.road, metric="ride_count", tz=MADRID, at=AT)
        assert values(series)["nov2026"] == 2 and values(series)["jul2026"] == 1
        hours = monthly_usage(garage.owner, bike=garage.gravel, metric="moving_time_s", tz="Europe/Madrid", at=AT)
        assert values(hours)["mar2026"] == Decimal(3600) and values(hours)["abr2026"] == Decimal(3600)

    def test_untrusted_materialization(self, garage):
        UsageMaterializationState.objects.filter(owner=garage.owner).update(initialized_at=None)
        series = monthly_usage(garage.owner, item=garage.chain, tz=MADRID, at=AT)
        assert not series.trusted and all(bucket.value is None for bucket in series.buckets)
        assert values(monthly_usage(garage.owner, bike=garage.road, tz=MADRID, at=AT))["nov2026"] == Decimal(35000)

    def test_validation_and_ownership(self, garage):
        for kwargs in ({}, {"item": garage.chain, "bike": garage.road}, {"item": garage.chain, "metric": "calendar_days"},
                       {"item": garage.chain, "months": 0}, {"item": garage.chain, "months": 61}, {"item": garage.chain, "months": True}):
            with pytest.raises(InventoryWriteError):
                monthly_usage(garage.owner, tz=MADRID, at=AT, **kwargs)
        with pytest.raises(InventoryNotFound):
            monthly_usage(garage.owner, item=garage.foreign, tz=MADRID, at=AT)
        with pytest.raises(InventoryNotFound):
            monthly_usage(garage.other, item=garage.chain, tz=MADRID, at=AT)

    def test_query_budget(self, garage):
        with CaptureQueriesContext(connection) as queries:
            monthly_usage(garage.owner, item=garage.chain, tz=MADRID, at=AT)
        assert len(queries) <= 8, len(queries)  # savepoint, owner lock, target, state, rows, release


def bucket(label, value, partial=False):
    return MonthBucket(None, None, label, label + " 2026", None if value is None else Decimal(value), 0, partial)


class TestChart:
    def test_scale_ticks_and_labels(self):
        chart = line_chart([bucket("mar", 180000), bucket("abr", 414000), bucket("may", None), bucket("jun", 300000),
                            bucket("jul", 130000, partial=True)])
        assert [text for _, _, text in chart.ticks] == ["0", "200", "400", "600"]
        assert chart.ticks[0][0] == "140.00" and not chart.empty
        assert len(chart.solid) == 2  # the missing month breaks the line
        assert chart.dashed is not None and chart.dashed[0] == chart.points[3].x
        assert [text for _, _, text in chart.value_labels] == ["414", "130"]
        assert chart.points[2].y is None and chart.points[2].tip == "may 2026: sin datos"
        assert chart.points[4].tip == "jul 2026 (en curso): 130 km"
        assert "Máximo en abr 2026 con 414 km" in chart.summary

    def test_small_values_keep_their_ticks(self):
        chart = line_chart([bucket("a", 400), bucket("b", 1000, partial=True)])
        assert [text for _, _, text in chart.ticks] == ["0", "0,25", "0,5", "0,75", "1"]

    def test_isolated_month_gets_a_dot(self):
        chart = line_chart([bucket("a", 1000), bucket("b", None), bucket("c", 3000), bucket("d", None), bucket("e", 2000, partial=True)])
        assert [p.label for p in chart.dots] == ["a", "c"] and chart.dashed is None

    def test_empty(self):
        chart = line_chart([bucket("a", 0), bucket("b", None, partial=True)])
        assert chart.empty and chart.ticks == () and chart.value_labels == ()

    def test_coordinates_are_locale_independent(self):
        chart = line_chart([bucket("a", 1234), bucket("b", 5678, partial=True)])
        assert all(re.fullmatch(r"\d+\.\d{2}", p.x) for p in chart.points)


class TestSectionsInCards:
    """Spec §4.3, the #pieza-fox38 of the mockup and the screen of a bike: the same sections, in the same order, in cards."""

    TITLES = ["Uso registrado en Garage", "Km por mes", "Montajes", "Piezas", "Intervenciones", "Fotos privadas", "Más acciones"]  # garage-047 F14

    def root(self, garage, client):
        client.force_login(garage.owner)
        return parse(client.get(reverse("garage:item-detail", args=[garage.chain.pk])).content.decode())

    def test_each_section_is_a_card(self, garage, client):
        sections = find_all(self.root(garage, client), "section", aria_labelledby=True)
        assert [visible_text(find_all(section, "h2")[0]) for section in sections] == self.TITLES
        for section in sections:
            assert {"card", "panel"} & set(section.attrs["class"].split()), section.attrs["class"]

    def test_no_card_holds_another(self, garage, client):
        root = self.root(garage, client)
        for surface in find_all(root, cls="card") + find_all(root, cls="panel"):
            assert not find_all(surface, cls="card") and not find_all(surface, cls="panel"), surface.attrs

    def test_the_cost_per_km_is_a_group_of_the_card_of_interventions(self, garage, client):
        section = find_all(self.root(garage, client), "section", aria_labelledby="events-title")[0]
        assert [heading.attrs.get("class") for heading in find_all(section, "h3") if visible_text(heading) == "Coste por km"] == ["sub-h"]

    def test_the_action_bar_stays_outside_of_them(self, garage, client):
        """Sticky, it only stays in view within its parent: inside a card it would scroll away with it."""
        main = find_all(self.root(garage, client), "main")[0]
        assert [child for child in main.children if not isinstance(child, str) and "actionbar" in child.attrs.get("class", "").split()]


class TestComponentScreen:
    def test_page(self, garage, client):
        from unittest.mock import patch
        lub = save_maintenance(garage.owner, ServiceType, name="Lubricación")
        save_maintenance(garage.owner, ServiceEvent, item=garage.chain, service_type=lub, performed_at=datetime(2026, 2, 1, tzinfo=UTC))
        save_maintenance(garage.owner, ServiceEvent, item=garage.chain, service_type=garage.kind, performed_at=datetime(2026, 9, 1, tzinfo=UTC),
                         notes="Segunda cadena")
        save_maintenance(garage.owner, MaintenanceRule, item=garage.chain, service_type=lub, distance_m=Decimal(1000000))
        url = reverse("garage:item-detail", args=[garage.chain.pk])
        with patch("django.utils.timezone.now", return_value=AT):
            client.force_login(garage.owner)
            with CaptureQueriesContext(connection) as queries:
                response = client.get(url)
        html = response.content.decode()
        assert response.status_code == 200
        assert not any(q["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"} for q in queries)
        # garage-035: one query for the parts and the bike above; garage-042: one for the state line of a mounted item.
        assert len(queries) <= 47, len(queries)
        for text in ("Cadena 11v", "En Carretera desde el", "Cambio de cadena", "km como máx.", "Uso registrado en Garage",
                     "Km por mes", 'data-chart', "Montajes", "Gravel", "Intervenciones", "32,90 EUR", "Compra y montaje",
                     "Coste por km", "Historial completo de montajes", "Material montado sobre este objeto", "Fotos privadas",
                     f'href="{reverse("garage:service-event-create")}?item={garage.chain.pk}"', 'class="actionbar"'):
            assert text in html, text
        assert "SECRET" not in html and "<script>" not in html and ' style="' not in html
        # Observed in Garage up to AT: 20 + 10 (Gravel, March) + 30 + 5 (Carretera); July has no distance.
        assert '<b>65</b><span>km</span>' in html.replace("\n", "").replace("      ", "")
        # Wear cards: the most severe first (35 km since 1 Sep of 60 is not urgent; lubrication of 1000 km neither).
        section = find_all(parse(html), "section", aria_labelledby="events-title")[0]
        events = [(visible_text(find_all(row, cls="entry-name")[0]), visible_text(find_all(row, cls="entry-sub")[0]))
                  for row in find_all(section, cls="entry")]
        assert [name for name, _ in events] == ["Cambio de cadena", "Lubricación", "Cambio de cadena"]  # newest first, across service types
        assert "Segunda cadena" in events[0][1] and events[1][1].startswith("1 feb 2026") and "Compra y montaje" in events[2][1]
        first = len(queries)
        for number in range(4):  # more rules and interventions: same number of queries
            kind = save_maintenance(garage.owner, ServiceType, name=f"Tipo {number}")
            save_maintenance(garage.owner, ServiceEvent, item=garage.chain, service_type=kind, performed_at=datetime(2026, 5, 1, tzinfo=UTC))
            save_maintenance(garage.owner, MaintenanceRule, item=garage.chain, service_type=kind, calendar_days=30)
        with patch("django.utils.timezone.now", return_value=AT):
            with CaptureQueriesContext(connection) as queries:
                client.get(url)
        assert len(queries) == first

    def test_mount_actions_and_future_end(self, garage, client):
        from .models import Installation
        client.force_login(garage.owner)
        url = reverse("garage:item-detail", args=[garage.chain.pk])
        html = client.get(url).content.decode()
        assert ">Mover</a>" in html and f'href="{reverse("garage:installation-create", args=[garage.chain.pk])}">Montar</a>' not in html
        open_mount = Installation.objects.get(item=garage.chain, ended_at__isnull=True)
        Installation.objects.filter(pk=open_mount.pk).update(ended_at=datetime(2030, 1, 1, tzinfo=UTC))
        html = client.get(url).content.decode()
        timeline = visible_text(find_all(parse(html), "section", aria_labelledby="mounts-title")[0])
        assert "En Carretera desde el" in html and "→ 1 ene 2030, 1:00" in timeline  # garage-047 F15: not a local midnight in Madrid
        loose = create_inventory(garage.owner, Item, name="Suelta", category=garage.chain.category)
        html = client.get(reverse("garage:item-detail", args=[loose.pk])).content.decode()
        assert ">Mover</a>" not in html and f'href="{reverse("garage:installation-create", args=[loose.pk])}">Montar</a>' in html
        assert 'role="group"' in client.get(url).content.decode()

    def test_statistics_item_filter_gives_the_same_row(self, garage):
        from .services.statistics import statistics
        create_inventory(garage.owner, Item, name="Otra", category=garage.chain.category)
        whole = {row.target.pk: row for row in statistics(garage.owner, started_to=AT).rows if row.kind == "item"}
        only = statistics(garage.owner, item=garage.chain, started_to=AT).rows[0]
        assert only == whole[garage.chain.pk]

    def test_untrusted_usage_and_mount_headers(self, garage, client):
        shoes = create_inventory(garage.owner, Item, name="Zapatillas", category=garage.chain.category)
        cleats = create_inventory(garage.owner, Item, name="Calas", category=garage.chain.category)
        create_installation(garage.owner, item=cleats, bike=None, parent_item=shoes, started_at=datetime(2026, 1, 1, tzinfo=UTC), ended_at=None, slot=None)
        UsageMaterializationState.objects.filter(owner=garage.owner).update(initialized_at=None)
        client.force_login(garage.owner)
        html = client.get(reverse("garage:item-detail", args=[cleats.pk])).content.decode()
        assert "Sobre Zapatillas desde el 1 ene 2026" in html and "Uso pendiente de calcular" in html  # garage-042: as in Material

    def test_foreign_item_is_404(self, garage, client):
        # Since garage-032.2 the bike has its own mobile screen (tests_mobile_bike.py).
        client.force_login(garage.owner)
        assert client.get(reverse("garage:item-detail", args=[garage.foreign.pk])).status_code == 404

    def test_the_link_to_another_rule_has_room_for_a_finger(self, garage, client):
        client.force_login(garage.owner)
        html = client.get(reverse("garage:item-detail", args=[garage.chain.pk])).content.decode()
        links = [a for a in find_all(parse(html), "a", cls="link solo") if visible_text(a) == "Crear otra regla"]
        assert len(links) == 1

    def test_correcting_a_reading_has_room_for_a_finger(self, garage, client):
        # It measured 19 px, 2 px under the block before it. As a plain link right in an `.actions` row it gets the 44 px of
        # `.page .actions > a:not([class])`; as a block of the card, its 12 px.
        reading = record_baseline(garage.owner, item=garage.chain, metric="distance_m", scope="lifetime", cut_at=datetime(2026, 1, 1, tzinfo=UTC), value=Decimal("1000000"))
        client.force_login(garage.owner)
        page = parse(client.get(reverse("garage:item-detail", args=[garage.chain.pk])).content.decode())
        cards = [card for card in find_all(page, "article", cls="card") if "Corregir lectura" in visible_text(card)]
        assert len(cards) == 1
        rows = [child for child in cards[0].children if not isinstance(child, str) and "actions" in child.attrs.get("class", "").split()]
        assert len(rows) == 1
        links = [child for child in rows[0].children if not isinstance(child, str)]
        assert [(link.tag, link.attrs) for link in links] == [("a", {"href": reverse("garage:baseline-edit", args=[reading.pk])})]
        assert visible_text(links[0]) == "Corregir lectura"

    def test_without_rules_offers_one(self, garage, client):
        loose = create_inventory(garage.owner, Item, name="Luz", category=garage.chain.category)
        client.force_login(garage.owner)
        html = client.get(reverse("garage:item-detail", args=[loose.pk])).content.decode()
        assert f'{reverse("garage:maintenance-rule-create")}?item={loose.pk}' in html and "Nunca montado." in html

    @pytest.mark.parametrize("route", ["service-event-create", "maintenance-rule-create"])
    def test_prefill_only_own_item(self, garage, client, route):
        client.force_login(garage.owner)
        html = client.get(reverse("garage:" + route) + f"?item={garage.chain.pk}").content.decode()
        assert re.search(rf'<option value="{garage.chain.pk}" selected>', html)
        assert reverse("garage:item-detail", args=[garage.chain.pk]) in html
        assert client.get(reverse("garage:" + route) + f"?item={garage.foreign.pk}").status_code == 404
        assert client.get(reverse("garage:" + route) + "?item=not-a-uuid").status_code == 404
        assert client.get(reverse("garage:" + route)).status_code == 200


class TestReadings:
    """garage-047 F05 (D15): a usage reading on the item page reads in Spanish, with its figure in km, hours or rides."""

    def cards(self, garage, client, **reading):
        values = {"metric": "moving_time_s", "scope": "lifetime", "cut_at": datetime(2026, 1, 1, tzinfo=UTC), "value": Decimal("298800"),
                  "source": "manual", **reading}
        record_baseline(garage.owner, item=garage.chain, **values)
        client.force_login(garage.owner)
        client.cookies["garage_tz"] = "Europe/Madrid"
        html = client.get(reverse("garage:item-detail", args=[garage.chain.pk])).content.decode()
        cards = [card for card in find_all(parse(html), "article", cls="card") if "Corregir lectura" in visible_text(card)]
        assert len(cards) == 1
        return html, [visible_text(child) for child in cards[0].children if not isinstance(child, str) and child.tag in ("h3", "p")]

    def test_the_item_page_shows_readings_in_spanish(self, garage, client):
        html, lines = self.cards(garage, client)
        assert lines[:3] == ["Tiempo en movimiento", "83 h · Toda la vida · 1 ene 2026, 1:00", "Procedencia: Lectura manual propia"]
        for english in ("Lifetime", "Moving time", "298800.000", "(seconds)", "Procedencia: manual"):
            assert english not in html, english

    @pytest.mark.parametrize("reading,title,line", [
        ({"metric": "distance_m", "value": Decimal("0")}, "Distancia", "0 km · Toda la vida"),  # a known zero
        ({"metric": "distance_m", "value": Decimal("2840500")}, "Distancia", "2.841 km · Toda la vida"),
        ({"metric": "ride_count", "value": Decimal("12")}, "Salidas", "12 salidas · Toda la vida"),
        ({"metric": "ride_count", "value": Decimal("1")}, "Salidas", "1 salida · Toda la vida"),
        ({"metric": "ride_count", "value": Decimal("0")}, "Salidas", "0 salidas · Toda la vida"),  # a known zero, plural
        ({"is_estimated": True}, "Tiempo en movimiento", "≈ 83 h · Toda la vida"),
    ])
    def test_each_metric_has_its_unit(self, garage, client, reading, title, line):
        _, lines = self.cards(garage, client, **reading)
        assert lines[0] == title and lines[1].startswith(line + " · "), lines

    def test_an_estimated_reading_still_says_so(self, garage, client):
        _, lines = self.cards(garage, client, is_estimated=True, source="manual_garmin_reading")
        assert lines[2] == "Procedencia: Lectura manual de Garmin · Estimada"

    def test_since_acquisition(self, garage, client):
        from .services.ownership import update_inventory
        update_inventory(garage.owner, Item, garage.chain.pk, acquisition_anchor_at=datetime(2025, 12, 1, tzinfo=UTC))
        _, lines = self.cards(garage, client, scope="acquisition")
        assert " · Desde mi adquisición · " in lines[1]

    def test_since_an_intervention(self, garage, client):
        event = ServiceEvent.objects.get(item=garage.chain)
        _, lines = self.cards(garage, client, scope="service", service_event=event)
        assert " · Desde una intervención concreta · " in lines[1]

    def test_another_source_is_shown_as_it_is_escaped(self, garage, client):
        html, lines = self.cards(garage, client, source="<b>sensor</b> propio")
        assert lines[2] == "Procedencia: <b>sensor</b> propio"
        assert "&lt;b&gt;sensor&lt;/b&gt; propio" in html and "<b>sensor</b>" not in html


def element_children(node):
    return [child for child in node.children if not isinstance(child, str)]


def links_to(node, href):
    return [link for link in find_all(node, "a") if link.attrs.get("href") == href]


def inside(container, nodes):
    within = {id(node) for node in find_all(container)}
    return [node for node in nodes if id(node) in within]


class TestActionsInSight:
    """garage-047 F14 (D17): retiring, reactivating and the actions of the current mount are in sight, not folded in «Detalles»."""

    def page(self, client, item):
        response = client.get(reverse("garage:item-detail", args=[item.pk]))
        assert response.status_code == 200
        return parse(response.content.decode())

    @staticmethod
    def details(page):
        folds = find_all(page, "details", cls="more")
        assert len(folds) == 1, folds
        return folds[0]

    @staticmethod
    def card(page):
        cards = [section for section in find_all(page, "section", cls="sec card") if find_all(section, "h2")
                 and visible_text(find_all(section, "h2")[0]) == "Más acciones"]
        assert len(cards) == 1, cards
        return cards[0]

    @staticmethod
    def loose(garage, name="Suelta"):
        return create_inventory(garage.owner, Item, name=name, category=garage.chain.category)

    def test_retire_is_visible_without_opening_details(self, garage, client):
        from .services.ownership import retire_inventory
        client.force_login(garage.owner)
        loose = self.loose(garage)
        page = self.page(client, loose)
        retire = links_to(page, reverse("garage:item-retire", args=[loose.pk]))
        assert [visible_text(link) for link in retire] == ["Retirar"]
        assert inside(self.card(page), retire) == retire and not inside(self.details(page), retire)
        retire_inventory(garage.owner, Item, loose.pk, at=datetime(2026, 1, 1, tzinfo=UTC))
        page = self.page(client, loose)
        forms = [form for form in find_all(page, "form") if form.attrs.get("action") == reverse("garage:item-reactivate", args=[loose.pk])]
        assert len(forms) == 1 and forms[0].attrs.get("method") == "post"
        assert [visible_text(button) for button in find_all(forms[0], "button")] == ["Reactivar"]
        assert inside(self.card(page), forms) == forms and not inside(self.details(page), forms)
        assert not links_to(page, reverse("garage:item-retire", args=[loose.pk]))

    def test_a_retirement_still_to_come_offers_reactivating(self, garage, client):
        # The rule of garage-042 §8 does not change: with a `retired_at`, even ahead, «Reactivar».
        from django.utils import timezone
        from .services.ownership import retire_inventory
        retire_inventory(garage.owner, Item, garage.chain.pk, at=timezone.now() + timedelta(days=3))
        client.force_login(garage.owner)
        page = self.page(client, garage.chain)
        card = self.card(page)
        assert [visible_text(button) for button in find_all(card, "button")] == ["Reactivar"]
        assert not links_to(page, reverse("garage:item-retire", args=[garage.chain.pk]))

    def mount_links(self, client, item):
        page = self.page(client, item)
        return page, links_to(page, reverse("garage:installation-create", args=[item.pk]))

    def test_mount_links_by_state(self, garage, client):
        from django.utils import timezone
        from .services.ownership import retire_inventory
        client.force_login(garage.owner)
        loose = self.loose(garage)
        _, links = self.mount_links(client, loose)  # loose and active: the head of «Montajes» and the action bar
        assert [visible_text(link) for link in links] == ["Montar", "Montar"]
        page, links = self.mount_links(client, garage.chain)  # mounted
        assert [visible_text(link) for link in links] == ["Añadir un montaje pasado"] and inside(self.card(page), links) == links
        retire_inventory(garage.owner, Item, loose.pk, at=datetime(2026, 1, 1, tzinfo=UTC))
        page, links = self.mount_links(client, loose)  # retired
        assert [visible_text(link) for link in links] == ["Añadir un montaje pasado"] and inside(self.card(page), links) == links
        retire_inventory(garage.owner, Item, garage.chain.pk, at=timezone.now() + timedelta(days=3))
        _, links = self.mount_links(client, garage.chain)  # mounted, and its retirement still to come: once, not twice
        assert [visible_text(link) for link in links] == ["Añadir un montaje pasado"]

    def test_a_mount_whose_end_is_set_offers_no_unmount(self, garage, client):
        # «Desmontar» closes an open period: one whose end is already set is refused, whatever the instant (as `periods.html`
        # knows). Offered, it would only lead to that error. «Reemplazar» works inside the period, and stays.
        from .models import Installation
        current = Installation.objects.get(item=garage.chain, ended_at__isnull=True)
        end = datetime(2030, 1, 1, tzinfo=UTC)
        Installation.objects.filter(pk=current.pk).update(ended_at=end)
        client.force_login(garage.owner)
        response = client.post(reverse("garage:installation-close", args=[current.pk]), {"at": "2029-06-01T10:00", "time_zone": "UTC"})
        assert response.status_code == 200 and Installation.objects.get(pk=current.pk).ended_at == end  # refused
        card = self.card(self.page(client, garage.chain))
        assert not links_to(card, reverse("garage:installation-close", args=[current.pk]))
        assert [visible_text(link) for link in links_to(card, reverse("garage:installation-replace", args=[current.pk]))] == ["Reemplazar"]
        assert [visible_text(link) for link in find_all(card, "a")] == ["Retirar", "Reemplazar", "Añadir un montaje pasado"]

    def test_mounting_is_no_longer_folded(self, garage, client):
        client.force_login(garage.owner)
        for item in (garage.chain, self.loose(garage)):
            html = client.get(reverse("garage:item-detail", args=[item.pk])).content.decode()
            assert "Montar / remontar" not in html
            assert not links_to(self.details(parse(html)), reverse("garage:installation-create", args=[item.pk]))

    def test_a_mounted_piece_offers_unmount_and_replace_outside_details(self, garage, client):
        from .models import Installation
        client.force_login(garage.owner)
        current = Installation.objects.get(item=garage.chain, ended_at__isnull=True)
        page = self.page(client, garage.chain)
        card = self.card(page)
        for route, text in (("installation-close", "Desmontar"), ("installation-replace", "Reemplazar")):
            links = links_to(card, reverse(f"garage:{route}", args=[current.pk]))
            assert [visible_text(link) for link in links] == [text], route
        past = Installation.objects.get(item=garage.chain, ended_at__isnull=False)
        assert not links_to(card, reverse("garage:installation-close", args=[past.pk]))
        assert [visible_text(link) for link in find_all(card, "a")] == ["Retirar", "Desmontar", "Reemplazar", "Añadir un montaje pasado"]

    def test_a_piece_inside_another_unmounts_from_it(self, garage, client):
        shoes = self.loose(garage, "Zapatillas")
        cleats = self.loose(garage, "Calas")
        mount = create_installation(garage.owner, item=cleats, bike=None, parent_item=shoes, started_at=datetime(2026, 1, 1, tzinfo=UTC),
                                    ended_at=None, slot=None)
        client.force_login(garage.owner)
        card = self.card(self.page(client, cleats))
        assert [visible_text(link) for link in links_to(card, reverse("garage:installation-close", args=[mount.pk]))] == ["Desmontar"]
        assert [visible_text(link) for link in links_to(card, reverse("garage:installation-replace", args=[mount.pk]))] == ["Reemplazar"]

    def test_a_loose_piece_has_nothing_to_unmount(self, garage, client):
        client.force_login(garage.owner)
        card = self.card(self.page(client, self.loose(garage)))
        assert [visible_text(link) for link in find_all(card, "a")] == ["Retirar"]

    def test_registering_a_reading_sits_with_the_readings(self, garage, client):
        client.force_login(garage.owner)
        details = self.details(self.page(client, garage.chain))
        children = element_children(details)
        headings = [visible_text(child) if child.tag == "h2" else None for child in children]
        readings, history = headings.index("Lecturas de uso"), headings.index("Historial completo de montajes")
        rows = [index for index, child in enumerate(children) if links_to(child, reverse("garage:baseline-create", args=[garage.chain.pk]))]
        assert len(rows) == 1 and readings < rows[0] < history, (readings, rows, history)
        row = children[rows[0]]
        assert "actions" in row.attrs.get("class", "").split()
        assert [visible_text(link) for link in find_all(row, "a")] == ["Registrar lectura"]
        assert all(child.tag == "p" for child in children[readings + 1:rows[0]])  # only its explanation in between


class TestMountTimes:
    """garage-047 F15 (D18): the timeline of «Montajes» gives the time when it is not a local midnight, and the zone is named."""

    def timeline(self, client, item):
        page = parse(client.get(reverse("garage:item-detail", args=[item.pk])).content.decode())
        section = find_all(page, "section", aria_labelledby="mounts-title")[0]
        return [(visible_text(find_all(row, "b")[0]), visible_text(find_all(row, "span")[1])) for row in find_all(section, "li")]

    def test_the_timeline_shows_the_time_when_it_is_not_midnight(self, garage, client):
        wheel = create_inventory(garage.owner, Item, name="Rueda", category=garage.chain.category)
        nine = datetime(2026, 3, 10, 9, tzinfo=MADRID)  # 8:00 UTC (CET)
        midnight = datetime(2026, 4, 1, tzinfo=MADRID)  # 22:00 UTC on 31 March (CEST)
        create_installation(garage.owner, item=wheel, bike=garage.gravel, parent_item=None, started_at=nine, ended_at=midnight, slot=None)
        create_installation(garage.owner, item=wheel, bike=garage.road, parent_item=None, started_at=midnight, ended_at=None, slot=None)
        client.force_login(garage.owner)
        client.cookies["garage_tz"] = "Europe/Madrid"
        assert self.timeline(client, wheel) == [("Carretera", "1 abr 2026 → hoy"), ("Gravel", "10 mar 2026, 9:00 → 1 abr 2026")]
        client.cookies["garage_tz"] = "America/Argentina/Buenos_Aires"
        # The same instants: 5:00 there, and Madrid's midnight is 19:00 of the day before.
        assert self.timeline(client, wheel) == [("Carretera", "31 mar 2026, 19:00 → hoy"), ("Gravel", "10 mar 2026, 5:00 → 31 mar 2026, 19:00")]

    def test_a_time_keeps_the_exact_instant(self, garage, client):
        client.force_login(garage.owner)
        client.cookies["garage_tz"] = "Europe/Madrid"
        page = parse(client.get(reverse("garage:item-detail", args=[garage.chain.pk])).content.decode())
        section = find_all(page, "section", aria_labelledby="mounts-title")[0]
        # The fixture mounts at midnight UTC: 1:00 or 2:00 in Madrid, so a time, inside <time> with the instant.
        assert [time.attrs["datetime"] for time in find_all(section, "time")] == ["2026-06-01T00:00:00Z", "2026-01-01T00:00:00Z", "2026-06-01T00:00:00Z"]

    def test_the_end_still_to_come_keeps_its_time(self, garage, client):
        from .models import Installation
        Installation.objects.filter(item=garage.chain, ended_at__isnull=True).update(ended_at=datetime(2030, 1, 1, 8, 30, tzinfo=MADRID))
        client.force_login(garage.owner)
        client.cookies["garage_tz"] = "Europe/Madrid"
        assert self.timeline(client, garage.chain)[0] == ("Carretera", "1 jun 2026, 2:00 → 1 ene 2030, 8:30")

    def notes(self, client, item, zone=None):
        if zone:
            client.cookies["garage_tz"] = zone
        page = parse(client.get(reverse("garage:item-detail", args=[item.pk])).content.decode())
        section = find_all(page, "section", aria_labelledby="mounts-title")[0]
        details = find_all(page, "details", cls="more")[0]
        children = element_children(details)
        history = next(index for index, child in enumerate(children) if child.tag == "h2" and visible_text(child) == "Historial completo de montajes")
        after = children[history + 1] if history + 1 < len(children) else None
        return ([visible_text(note) for note in find_all(section, "p", cls="note")],
                visible_text(after) if after is not None and after.tag == "p" else None)

    def test_the_zone_of_the_times_is_named(self, garage, client):
        client.force_login(garage.owner)
        assert self.notes(client, garage.chain, "Europe/Madrid") == (["Horas en la zona Europe/Madrid."], "Horas en la zona Europe/Madrid.")
        assert self.notes(client, garage.chain, "America/Argentina/Buenos_Aires") == (
            ["Horas en la zona America/Argentina/Buenos_Aires."], "Horas en la zona America/Argentina/Buenos_Aires.")

    def test_an_unknown_zone_names_the_one_used(self, garage, client):
        client.force_login(garage.owner)
        assert self.notes(client, garage.chain, "Mars/Base") == (["Horas en la zona Europe/Madrid."], "Horas en la zona Europe/Madrid.")

    def test_never_mounted_names_no_zone(self, garage, client):
        loose = create_inventory(garage.owner, Item, name="Luz", category=garage.chain.category)
        client.force_login(garage.owner)
        notes, after = self.notes(client, loose, "Europe/Madrid")
        assert notes == [] and after != "Horas en la zona Europe/Madrid."
        assert "Horas en la zona" not in client.get(reverse("garage:item-detail", args=[loose.pk])).content.decode()
