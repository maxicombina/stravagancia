"""garage-050 F2b: «Revisar» wears the magnifier, so the icon alone tells it from «Próximo» (spec D8, §4.2)."""
import re
from decimal import Decimal
from pathlib import Path

import pytest
from django.conf import settings
from django.template import Context, Template
from django.urls import reverse

from .presentation import STATES
from .services.rides import create_manual_ride
from .test_html import accessible_text, find_all, parse, row_by_href, visible_text
from .tests_categories import SPRITE
from .tests_mobile_home import at, garage  # noqa: F401 (fixture)


def sprite():
    return (Path(settings.BASE_DIR) / SPRITE).read_text()


def hrefs(node):
    return [use.attrs["href"] for use in find_all(node, "use")]


def filtered(state):
    """The word and the icon a template gets for `state`, through the filters it would load."""
    template = Template("{% load garage_ui %}{{ state|state_word }}|{{ state|state_icon }}")
    return template.render(Context({"state": state})).split("|")


def page(client, owner, url_name, **params):
    client.force_login(owner)
    response = client.get(reverse(url_name), params)
    assert response.status_code == 200
    return response.content.decode()


def review_chip(node):
    chips = find_all(node, "span", cls="chip st-review")
    assert len(chips) == 1, chips
    return chips[0]


class TestStatesAndSprite:
    @pytest.mark.parametrize("state", STATES)
    def test_the_icon_of_every_state_has_its_symbol(self, state):
        assert re.search(rf'<symbol id="i-{STATES[state][1]}" viewBox="0 0 24 24">', sprite())

    def test_review_is_the_magnifier_and_soon_keeps_the_triangle(self):
        assert STATES["review"] == ("Revisar", "search") and STATES["soon"] == ("Próximo", "alert")

    def test_no_two_states_share_an_icon(self):
        icons = [icon for _, icon in STATES.values()]
        assert len(icons) == 7 and len(set(icons)) == 7

    def test_the_magnifier_is_drawn_once_and_only_with_lines(self):
        drawings = re.findall(r'<symbol id="i-search" viewBox="0 0 24 24">(.*?)</symbol>', sprite())
        assert len(drawings) == 1
        assert "<circle" in drawings[0] and "<path" in drawings[0] and "fill=" not in drawings[0]


class TestFilters:
    @pytest.mark.parametrize("state", STATES)
    def test_word_and_icon_are_those_of_states(self, state):
        assert tuple(filtered(state)) == STATES[state]

    @pytest.mark.parametrize("unknown", ["nope", "", None])
    def test_an_unknown_state_gives_nothing(self, unknown):
        assert filtered(unknown) == ["", ""]


class TestRidesToReview:
    def assert_says_review(self, html, href):
        chip = review_chip(row_by_href(html, href))
        assert hrefs(chip) == ["#i-search"]
        assert visible_text(chip) == accessible_text(chip) == STATES["review"][0]
        assert len(find_all(chip, "svg", aria_hidden="true")) == 1

    def test_one_ride(self, garage, client):
        html = page(client, garage.owner, "garage:index")
        self.assert_says_review(html, f'{reverse("garage:ride-review", args=[garage.pending.pk])}?next={reverse("garage:index")}')

    def test_several_rides(self, garage, client):
        create_manual_ride(garage.owner, started_at=at(2), name="Otra sin bici", distance_m=Decimal(1000))
        html = page(client, garage.owner, "garage:index")
        self.assert_says_review(html, f'{reverse("garage:usage-ride-list")}?pending=1')

    def test_the_chip_takes_icon_and_word_from_states(self, garage, client, monkeypatch):
        monkeypatch.setitem(STATES, "review", ("Mirar", "gauge"))
        html = page(client, garage.owner, "garage:index")
        href = f'{reverse("garage:ride-review", args=[garage.pending.pk])}?next={reverse("garage:index")}'
        chip = review_chip(row_by_href(html, href))
        assert hrefs(chip) == ["#i-gauge"] and visible_text(chip) == "Mirar"


class TestRuleToReview:
    """The fixture's chain is at «Revisar»: its partial history stops the rule certifying «Próximo»."""

    @pytest.mark.parametrize("url_name", ["garage:index", "garage:maintenance"])
    def test_the_row_of_a_rule(self, garage, client, url_name):
        html = page(client, garage.owner, url_name)
        chip = review_chip(row_by_href(html, reverse("garage:item-detail", args=[garage.chain.pk])))
        assert hrefs(chip) == ["#i-search"] and visible_text(chip).startswith("Revisar · ≥ ")

    def test_the_piece_screen(self, garage, client):
        client.force_login(garage.owner)
        root = parse(client.get(reverse("garage:item-detail", args=[garage.chain.pk])).content.decode())
        assert hrefs(review_chip(root)) == ["#i-search"]


class TestNoBikeInStatistics:
    def test_the_row_wears_the_magnifier(self, garage, client):
        html = page(client, garage.owner, "garage:statistics", period="all")
        row = row_by_href(html, f'{reverse("garage:usage-ride-list")}?pending=1')
        assert "st-review" in row.attrs["class"].split() and visible_text(row).startswith("Sin bici")
        glyphs = find_all(row, "span", cls="glyph")
        assert len(glyphs) == 1 and hrefs(glyphs[0]) == ["#i-search"]


class TestGenericNoticesStay:
    def test_a_strava_notice_keeps_the_triangle(self, garage, client, settings):
        """A notice in amber is not the state «Revisar» of a rule or a ride (D8)."""
        settings.GARAGE_STRAVA_USER = ""
        html = page(client, garage.owner, "garage:strava")
        notices = find_all(parse(html), "p", cls="pending st-review")
        assert len(notices) == 1 and hrefs(notices[0]) == ["#i-alert"]
        assert visible_text(notices[0]).startswith("Sin configurar")
