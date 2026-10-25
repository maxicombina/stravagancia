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
from .services.installations import create_installation
from .services.maintenance import save_maintenance
from .services.monthly import MonthBucket, monthly_usage
from .services.ownership import InventoryNotFound, InventoryWriteError, create_inventory
from .services.rides import create_manual_ride
from .services.usage import rebuild_usage

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
        events = [html.index(text) for text in ("Segunda cadena", "Lubricación</span><span class=\"entry-sub\">1 feb 2026", "Compra y montaje")]
        assert events == sorted(events)  # newest first, across service types
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
        assert "En Carretera desde el" in html and "→ 1 ene 2030" in html
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
