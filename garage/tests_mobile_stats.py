"""garage-032.3: statistics by period, monthly chart of every ride, split by bike and gear, spending."""
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .models import Item, ServiceEvent, ServiceType
from .services.maintenance import save_maintenance
from .services.monthly import monthly_usage
from .services.ownership import InventoryWriteError, create_inventory
from .services.rides import create_manual_ride
from .services.statistics import statistics
from .statistics_views import period_bounds
from .tests_mobile_home import NOW, at, garage  # noqa: F401 (fixture)

UTC = dt_timezone.utc
MADRID = ZoneInfo("Europe/Madrid")
BUENOS_AIRES = ZoneInfo("America/Argentina/Buenos_Aires")
WRITES = {"INSERT", "UPDATE", "DELETE"}


class TestPeriods:
    def test_bounds_in_the_viewer_zone(self):
        now = datetime(2026, 10, 16, 23, 30, tzinfo=UTC)  # already 17 oct in Madrid, still 16 oct in Buenos Aires
        assert period_bounds("12m", MADRID, now) == (datetime(2025, 11, 1, tzinfo=MADRID), now, (2026, 10), 12)
        assert period_bounds("year", BUENOS_AIRES, now) == (datetime(2026, 1, 1, tzinfo=BUENOS_AIRES), now, (2026, 10), 10)
        assert period_bounds("last", MADRID, now) == (datetime(2025, 1, 1, tzinfo=MADRID), datetime(2026, 1, 1, tzinfo=MADRID), (2025, 12), 12)
        assert period_bounds("all", MADRID, now) == (None, now, (2026, 10), 12)

    def test_year_boundary_is_local(self):
        now = datetime(2026, 12, 31, 23, 30, tzinfo=UTC)  # 1 Jan 2027 in Madrid
        assert period_bounds("12m", MADRID, now)[0] == datetime(2026, 2, 1, tzinfo=MADRID)
        assert period_bounds("year", MADRID, now)[:1] == (datetime(2027, 1, 1, tzinfo=MADRID),)
        assert period_bounds("year", BUENOS_AIRES, now)[0] == datetime(2026, 1, 1, tzinfo=BUENOS_AIRES)


class TestMonthlyAllRides:
    def test_every_ride_with_or_without_bike(self, garage):
        series = monthly_usage(garage.owner, all_rides=True, tz=MADRID, at=NOW)
        assert sum(b.value for b in series.buckets) == Decimal(400000 + 50000 + 92400 + 1000)
        assert [b.partial for b in series.buckets] == [False] * 11 + [True]

    def test_through_a_past_month_has_no_partial_bucket(self, garage):
        series = monthly_usage(garage.owner, all_rides=True, tz=MADRID, at=NOW, through=(2025, 12))
        assert series.buckets[-1].name == "diciembre 2025" and not any(b.partial for b in series.buckets)
        assert all(b.value == 0 for b in series.buckets)

    @pytest.mark.parametrize("case", ["future", "month13", "bool", "text", "two targets", "no target"])
    def test_rejects(self, garage, case):
        kwargs = {"future": {"all_rides": True, "through": (2026, 11)}, "month13": {"all_rides": True, "through": (2026, 13)},
                  "bool": {"all_rides": True, "through": (True, 1)}, "text": {"all_rides": True, "through": "2026-01"},
                  "two targets": {"all_rides": True, "bike": garage.road}, "no target": {}}[case]
        with pytest.raises(InventoryWriteError):
            monthly_usage(garage.owner, tz=MADRID, at=NOW, **kwargs)


class TestReport:
    def test_overall_and_no_bike(self, garage):
        create_manual_ride(garage.owner, started_at=at(2), bike=garage.road, name="Sin distancia")
        report = statistics(garage.owner, started_from=at(160), started_to=NOW)
        km, hours, rides, elevation = report.overall
        assert (km.value, km.missing_values, rides.value) == (Decimal(400000 + 50000 + 92400 + 1000), 1, 8)
        assert (elevation.value, elevation.missing_values) == (None, 8), "no ride has elevation: unknown, never zero"
        assert hours.value == Decimal(4 * 14400 + 9000)
        assert (report.no_bike[0].value, report.no_bike[2].value, report.unknown_bike_rides) == (Decimal(93400), 2, 2)


def get(client, **params):
    with CaptureQueriesContext(connection) as queries:
        response = client.get(reverse("garage:statistics"), params)
    assert response.status_code == 200 and "no-store" in response.headers["Cache-Control"]
    assert not [q for q in queries if q["sql"].lstrip().split()[0].upper() in WRITES]
    return response.content.decode(), len(queries)


class TestPage:
    def test_default_period_and_chips(self, garage, client):
        client.force_login(garage.owner)
        html, count = get(client)
        assert count <= 32, count
        assert '<a class="chip-link on" href="?period=12m" aria-current="page">12 meses</a>' in html
        assert "<script>" not in html and ' style="' not in html and "SECRET" not in html
        for text in ("Km por mes", "Por bici", "Material más usado", "Gasto en mantenimiento", "Informe detallado y filtros", "Del 1 "):
            assert text in html, text

    def test_all_period_figures(self, garage, client):
        kind = save_maintenance(garage.owner, ServiceType, name="Lavado")
        save_maintenance(garage.owner, ServiceEvent, bike=garage.road, service_type=kind, performed_at=at(5), amount=Decimal("10.5"), currency="EUR")
        save_maintenance(garage.owner, ServiceEvent, item=garage.chain, service_type=kind, performed_at=at(6), amount=Decimal("4"), currency="EUR")
        save_maintenance(garage.owner, ServiceEvent, item=garage.chain, service_type=kind, performed_at=at(7), amount=Decimal("3"), currency="USD")
        save_maintenance(garage.owner, ServiceEvent, item=garage.helmet, service_type=kind, performed_at=at(8))
        from .services.ownership import update_inventory
        update_inventory(garage.owner, Item, garage.chain.pk, purchase_amount=Decimal("99"), purchase_currency="EUR", acquisition_anchor_at=at(300))
        client.force_login(garage.owner)
        html, _ = get(client, period="all")
        for text in ("Todo lo registrado", "<b>543</b>", "Carretera", "<b>400</b>", "Gravel", "Sin bici", "2 salidas · revisar",
                     f'href="{reverse("garage:usage-ride-list")}?pending=1"', "Casco", "<b>14,50</b>", "<b>3,00</b>", "USD",
                     "1 sin importe: el gasto real es al menos esto.", "Últimos 12 meses"):
            assert text in html, text
        assert "<b>113,50</b>" not in html  # the purchase is never added to the spending

    def test_custom_form_keeps_the_detailed_report(self, garage, client):
        client.force_login(garage.owner)
        html, _ = get(client, time_zone="UTC", started_from="2026-01-01T00:00", started_to="2026-12-01T00:00")
        assert '<span class="chip-link on" aria-current="page">Personalizado</span>' in html and "Km por mes" not in html
        assert '<details class="more" open>' in html and "Uso observado del período" in html
        assert "Del 1 ene 2026 hasta el 1 dic 2026 (sin incluir)" in html

    def test_unbound_form_shows_the_viewer_zone(self, garage, client):
        client.force_login(garage.owner)
        client.cookies["garage_tz"] = "America/Argentina/Buenos_Aires"
        html, _ = get(client, period="year")
        assert 'name="time_zone" value="America/Argentina/Buenos_Aires"' in html and 'type="datetime-local" name="started_from"' in html

    def test_query_count_is_constant(self, garage, client):
        client.force_login(garage.owner)
        get(client, period="all")
        _, before = get(client, period="all")
        for number in range(10):
            create_inventory(garage.owner, Item, name=f"Extra {number}", category=garage.helmet.category)
            create_manual_ride(garage.owner, started_at=at(number + 1), bike=garage.gravel, name=f"E{number}", distance_m=Decimal(1000))
        _, after = get(client, period="all")
        assert after == before, (before, after)

    def test_unknown_period_falls_back(self, garage, client):
        client.force_login(garage.owner)
        html, _ = get(client, period="nope")
        assert 'href="?period=12m" aria-current="page"' in html


class TestBoundariesAndConsistency:
    @pytest.fixture
    def edges(self, garage):
        # Local midnights in Madrid: 1 nov 2025 (after the October change), 1 jan 2026.
        for name, instant, km in (("Antes nov", datetime(2025, 10, 31, 23, 30, tzinfo=MADRID), 1000),
                                  ("Nov 00:30", datetime(2025, 11, 1, 0, 30, tzinfo=MADRID), 2000),
                                  ("Nochevieja", datetime(2025, 12, 31, 23, 30, tzinfo=MADRID), 4000),
                                  ("Año nuevo", datetime(2026, 1, 1, 0, 30, tzinfo=MADRID), 8000)):
            create_manual_ride(garage.owner, started_at=instant, bike=garage.gravel, name=name, distance_m=Decimal(km), moving_time_s=Decimal(60))
        return garage

    @pytest.mark.parametrize("period", ["12m", "year", "last"])
    def test_figures_match_the_chart(self, edges, period):
        now = datetime(2026, 10, 16, 12, tzinfo=UTC)
        start, end, through, months = period_bounds(period, MADRID, now)
        report = statistics(edges.owner, started_from=start, started_to=end)
        series = monthly_usage(edges.owner, all_rides=True, tz=MADRID, at=now, months=months, through=through)
        assert sum(b.value for b in series.buckets) == report.overall[0].value
        names = {"12m": 2000 + 4000 + 8000, "year": 8000, "last": 1000 + 2000 + 4000}
        expected = {"12m": Decimal(400000 + 50000 + 92400 + 1000 + names["12m"]), "year": Decimal(400000 + 50000 + 92400 + 1000 + names["year"]),
                    "last": Decimal(names["last"])}[period]
        assert report.overall[0].value == expected

    def test_first_instant_of_the_year_has_no_data_yet(self, garage, client, monkeypatch):
        monkeypatch.setattr("django.utils.timezone.now", lambda: datetime(2026, 1, 1, tzinfo=MADRID).astimezone(UTC))
        client.force_login(garage.owner)
        html, _ = get(client, period="year")
        assert "Aún no hay datos en este período." in html

    def test_missing_times_are_flagged(self, garage, client):
        client.force_login(garage.owner)
        html, _ = get(client, period="all")
        assert "sin tiempo en movimiento: las horas son un mínimo." in html


class TestCustomScope:
    def test_filters_show_only_the_detailed_report(self, garage, client):
        client.force_login(garage.owner)
        html, _ = get(client, time_zone="UTC", item=str(garage.chain.pk))
        assert "Filtrado por bici, categoría u objeto" in html and "Por bici" not in html and "Gasto en mantenimiento" not in html
        assert "Uso observado del período" in html

    def test_dates_follow_the_form_zone(self, garage, client):
        client.force_login(garage.owner)
        client.cookies["garage_tz"] = "Europe/Madrid"
        html, _ = get(client, time_zone="America/Argentina/Buenos_Aires", started_from="2026-01-01T00:00", started_to="2026-12-01T00:00")
        assert "Del 1 ene 2026 hasta el 1 dic 2026 (sin incluir)" in html


class TestBudgetWithEverything:
    def test_query_count_is_constant(self, garage, client):
        from .services.baselines import record_baseline
        from .services.installations import create_installation
        from .models import Bike
        client.force_login(garage.owner)
        get(client, period="12m")
        _, before = get(client, period="12m")
        kind = save_maintenance(garage.owner, ServiceType, name="Lavado")
        for number in range(6):
            bike = create_inventory(garage.owner, Bike, name=f"Bici {number}")
            item = create_inventory(garage.owner, Item, name=f"Pieza {number}", category=garage.helmet.category)
            create_installation(garage.owner, item=item, bike=bike, parent_item=None, started_at=at(40), ended_at=None, slot=None)
            create_manual_ride(garage.owner, started_at=at(number + 1), bike=bike, name=f"B{number}", distance_m=Decimal(1000))
            save_maintenance(garage.owner, ServiceEvent, item=item, service_type=kind, performed_at=at(3), amount=Decimal(2), currency="EUR")
            record_baseline(garage.owner, item=item, metric="distance_m", scope="lifetime", cut_at=at(50), value=Decimal(100), source="manual")
        _, after = get(client, period="12m")
        assert after == before, (before, after)

    def test_open_end_and_exact_bounds(self, garage, client):
        client.force_login(garage.owner)
        client.cookies["garage_tz"] = "Europe/Madrid"
        html, _ = get(client, time_zone="Europe/Madrid", started_from="2026-01-01T07:30")
        assert "Del <time" in html and "1 ene 2026, 7:30</time> hasta hoy" in html
