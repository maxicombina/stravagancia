"""garage-030 phase 3 (garage-037), screens half: elevation in rules, snoozes, statistics and screens;
power only on the ride's own screens; the four minors deferred from phases 1–2."""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
import requests
from django import forms
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .lifespan_forms import LifespanForm
from .maintenance_forms import MaintenanceRuleWebForm, WholeNumberInput
from .models import MaintenanceRule, ServiceEvent, ServiceType, StravaEvent, UsageProfile
from .presentation import NAMES, UNITS, power_figures, quantity, thresholds, wear
from .services.lifespan import set_lifespan
from .services.maintenance import save_maintenance
from .services.maintenance_due import METRICS, _metric, maintenance_due
from .services.monthly import monthly_usage
from .services.rides import create_manual_ride
from .services.snoozes import snooze_rule
from .services.statistics import statistics
from .services.strava_client import TIMEOUT, StravaClient, StravaError
from .services.strava_sync import process_pending_events, sync_now
from .services.usage import rebuild_usage
from .services.usage_profiles import create_profile_history
from .snooze_forms import SnoozeForm, presets
from .templatetags.garage_ui import metric_m, span_text
from .tests_mobile_home import NOW, at, due, garage, metric  # noqa: F401 (fixture)
from .tests_strava_client import ATHLETE, connected, strava  # noqa: F401 (fixture)
from .tests_strava_sync import ago, hint

MADRID = ZoneInfo("Europe/Madrid")
WRITES = {"INSERT", "UPDATE", "DELETE"}


@pytest.fixture
def now(monkeypatch):
    monkeypatch.setattr("django.utils.timezone.now", lambda: NOW)
    return NOW


@pytest.fixture
def hills(garage):
    """Two road rides with elevation; the fixture's other rides have none."""
    climbs = {day: create_manual_ride(garage.owner, started_at=at(day), bike=garage.road, name=f"Puerto {day}",
                                      distance_m=Decimal(50000), moving_time_s=Decimal(7200), elevation_gain_m=Decimal(metres))
              for day, metres in ((30, 1200), (5, 800))}
    rebuild_usage(garage.owner)
    return SimpleNamespace(**vars(garage), climbs=climbs)


def kind(garage, name="Revisión de frenos"):
    return save_maintenance(garage.owner, ServiceType, name=name)


def road_rule(g, **values):
    return save_maintenance(g.owner, MaintenanceRule, bike=g.road, service_type=kind(g), anchor_at=at(60), **values)


def due_of(owner, rule):
    return next(entry for entry in maintenance_due(owner, at=NOW) if entry.rule.pk == rule.pk)


def elevation_of(entry):
    return next(m for m in entry.metrics if m.name == "elevation_gain_m")


def html_of(client, name, *args, **params):
    with CaptureQueriesContext(connection) as queries:
        response = client.get(reverse(f"garage:{name}", args=args), params)
    assert response.status_code == 200, response.status_code
    assert not [q for q in queries if q["sql"].lstrip().split()[0].upper() in WRITES], "GET never writes"
    html = response.content.decode()
    assert "<script>" not in html and ' style="' not in html
    return html, len(queries)


# Rules -----------------------------------------------------------------------

class TestRules:
    def test_metric_order_and_names(self):
        assert METRICS[-1] == "elevation_gain_m" and UNITS["elevation_gain_m"] == "m" and NAMES["elevation_gain_m"] == "Desnivel"

    def test_bike_rule_first_reached_wins(self, hills):
        rule = road_rule(hills, distance_m=Decimal(10_000_000), elevation_gain_m=Decimal(1500))
        entry = due_of(hills.owner, rule)
        climb = elevation_of(entry)
        # [at(60), NOW): 1200 + 800 m; the rides at 50 and 10 days have no elevation and are a missing contribution.
        assert (climb.value, climb.missing_values, climb.status, climb.coverage) == (Decimal(2000), 2, "due", "partial")
        assert next(m for m in entry.metrics if m.name == "distance_m").status == "unknown"
        assert entry.status == "due" and climb.label == "Desnivel (m)" and climb.display_value == Decimal(2000)

    def test_ninety_percent_and_lower_bound(self, hills):
        near = due_of(hills.owner, road_rule(hills, elevation_gain_m=Decimal(2200)))
        headline = wear(near).headline
        assert elevation_of(near).status == "unknown" and headline.state == "review" and headline.percent_text == "≥ 90 %"
        assert (headline.big, headline.big_caption, headline.unit_text) == ("200", "↑ m como máx.", "↑ m")
        assert _metric("elevation_gain_m", 1000, Decimal(900), True).status == "soon"
        assert _metric("elevation_gain_m", 1000, Decimal(899), True).status == "current"

    def test_reference_is_the_latest_event_of_the_same_target_and_type(self, hills):
        rule = road_rule(hills, elevation_gain_m=Decimal(1500))
        save_maintenance(hills.owner, ServiceEvent, bike=hills.road, service_type=rule.service_type, performed_at=at(20))
        save_maintenance(hills.owner, ServiceEvent, bike=hills.road, service_type=kind(hills, "Lavado"), performed_at=at(1))
        entry = due_of(hills.owner, rule)
        assert entry.reference_at == at(20) and elevation_of(entry).value == Decimal(800) and entry.status == "unknown"

    def test_item_rule_counts_its_materialized_elevation(self, hills):
        rule = save_maintenance(hills.owner, MaintenanceRule, item=hills.chain, service_type=kind(hills), anchor_at=at(40),
                                elevation_gain_m=Decimal(1000))
        assert elevation_of(due_of(hills.owner, rule)).value == Decimal(2000)
        on_gravel = save_maintenance(hills.owner, MaintenanceRule, bike=hills.gravel, service_type=kind(hills, "Otra"),
                                     anchor_at=at(40), elevation_gain_m=Decimal(1000))
        climb = elevation_of(due_of(hills.owner, on_gravel))
        # Code review: the only ride since the anchor has no elevation, so it is unknown, never an observed 0.
        assert (climb.value, climb.missing_values, climb.unrecorded) == (None, 1, True)
        assert wear(due_of(hills.owner, on_gravel)).headline.state == "nodata"

    def test_thresholds_text_is_exact(self):
        rule = SimpleNamespace(distance_m=Decimal(3000000), moving_time_s=None, ride_count=None, calendar_days=365,
                               elevation_gain_m=Decimal("20000"))
        assert thresholds(rule) == "3.000 km · 365 días · 20.000 m de desnivel"
        assert thresholds(SimpleNamespace(**{**vars(rule), "elevation_gain_m": Decimal("1234.5")}), separator=" o ") == \
            "3.000 km o 365 días o 1.234,5 m de desnivel"

    def test_quantity_in_whole_metres(self):
        assert [quantity("elevation_gain_m", Decimal("1234.5")), quantity("elevation_gain_m", Decimal("1234.5"), down=True),
                quantity("elevation_gain_m", Decimal("1234.1"), up=True), quantity("elevation_gain_m", Decimal("12.4"))] == \
            ["1.235", "1.234", "1.235", "12"]


# Snoozes ---------------------------------------------------------------------

class TestSnoozes:
    def test_active_reached_and_unknown(self, hills, now):
        rule = road_rule(hills, elevation_gain_m=Decimal(1500))
        snooze_rule(hills.owner, rule, elevation_gain_m=Decimal(1000), calendar_days=30, at=at(7))
        entry = due_of(hills.owner, rule)
        # Since at(7): only the 800 m ride at(5); the rides without a bike never count for a bike rule.
        assert entry.status == "due" and entry.snooze.status == "active"
        shown = wear(entry)
        assert shown.state == "snoozed" and shown.snooze_left == "23 días o como máx. ↑ 200 m"
        create_manual_ride(hills.owner, started_at=at(2), bike=hills.road, name="Sin altímetro", distance_m=Decimal(10000))
        entry = due_of(hills.owner, rule)
        assert entry.snooze.status == "unknown" and elevation_of(entry.snooze).value is None
        assert wear(entry).state == "due", "a ride without elevation never keeps the alert hidden"

    def test_unknown_elevation_is_explained(self, hills, now, client):
        rule = road_rule(hills, elevation_gain_m=Decimal(1500))
        snooze_rule(hills.owner, rule, elevation_gain_m=Decimal(1000), calendar_days=30, at=at(7))
        client.force_login(hills.owner)
        html, _ = html_of(client, "maintenance-rule-snooze", rule.pk)
        assert "Pospuesto" in html and "por revisar" not in html
        create_manual_ride(hills.owner, started_at=at(2), bike=hills.road, name="Sin altímetro", distance_m=Decimal(10000))
        entry = due_of(hills.owner, rule)
        assert entry.snooze.unknown_elevation
        html, _ = html_of(client, "maintenance-rule-snooze", rule.pk)
        assert "Aplazamiento por revisar" in html and "Alguna salida desde entonces no registra desnivel" in html
        assert "el aviso se sigue mostrando" in html and "El uso desde entonces está pendiente de calcular" not in html
        from .models import UsageMaterializationState
        UsageMaterializationState.objects.filter(owner=hills.owner).update(initialized_at=None)
        item_rule = save_maintenance(hills.owner, MaintenanceRule, item=hills.chain, service_type=kind(hills, "Otra"), anchor_at=at(40),
                                     elevation_gain_m=Decimal(1000))
        snooze_rule(hills.owner, item_rule, elevation_gain_m=Decimal(100), calendar_days=30, at=at(7))
        assert not due_of(hills.owner, item_rule).snooze.unknown_elevation, "usage still to be calculated is another reason"

    def test_reached_names_the_elevation(self, hills, now):
        rule = road_rule(hills, elevation_gain_m=Decimal(1500))
        snooze_rule(hills.owner, rule, elevation_gain_m=Decimal(500), calendar_days=30, at=at(7))
        shown = wear(due_of(hills.owner, rule))
        assert shown.snooze.status == "reached" and shown.state == "due" and shown.snooze_reached == "500 m de desnivel"

    def test_snooze_page_posts_whole_metres(self, hills, now, client):
        rule = road_rule(hills, elevation_gain_m=Decimal(1500))
        client.force_login(hills.owner)
        url = reverse("garage:maintenance-rule-snooze", args=[rule.pk])
        html, _ = html_of(client, "maintenance-rule-snooze", rule.pk)
        assert 'name="elevation_gain_m"' in html and 'inputmode="numeric"' in html and "el desnivel o los días" in html
        bad = client.post(url, {"calendar_days": "30", "elevation_gain_m": "2,5"})
        assert bad.status_code == 200 and "Introduce metros enteros, sin decimales (1500 o 1.500)." in bad.content.decode()
        response = client.post(url, {"calendar_days": "30", "elevation_gain_m": "300"}, follow=True)
        assert "pospuesto 30 días o 300 m de desnivel, lo primero que llegue" in response.content.decode()
        assert rule.snoozes.get().elevation_gain_m == Decimal(300)


# Forms -----------------------------------------------------------------------

class TestForms:
    def rule_form(self, g, instance=None, **data):
        if data:
            data = {"bike": g.road.pk, "service_type": kind(g).pk if instance is None else instance.service_type_id,
                    "time_zone": "UTC", **data}
        return MaintenanceRuleWebForm(data or None, user=g.owner, instance=instance)

    def test_rule_takes_whole_metres(self, garage):
        form = self.rule_form(garage, elevation_gain_m="1500")
        assert form.is_valid(), form.errors
        assert type(form.cleaned_data["elevation_gain_m"]) is Decimal and form.cleaned_data["elevation_gain_m"] == Decimal(1500)
        rule = form.save()
        assert rule.elevation_gain_m == Decimal("1500.000") and rule.distance_m is None
        field = form.fields["elevation_gain_m"]
        assert type(field) is WholeNumberInput and field.label == "Desnivel (m)" and "Metros enteros" in field.help_text
        assert isinstance(field, forms.IntegerField) and type(field.widget) is forms.TextInput
        assert field.widget.attrs["inputmode"] == "numeric" and "min" not in field.widget.attrs
        shown = self.rule_form(garage, instance=rule)
        assert shown["elevation_gain_m"].value() == 1500

    @pytest.mark.parametrize("value,message", [("1500,5", "Introduce metros enteros, sin decimales (1500 o 1.500)."),
                                               ("1.5", "Introduce metros enteros, sin decimales (1500 o 1.500)."),
                                               ("1.000,5", "Introduce metros enteros, sin decimales (1500 o 1.500)."),
                                               ("0.500", "Introduce metros enteros, sin decimales (1500 o 1.500)."),
                                               ("1.50", "Introduce metros enteros, sin decimales (1500 o 1.500)."),
                                               ("0", "Debe ser al menos 1 m."), ("0.000", "Introduce metros enteros, sin decimales (1500 o 1.500).")])
    def test_rule_rejects(self, garage, value, message):
        form = self.rule_form(garage, elevation_gain_m=value)
        assert not form.is_valid() and form.errors["elevation_gain_m"] == [message]

    def test_without_any_threshold_the_message_names_elevation(self, garage):
        form = self.rule_form(garage, notes="nada")
        assert not form.is_valid() and "distancia, tiempo, salidas, días o desnivel" in str(form.errors)

    def test_a_decimal_elevation_keeps_its_exact_field(self, garage):
        rule = road_rule(garage, elevation_gain_m=Decimal("1234.5"))
        assert isinstance(self.rule_form(garage, instance=rule).fields["elevation_gain_m"], forms.DecimalField)

    def test_snooze_form_and_tenth_preset(self, garage):
        form = SnoozeForm({"calendar_days": "30", "elevation_gain_m": "300"})
        assert form.is_valid(), form.errors
        assert form.amounts["elevation_gain_m"] == Decimal(300) and type(form.amounts["elevation_gain_m"]) is Decimal
        assert not SnoozeForm({"calendar_days": "30", "elevation_gain_m": "0"}).is_valid()
        rule = SimpleNamespace(distance_m=None, moving_time_s=None, ride_count=None, calendar_days=None, elevation_gain_m=Decimal(1505))
        assert presets(rule)["tenth"][1] == {"calendar_days": 30, "elevation_gain_m": Decimal(151)}
        assert presets(SimpleNamespace(**{**vars(rule), "elevation_gain_m": Decimal(5)}))["tenth"][1]["elevation_gain_m"] == Decimal(1)

    def test_lifespan_form(self, garage):
        form = LifespanForm({"start": "2026-01-01T00:00", "time_zone": "UTC", "time_unit": "days", "elevation_gain_m": "20000"})
        assert form.is_valid(), form.errors
        assert form.lifespan["elevation_gain_m"] == Decimal(20000) and type(form.lifespan["elevation_gain_m"]) is Decimal
        rule = set_lifespan(garage.owner, garage.light, calendar_days=10, elevation_gain_m=Decimal("1.5"), start=at(1))
        shown = LifespanForm(rule=rule, start=at(1))
        assert "elevation_gain_m" not in shown.fields
        kept = LifespanForm({"start": "2026-01-01T00:00", "time_zone": "UTC", "time_value": "10", "time_unit": "days"}, rule=rule, start=at(1))
        assert kept.is_valid() and kept.lifespan["elevation_gain_m"] == Decimal("1.5")
        whole = set_lifespan(garage.owner, garage.chain, elevation_gain_m=Decimal(20000), start=at(1))
        assert LifespanForm(rule=whole, start=at(1)).initial["elevation_gain_m"] == 20000

    def test_lifespan_page(self, garage, client):
        client.force_login(garage.owner)
        url = reverse("garage:item-lifespan", args=[garage.chain.pk])
        html, _ = html_of(client, "item-lifespan", garage.chain.pk)
        assert "los km, las horas, el desnivel o el tiempo" in html and 'name="elevation_gain_m"' in html
        response = client.post(url, {"elevation_gain_m": "20000", "time_unit": "days", "start": "2026-03-30T12:00",
                                     "time_zone": "Europe/Madrid"}, follow=True)
        assert "Vida útil de Cadena 11v: 20.000 m de desnivel, lo primero que llegue." in response.content.decode()


# Statistics ------------------------------------------------------------------

class TestStatistics:
    def test_per_bike_and_overall(self, hills):
        report = statistics(hills.owner, started_from=at(160), started_to=NOW)
        rows = {row.target.name: row for row in report.rows if row.kind == "bike"}
        road, gravel = rows["Carretera"].observed[3], rows["Gravel"].observed[3]
        assert (road.name, road.value, road.missing_values, road.label) == ("elevation_gain_m", Decimal(2000), 4, "Desnivel (m)")
        assert gravel.value is None, "rides without elevation: unknown, not zero"
        assert report.overall[3].value == Decimal(2000) and report.overall[3].display_value == Decimal(2000)
        chain = statistics(hills.owner, item=hills.chain, started_to=NOW).rows[0]
        assert chain.observed[3].value == Decimal(2000)
        assert chain.totals[0].metrics[3].value is None, "no reading holds elevation: the lifetime total stays unknown"

    def test_per_month(self, hills):
        series = monthly_usage(hills.owner, bike=hills.road, metric="elevation_gain_m", tz=MADRID, at=NOW)
        values = {bucket.label: (bucket.value, bucket.missing) for bucket in series.buckets[-6:]}
        assert values == {"may": (None, 1), "jun": (Decimal(0), 0), "jul": (None, 1), "ago": (None, 1), "sep": (Decimal(1200), 0),
                          "oct": (Decimal(800), 1)}

    def test_page(self, hills, client):
        client.force_login(hills.owner)
        default, count = html_of(client, "statistics")
        assert "Km por mes" in default and "<b>↑ 2.000</b><span>m de desnivel</span>" in default and 'class="stats four"' in default
        assert "7 sin desnivel: el desnivel es un mínimo." in default and "· ↑ ≥ 2.000 m" in default, "a minimum per bike too"
        assert 'href="?period=12m&amp;chart=elevation"' in default and 'href="?period=year"' in default
        html, elevated = html_of(client, "statistics", chart="elevation")
        assert elevated == count, "the chart only changes which metric is summed"
        assert "Desnivel por mes" in html and '<th>Desnivel</th>' in html and "1.200 m" in html
        assert 'class="chip-link on" href="?period=12m&amp;chart=elevation"' in html and 'href="?period=year&amp;chart=elevation"' in html
        assert "Desnivel (m) por mes de" in html
        assert "Km por mes" in html_of(client, "statistics", chart="watts")[0]

    def test_nothing_when_no_ride_has_elevation(self, garage, client):
        client.force_login(garage.owner)
        html, _ = html_of(client, "statistics")
        assert "m de desnivel" not in html and "↑" not in html and 'class="stats four"' not in html
        assert "Aún no hay desnivel registrado en estos meses." in html_of(client, "statistics", chart="elevation")[0]


# Screens ---------------------------------------------------------------------

@pytest.fixture
def powered(hills):
    ride = create_manual_ride(hills.owner, started_at=at(1), bike=hills.road, name="Con potenciómetro", distance_m=Decimal(80000),
                              moving_time_s=Decimal(10800), elevation_gain_m=Decimal("1234.4"), average_power_w=Decimal("212.4"),
                              max_power_w=Decimal(845), weighted_power_w=Decimal(238), energy_kj=Decimal("2345.6"))
    return SimpleNamespace(**vars(hills), ride=ride)


class TestScreens:
    def test_filters(self):
        assert [metric_m(Decimal("1234.4")), metric_m(Decimal("1234.5")), metric_m(0), metric_m(None)] == ["1.234 m", "1.235 m", "0 m", "—"]
        ride = SimpleNamespace(average_power_w=Decimal("212.4"), max_power_w=None, weighted_power_w=Decimal(238), energy_kj=Decimal("2345.6"))
        assert power_figures(ride) == (("Ø 212", "W media"), ("NP 238", "W normalizada"), ("2.346", "kJ"))
        assert power_figures(SimpleNamespace()) == ()

    def test_review_shows_power_and_elevation(self, powered, client):
        client.force_login(powered.owner)
        html, _ = html_of(client, "ride-review", powered.ride.pk)
        for text in ('class="stats four"', "<b>↑ 1.234</b><span>m de desnivel</span>", 'aria-label="Potencia y energía"',
                     "<b>Ø 212</b><span>W media</span>", "<b>máx 845</b><span>W máxima</span>", "<b>NP 238</b><span>W normalizada</span>",
                     "<b>2.346</b><span>kJ</span>"):
            assert text in html, text
        detail, _ = html_of(client, "usage-ride-detail", powered.ride.pk)
        assert "<b>Ø 212</b>" in detail and "<b>↑ 1.234</b>" in detail and "<b>80</b><span>km</span>" in detail

    def test_review_without_them_shows_nothing_new(self, garage, client):
        ride = garage.pending
        client.force_login(garage.owner)
        html, _ = html_of(client, "ride-review", ride.pk)
        for absent in ("stats four", "Potencia", "Ø", "NP ", "<span>kJ</span>", "desnivel", "↑"):  # «kJ» alone can appear inside a CSRF token
            assert absent not in html, absent

    def test_review_effects_carry_the_elevation(self, hills, client):
        client.force_login(hills.owner)
        html, _ = html_of(client, "ride-review-preview", hills.climbs[30].pk, bike=str(hills.gravel.pk))
        assert html.count("· 2 h 00 · ↑ 1.200 m</span>") >= 2, html  # the bike it leaves and the one it joins

    def test_lists_show_elevation_never_power(self, powered, client):
        client.force_login(powered.owner)
        rides, _ = html_of(client, "usage-ride-list")
        assert "Carretera · ↑ 1.200 m" in rides and "Carretera · ↑ 1.234 m" in rides and rides.count("↑") == 3
        history, _ = html_of(client, "history")
        assert history.count("↑ ") == 3 and "↑ 800 m" in history
        home, _ = html_of(client, "index")
        assert "h · ↑ ≥ 3.234 m" in home and home.count("↑") == 1, "only the bike that has elevation, a minimum"
        for html in (rides, history, home):
            assert "Ø" not in html and "W media" not in html and "<span>kJ</span>" not in html

    def test_bike_screen(self, hills, client):
        client.force_login(hills.owner)
        road, _ = html_of(client, "bike-detail", hills.road.pk)
        assert 'class="stats four"' in road and "<b>↑ 2.000</b><span>m de desnivel</span>" in road
        assert "4 sin desnivel: el desnivel es un mínimo." in road and "· ↑ 800 m</span>" in road
        gravel, _ = html_of(client, "bike-detail", hills.gravel.pk)
        assert "desnivel" not in gravel and "↑" not in gravel

    def test_item_screen_and_intervention_usage(self, hills, client):
        rule = save_maintenance(hills.owner, MaintenanceRule, item=hills.chain, service_type=kind(hills), anchor_at=at(40),
                                elevation_gain_m=Decimal(3000))
        event = save_maintenance(hills.owner, ServiceEvent, item=hills.chain, service_type=kind(hills, "Limpieza"), performed_at=at(40))
        client.force_login(hills.owner)
        html, _ = html_of(client, "item-detail", hills.chain.pk)
        assert "<b>↑ 2.000</b><span>m de desnivel</span>" in html and "salidas sin desnivel: el desnivel es un mínimo." in html
        assert "↑ m de 3.000" in html and "de ↑ 3.000 m" in html, "the rule's elevation figures on the item screen"
        usage, _ = html_of(client, "service-event-detail", event.pk)
        assert "↑ ≥ 2.000 m" in usage and "Km, horas, salidas y desnivel (↑)" in usage
        assert rule.pk

    def test_span_text_leaves_unknown_elevation_out(self):
        known = SimpleNamespace(name="elevation_gain_m", value=Decimal(2000), display_value=Decimal(2000), estimated=False, complete=False)
        unknown = SimpleNamespace(**{**vars(known), "value": None})
        span = SimpleNamespace(metrics=(known,), days=Decimal(3))
        assert span_text(span) == "↑ ≥ 2.000 m · 3 días"
        assert span_text(SimpleNamespace(metrics=(unknown,), days=Decimal(3))) == "3 días · uso desconocido"

    def test_query_budgets_do_not_grow_with_elevation(self, garage, client):
        client.force_login(garage.owner)
        pages = (("index", ()), ("statistics", ()), ("bike-detail", (garage.road.pk,)), ("item-detail", (garage.chain.pk,)),
                 ("usage-ride-list", ()), ("history", ()))
        before = {name: html_of(client, name, *args)[1] for name, args in pages}
        for day in (40, 35, 25, 15):
            create_manual_ride(garage.owner, started_at=at(day), bike=garage.road, name=f"Subida {day}", distance_m=Decimal(1000),
                               elevation_gain_m=Decimal(100 + day))
        rebuild_usage(garage.owner)
        assert {name: html_of(client, name, *args)[1] for name, args in pages} == before

    def test_wear_names(self):
        headline = wear(due(metric("elevation_gain_m", "1000", "1100", "due", "partial"))).headline
        assert (headline.title, headline.unit, headline.big, headline.big_caption) == ("Desnivel", "m", "+100", "↑ m de más como mín.")
        assert headline.threshold_label == "↑ 1.000 m" and wear(due(metric())).headline.threshold_label == "3.000 km"


# Deferred minors of phases 1–2 ---------------------------------------------

@pytest.mark.django_db
def test_hints_arriving_in_the_last_round_get_a_fresh_worker(strava):
    from .services import strava_sync
    connected(strava)
    strava.fake.add(1, start=ago(40))
    strava.fake.add(2, start=ago(41))
    hint(1, "create")
    token = strava_sync._enter(ATHLETE)
    original = strava.fake.get

    def late_hint(url, **kwargs):
        if url.endswith("/activities/1"):
            hint(2, "create")
            assert not strava_sync._start_worker(ATHLETE)  # busy: the running worker is asked for one more round
        return original(url, **kwargs)
    with patch("garage.services.strava_client.requests.get", side_effect=late_hint), \
         patch("garage.services.strava_client.refresh_access_token", return_value="synthetic"), \
         patch("garage.services.strava_sync.threading.Thread") as thread:
        result = process_pending_events(ATHLETE, rounds=1, _token=token)
    assert result.settled == 1 and thread.call_count == 1, "the last round never swallows the request"
    assert thread.call_args.kwargs["target"] is strava_sync._process_in_thread
    assert StravaEvent.objects.filter(processed_at__isnull=True).get().object_id == 2


@pytest.mark.django_db
def test_a_full_batch_takes_another_round(strava):
    connected(strava)
    for key in (1, 2, 3):
        strava.fake.add(key, start=ago(40 + key))
        hint(key, "create")
    with strava.fake.serving(), patch("garage.services.strava_sync.threading.Thread") as thread:
        from .services import strava_sync
        result = process_pending_events(ATHLETE, limit=2, rounds=3, _token=strava_sync._enter(ATHLETE))
    assert result.settled == 3 and not StravaEvent.objects.filter(processed_at__isnull=True).exists()
    assert thread.call_count == 0 and ATHLETE not in strava_sync._workers


@pytest.mark.django_db
def test_a_full_batch_that_settles_nothing_is_not_repeated_at_once(strava):
    from .services import strava_sync
    from .tests_strava_client import FakeResponse
    connected(strava)
    stuck = [hint(key, "create") for key in (1, 2)]
    for key in (1, 2):
        strava.fake.script(f"/activities/{key}", *[FakeResponse(200, "[]")] * 3)  # not an activity: invalid_response
    with strava.fake.serving(), patch("garage.services.strava_sync.threading.Thread") as thread:
        result = process_pending_events(ATHLETE, limit=2, rounds=3, _token=strava_sync._enter(ATHLETE))
    assert result.settled == 0 and thread.call_count == 0
    for event in stuck:
        event.refresh_from_db()
        assert (event.attempts, event.error_code, event.processed_at) == (1, "invalid_response", None), "one attempt, not a burst"


@pytest.mark.django_db
def test_a_full_last_batch_goes_to_a_fresh_worker_but_a_sync_only_reports_it(strava):
    from .services import strava_sync
    connected(strava)
    for key in (1, 2, 3, 4, 5):
        strava.fake.add(key, start=ago(40 + key))
        hint(key, "create")
    with strava.fake.serving(), patch("garage.services.strava_sync.threading.Thread") as thread:
        assert process_pending_events(ATHLETE, limit=2, rounds=1, _token=strava_sync._enter(ATHLETE)).settled == 2
        assert thread.call_count == 1, "more than a batch pending: a background worker hands it on"
        strava_sync._workers.clear()
        assert process_pending_events(ATHLETE, limit=2).settled == 2
        assert thread.call_count == 1, "a sync press reports the rest as pending instead"
    assert StravaEvent.objects.filter(processed_at__isnull=True).count() == 1


@pytest.mark.django_db
def test_the_client_cuts_its_timeout_to_the_deadline(strava):
    strava.fake.add(7, start=ago(1))
    with strava.fake.serving():
        StravaClient(deadline=SimpleNamespace(left=lambda: 3.5)).activity(7)
        StravaClient(deadline=SimpleNamespace(left=lambda: 100)).activity(7)
        StravaClient().activity(7)
        calls = len(strava.fake.calls)
        with pytest.raises(StravaError) as error:
            StravaClient(deadline=SimpleNamespace(left=lambda: 0)).activity(7)
    assert error.value.code == "deadline" and len(strava.fake.calls) == calls, "no call starts without time left"
    assert [call.timeout for call in strava.fake.calls] == [(1.75, 1.75), TIMEOUT, TIMEOUT], "connect + read fit in what is left"
    with patch("garage.services.strava_client.requests.get", side_effect=requests.Timeout), \
         patch("garage.services.strava_client.refresh_access_token", return_value="synthetic"):
        with pytest.raises(StravaError) as cut:
            StravaClient(deadline=SimpleNamespace(left=lambda: 3.5)).activity(7)
        with pytest.raises(StravaError) as plain:
            StravaClient(deadline=SimpleNamespace(left=lambda: 100)).activity(7)
    assert (cut.value.code, plain.value.code) == ("deadline", "network")


@pytest.mark.django_db
def test_sync_now_answers_within_its_response_limit(strava):
    connected(strava)
    strava.fake.add(1, start=ago(1))
    pending = hint(60, "create")
    seen = []

    def slow(url, **kwargs):
        seen.append(kwargs["timeout"])
        if "/activities" in url:
            raise requests.Timeout  # what a timeout cut to the time left looks like
        return strava.fake.get(url, **kwargs)
    with patch("garage.services.strava_sync.RESPONSE_SECONDS", 10), \
         patch("garage.services.strava_client.requests.get", side_effect=slow), \
         patch("garage.services.strava_client.refresh_access_token", return_value="synthetic"):
        result = sync_now(strava.owner)
    assert (result.error, result.complete, result.pending, result.imported) == ("", False, 1, 0)
    assert seen and all(sum(timeout) <= 10 for timeout in seen), seen
    pending.refresh_from_db()
    assert pending.processed_at is None and pending.error_code == "", "out of time is not the hint's error"


@pytest.mark.django_db
def test_an_import_page_cut_by_the_time_limit_pauses_the_job(strava):
    from .services import rides, strava_sync
    connected(strava)
    run = rides.create_import_run(strava.owner, requested_from=ago(5), source_kind="strava")
    with patch("garage.services.strava_sync.RESPONSE_SECONDS", 10), \
         patch("garage.services.strava_client.requests.get", side_effect=requests.Timeout), \
         patch("garage.services.strava_client.refresh_access_token", return_value="synthetic"):
        run = strava_sync.resume_strava_import(strava.owner, run.pk)
    assert (run.state, run.cursor, run.errors) == ("paused", 0, []), "«Continuar» asks for the same page again"


@pytest.mark.django_db
def test_profiles_show_the_sport_label(garage, client):
    create_profile_history(garage.owner, name="Gravel de invierno", started_at=at(30), items=[garage.light], sport_type="gravel_ride")
    client.force_login(garage.owner)
    listing, _ = html_of(client, "usage-profile-list")
    assert "Gravel de invierno" in listing and "gravel_ride" not in listing and "· gravel ·" in listing
    profile = UsageProfile.objects.get(owner=garage.owner, name="Gravel de invierno")
    detail, _ = html_of(client, "usage-profile-detail", profile.pk)
    assert "gravel_ride" not in detail and "Todas mis bicis / sin bici · gravel" in detail
