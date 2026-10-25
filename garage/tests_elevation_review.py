"""garage-030 phase 3, code review fixes: Spanish thousands in whole-number inputs, the time cap of
one Strava call, and rides without elevation shown as unknown or as a minimum on rule, statistics
and home screens. The lenient optional FIT fields are tested in tests_elevation_power."""
import re
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django import forms

from .lifespan_forms import LifespanForm
from .maintenance_forms import DecimalInput, MaintenanceRuleWebForm, WholeNumberInput
from .models import Bike, MaintenanceRule, ServiceType
from .presentation import wear
from .services.maintenance import save_maintenance
from .services.ownership import create_inventory
from .services.rides import create_manual_ride
from .services.strava_client import TIMEOUT, StravaClient
from .services.workshop import nodata_reason
from .snooze_forms import SnoozeForm
from .tests_elevation_screens import due_of, elevation_of, hills, html_of, kind, road_rule  # noqa: F401 (fixture hills)
from .tests_mobile_home import at, garage  # noqa: F401 (fixture garage)

HINT = "Volver a importar los FIT o el histórico de Strava completa el desnivel de las salidas anteriores."
INVALID_METRES = "Introduce metros enteros, sin decimales (1500 o 1.500)."
# Django's IntegerField read '1.000' as 1 and '20.000' as 20: a rule or snooze 1000 times smaller.
THOUSANDS = [("1.000", 1000), ("20.000", 20000), ("1.000.000", 1000000), ("20 000", 20000), ("20 000", 20000),
             ("20 000", 20000), (" 1500 ", 1500), ("1500", 1500), ("+2.000", 2000)]
DECIMALS = ["1.5", "1,5", "2,000", "1.000,0", "0.500", "1.0", "1.00", "20.0000", "1e3", ".5", "1."]


def rule_form(g, **data):
    service_type = ServiceType.objects.filter(owner=g.owner, name="Revisión de frenos").first() or kind(g)
    return MaintenanceRuleWebForm({"bike": g.road.pk, "service_type": service_type.pk, "time_zone": "UTC", **data}, user=g.owner)


def snooze_form(**data):
    return SnoozeForm({"calendar_days": "30", **data})


def lifespan_form(**data):
    return LifespanForm({"start": "2026-01-01T00:00", "time_zone": "UTC", "time_unit": "days", **data})


# Whole-number inputs ---------------------------------------------------------------

@pytest.mark.parametrize("typed,metres", THOUSANDS)
def test_spanish_thousands_are_metres_on_every_elevation_form(garage, typed, metres):
    rule = rule_form(garage, elevation_gain_m=typed)
    assert rule.is_valid(), rule.errors
    snooze = snooze_form(elevation_gain_m=typed)
    assert snooze.is_valid(), snooze.errors
    life = lifespan_form(elevation_gain_m=typed)
    assert life.is_valid(), life.errors
    for value in (rule.cleaned_data["elevation_gain_m"], snooze.amounts["elevation_gain_m"], life.lifespan["elevation_gain_m"]):
        assert type(value) is Decimal and value == Decimal(metres)


@pytest.mark.parametrize("typed", DECIMALS)
def test_decimals_are_rejected_never_truncated(garage, typed):
    for form in (rule_form(garage, elevation_gain_m=typed), snooze_form(elevation_gain_m=typed), lifespan_form(elevation_gain_m=typed)):
        assert not form.is_valid() and form.errors["elevation_gain_m"] == [INVALID_METRES], (typed, type(form).__name__)


def test_rides_days_and_time_read_thousands_too(garage):
    rule = rule_form(garage, ride_count="1.000", calendar_days="1.000")
    assert rule.is_valid(), rule.errors
    assert (rule.cleaned_data["ride_count"], rule.cleaned_data["calendar_days"]) == (1000, 1000)
    assert rule.save().ride_count == 1000
    snooze = snooze_form(ride_count="1.000", calendar_days="1.000")
    assert snooze.is_valid(), snooze.errors
    assert (snooze.amounts["ride_count"], snooze.amounts["calendar_days"]) == (1000, 1000)
    life = lifespan_form(time_value="1.000")
    assert life.is_valid(), life.errors
    assert life.lifespan["calendar_days"] == 1000
    for form, field in ((rule_form(garage, ride_count="1.0"), "ride_count"), (rule_form(garage, calendar_days="2,5"), "calendar_days"),
                        (snooze_form(calendar_days="30.0"), "calendar_days"), (snooze_form(ride_count="1.5"), "ride_count"),
                        (lifespan_form(time_value="1.5"), "time_value")):
        assert not form.is_valid() and form.errors[field] == ["Introduce un número entero."], (field, form.errors)
    assert not snooze_form(calendar_days="36.501").is_valid(), "36.501 días is beyond the 100-year maximum, not 36"


def test_whole_number_inputs_are_text_with_a_numeric_keypad(garage, client):
    for form, names in ((rule_form(garage), ("ride_count", "calendar_days", "elevation_gain_m")),
                        (SnoozeForm(), ("ride_count", "calendar_days", "elevation_gain_m")),
                        (LifespanForm(), ("time_value", "elevation_gain_m"))):
        for name in names:
            field = form.fields[name]
            assert type(field) is WholeNumberInput and type(field.widget) is forms.TextInput, name
            assert field.widget.attrs["inputmode"] == "numeric" and "min" not in field.widget.attrs, name
    client.force_login(garage.owner)
    html, _ = html_of(client, "maintenance-rule-create")
    for name in ("ride_count", "calendar_days", "elevation_gain_m"):
        assert re.search(rf'<input type="text" name="{name}"[^>]*inputmode="numeric"', html), name
        assert f'type="number" name="{name}"' not in html, name


def test_a_decimal_elevation_set_in_the_admin_is_read_the_spanish_way(garage):
    """Re-verification of the review: the exact field kept for a fractional value must not read «2.000» as 2 m either."""
    rule = road_rule(garage, elevation_gain_m=Decimal("1234.5"))
    shown = MaintenanceRuleWebForm(user=garage.owner, instance=rule)
    assert type(shown.fields["elevation_gain_m"]) is DecimalInput and shown.initial["elevation_gain_m"] == Decimal("1234.5")
    assert 'value="1234,5"' in str(shown["elevation_gain_m"]) and 'inputmode="decimal"' in str(shown["elevation_gain_m"])
    base = {"bike": garage.road.pk, "service_type": rule.service_type_id, "time_zone": "UTC"}
    ambiguous = MaintenanceRuleWebForm({**base, "elevation_gain_m": "2.000"}, user=garage.owner, instance=rule)
    assert not ambiguous.is_valid() and ambiguous.errors["elevation_gain_m"][0].startswith("¿Miles o decimales?")
    too_fine = MaintenanceRuleWebForm({**base, "elevation_gain_m": "1,2345"}, user=garage.owner, instance=rule)
    assert not too_fine.is_valid() and too_fine.errors["elevation_gain_m"] == ["Como máximo 3 decimales."]
    for typed, metres in (("1.234,5", "1234.5"), ("1234.5", "1234.5"), ("2.000,0", "2000"), ("3000", "3000")):
        kept = MaintenanceRuleWebForm({**base, "elevation_gain_m": typed}, user=garage.owner, instance=rule)
        assert kept.is_valid(), (typed, kept.errors)
        assert kept.cleaned_data["elevation_gain_m"] == Decimal(metres), typed
    assert kept.save().elevation_gain_m == Decimal(3000)  # ModelForm.save() writes the whole value back to `rule`


def test_the_admin_rule_form_keeps_its_plain_fields():
    from .maintenance_forms import MaintenanceRuleForm
    assert type(MaintenanceRuleForm.base_fields["ride_count"]) is forms.IntegerField


# Time cap of one Strava call ---------------------------------------------------------

@pytest.mark.parametrize("left", [0.01, 1, 3.5, 6, 10, 24, 24.9, 25, 29.99])
def test_connect_and_read_add_up_to_what_is_left(left):
    timeout, cut = StravaClient(deadline=SimpleNamespace(left=lambda: left))._timeout()
    # requests waits for the connection and then for the answer: both together fit in what is left.
    assert sum(timeout) <= left + 1e-9 and min(timeout) > 0, timeout
    assert cut == (left < sum(TIMEOUT)) and timeout[0] <= TIMEOUT[0] and timeout[1] <= TIMEOUT[1]


def test_the_cut_only_applies_when_time_is_short():
    assert StravaClient(deadline=SimpleNamespace(left=lambda: 100))._timeout() == (TIMEOUT, False)
    assert StravaClient()._timeout() == (TIMEOUT, False)
    assert StravaClient(deadline=SimpleNamespace(left=lambda: 6))._timeout() == ((3, 3), True)
    assert StravaClient(deadline=SimpleNamespace(left=lambda: 24))._timeout() == ((5, 19), True)


# Rides without elevation ------------------------------------------------------------------

class TestRidesWithoutElevation:
    def test_an_interval_where_no_ride_has_elevation_is_unknown_not_zero(self, hills, client):
        rule = save_maintenance(hills.owner, MaintenanceRule, bike=hills.gravel, service_type=kind(hills), anchor_at=at(40),
                                elevation_gain_m=Decimal(1000))
        entry = due_of(hills.owner, rule)
        climb = elevation_of(entry)
        assert (climb.value, climb.status, climb.coverage, climb.missing_values, climb.unrecorded) == (None, "unknown", "unknown", 1, True)
        shown = wear(entry)
        assert shown.state == "nodata" and shown.headline.percent_text == "?" and shown.headline.unrecorded
        assert shown.headline.missing_text == "" and shown.elevation is shown.headline
        assert nodata_reason(entry) == "Ninguna salida desde la referencia registra desnivel: vuelve a importar sus FIT o el histórico de Strava."
        client.force_login(hills.owner)
        shop, _ = html_of(client, "maintenance")
        assert "Ninguna salida desde la referencia registra desnivel: vuelve a importar sus FIT o el histórico de Strava." in shop
        page, _ = html_of(client, "maintenance-rule-snooze", rule.pk)
        assert "Ninguna salida desde la referencia registra desnivel: no se sabe cuánto lleva. " + HINT in page
        # One ride with elevation: a known minimum again, with the count of those without it.
        create_manual_ride(hills.owner, started_at=at(2), bike=hills.gravel, name="Con altímetro", distance_m=Decimal(10000),
                           elevation_gain_m=Decimal(300))
        entry = due_of(hills.owner, rule)
        climb = elevation_of(entry)
        assert (climb.value, climb.missing_values, climb.unrecorded) == (Decimal(300), 1, False)
        assert wear(entry).state == "progress" and wear(entry).headline.missing_text == "1 sin desnivel"
        assert nodata_reason(entry) == "Sin datos de uso desde la referencia."

    def test_an_interval_without_rides_is_still_an_observed_zero(self, hills):
        rule = save_maintenance(hills.owner, MaintenanceRule, bike=hills.gravel, service_type=kind(hills), anchor_at=at(15),
                                elevation_gain_m=Decimal(1000))
        climb = elevation_of(due_of(hills.owner, rule))
        assert (climb.value, climb.missing_values, climb.unrecorded) == (Decimal(0), 0, False)
        assert wear(due_of(hills.owner, rule)).headline.percent_text == "≥ 0 %"

    def test_other_metrics_keep_counting_rides_without_them_as_a_minimum(self, hills):
        rule = save_maintenance(hills.owner, MaintenanceRule, bike=hills.gravel, service_type=kind(hills), anchor_at=at(40),
                                distance_m=Decimal(1000000), elevation_gain_m=Decimal(1000))
        entry = due_of(hills.owner, rule)
        distance = next(metric for metric in entry.metrics if metric.name == "distance_m")
        assert (distance.value, distance.unrecorded) == (Decimal(50000), False)
        assert wear(entry).state == "nodata", "the elevation threshold could already be reached: never «en curso»"

    def test_a_partial_interval_says_how_many_lack_it(self, hills, client):
        rule = road_rule(hills, elevation_gain_m=Decimal(5000))  # [at(60), NOW): 2.000 m, 2 rides without elevation
        shown = wear(due_of(hills.owner, rule))
        assert shown.headline.name == "elevation_gain_m" and shown.headline.missing_text == "2 sin desnivel"
        client.force_login(hills.owner)
        bike, _ = html_of(client, "bike-detail", hills.road.pk)
        assert '<span class="note">2 sin desnivel</span>' in bike
        page, _ = html_of(client, "maintenance-rule-snooze", rule.pk)
        assert "2 salidas sin desnivel: el desnivel es un mínimo. " + HINT in page
        save_maintenance(hills.owner, MaintenanceRule, item=hills.chain, service_type=kind(hills, "Otra"), anchor_at=at(60),
                         elevation_gain_m=Decimal(5000))
        item, _ = html_of(client, "item-detail", hills.chain.pk)
        assert "↑ m de 5.000 · mínimo · 2 sin desnivel" in item and "2 salidas sin desnivel: el desnivel es un mínimo. " + HINT in item

    def test_known_elevation_shows_no_marker(self, hills, client):
        rule = save_maintenance(hills.owner, MaintenanceRule, bike=hills.road, service_type=kind(hills), anchor_at=at(9),
                                elevation_gain_m=Decimal(5000))  # only the 800 m ride
        shown = wear(due_of(hills.owner, rule))
        assert shown.headline.missing_text == "" and not shown.headline.unrecorded
        client.force_login(hills.owner)
        page, _ = html_of(client, "maintenance-rule-snooze", rule.pk)
        assert "el desnivel es un mínimo" not in page and "no se sabe cuánto lleva" not in page and HINT not in page

    def test_statistics_rows_chart_and_home_mark_a_minimum(self, hills, client):
        mountain = create_inventory(hills.owner, Bike, name="Montaña")
        create_manual_ride(hills.owner, started_at=at(6), bike=mountain, name="Puerto completo", distance_m=Decimal(30000),
                           moving_time_s=Decimal(3600), elevation_gain_m=Decimal(500))
        client.force_login(hills.owner)
        html, _ = html_of(client, "statistics")
        # Carretera and its chain: 2.000 m known, 4 rides without it; Montaña's only ride has it.
        assert "Carretera</span>" in html and "· ↑ ≥ 2.000 m" in html and "1 h · ↑ 500 m" in html and "↑ ≥ 500 m" not in html
        assert "7 sin desnivel: el desnivel es un mínimo. " + HINT in html
        assert "no registran desnivel" not in html, "the km chart says nothing about elevation"
        chart, _ = html_of(client, "statistics", chart="elevation")
        assert "7 salidas de estos meses no registran desnivel: lo mostrado es un mínimo. " + HINT in chart
        home, _ = html_of(client, "index")
        assert "h · ↑ ≥ 2.000 m" in home and "1 h · ↑ 500 m" in home
