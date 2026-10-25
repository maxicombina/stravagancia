"""garage-036: usage between interventions and how long each part of a category lasted."""
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .models import Item, ServiceEvent, ServiceType, UsageMaterializationState
from .services.baselines import record_baseline
from .services.maintenance import save_maintenance
from .services.ownership import create_inventory, retire_inventory, update_inventory
from .services.service_usage import Span, category_comparison, event_usage
from .services.statistics import StatisticMetric
from .templatetags.garage_ui import metric_km, span_short, span_text
from .tests_mobile_home import NOW, at, garage  # noqa: F401 (fixture)

MADRID = ZoneInfo("Europe/Madrid")
WRITES = {"INSERT", "UPDATE", "DELETE"}


@pytest.fixture
def now(monkeypatch):
    monkeypatch.setattr("django.utils.timezone.now", lambda: NOW)
    return NOW


@pytest.fixture
def history(garage):
    change = ServiceType.objects.get(owner=garage.owner, name="Cambio de cadena")
    lube = save_maintenance(garage.owner, ServiceType, name="Lubricación")
    first = save_maintenance(garage.owner, ServiceEvent, item=garage.chain, service_type=change, performed_at=at(160))
    second = save_maintenance(garage.owner, ServiceEvent, item=garage.chain, service_type=change, performed_at=at(60))
    oil = save_maintenance(garage.owner, ServiceEvent, item=garage.chain, service_type=lube, performed_at=at(120))
    return first, second, oil


def metric(span, name):
    return span.metric(name).value


class TestService:
    def test_before_and_after_by_type(self, garage, history):
        first, second, oil = history
        usage = event_usage(garage.owner, first, at=NOW)
        assert (usage.previous, usage.before, usage.next) == (None, None, second)
        assert (metric(usage.after, "distance_m"), metric(usage.after, "ride_count"), usage.after.days) == (Decimal(200000), Decimal(2), Decimal(100))
        usage = event_usage(garage.owner, second, at=NOW)
        assert usage.previous == first and metric(usage.before, "distance_m") == Decimal(200000)
        assert usage.next is None and metric(usage.after, "distance_m") == Decimal(200000) and usage.after.days == Decimal(60)
        usage = event_usage(garage.owner, oil, at=NOW)  # another type: its own series
        assert usage.previous is None and metric(usage.after, "distance_m") == Decimal(300000)
        assert not usage.after.metric("distance_m").complete  # observed: a minimum

    def test_service_reading_is_exact(self, garage, history):
        first, second, _ = history
        record_baseline(garage.owner, item=garage.chain, metric="distance_m", scope="service", cut_at=at(60), value=Decimal(123000),
                        service_event=second)
        after = event_usage(garage.owner, second, at=NOW).after
        assert metric(after, "distance_m") == Decimal(123000) + Decimal(200000) and after.metric("distance_m").baseline is not None

    def test_unknown_usage(self, garage, history):
        UsageMaterializationState.objects.filter(owner=garage.owner).update(initialized_at=None)
        after = event_usage(garage.owner, history[1], at=NOW).after
        assert metric(after, "distance_m") is None and span_text(after) == "60 días · uso desconocido"

    def test_bike_interventions_count_its_rides(self, garage):
        kind = save_maintenance(garage.owner, ServiceType, name="Lavado")
        older = save_maintenance(garage.owner, ServiceEvent, bike=garage.road, service_type=kind, performed_at=at(120))
        newer = save_maintenance(garage.owner, ServiceEvent, bike=garage.road, service_type=kind, performed_at=at(30))
        usage = event_usage(garage.owner, newer, at=NOW)
        assert usage.previous == older and metric(usage.before, "ride_count") == Decimal(2) and metric(usage.after, "distance_m") == Decimal(100000)

    def test_category_comparison(self, garage, history):
        spare = create_inventory(garage.owner, Item, name="Cadena vieja", category=garage.chain.category, acquired_on=date(2025, 1, 1))
        retire_inventory(garage.owner, Item, spare.pk, at=at(300))
        record_baseline(garage.owner, item=spare, metric="distance_m", scope="lifetime", cut_at=at(300), value=Decimal(3240000))
        lives = category_comparison(garage.owner, garage.chain.category, zone=MADRID, at=NOW)
        assert [(life.item.name, life.state, life.reading, life.distance.value, life.days_kind) for life in lives] == [
            ("Cadena vieja", "retired", "lifetime", Decimal(3240000), "purchase"), ("Cadena 11v", "mounted", "", Decimal(400000), "mounted")]
        # Never mounted: days from the purchase at local midnight in the person's zone, until its retirement.
        assert round(lives[0].days, 6) == round(Decimal((at(300) - datetime(2025, 1, 1, tzinfo=MADRID)).total_seconds()) / 86400, 6)
        assert lives[1].days == Decimal(200)

    def test_comparison_marks_and_order(self, garage):
        cat = garage.chain.category
        estimated = create_inventory(garage.owner, Item, name="Estimada", category=cat)
        record_baseline(garage.owner, item=estimated, metric="distance_m", scope="lifetime", cut_at=at(1), value=Decimal(1000000), is_estimated=True)
        create_inventory(garage.owner, Item, name="Sin uso", category=cat, retired_at=NOW + timedelta(days=30))
        lives = {life.item.name: life for life in category_comparison(garage.owner, cat, zone=MADRID, at=NOW)}
        assert metric_km(lives["Estimada"].distance) == "≈ 1.000"
        assert lives["Sin uso"].state == "loose" and lives["Sin uso"].days is None  # retirement still to come; never mounted
        UsageMaterializationState.objects.filter(owner=garage.owner).update(initialized_at=None)
        pending = category_comparison(garage.owner, cat, zone=MADRID, at=NOW)
        assert all(life.distance.value is None for life in pending)  # usage not calculated: unknown, never zero
        assert [life.item.name for life in pending] == ["Cadena 11v", "Estimada", "Sin uso"]  # then by name

    def test_lower_bounds_round_down(self):
        observed = StatisticMetric("distance_m", Decimal("99960"))
        assert metric_km(observed) == "≥ 99,9" and metric_km(StatisticMetric("distance_m", Decimal("99960"), complete=True)) == "100"

    def test_future_interventions(self, garage, history):
        first, second, _ = history
        planned = save_maintenance(garage.owner, ServiceEvent, item=garage.chain, service_type=first.service_type, performed_at=NOW + timedelta(days=10))
        usage = event_usage(garage.owner, second, at=NOW)
        assert usage.next is None and usage.upcoming == planned and usage.after.days == Decimal(60)
        ahead = event_usage(garage.owner, planned, at=NOW)
        assert ahead.future and (ahead.previous, ahead.before, ahead.after) == (None, None, None)

    def test_ties_follow_creation(self, garage):
        kind = save_maintenance(garage.owner, ServiceType, name="Revisión doble")
        one = save_maintenance(garage.owner, ServiceEvent, item=garage.light, service_type=kind, performed_at=at(5))
        two = save_maintenance(garage.owner, ServiceEvent, item=garage.light, service_type=kind, performed_at=at(5))
        assert event_usage(garage.owner, two, at=NOW).previous == one and event_usage(garage.owner, one, at=NOW).next == two


def span(*values, days=10, complete=False, estimated=False):
    from types import SimpleNamespace
    names = ("distance_m", "moving_time_s", "ride_count")
    metrics = tuple(StatisticMetric(name, None if value is None else Decimal(value), 0, complete,
                                    SimpleNamespace(is_estimated=True) if estimated else None) for name, value in zip(names, values))
    return Span(NOW - timedelta(days=days), NOW, metrics)


class TestText:
    def test_marks_and_units(self):
        assert span_text(span(3240500, 432000, 45, days=210)) == "≥ 3.240 km · ≥ 120 h · ≥ 45 salidas · 210 días"
        assert span_text(span(1000, 3600, 1, days=1, complete=True)) == "1 km · 1 h · 1 salida · 1 día"
        assert span_text(span(1500, None, None, estimated=True)) == "≈ 1,5 km · 10 días"
        assert span_short(span(3240500, 1, 1)) == "≥ 3.240 km" and span_short(span(None, None, None, days=40)) == "40 días"
        assert span_text(None) == span_short(None) == ""


class TestScreens:
    def test_event_detail(self, garage, history, client, now):
        client.force_login(garage.owner)
        with CaptureQueriesContext(connection) as queries:
            html = client.get(reverse("garage:service-event-detail", args=[history[1].pk])).content.decode()
        assert not [q for q in queries if q["sql"].split()[0] in WRITES] and len(queries) <= 30, len(queries)
        assert "Desde la anterior, el" in html and "≥ 200 km · ≥ 8 h · ≥ 2 salidas · 100 días" in html
        assert "Desde entonces, hasta hoy" in html and "≥ 200 km · ≥ 8 h · ≥ 2 salidas · 60 días" in html
        first = client.get(reverse("garage:service-event-detail", args=[history[0].pk])).content.decode()
        assert "Primera de este tipo registrada" in first and "No hay ninguna intervención «Cambio de cadena» anterior en Cadena 11v" in first
        assert "Hasta la siguiente, el" in first
        planned = save_maintenance(garage.owner, ServiceEvent, item=garage.chain, service_type=history[0].service_type, performed_at=NOW + timedelta(days=10))
        assert "aún sin uso" in client.get(reverse("garage:service-event-detail", args=[planned.pk])).content.decode()
        latest = client.get(reverse("garage:service-event-detail", args=[history[1].pk])).content.decode()
        assert "Hasta hoy (la siguiente está programada para el" in latest
        foreign = ServiceEvent.objects.filter(owner=garage.other).first() or save_maintenance(
            garage.other, ServiceEvent, item=Item.objects.get(owner=garage.other), service_type=ServiceType.objects.get(owner=garage.other), performed_at=at(1))
        assert client.get(reverse("garage:service-event-detail", args=[foreign.pk])).status_code == 404

    def test_lists(self, garage, history, client, now):
        client.force_login(garage.owner)
        item = client.get(reverse("garage:item-detail", args=[garage.chain.pk])).content.decode()
        assert item.count("a ≥ 200 km de la anterior") == 1  # only the second change has a previous one
        kind = save_maintenance(garage.owner, ServiceType, name="Lavado")
        for days in (120, 30):
            save_maintenance(garage.owner, ServiceEvent, bike=garage.road, service_type=kind, performed_at=at(days))
        save_maintenance(garage.owner, ServiceEvent, bike=garage.road, service_type=kind, performed_at=NOW + timedelta(days=20))
        bike = client.get(reverse("garage:bike-detail", args=[garage.road.pk])).content.decode()
        assert bike.count("de la anterior") == 1 and "a ≥ 200 km de la anterior" in bike  # the planned one has no usage
        with CaptureQueriesContext(connection) as queries:
            category = client.get(reverse("garage:category-detail", args=[garage.chain.category_id])).content.decode()
        assert len(queries) <= 27, len(queries)
        assert "Cuánto dura cada uno" in category and "≥ 400" in category and "km en Garage" in category
        assert "Montado · 200 días montado" in category


class TestReviewFixes:
    def test_acquisition_reading_and_retired_end(self, garage, history, client, now):
        used = create_inventory(garage.owner, Item, name="Cadena usada", category=garage.chain.category, acquisition_anchor_at=at(30))
        record_baseline(garage.owner, item=used, metric="distance_m", scope="acquisition", cut_at=at(30), value=Decimal(2000000))
        lives = {life.item.name: life for life in category_comparison(garage.owner, garage.chain.category, zone=MADRID, at=NOW)}
        assert (lives["Cadena usada"].reading, lives["Cadena usada"].distance.value) == ("acquisition", Decimal(2000000))
        assert lives["Cadena usada"].days_kind == "use" and int(lives["Cadena usada"].days) == 30
        retire_inventory(garage.owner, Item, garage.chain.pk, at=at(30))
        usage = event_usage(garage.owner, history[1], at=NOW)
        assert usage.retired_at == at(30) and usage.after.days == Decimal(30)  # from at(60) to the retirement, not to today
        client.force_login(garage.owner)
        html = client.get(reverse("garage:service-event-detail", args=[history[1].pk])).content.decode()
        assert "Hasta su retiro, el" in html
        with CaptureQueriesContext(connection) as queries:
            page = client.get(reverse("garage:category-detail", args=[garage.chain.category_id])).content.decode()
        assert not [q for q in queries if q["sql"].split()[0] in WRITES] and "km desde que es tuyo" in page
