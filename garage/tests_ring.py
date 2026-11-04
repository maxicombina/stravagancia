"""garage-050 F2a: the ring shows the piece, the chip says the state and its percent (spec §4.1, §4.2, D9, D21)."""
import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.conf import settings
from django.db import connection
from django.template.loader import render_to_string
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from test_support import contrast

from .models import Item, MaintenanceRule, ServiceType
from .presentation import STATES, ring, wear
from .services import maintenance_due as due_module
from .services.installations import create_installation
from .services.maintenance import save_maintenance
from .services.maintenance_due import MaintenanceDue, MaintenanceMetric
from .services.ownership import create_inventory
from .services.snoozes import snooze_rule
from .test_html import accessible_text, find_all, parse, row_by_href, visible_text
from .tests_mobile_home import at, garage  # noqa: F401 (fixture)
from .tests_ui_guards import stylesheet

WHEN = datetime(2026, 10, 16, 12, tzinfo=dt_timezone.utc)


def metric(value="1000000", *, name="distance_m", threshold="1000000", status="due", coverage="complete", estimated=False, missing=0, unrecorded=False):
    value = None if value is None else Decimal(value)
    threshold = Decimal(threshold)
    remaining = None if value is None else max(Decimal(0), threshold - value)
    return MaintenanceMetric(name, threshold, value, remaining, status, coverage, estimated, missing, unrecorded)


def piece(name="Cadena 11v", category="Cadenas", icon=""):
    return SimpleNamespace(pk=uuid4(), name=name, category=SimpleNamespace(name=category, icon=icon))


def snoozed_five_days():
    return SimpleNamespace(active=True, metrics=(metric("5", name="calendar_days", threshold="10", status="unknown"),))


def due_of(*metrics, item=None, bike=None, snooze=None):
    item = None if bike else item or piece()
    rule = SimpleNamespace(pk=uuid4(), item=item, bike=bike, item_id=item.pk if item else None, bike_id=bike.pk if bike else None,
                           service_type=SimpleNamespace(name="Cambio"))
    return MaintenanceDue(rule, None, WHEN, WHEN, tuple(metrics), "unknown", 0, 0, True, snooze)


def rendered_row(result):
    """The row of a rule, from the template every screen includes."""
    html = render_to_string("garage/_wear_row.html", {"alert": SimpleNamespace(wear=result, target=result.target, place="Carretera")})
    rows = find_all(parse(html), "a", cls="entry")
    assert len(rows) == 1
    return rows[0]


def chip_of(node):
    chips = find_all(node, "span", cls="chip")
    assert len(chips) == 1, chips
    return chips[0]


def classes(node):
    return set(node.attrs.get("class", "").split())


def ring_row(html, href):
    """The row with a ring that links to `href`: the bike's screen also lists the piece under «Montado ahora», without one."""
    rows = [row for row in find_all(parse(html), "a", cls="entry", href=href) if find_all(row, "svg", cls="ring")]
    assert len(rows) == 1, rows
    return rows[0]


def item_url(item):
    return reverse("garage:item-detail", args=[item.pk])


def rule_at(garage, percent, *, mounted=False, **thresholds):
    """A real rule of an item at `percent` % of 100 days. Half a day past, so that the seconds of the test never change the figure."""
    kind = save_maintenance(garage.owner, ServiceType, name=f"Tipo {percent}")
    item = create_inventory(garage.owner, Item, name=f"Bidón {percent}", category=garage.helmet.category)
    if mounted:
        create_installation(garage.owner, item=item, bike=garage.road, parent_item=None, started_at=at(5), ended_at=None, slot=f"s{percent}")
    rule = save_maintenance(garage.owner, MaintenanceRule, item=item, service_type=kind, calendar_days=100,
                            anchor_at=timezone.now() - timedelta(days=percent, hours=12), **thresholds)
    return item, rule


class TestOverClass:
    """D21: the shade of a due rule depends on the percent shown, so that color and figure never disagree."""

    @pytest.mark.parametrize("value,percent,expected", [
        ("1000000", 100, ""),
        ("1490000", 149, ""),
        ("1499900", 149, ""),  # 1,4999: shows 149, so it is not 150 yet
        ("1500000", 150, "over-150"),
        ("1990000", 199, "over-150"),
        ("1999999", 199, "over-150"),
        ("2000000", 200, "over-200"),
        ("3500000", 350, "over-200"),
    ])
    def test_due_by_the_percent_shown(self, value, percent, expected):
        result = wear(due_of(metric(value)))
        assert result.state == "due" and result.headline.percent == percent
        assert result.over_class == expected and result.headline.over_class == expected

    @pytest.mark.parametrize("args,state", [
        (dict(status="unknown", coverage="partial"), "review"),
        (dict(status="soon"), "soon"),
        (dict(status="current"), "current"),
    ])
    def test_only_a_due_state_deepens(self, args, state):
        result = wear(due_of(metric("2000000", **args)))
        assert result.state == state and result.headline.percent == 200
        assert result.over_class == "" and result.headline.over_class == ""

    def test_a_snoozed_rule_does_not_deepen(self):
        result = wear(due_of(metric("2000000"), snooze=snoozed_five_days()))
        assert result.state == "snoozed" and result.real_state == "due"
        assert result.over_class == ""

    @pytest.mark.parametrize("args,text", [(dict(coverage="partial"), "≥ 160 %"), (dict(estimated=True), "≈ 160 %")])
    def test_a_minimum_and_an_estimate_also_deepen(self, args, text):
        result = wear(due_of(metric("1600000", **args)))
        assert result.headline.percent_text == text and result.over_class == "over-150"

    @pytest.mark.parametrize("built", [
        metric("5", threshold="0"),  # no proportion: a threshold of 0
        metric(None, status="unknown", coverage="unknown"),
    ])
    def test_without_a_proportion_there_is_no_class(self, built):
        result = wear(due_of(built))
        assert result.headline.percent is None and result.over_class == "" and result.headline.over_class == ""

    def test_a_rule_without_metrics_has_no_class(self):
        result = wear(due_of())
        assert result.headline is None and result.over_class == ""


class TestPieceIcon:
    def test_the_category_icon_first(self):
        assert wear(due_of(metric(), item=piece("Cosa", "Otra", icon="bottle"))).piece_icon == "bottle"

    def test_deduced_from_the_name(self):
        assert wear(due_of(metric(), item=piece("Cadena 11v", "Varios"))).piece_icon == "chain"

    def test_the_generic_part_by_default(self):
        assert wear(due_of(metric(), item=piece("Cosa rara", "Varios"))).piece_icon == "part"

    def test_a_rule_of_a_bike_shows_the_bike(self):
        assert wear(due_of(metric(), bike=SimpleNamespace(pk=uuid4(), name="Carretera"))).piece_icon == "bike"


STATE_METRICS = {
    "due": (metric("1080000"), "108 %"),
    "review": (metric("950000", status="unknown", coverage="partial"), "≥ 95 %"),
    "soon": (metric("950000", status="soon"), "95 %"),
    "progress": (metric("620000", status="unknown", coverage="partial"), "≥ 62 %"),
    "current": (metric("140000", status="current"), "14 %"),
    "nodata": (metric(None, status="unknown", coverage="unknown"), None),
}


class TestChipOfTheRow:
    @pytest.mark.parametrize("state", list(STATE_METRICS))
    def test_icon_word_and_percent(self, state):
        built, percent = STATE_METRICS[state]
        row = rendered_row(wear(due_of(built)))
        chip = chip_of(row)
        assert classes(chip) == {"chip", f"st-{state}"} and classes(row) == {"entry", f"st-{state}"}
        assert [use.attrs["href"] for use in find_all(chip, "use")] == [f"#i-{STATES[state][1]}"]
        assert visible_text(chip) == (f"{STATES[state][0]} · {percent}" if percent else STATES[state][0])

    def test_postponed(self):
        row = rendered_row(wear(due_of(metric("1080000"), snooze=snoozed_five_days())))
        chip = chip_of(row)
        assert classes(chip) == {"chip", "st-snoozed"} and classes(row) == {"entry", "st-snoozed"}
        assert [use.attrs["href"] for use in find_all(chip, "use")] == [f"#i-{STATES['snoozed'][1]}"]
        assert visible_text(chip) == "Pospuesto · 108 %"

    def test_the_figure_of_the_chip_stays_whole_when_it_wraps(self):
        chip = chip_of(rendered_row(wear(due_of(metric("950000", status="unknown", coverage="partial")))))
        assert [visible_text(part) for part in find_all(chip, "span")] == ["≥ 95 %"]

    def test_the_chip_icon_is_hidden_from_screen_readers(self):
        chip = chip_of(rendered_row(wear(due_of(metric()))))
        assert len(find_all(chip, "svg", aria_hidden="true")) == 1

    @pytest.mark.parametrize("value,expected", [("1650000", "over-150"), ("2300000", "over-200")])
    def test_the_excess_is_on_the_row_and_on_the_chip(self, value, expected):
        row = rendered_row(wear(due_of(metric(value))))
        chip = chip_of(row)
        assert classes(row) == {"entry", "st-due", expected} and classes(chip) == {"chip", "st-due", expected}
        assert visible_text(chip) == f"Vencido · {int(Decimal(value) / 10000)} %"

    def test_a_snoozed_row_never_carries_the_excess(self):
        row = rendered_row(wear(due_of(metric("2300000"), snooze=snoozed_five_days())))
        assert classes(row) == {"entry", "st-snoozed"} and classes(chip_of(row)) == {"chip", "st-snoozed"}


class TestAccessibleText:
    @pytest.mark.parametrize("built,snooze,wanted", [
        (metric("950000", status="unknown", coverage="partial"), None, ("≥ 95 %", "km como máx.")),
        (metric("950000", status="unknown", estimated=True), None, ("≈ 95 %", "estimado")),
        (metric("397.27", name="calendar_days", threshold="365"), None, ("108 %", "+32", "días de más")),
        (metric("1030000", coverage="partial"), None, ("≥ 103 %", "como mín.")),
        (metric("1080000"), snoozed_five_days(), ("Pospuesto · 108 %", "Vencido · quedan 5 días")),
        (metric("500", name="elevation_gain_m", threshold="1000", status="unknown", coverage="partial", missing=2), None, ("≥ 50 %", "2 sin desnivel")),
    ])
    def test_says_what_each_state_needs(self, built, snooze, wanted):
        text = accessible_text(rendered_row(wear(due_of(built, snooze=snooze))))
        for piece_of_text in wanted:
            assert piece_of_text in text, text

    def test_no_data_says_no_percent(self):
        text = accessible_text(rendered_row(wear(due_of(metric(None, status="unknown", coverage="unknown")))))
        assert "Sin datos" in text and "sin datos" in text and "%" not in text

    def test_no_ride_with_elevation(self):
        built = metric(None, name="elevation_gain_m", threshold="1000", status="unknown", coverage="unknown", unrecorded=True)
        text = accessible_text(rendered_row(wear(due_of(built))))
        assert "ninguna salida con desnivel" in text and "%" not in text

    def test_the_percent_is_read_only_once(self):
        row = rendered_row(wear(due_of(metric("950000", status="unknown", coverage="partial"))))
        assert accessible_text(row).count("≥ 95 %") == 1

    def test_a_minimum_is_visible(self):
        assert "≥" in visible_text(rendered_row(wear(due_of(metric("950000", status="unknown", coverage="partial")))))


class TestRing:
    def test_shows_the_piece_and_no_figure(self):
        row = rendered_row(wear(due_of(metric(), item=piece("Cosa", "Otra", icon="bottle"))))
        rings = find_all(row, "svg", cls="ring", aria_hidden="true")
        assert len(rings) == 1
        assert [use.attrs["href"] for use in find_all(rings[0], "use", cls="ring-glyph")] == ["#i-bottle"]
        assert find_all(rings[0], "text") == []

    def test_past_the_threshold_the_arc_is_full_and_the_chip_says_how_much(self):
        row = rendered_row(wear(due_of(metric("1160000"))))
        arcs = find_all(row, "circle", cls="arc")
        assert [arc.attrs["stroke-dasharray"] for arc in arcs] == [ring(Decimal(1), 22)]
        assert visible_text(chip_of(row)) == "Vencido · 116 %"

    def test_no_arc_at_zero(self):
        row = rendered_row(wear(due_of(metric("0", status="current"))))
        assert find_all(row, "circle", cls="arc") == [] and len(find_all(row, "circle", cls="trk")) == 1
        assert visible_text(chip_of(row)) == "Al día · 0 %"

    def test_a_rule_without_metrics_has_no_arc_and_does_not_break(self):
        row = rendered_row(wear(due_of()))
        assert find_all(row, "circle", cls="arc") == [] and len(find_all(row, "circle", cls="trk")) == 1
        assert visible_text(chip_of(row)) == "Sin datos"
        assert visible_text(find_all(row, "span", cls="big")[0]) == "—"


@pytest.mark.parametrize("page", ["index", "maintenance", "bike"])
class TestScreens:
    def get(self, garage, client, page):
        client.force_login(garage.owner)
        url = reverse("garage:bike-detail", args=[garage.road.pk]) if page == "bike" else reverse(f"garage:{page}")
        response = client.get(url)
        assert response.status_code == 200
        return response.content.decode()

    def test_the_row_of_a_piece_has_its_icon_inside_the_ring(self, garage, client, page):
        row = ring_row(self.get(garage, client, page), item_url(garage.chain))
        rings = find_all(row, "svg", cls="ring", aria_hidden="true")
        assert len(rings) == 1
        assert len(find_all(rings[0], "use", href="#i-chain")) == 1

    @pytest.mark.parametrize("percent,expected", [(149, set()), (165, {"over-150"}), (230, {"over-200"})])
    def test_the_excess_on_a_real_row(self, garage, client, page, percent, expected):
        item, _ = rule_at(garage, percent, mounted=True)
        row = ring_row(self.get(garage, client, page), item_url(item))
        chip = chip_of(row)
        assert classes(row) == {"entry", "st-due"} | expected and classes(chip) == {"chip", "st-due"} | expected
        assert visible_text(chip) == f"Vencido · {percent} %"  # the word does not change, and the percent is in the chip of this row


class TestBikeRule:
    def test_the_row_of_a_bike_rule_shows_the_bike(self, garage, client):
        kind = save_maintenance(garage.owner, ServiceType, name="Lavado")
        rule = save_maintenance(garage.owner, MaintenanceRule, bike=garage.road, service_type=kind, calendar_days=10, anchor_at=at(30))
        client.force_login(garage.owner)
        html = client.get(reverse("garage:bike-detail", args=[garage.road.pk])).content.decode()
        row = row_by_href(html, reverse("garage:maintenance-rule-snooze", args=[rule.pk]))
        assert len(find_all(row, "use", cls="ring-glyph", href="#i-bike")) == 1


class TestLargeGauge:
    def page(self, garage, client, item):
        client.force_login(garage.owner)
        response = client.get(item_url(item))
        assert response.status_code == 200
        return parse(response.content.decode())

    def gauge_chip(self, panel):
        return find_all(find_all(panel, "div", cls="gauge")[0], "span", cls="chip")[0]

    @pytest.mark.parametrize("percent,expected", [(149, set()), (165, {"over-150"}), (230, {"over-200"})])
    def test_the_panel_its_chip_and_its_metric_carry_the_excess(self, garage, client, percent, expected):
        item, _ = rule_at(garage, percent)
        panel = find_all(self.page(garage, client, item), "section", cls="panel st-due")[0]
        chip = self.gauge_chip(panel)
        assert classes(panel) == {"panel", "st-due"} | expected and classes(chip) == {"chip", "st-due"} | expected
        assert visible_text(chip).startswith(f"Vencido · {percent} %")
        metrics = find_all(find_all(panel, "div", cls="trio")[0], "div", cls="st-due")
        assert [classes(entry) for entry in metrics] == [{"st-due"} | expected]

    def test_each_metric_says_its_own(self, garage, client):
        item, _ = rule_at(garage, 230, ride_count=500)
        panel = find_all(self.page(garage, client, item), "section", cls="panel st-due")[0]
        entries = [node for node in find_all(panel, "div", cls="trio")[0].children if not isinstance(node, str)]
        assert len(entries) == 2
        assert {"st-due", "over-200"} in [classes(entry) for entry in entries]
        assert not any("over-200" in classes(entry) or "over-150" in classes(entry) for entry in entries if "st-due" not in classes(entry))

    def test_a_snoozed_rule_is_never_deepened(self, garage, client):
        item, rule = rule_at(garage, 230)
        snooze_rule(garage.owner, rule, calendar_days=5)
        panel = find_all(self.page(garage, client, item), "section", cls="panel st-snoozed")[0]
        assert classes(panel) == {"panel", "st-snoozed"} and classes(self.gauge_chip(panel)) == {"chip", "st-snoozed"}
        assert visible_text(self.gauge_chip(panel)).startswith("Pospuesto · 230 %")
        assert not [node for node in find_all(panel, "div") if classes(node) & {"over-150", "over-200"}]

    def rule_without_data(self, garage, **thresholds):
        kind = save_maintenance(garage.owner, ServiceType, name="Tipo sin datos")
        item = create_inventory(garage.owner, Item, name="Pieza sin datos", category=garage.helmet.category)
        return item, save_maintenance(garage.owner, MaintenanceRule, item=item, service_type=kind, **thresholds)

    @pytest.mark.parametrize("thresholds,threshold", [({"elevation_gain_m": 1000}, "1.000"), ({"calendar_days": 1825}, "1.825")])
    def test_without_data_the_chip_says_so_with_no_percent(self, garage, client, thresholds, threshold):
        """§4.1, as the row of a rule does. The threshold stays where the metric is, and in what the gauge says aloud."""
        item, _ = self.rule_without_data(garage, **thresholds)
        panel = find_all(self.page(garage, client, item), "section", cls="panel st-nodata")[0]
        chip = self.gauge_chip(panel)
        assert visible_text(chip) == "Sin datos" and accessible_text(chip) == "Sin datos"
        assert threshold in visible_text(find_all(panel, "div", cls="trio")[0])
        assert threshold in find_all(panel, "svg", role="img")[0].attrs["aria-label"]

    def test_with_a_percent_the_chip_keeps_its_threshold(self, garage, client):
        item, _ = rule_at(garage, 230)
        panel = find_all(self.page(garage, client, item), "section", cls="panel st-due")[0]
        assert visible_text(self.gauge_chip(panel)) == "Vencido · 230 % de 100 días"

    def test_a_minimum_is_in_the_chip_and_not_in_the_label(self, garage, client):
        panel = find_all(self.page(garage, client, garage.chain), "section", cls="panel st-review")[0]
        label = find_all(panel, "svg", role="img")[0].attrs["aria-label"]
        assert "≥" not in label and "%" not in label
        assert "≥ 95 %" in visible_text(self.gauge_chip(panel))

    def test_an_estimate_is_in_the_chip_and_not_in_the_label(self, garage, client, monkeypatch):
        real = due_module.maintenance_due

        def estimated(*args, **kwargs):
            return tuple(replace(due, metrics=tuple(replace(one, is_estimated=True) for one in due.metrics)) for due in real(*args, **kwargs))
        monkeypatch.setattr(due_module, "maintenance_due", estimated)
        panel = find_all(self.page(garage, client, garage.chain), "section", cls="panel st-review")[0]
        label = find_all(panel, "svg", role="img")[0].attrs["aria-label"]
        assert "≈" not in label and "%" not in label
        assert "≈ 95 %" in visible_text(self.gauge_chip(panel))


class TestLongFigureInTheLargeGauge:
    """36 px hold 5 characters. A longer figure would cross the ring, of its own color from 200 % (D21), and lose its first and last digits."""

    @pytest.mark.parametrize("built,figure,expected", [
        (metric("1450000"), "+450", ""),
        (metric("0", threshold="7256000", status="current"), "7.256", ""),
        (metric("0", threshold="10000000", status="current"), "10.000", "long"),
        (metric("4000000"), "+3.000", "long"),
        (metric("34600", name="elevation_gain_m", threshold="10000"), "+24.600", "longer"),
        (metric("0", threshold="100000000", status="current"), "100.000", "longer"),
        (metric("125600000"), "+124.600", "longest"),
        (metric("1235567000"), "+1.234.567", "longest"),
        (metric(None, status="unknown"), "—", ""),
    ])
    def test_the_longer_the_figure_the_smaller_its_type(self, built, figure, expected):
        headline = wear(due_of(built)).headline
        assert headline.big == figure and headline.big_class == expected

    def test_on_the_screen_of_a_piece(self, garage, client):
        item, _ = rule_at(garage, 3100)
        client.force_login(garage.owner)
        root = parse(client.get(item_url(item)).content.decode())
        figures = find_all(root, "text", cls="g-num")
        assert [(visible_text(one), classes(one)) for one in figures] == [("+3.000", {"g-num", "long"})]

    def test_each_length_has_a_smaller_type_than_the_one_before(self):
        css = stylesheet()
        assert "36px" in contrast.declared(css, ".gauge .g-num")["font"]
        sizes = [36] + [int(contrast.declared(css, f".gauge .g-num.{name}")["font-size"].removesuffix("px")) for name in ("long", "longer", "longest")]
        assert sizes == sorted(set(sizes), reverse=True)

    def test_what_still_touches_the_ring_keeps_a_halo(self):
        """Nothing limits a figure: «+1.234.567» still reaches the ring, and with its own color only the halo keeps it legible."""
        figure = contrast.declared(stylesheet(), ".gauge .g-num")
        assert figure["paint-order"] == "stroke" and figure["stroke"] == "var(--surface)"


class TestOtherChipsOfARule:
    """The same rule, with the same word, must not change color from one chip to the next (D21: wherever a due state is painted)."""

    def test_mounted_now(self, garage, client):
        item, _ = rule_at(garage, 230, mounted=True)
        client.force_login(garage.owner)
        html = client.get(reverse("garage:bike-detail", args=[garage.road.pk])).content.decode()
        rows = [row for row in find_all(parse(html), "a", cls="entry compact", href=item_url(item))]
        assert len(rows) == 1 and classes(chip_of(rows[0])) == {"chip", "st-due", "over-200"}

    def test_parts_of_an_item(self, garage, client):
        item, _ = rule_at(garage, 165)
        create_installation(garage.owner, item=item, bike=None, parent_item=garage.chain, started_at=at(5), ended_at=None, slot=None)
        client.force_login(garage.owner)
        html = client.get(item_url(garage.chain)).content.decode()
        rows = [row for row in find_all(parse(html), "a", cls="entry compact", href=item_url(item))]
        assert len(rows) == 1 and classes(chip_of(rows[0])) == {"chip", "st-due", "over-150"}

    def test_also_in_this_visit(self, garage, client):
        rule_at(garage, 230, mounted=True)
        client.force_login(garage.owner)
        html = client.get(reverse("garage:service-event-create") + f"?bike={garage.road.pk}").content.decode()
        chips = find_all(find_all(parse(html), "fieldset", cls="together")[0], "span", cls="chip st-due over-200")
        assert [visible_text(chip) for chip in chips] == ["Vencido"]

    @pytest.mark.parametrize("snoozed", [False, True])
    def test_the_postpone_screen_shows_the_real_state_with_its_figure(self, garage, client, snoozed):
        _, rule = rule_at(garage, 230)
        if snoozed:
            snooze_rule(garage.owner, rule, calendar_days=5)
        client.force_login(garage.owner)
        root = parse(client.get(reverse("garage:maintenance-rule-snooze", args=[rule.pk])).content.decode())
        panel = find_all(root, "section", cls="panel st-due")[0]
        assert classes(panel) == {"panel", "st-due", "over-200"} and classes(chip_of(panel)) == {"chip", "st-due", "over-200"}
        assert visible_text(chip_of(panel)) == "Vencido" and "230 %" in visible_text(panel)

    def test_the_percent_on_the_postpone_screen_stays_whole(self, garage, client):
        """Outside a chip nothing else holds it: at 320 px it left «110» on a line and «% de 365 días» on the next."""
        _, rule = rule_at(garage, 110)
        client.force_login(garage.owner)
        root = parse(client.get(reverse("garage:maintenance-rule-snooze", args=[rule.pk])).content.decode())
        panel = find_all(root, "section", cls="panel st-due")[0]
        assert [visible_text(span) for span in find_all(panel, "span", cls="nowrap")] == ["110 %"]
        assert contrast.declared(stylesheet(), ".nowrap") == {"white-space": "nowrap"}

    def test_a_snoozed_chip_outside_the_row_is_not_deepened(self, garage, client):
        item, rule = rule_at(garage, 230, mounted=True)
        snooze_rule(garage.owner, rule, calendar_days=5)
        client.force_login(garage.owner)
        html = client.get(reverse("garage:bike-detail", args=[garage.road.pk])).content.decode()
        rows = find_all(parse(html), "a", cls="entry compact", href=item_url(item))
        assert len(rows) == 1 and classes(chip_of(rows[0])) == {"chip", "st-snoozed"}


class TestStateIconsAreHidden:
    """§4.2: the word in the chip says it; to a screen reader the icon beside it is only noise."""

    def assert_hidden(self, root):
        chips = find_all(root, "span", cls="chip") + find_all(root, "span", cls="trio-state")
        assert chips
        for chip in chips:
            assert len(find_all(chip, "svg", aria_hidden="true")) == len(find_all(chip, "svg")), chip

    def test_on_the_screen_of_a_piece(self, garage, client):
        item, _ = rule_at(garage, 230, ride_count=500)  # Two metrics: each says its own state.
        create_installation(garage.owner, item=garage.helmet, bike=None, parent_item=item, started_at=at(5), ended_at=None, slot=None)
        kind = save_maintenance(garage.owner, ServiceType, name="Tipo casco")
        save_maintenance(garage.owner, MaintenanceRule, item=garage.helmet, service_type=kind, calendar_days=1, anchor_at=at(30))
        client.force_login(garage.owner)
        root = parse(client.get(item_url(item)).content.decode())
        assert find_all(root, "span", cls="trio-state") and find_all(root, "a", cls="entry compact", href=item_url(garage.helmet))
        self.assert_hidden(root)

    def test_on_the_screen_of_a_bike(self, garage, client):
        rule_at(garage, 230, mounted=True)
        client.force_login(garage.owner)
        self.assert_hidden(parse(client.get(reverse("garage:bike-detail", args=[garage.road.pk])).content.decode()))

    def test_on_the_postpone_screen(self, garage, client):
        _, rule = rule_at(garage, 230)
        client.force_login(garage.owner)
        self.assert_hidden(parse(client.get(reverse("garage:maintenance-rule-snooze", args=[rule.pk])).content.decode()))

    def test_in_every_template(self):
        """Also what no fixture reaches: a chip or a state with an icon, in the source of each template."""
        chip = re.compile(r'class="(?:chip st-|trio-state)[^>]*>\s*(<svg [^>]*>)')
        found = [(path.name, tag) for path in Path(settings.BASE_DIR, "garage/templates/garage").glob("*.html")
                 for tag in chip.findall(path.read_text(encoding="utf-8"))]
        assert found and [one for one in found if 'aria-hidden="true"' not in one[1]] == []


class TestQueryCount:
    """The icon reads each rule's item.category: without it in the snapshot, a query per row (spec §4.1)."""

    def rule_rows(self, html):
        return [row for row in find_all(parse(html), "a", cls="entry") if find_all(row, "svg", cls="ring")]

    def add_due_rules(self, garage):
        kind = save_maintenance(garage.owner, ServiceType, name="Revisión extra")
        for number in range(8):
            item = create_inventory(garage.owner, Item, name=f"Extra {number}", category=garage.helmet.category)
            save_maintenance(garage.owner, MaintenanceRule, item=item, service_type=kind, calendar_days=1, anchor_at=at(30))

    def measure(self, client, url):
        with CaptureQueriesContext(connection) as queries:
            response = client.get(url)
        assert response.status_code == 200
        return response.content.decode(), len(queries)

    def test_home(self, garage, client):
        client.force_login(garage.owner)
        url = reverse("garage:index")
        self.measure(client, url)  # the first one fills what stays cached
        html, before = self.measure(client, url)
        assert len(self.rule_rows(html)) == 2
        self.add_due_rules(garage)
        html, after = self.measure(client, url)
        assert len(self.rule_rows(html)) == 6
        assert after == before, (before, after)

    def test_workshop(self, garage, client):
        client.force_login(garage.owner)
        url = reverse("garage:maintenance")
        self.measure(client, url)
        html, before = self.measure(client, url)
        rows = len(self.rule_rows(html))
        self.add_due_rules(garage)
        html, after = self.measure(client, url)
        assert len(self.rule_rows(html)) == rows + 8
        assert after == before, (before, after)
