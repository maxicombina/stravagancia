"""garage-032.4: inventory lists, local dates in the remaining screens, profile, history and export pages."""
import re
from datetime import date, datetime, timezone as dt_timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from django.template import Context, Template
from django.urls import reverse

from .models import Category, UsageProfile
from .services.ownership import create_inventory
from .test_html import find_all, parse, visible_text
from .tests_mobile_home import at, garage  # noqa: F401 (fixture)

UTC = dt_timezone.utc
TEMPLATES = Path(__file__).parent / "templates" / "garage"


def render(source, **context):
    return Template("{% load garage_ui %}" + source).render(Context({"user_tz": ZoneInfo("Europe/Madrid"), **context}))


class TestLocalDatetime:
    @pytest.mark.parametrize("instant,text", [
        (datetime(2026, 10, 17, 8, 30, tzinfo=UTC), "17 oct 2026, 10:30"),
        (datetime(2026, 1, 2, 9, 0, 5, tzinfo=UTC), "2 ene 2026, 10:00:05"),
        (datetime(2026, 1, 2, 9, 0, 0, 123456, tzinfo=UTC), "2 ene 2026, 10:00:00,123456"),
        (datetime(2026, 10, 25, 0, 30, tzinfo=UTC), "25 oct 2026, 2:30 (UTC+02:00)"),
        (datetime(2026, 10, 25, 1, 30, tzinfo=UTC), "25 oct 2026, 2:30 (UTC+01:00)"),
    ])
    def test_text_and_exact_instant(self, instant, text):
        html = render("{% local_datetime value %}", value=instant)
        exact = instant.isoformat().replace("+00:00", "Z")
        assert html == f'<time datetime="{exact}">{text}</time>'

    def test_dates_and_unknowns(self):
        assert render("{% local_date value %}", value=date(2026, 3, 1)) == "1 mar 2026"
        assert render("{% local_datetime value %}", value=None) == ""

    def test_the_day_and_the_month_alone_for_the_tile_of_a_ride(self):
        def tile(value):
            return render('{% local_date value "day" %}', value=value), render('{% local_date value "month" %}', value=value)

        assert tile(datetime(2026, 12, 31, 23, 30, tzinfo=UTC)) == ("1", "ene")  # Already next year in Madrid.
        assert tile(datetime(2026, 3, 5, 8, 0, tzinfo=UTC)) == ("5", "mar")  # As in the line of text: no leading zero.
        assert tile(date(2026, 9, 30)) == ("30", "sep")
        assert tile(None) == ("", "") and tile("") == ("", "")
        # Year 9999 ahead of UTC falls back to UTC: the line of text says so, and the tile has no room for it.
        assert tile(datetime(9999, 12, 31, 23, 30, tzinfo=UTC)) == ("31", "dic")

    def test_no_raw_utc_formats_left(self):
        # Only a bare year may still use Django's date filter; instants go through local_date/local_datetime.
        uses = [(path.name, fmt) for path in TEMPLATES.glob("*.html") for fmt in re.findall(r"\|date(?::(\S+?))?[ }|]", path.read_text())]
        assert [use for use in uses if use[1] not in ('"Y"', "'Y'")] == []

    def test_overflowing_year_falls_back_to_utc(self):
        instant = datetime(9999, 12, 31, 23, 30, tzinfo=UTC)
        assert render("{% local_datetime value %}", value=instant) == '<time datetime="9999-12-31T23:30:00Z">31 dic 9999, 23:30 (UTC)</time>'
        assert render("{% local_date value %}", value=instant) == "31 dic 9999 (UTC)"


class TestLists:
    def test_bike_list(self, garage, client):
        client.force_login(garage.owner)
        html = client.get(reverse("garage:bike-list")).content.decode()
        assert "Carretera" in html and "Vieja" in html and '<span class="chip st-nodata">Retirada</span>' in html
        assert '<a class="chip-link on" href="?state=all" aria-current="page">Todas</a>' in html and "SECRET" not in html
        assert 'aria-label="Volver a Garaje"' in html and 'aria-label="Añadir bici"' in html and "Página 1 de" not in html
        active = client.get(reverse("garage:bike-list"), {"state": "active", "q": "ca"}).content.decode()
        assert "Carretera" in active and "Vieja" not in active and "Gravel" not in active
        assert 'href="?q=ca&amp;state=retired"' in active

    def test_item_and_category_lists(self, garage, client):
        client.force_login(garage.owner)
        items = client.get(reverse("garage:item-list")).content.decode()
        assert "Cadena 11v" in items and 'href="#i-chain"' in items and "Cadenas" in items and "material usado" in items
        # garage-042: category and state on each row, with the state chips of Material.
        for text in ("Cadenas · En Carretera desde el 30 mar 2026", "Calas · Sobre Zapatillas desde el 30 mar 2026",
                     "Cascos · En uso · Cualquier bici", "Zapatillas · En uso · Carretera", "Luces · Sin estrenar",
                     '<a class="chip-link on" href="?state=all" aria-current="page">Todos</a>', 'href="?state=mounted">Montados</a>'):
            assert text in items, text
        assert "Sin montar" not in items and "Guardado" not in items
        categories = client.get(reverse("garage:category-list")).content.decode()
        assert "Todas" in categories and "Archivadas" in categories and 'aria-label="Volver a Más"' in categories
        detail = client.get(reverse("garage:category-detail", args=[garage.chain.category_id])).content.decode()
        assert "Cuánto dura cada uno" in detail and "Cadena 11v" in detail and "1 objeto" in detail  # garage-036
        lights = client.get(reverse("garage:category-detail", args=[garage.light.category_id])).content.decode()
        assert "Sin estrenar" in lights and "Sin montar" not in lights  # garage-042: the state of the Material list
        foreign = Category.objects.get(name="X")
        assert client.get(reverse("garage:category-detail", args=[foreign.pk])).status_code == 404

    def test_empty_list_offers_creation(self, db, client):
        from django.contrib.auth import get_user_model
        owner = get_user_model().objects.create_user("empty-lists", password="test-only-password")
        client.force_login(owner)
        html = client.get(reverse("garage:bike-list")).content.decode()
        assert "No hay resultados." in html and f'href="{reverse("garage:bike-create")}">Crear la primera' in html


LIST_ROUTES = ["garage:bike-list", "garage:item-list", "garage:category-list"]


class TestListsInACard:
    """Spec garage-050 §5, `list.html`: the rows in one card. D19: not one card per state, as in the mockup; the filters stay the server's."""

    @staticmethod
    def page(client, route, **params):
        return parse(client.get(reverse(route), params).content.decode())

    @staticmethod
    def card(page):
        cards = find_all(page, cls="card")
        assert len(cards) == 1, cards
        return cards[0]

    @pytest.mark.parametrize("route", LIST_ROUTES)
    def test_all_the_rows_are_in_one_card(self, garage, client, route):
        client.force_login(garage.owner)
        page = self.page(client, route)
        rows = find_all(page, "a", cls="entry")
        assert rows and find_all(self.card(page), "a", cls="entry") == rows

    @pytest.mark.parametrize("route", LIST_ROUTES)
    def test_the_title_the_search_and_the_filters_stay_above_it(self, garage, client, route):
        client.force_login(garage.owner)
        page = self.page(client, route)
        assert len(find_all(page, "nav", cls="chips")) == 1 and len(find_all(page, "form", cls="filters")) == 1
        card = self.card(page)
        assert not find_all(card, "h1") and not find_all(card, "nav") and not find_all(card, "form")

    @pytest.mark.parametrize("route", LIST_ROUTES)
    def test_no_results_is_said_in_the_card(self, garage, client, route):
        client.force_login(garage.owner)
        empties = find_all(self.card(self.page(client, route, q="nada se llama así")), "li", cls="empty")
        assert len(empties) == 1 and "No hay resultados." in visible_text(empties[0])

    @pytest.mark.parametrize("route", ["garage:category-list", "garage:item-list"])
    def test_the_offer_of_the_usual_categories_is_a_panel_of_its_own(self, db, client, route):
        from django.contrib.auth import get_user_model
        client.force_login(get_user_model().objects.create_user("sin-categorias", password="test-only-password"))
        page = self.page(client, route)
        assert len(find_all(page, "section", cls="panel starter")) == 1
        assert not find_all(self.card(page), cls="panel")

    def test_the_pages_are_outside_the_card(self, garage, client):
        for number in range(21):
            create_inventory(garage.owner, Category, name=f"Categoría {number:02}")
        client.force_login(garage.owner)
        page = self.page(client, "garage:category-list", state="active")
        assert len(find_all(page, "nav", cls="pagination")) == 1
        assert not find_all(self.card(page), cls="pagination")

    def test_the_grey_chip_of_a_retired_bike_does_not_change(self, garage, client):
        client.force_login(garage.owner)
        chips = find_all(self.card(self.page(client, "garage:bike-list")), "span", cls="chip st-nodata")
        assert [visible_text(chip) for chip in chips] == ["Retirada"] and not find_all(chips[0], "svg")


class TestOtherScreens:
    def test_profiles(self, garage, client):
        client.force_login(garage.owner)
        client.cookies["garage_tz"] = "Europe/Madrid"
        html = client.get(reverse("garage:usage-profile-list")).content.decode()
        assert "Ruta" in html and "Siempre" in html and "Zapatillas" in html and "Todas mis bicis / sin bici" in html
        profile = UsageProfile.objects.get(owner=garage.owner, name="Ruta")
        detail = client.get(reverse("garage:usage-profile-detail", args=[profile.pk])).content.decode()
        assert "Historial de versiones" in detail and '<time datetime="' in detail and "versión seleccionada" in detail
        create = client.get(reverse("garage:usage-profile-create")).content.decode()
        assert 'name="time_zone" value="Europe/Madrid"' in create

    def test_history_defaults_to_the_viewer_zone(self, garage, client):
        client.force_login(garage.owner)
        client.cookies["garage_tz"] = "America/Argentina/Buenos_Aires"
        html = client.get(reverse("garage:history")).content.decode()
        assert 'value="America/Argentina/Buenos_Aires"' in html and "Completitud del histórico:" in html
        assert 'type="datetime-local" name="requested_from"' in html
        batch = client.get(reverse("garage:history-bike-batch")).content.decode()
        local = garage.pending.started_at.astimezone(ZoneInfo("America/Argentina/Buenos_Aires"))
        assert f"{local.day} oct {local.year}, {local.hour}:{local.minute:02d} · Sin bici" in batch and garage.pending.started_at.isoformat() not in batch
        assert "Ruta 10" in html and "Sin bici" in html and 'aria-label="Volver a Salidas"' in html

    def test_ride_detail_and_export(self, garage, client):
        client.force_login(garage.owner)
        html = client.get(reverse("garage:usage-ride-detail", args=[garage.pending.pk])).content.decode()
        assert "Revisar bici y material" in html and "Material resuelto" in html and "Añadir o cambiar excepción" in html
        export = client.get(reverse("garage:export")).content.decode()
        assert "Descargar JSON" in export and "Descargar CSV (ZIP)" in export and 'aria-label="Volver a Más"' in export
