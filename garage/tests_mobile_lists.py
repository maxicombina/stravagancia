"""garage-032.4: inventory lists, local dates in the remaining screens, profile, history and export pages."""
import re
from datetime import date, datetime, timezone as dt_timezone
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit
from zoneinfo import ZoneInfo

import pytest
from django.template import Context, Template
from django.urls import reverse

from test_support import contrast

from .models import Bike, Category, Item, UsageProfile
from .services.ownership import create_inventory
from .test_html import find_all, parse, visible_text
from .tests_mobile_home import at, garage  # noqa: F401 (fixture)
from .tests_ordering import SPANISH, owner_named, row_names, spanish  # noqa: F401 (fixture)

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

    def test_a_bike_is_named_as_a_title_and_a_piece_is_not(self, garage, client):
        # §3.1: «títulos, nombres de bici» in the face of the titles; the other rows keep the face of a row (§4.4).
        client.force_login(garage.owner)
        names = find_all(parse(client.get(reverse("garage:bike-list")).content.decode()), cls="entry-name")
        assert names and all("bike-name" in name.attrs["class"].split() for name in names)
        for route in ("garage:item-list", "garage:category-list"):
            names = find_all(parse(client.get(reverse(route)).content.decode()), cls="entry-name")
            assert names and not [name for name in names if "bike-name" in name.attrs["class"].split()], route

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


class TestSearchRows:
    """Salidas and Material search the same way: one control, not a class-less button with a border and a width of its own."""

    @pytest.mark.parametrize("route", ["garage:usage-ride-list", "garage:item-list"])
    def test_the_button_of_a_search_is_the_quiet_button_of_the_app(self, garage, client, route):
        client.force_login(garage.owner)
        forms = find_all(parse(client.get(reverse(route)).content.decode()), "form", role="search")
        assert len(forms) == 1
        buttons = find_all(forms[0], "button")
        assert len(buttons) == 1
        assert buttons[0].attrs.get("class", "").split() == ["btn", "ghost"]
        assert visible_text(buttons[0]) == "Buscar" and buttons[0].attrs.get("type", "submit") == "submit"


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

    def test_the_links_of_a_version_have_room_for_a_finger(self, garage, client):
        # They measured 19 px (the name of a version, the only way between versions) and 17 px (its material, a row of links and not a sentence).
        client.force_login(garage.owner)
        profile = UsageProfile.objects.get(owner=garage.owner, name="Ruta")
        page = parse(client.get(reverse("garage:usage-profile-detail", args=[profile.pk])).content.decode())
        rows = find_all(find_all(page, "ul", cls="timeline")[0], "li")
        assert rows
        for row in rows:
            body = [child for child in row.children if not isinstance(child, str)][0]
            blocks = [child for child in body.children if not isinstance(child, str)]
            assert body.tag == "span" and blocks[0].tag == "b" and [c.tag for c in blocks[0].children if not isinstance(c, str)] == ["a"]
            assert blocks[-1].tag == "span" and {c.tag for c in blocks[-1].children if not isinstance(c, str)} == {"a"}
        css = (Path(__file__).parent / "static" / "garage" / "garage.css").read_text(encoding="utf-8")
        # The name keeps its line: padding over the 19 px of its text, since a taller box would leave the dot of its row behind and overlap a name that wraps.
        name = contrast.declared(css, ".timeline b > a")
        assert float(name.get("padding-block", "0px").removesuffix("px")) * 2 + 19 >= 44
        assert name.get("position") == "relative"  # Without it the date below takes the lower edge of that padding: a tap there does nothing.
        material = contrast.declared(css, ".timeline li > span > span > a")
        assert (material.get("display"), material.get("min-height")) == ("inline-flex", "44px")

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


# The four lists with a search box, each with a search that finds some of its rows and not all of them.
SEARCH_LISTS = [("garage:bike-list", "ra"), ("garage:item-list", "Ca"), ("garage:category-list", "Ca"), ("garage:usage-ride-list", "Ruta")]


def shown(client, route, **params):
    """A list as a browser gets it: the names of its rows, what its search box says and the parameters of each link."""
    response = client.get(reverse(route), params)
    assert response.status_code == 200, (route, params)
    root = parse(response.content.decode())
    boxes = find_all(root, "input", id="q")
    assert len(boxes) == 1
    links = [parse_qs(urlsplit(link.attrs["href"]).query) for link in find_all(root, "a", href=True)]
    return [visible_text(name) for name in find_all(root, cls="entry-name")], boxes[0].attrs.get("value", ""), links


class TestNullCharactersInTheSearch:
    """F25 (garage-047, D2): PostgreSQL takes no null character in a literal and a name cannot hold one, so the rest is searched."""

    @pytest.mark.parametrize("route,search", SEARCH_LISTS)
    @pytest.mark.parametrize("where", ["first", "inside", "last", "everywhere"])
    def test_a_null_character_in_the_search_is_ignored(self, garage, client, route, search, where):
        dirty = {"first": "\x00" + search, "inside": search[0] + "\x00" + search[1:], "last": search + "\x00",
                 "everywhere": "\x00" + "\x00".join(search) + "\x00\x00"}[where]
        client.force_login(garage.owner)
        names, box, links = shown(client, route, q=dirty)
        clean_names = shown(client, route, q=search)[0]
        assert names == clean_names and 0 < len(names) < len(shown(client, route)[0]), (names, clean_names)
        assert box == search
        carried = [link["q"] for link in links if "q" in link]
        assert carried and all(value == [search] for value in carried), carried  # the filters and pages go on with the clean search

    @pytest.mark.parametrize("route", [route for route, _ in SEARCH_LISTS])
    @pytest.mark.parametrize("dirty", ["\x00", "\x00" * 250, " \x00\t\x00 "], ids=["one", "250", "and-spaces"])
    def test_a_search_of_only_null_characters_is_no_search(self, garage, client, route, dirty):
        client.force_login(garage.owner)
        names, box, links = shown(client, route, q=dirty)
        assert names and names == shown(client, route)[0]
        assert box == "" and not [link for link in links if "q" in link]

    @pytest.mark.parametrize("route,search", SEARCH_LISTS)
    def test_the_200_character_cap_counts_after_cleaning(self, garage, client, route, search):
        client.force_login(garage.owner)
        # Two hundred null characters first: cutting before cleaning would leave nothing to search, and every row would show.
        names, box, _ = shown(client, route, q="\x00" * 200 + search)
        assert box == search and names == shown(client, route, q=search)[0]
        assert shown(client, route, q="\x00" * 50 + "x" * 250)[1] == "x" * 200


ONLY_PENDING = "Sólo las que están por revisar"
NO_MATCH = "Ninguna salida coincide con estos filtros."


class TestThePendingPillAndABike:
    """F24 (garage-047, D3): the rides «por revisar» have no bike, so with a bike chosen that pill always led to an empty list."""

    @staticmethod
    def rides(client, url=None, **params):
        response = client.get(url or reverse("garage:usage-ride-list"), params)
        assert response.status_code == 200, (url, params)
        return parse(response.content.decode())

    @staticmethod
    def pills(root):
        """What each pill of Salidas says and what it asks for."""
        navs = find_all(root, "nav", cls="chips")
        assert len(navs) == 1
        return {visible_text(pill): parse_qs(urlsplit(pill.attrs["href"]).query) for pill in find_all(navs[0], "a")}

    @staticmethod
    def message(root):
        empties = find_all(root, "li", cls="card empty")
        assert len(empties) == 1
        return visible_text(empties[0])

    @pytest.mark.parametrize("search", ["", "bici"])
    def test_pending_pill_without_a_bike(self, garage, client, search):
        client.force_login(garage.owner)
        searched = {"q": search} if search else {}
        root = self.rides(client, **searched)
        assert self.pills(root) == {ONLY_PENDING: {"pending": ["1"], **{name: [value] for name, value in searched.items()}}}
        href = find_all(find_all(root, "nav", cls="chips")[0], "a")[0].attrs["href"]
        target = self.rides(client, urljoin(reverse("garage:usage-ride-list"), href))
        assert [visible_text(name) for name in find_all(target, cls="entry-name")] == ["Sin bici"]

    @pytest.mark.parametrize("search", ["", "Pista", "nada se llama así"])
    def test_no_pending_pill_with_a_bike(self, garage, client, search):
        client.force_login(garage.owner)
        root = self.rides(client, bike=garage.gravel.pk, **({"q": search} if search else {}))
        assert list(self.pills(root)) == ["Gravel"]  # only the chip that takes the bike off
        asks = [parse_qs(urlsplit(link.attrs["href"]).query) for link in find_all(root, "a", href=True)]
        assert asks and not [ask for ask in asks if "pending" in ask]

    @pytest.mark.parametrize("search", ["", "bici"])
    def test_pending_and_bike_explain_the_empty_list(self, garage, client, search):
        # As an old link or a bookmark may still ask: the list says why it is empty, and the chip takes the bike off and keeps the rest.
        client.force_login(garage.owner)
        searched = {"q": search} if search else {}
        root = self.rides(client, bike=garage.gravel.pk, pending="1", **searched)
        assert not find_all(root, cls="entry-name")
        assert self.message(root) == "Las salidas por revisar no tienen bici: quita el filtro de Gravel para verlas."
        chip = find_all(root, "a", cls="chip-link on")
        assert len(chip) == 1 and parse_qs(urlsplit(chip[0].attrs["href"]).query) == {"pending": ["1"], **{k: [v] for k, v in searched.items()}}
        target = self.rides(client, urljoin(reverse("garage:usage-ride-list"), chip[0].attrs["href"]))
        assert [visible_text(name) for name in find_all(target, cls="entry-name")] == ["Sin bici"]

    def test_the_name_of_the_bike_in_that_sentence_is_text(self, garage, client):
        bike = create_inventory(garage.owner, Bike, name='Tándem <b>& "dos"')
        client.force_login(garage.owner)
        root = self.rides(client, bike=bike.pk, pending="1")
        assert self.message(root) == 'Las salidas por revisar no tienen bici: quita el filtro de Tándem <b>& "dos" para verlas.'
        assert not find_all(find_all(root, "li", cls="card empty")[0], "b")

    @pytest.mark.parametrize("params", [{"pending": "1", "q": "nada se llama así"}, {"bike": "gravel", "q": "nada se llama así"}])
    def test_the_other_empty_lists_say_what_they_said(self, garage, client, params):
        client.force_login(garage.owner)
        params = {name: garage.gravel.pk if value == "gravel" else value for name, value in params.items()}
        assert self.message(self.rides(client, **params)) == NO_MATCH


class TestSpanishOrder:
    """garage-047 F10: the three lists sort as in Spanish (§4 F10 of the spec), and so do their pages of 20."""

    @pytest.mark.parametrize("route", LIST_ROUTES)
    def test_names_sort_as_in_spanish(self, spanish, route):
        html = spanish.client.get(reverse(route)).content.decode()
        assert row_names(html, SPANISH) == SPANISH

    @pytest.mark.parametrize("model", [Item, Bike])
    def test_pages_of_twenty_follow_the_new_order(self, db, client, model):
        # In Spanish order the 20 «alfa» and «Ébano» fill the first page and the five «Zeta» go to the second; in byte
        # order the «Zeta» would come first (uppercase) and «Ébano» last (a byte above every ASCII letter).
        owner = owner_named("paginas")
        names = [f"alfa {number:02}" for number in range(1, 20)] + ["Ébano"] + [f"Zeta {number}" for number in range(1, 6)]
        extra = {"category": create_inventory(owner, Category, name="Varios")} if model is Item else {}
        for name in reversed(names):
            create_inventory(owner, model, name=name, **extra)
        client.force_login(owner)
        route = "garage:item-list" if model is Item else "garage:bike-list"
        first = client.get(reverse(route)).content.decode()
        second = client.get(reverse(route), {"page": 2}).content.decode()
        assert row_names(first, set(names)) == names[:20]
        assert row_names(second, set(names)) == names[20:]
