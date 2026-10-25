"""garage-042: the life of each item at a glance — mounted, available (or never used), in use, retired."""
import re
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.template import Context, Template
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .models import Bike, Category, Installation, Item, UsageProfile, UsageProfileItem
from .services.baselines import record_baseline
from .services.home import home_snapshot
from .services.installations import close_installation, create_installation
from .services.lifecycle import AVAILABLE, IN_USE, MOUNTED, RETIRED, ItemLifecycle, filter_state, item_lifecycles
from .services.ownership import InventoryWriteError, create_inventory, retire_inventory, scoped_inventory
from .services.rides import create_manual_ride
from .services.service_usage import category_comparison
from .services.usage_profiles import create_profile_history, set_usage_override

UTC = dt_timezone.utc
NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)


def ago(days):
    return NOW - timedelta(days=days)


@pytest.fixture
def now(monkeypatch):
    monkeypatch.setattr("django.utils.timezone.now", lambda: NOW)
    return NOW


@pytest.fixture
def life(db):
    users = get_user_model().objects
    owner = users.create_user("life-owner", password="test-only-password")
    other = users.create_user("life-other", password="test-only-password")
    cats = {name: create_inventory(owner, Category, name=name) for name in
            ("Ruedas", "Cámaras", "Válvulas", "Casetes", "Cascos", "Zapatillas", "Cadenas", "Pastillas", "Cubiertas", "Sillines", "Bidones")}
    gravel = create_inventory(owner, Bike, name="Gravel")
    road = create_inventory(owner, Bike, name="Carretera")

    def item(name, category, **values):
        return create_inventory(owner, Item, name=name, category=cats[category], **values)
    items = SimpleNamespace(
        rear=item("Rueda trasera", "Ruedas"), tube=item("Cámara", "Cámaras"), valve=item("Válvula", "Válvulas"),
        spare=item("Rueda de repuesto", "Ruedas"), old_cassette=item("Casete viejo", "Casetes"),
        helmet=item("Casco", "Cascos"), shoes=item("Zapatillas", "Zapatillas"),
        chain=item("Cadena usada", "Cadenas"), new_chain=item("Cadena nueva", "Cadenas"), pads=item("Pastillas", "Pastillas"),
        tyre=item("Cubierta vieja", "Cubiertas", retired_at=ago(10)), saddle=item("Sillín", "Sillines", retired_at=NOW + timedelta(days=5)),
        bottle=item("Bidón", "Bidones", acquisition_anchor_at=ago(7)))
    create_installation(owner, item=items.rear, bike=gravel, parent_item=None, started_at=ago(100), ended_at=None, slot="rear_wheel")
    create_installation(owner, item=items.tube, bike=None, parent_item=items.rear, started_at=ago(80), ended_at=None, slot=None)
    create_installation(owner, item=items.valve, bike=None, parent_item=items.tube, started_at=ago(60), ended_at=None, slot=None)
    create_installation(owner, item=items.old_cassette, bike=None, parent_item=items.spare, started_at=ago(40), ended_at=None, slot=None)
    chain_mount = create_installation(owner, item=items.chain, bike=road, parent_item=None, started_at=ago(200), ended_at=None, slot="chain")
    close_installation(owner, chain_mount.pk, at=ago(20))  # «Desmontar»
    create_profile_history(owner, name="Siempre", started_at=ago(300), items=[items.helmet])
    create_profile_history(owner, name="Monte", bike=gravel, sport_type="mountain_bike_ride", started_at=ago(30), items=[items.helmet])
    create_profile_history(owner, name="Antes", bike=road, started_at=ago(300), ended_at=ago(100), items=[items.shoes])
    record_baseline(owner, item=items.pads, metric="distance_m", scope="lifetime", cut_at=ago(5), value=Decimal(1500000))
    foreign_cat = create_inventory(other, Category, name="Ajena")
    foreign = create_inventory(other, Item, name="SECRET item", category=foreign_cat)
    foreign_bike = create_inventory(other, Bike, name="SECRET bike")
    create_installation(other, item=foreign, bike=foreign_bike, parent_item=None, started_at=ago(10), ended_at=None, slot=None)
    return SimpleNamespace(owner=owner, other=other, gravel=gravel, road=road, cats=cats, foreign=foreign, chain_mount=chain_mount, **vars(items))


def lives(fixture, at=NOW):
    return item_lifecycles(fixture.owner, scoped_inventory(fixture.owner, Item), at=at)


def by_name(fixture, at=NOW):
    items = {item.pk: item.name for item in scoped_inventory(fixture.owner, Item)}
    return {items[pk]: value for pk, value in lives(fixture, at).items()}


def render(source, **context):
    return Template("{% load garage_ui %}" + source).render(Context({"user_tz": ZoneInfo("Europe/Madrid"), **context}))


class TestService:
    def test_every_state_and_its_words(self, life):
        result = by_name(life)
        assert {name: value.state for name, value in result.items()} == {
            "Rueda trasera": MOUNTED, "Cámara": MOUNTED, "Válvula": MOUNTED, "Casete viejo": MOUNTED,
            "Casco": IN_USE, "Rueda de repuesto": AVAILABLE, "Zapatillas": AVAILABLE, "Cadena usada": AVAILABLE,
            "Cadena nueva": AVAILABLE, "Pastillas": AVAILABLE, "Bidón": AVAILABLE, "Sillín": AVAILABLE, "Cubierta vieja": RETIRED}
        assert result["Rueda trasera"] == ItemLifecycle(MOUNTED, "En Gravel desde el", since=ago(100), bike="Gravel")
        assert result["Cubierta vieja"] == ItemLifecycle(RETIRED, "Retirado el", since=ago(10))
        assert result["Casco"] == ItemLifecycle(IN_USE, "En uso · Cualquier bici, Gravel · MTB", contexts=("Cualquier bici", "Gravel · MTB"))
        assert (result["Cadena nueva"].text, result["Cadena nueva"].unused) == ("Sin estrenar", True)

    def test_nested_parts_name_their_parent_and_the_bike_above(self, life):
        result = by_name(life)
        assert (result["Cámara"].text, result["Cámara"].since) == ("Sobre Rueda trasera · Gravel desde el", ago(80))
        # Two levels down: the bike is still found through the parents.
        assert (result["Válvula"].text, result["Válvula"].parent, result["Válvula"].bike) == ("Sobre Cámara · Gravel desde el", "Cámara", "Gravel")
        # Inside an item that is not on a bike: no bike to name.
        assert (result["Casete viejo"].text, result["Casete viejo"].bike) == ("Sobre Rueda de repuesto desde el", "")
        # Holding a part says nothing about the wheel itself: it was never mounted, read or in a profile.
        assert result["Rueda de repuesto"].text == "Sin estrenar"

    def test_never_used_versus_available(self, life):
        result = by_name(life)
        assert {name for name, value in result.items() if value.unused} == {"Cadena nueva", "Sillín", "Rueda de repuesto"}
        # Unmounted, a past profile, a previous reading or a confirmed start of use: «Disponible», never «Sin estrenar».
        for name in ("Cadena usada", "Zapatillas", "Pastillas", "Bidón"):
            assert (result[name].text, result[name].unused) == ("Disponible", False), name

    def test_future_retirement_is_not_retired_yet(self, life):
        assert by_name(life)["Sillín"].state == AVAILABLE
        assert by_name(life, at=NOW + timedelta(days=5))["Sillín"] == ItemLifecycle(RETIRED, "Retirado el", since=NOW + timedelta(days=5))

    def test_retired_prevails_over_an_open_mount(self, life):
        Item.objects.filter(pk=life.rear.pk).update(retired_at=ago(1))  # inconsistent data written behind the services
        assert by_name(life)["Rueda trasera"].state == RETIRED

    def test_a_mount_ending_at_the_instant_is_over(self, life):
        assert by_name(life, at=ago(20))["Cadena usada"].state == AVAILABLE
        assert by_name(life, at=ago(20) - timedelta(microseconds=1))["Cadena usada"] == \
            ItemLifecycle(MOUNTED, "En Carretera desde el", since=ago(200), bike="Carretera")

    def test_profiles_count_while_current(self, life):
        assert by_name(life, at=ago(100))["Zapatillas"].state == AVAILABLE  # ended at that instant
        assert by_name(life, at=ago(101))["Zapatillas"].text == "En uso · Carretera"
        assert by_name(life, at=ago(31))["Casco"].contexts == ("Cualquier bici",)  # «Monte» not started yet

    def test_history_counts_only_up_to_the_instant(self, life):
        # Before its first mount the chain was new; the reading and the start of use likewise.
        earlier = by_name(life, at=ago(250))
        assert [earlier[name].text for name in ("Cadena usada", "Pastillas", "Bidón")] == ["Sin estrenar"] * 3
        later = create_inventory(life.owner, Item, name="Para la semana que viene", category=life.cats["Cadenas"])
        create_installation(life.owner, item=later, bike=life.road, parent_item=None, started_at=NOW + timedelta(days=7), ended_at=None, slot=None)
        assert item_lifecycles(life.owner, [later], at=NOW)[later.pk].text == "Sin estrenar"

    def test_a_ride_that_includes_it_by_exception_means_used(self, life, client, now):
        # R042-1: the ride screen can include any item, even one never mounted nor in a profile; it then has km.
        light = create_inventory(life.owner, Item, name="Luz", category=life.cats["Bidones"])
        ride = create_manual_ride(life.owner, started_at=ago(3), bike=life.gravel.pk, distance_m=Decimal(45000))
        set_usage_override(life.owner, ride=ride, item=light, action="include")
        assert item_lifecycles(life.owner, [light], at=NOW)[light.pk] == ItemLifecycle(AVAILABLE, "Disponible")
        assert item_lifecycles(life.owner, [light], at=ago(4))[light.pk].text == "Sin estrenar"  # before that ride
        client.force_login(life.owner)
        assert rows(client.get(reverse("garage:item-list")).content.decode())["Luz"] == "Bidones · Disponible"
        # An exclusion, or an inclusion in a ride still to come, gives it no use: still new.
        other = create_inventory(life.owner, Item, name="Luz de repuesto", category=life.cats["Bidones"])
        later = create_manual_ride(life.owner, started_at=NOW + timedelta(days=2), bike=life.gravel.pk, distance_m=Decimal(1000))
        set_usage_override(life.owner, ride=later, item=other, action="include")
        set_usage_override(life.owner, ride=ride, item=other, action="exclude")
        assert item_lifecycles(life.owner, [other], at=NOW)[other.pk].unused

    def test_rows_of_another_owner_never_count(self, life):
        # R042-7: written behind the services (their clean() forbids it), another owner's mount and profile on my items.
        foreign_bike = Bike.objects.get(owner=life.other)
        Installation.objects.create(owner=life.other, item=life.new_chain, bike=foreign_bike, started_at=ago(5))
        profile = UsageProfile.objects.create(owner=life.other, name="Ajeno", started_at=ago(5))
        UsageProfileItem.objects.create(owner=life.other, profile=profile, item=life.spare)
        result = lives(life)
        assert (result[life.new_chain.pk].text, result[life.spare.pk].text) == ("Sin estrenar", "Sin estrenar")
        mine = scoped_inventory(life.owner, Item)
        for state in (MOUNTED, AVAILABLE, IN_USE):
            assert set(filter_state(mine, state, at=NOW).values_list("pk", flat=True)) == \
                {pk for pk, value in result.items() if value.state == state}, state

    def test_only_own_items(self, life):
        with pytest.raises(InventoryWriteError):
            item_lifecycles(life.owner, [life.foreign], at=NOW)
        assert item_lifecycles(life.owner, [], at=NOW) == {}

    def test_three_reads_whatever_the_number_of_items(self, life):
        items = list(scoped_inventory(life.owner, Item))
        with CaptureQueriesContext(connection) as queries:
            item_lifecycles(life.owner, items, at=NOW)
        assert len(queries) == 3, len(queries)  # open mounts, current profiles, earlier history
        for number in range(8):
            extra = create_inventory(life.owner, Item, name=f"Extra {number}", category=life.cats["Cascos"])
            if number % 2:
                create_installation(life.owner, item=extra, bike=None, parent_item=life.tube, started_at=ago(2), ended_at=None, slot=None)
            else:
                create_profile_history(life.owner, name=f"P{number}", started_at=ago(2), items=[extra])
        items = list(scoped_inventory(life.owner, Item))
        with CaptureQueriesContext(connection) as queries:
            item_lifecycles(life.owner, items, at=NOW)
        assert len(queries) == 3
        retired = [life.tyre]
        with CaptureQueriesContext(connection) as queries:
            assert item_lifecycles(life.owner, retired, at=NOW)[life.tyre.pk].state == RETIRED
        assert len(queries) == 0  # nothing else to look up

    # R042-8: the boundaries too — the unmount, a profile ending and one not started yet, the first mount, both retirements.
    @pytest.mark.parametrize("at", [NOW, ago(20), ago(20) - timedelta(microseconds=1), ago(100), ago(31), ago(250), ago(10),
                                    NOW + timedelta(days=5)], ids=["now", "unmount", "before-unmount", "first-mount-and-profile-end",
                                                                    "profile-not-started", "long-ago", "retirement", "scheduled-retirement"])
    def test_database_filter_matches_the_service(self, life, at):
        result = lives(life, at)
        mine = scoped_inventory(life.owner, Item)
        for state in (MOUNTED, AVAILABLE, IN_USE, RETIRED):
            assert set(filter_state(mine, state, at=at).values_list("pk", flat=True)) == \
                {pk for pk, value in result.items() if value.state == state}, state
        assert set(filter_state(mine, "active", at=at).values_list("pk", flat=True)) == \
            {pk for pk, value in result.items() if value.state != RETIRED}
        assert filter_state(mine, "all", at=at).count() == filter_state(mine, "nonsense", at=at).count() == len(result)

    def test_life_text_shows_the_date_in_the_viewer_zone(self):
        mounted = ItemLifecycle(MOUNTED, "En <Gravel> desde el", since=datetime(2026, 3, 2, 23, 30, tzinfo=UTC))
        assert render("{% life_text value %}", value=mounted) == "En &lt;Gravel&gt; desde el 3 mar 2026"
        assert render("{% life_text value %}", value=ItemLifecycle(AVAILABLE, "Disponible")) == "Disponible"
        assert render("{% life_text value %}", value=None) == ""
        scheduled = ItemLifecycle(AVAILABLE, "Disponible", retires=datetime(2026, 10, 20, 22, 30, tzinfo=UTC))
        assert render("{% life_text value %}", value=scheduled) == "Disponible · se retira el 21 oct 2026"

    def test_a_scheduled_retirement_is_carried_until_it_comes(self, life):
        result = by_name(life)
        assert result["Sillín"].retires == NOW + timedelta(days=5) and result["Sillín"].text == "Sin estrenar"
        assert {name for name, value in result.items() if value.retires} == {"Sillín"}
        assert by_name(life, at=NOW + timedelta(days=5))["Sillín"].retires is None  # retired by then: «Retirado el …»


def rows(html):
    """{name: secondary line} of the list rows."""
    return {name: re.sub(r"\s+", " ", sub).strip() for name, sub in
            re.findall(r'<span class="entry-name">([^<]+)</span>\s*<span class="entry-sub">([^<]*)</span>', html)}


class TestMaterialList:
    def get(self, client, **params):
        return client.get(reverse("garage:item-list"), params).content.decode()

    def test_chips_and_default(self, life, client, now):
        client.force_login(life.owner)
        html = self.get(client)
        chips = re.findall(r'<a class="chip-link(?: on)?" href="\?state=(\w+)"[^>]*>([^<]+)</a>', html)
        assert chips == [("mounted", "Montados"), ("available", "Disponibles"), ("in_use", "En uso"), ("retired", "Retirados"), ("all", "Todos")]
        assert '<a class="chip-link on" href="?state=all" aria-current="page">Todos</a>' in html
        assert len(rows(html)) == 13 and "SECRET" not in html

    @pytest.mark.parametrize("state,names", [
        ("mounted", {"Rueda trasera", "Cámara", "Válvula", "Casete viejo"}),
        ("available", {"Rueda de repuesto", "Zapatillas", "Cadena usada", "Cadena nueva", "Pastillas", "Bidón", "Sillín"}),
        ("in_use", {"Casco"}),
        ("retired", {"Cubierta vieja"}),
    ])
    def test_each_chip(self, life, client, now, state, names):
        client.force_login(life.owner)
        html = self.get(client, state=state)
        assert set(rows(html)) == names
        assert f'<a class="chip-link on" href="?state={state}" aria-current="page">' in html and "SECRET" not in html

    def test_active_alias_and_unknown_values(self, life, client, now):
        client.force_login(life.owner)
        active = self.get(client, state="active")
        assert set(rows(active)) == set(rows(self.get(client))) - {"Cubierta vieja"}
        assert 'class="chip-link on"' not in active and 'value="active"' in active  # accepted, without a chip of its own
        for value in ("bogus", "Retired", ""):
            html = self.get(client, state=value)
            assert len(rows(html)) == 13 and '<a class="chip-link on" href="?state=all"' in html, value

    def test_row_texts(self, life, client, now):
        client.force_login(life.owner)
        texts = rows(self.get(client))
        assert texts["Rueda trasera"] == "Ruedas · En Gravel desde el 8 jul 2026"
        assert texts["Válvula"] == "Válvulas · Sobre Cámara · Gravel desde el 17 ago 2026"
        assert texts["Casete viejo"] == "Casetes · Sobre Rueda de repuesto desde el 6 sep 2026"
        assert texts["Casco"] == "Cascos · En uso · Cualquier bici, Gravel · MTB"
        assert texts["Cadena usada"] == "Cadenas · Disponible" and texts["Cadena nueva"] == "Cadenas · Sin estrenar"
        assert texts["Cubierta vieja"] == "Cubiertas · Retirado el 6 oct 2026"
        html = self.get(client)
        # The «Retirado» chip stays, only for what is retired now (as the «Retirados» filter); a retirement still to
        # come keeps the row's state and says when (R042-6).
        assert html.count('<span class="chip st-nodata">Retirado</span>') == 1
        assert texts["Sillín"] == "Sillines · Sin estrenar · se retira el 21 oct 2026"

    def test_search_combines_with_the_state(self, life, client, now):
        client.force_login(life.owner)
        assert set(rows(self.get(client, state="available", q="cadena"))) == {"Cadena usada", "Cadena nueva"}
        html = self.get(client, state="mounted", q="cadena")
        assert "No hay resultados." in html and "Crear el primero" not in html
        assert 'href="?q=cadena&amp;state=available"' in html

    def test_empty_offers_creation_only_for_all(self, db, client, now):
        owner = get_user_model().objects.create_user("life-empty", password="test-only-password")
        client.force_login(owner)
        assert "Crear el primero" in self.get(client)
        for state in ("mounted", "available", "in_use", "retired", "active"):
            html = self.get(client, state=state)
            assert "No hay resultados." in html and "Crear el primero" not in html, state

    def test_pagination_keeps_the_filter(self, life, client, now):
        for number in range(20):
            create_inventory(life.owner, Item, name=f"Repuesto {number:02d}", category=life.cats["Cadenas"])
        client.force_login(life.owner)
        first = self.get(client, state="available")
        assert len(rows(first)) == 20 and "Página 1 de 2" in first
        assert 'href="?q=&amp;state=available&amp;page=2"' in first
        second = self.get(client, state="available", page=2)
        assert len(rows(second)) == 7 and "Página 2 de 2" in second and 'href="?q=&amp;state=available&amp;page=1"' in second
        assert not set(rows(first)) & set(rows(second))
        assert set(rows(first)) | set(rows(second)) == {f"Repuesto {number:02d}" for number in range(20)} | {
            "Rueda de repuesto", "Zapatillas", "Cadena usada", "Cadena nueva", "Pastillas", "Bidón", "Sillín"}
        assert "Página" not in self.get(client, state="mounted")

    def test_queries_do_not_grow_with_rows(self, life, client, now):
        client.force_login(life.owner)
        url = reverse("garage:item-list")
        with CaptureQueriesContext(connection) as queries:
            assert client.get(url).status_code == 200
        few = len(queries)
        assert few <= 10, few
        assert not any(q["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"} for q in queries)
        for number in range(7):  # fill the page with every kind of row
            extra = create_inventory(life.owner, Item, name=f"Aaa {number}", category=life.cats["Cascos"])
            if number % 3 == 0:
                create_installation(life.owner, item=extra, bike=None, parent_item=life.valve, started_at=ago(3), ended_at=None, slot=None)
            elif number % 3 == 1:
                create_profile_history(life.owner, name=f"Q{number}", bike=life.road, started_at=ago(3), items=[extra])
        with CaptureQueriesContext(connection) as queries:
            assert client.get(url).status_code == 200
        assert len(queries) == few
        with CaptureQueriesContext(connection) as queries:
            assert client.get(url, {"state": "available"}).status_code == 200
        assert len(queries) <= few

    def test_other_lists_keep_their_chips(self, life, client, now):
        client.force_login(life.owner)
        bikes = client.get(reverse("garage:bike-list")).content.decode()
        assert re.findall(r'href="\?state=(\w+)"[^>]*>([^<]+)</a>', bikes) == [("active", "Activas"), ("retired", "Retiradas"), ("all", "Todas")]
        categories = client.get(reverse("garage:category-list")).content.decode()
        assert re.findall(r'href="\?state=(\w+)"[^>]*>([^<]+)</a>', categories) == [("active", "Activas"), ("retired", "Archivadas"), ("all", "Todas")]
        assert client.get(reverse("garage:bike-list"), {"state": "mounted"}).content.decode().count('aria-current="page">Todas<') == 1
        # R042-6: Bicis keep their meaning of «Activas» (no retirement date at all); Material's `active` is «not retired now».
        create_inventory(life.owner, Bike, name="Futura", retired_at=NOW + timedelta(days=1))
        assert "Futura" not in client.get(reverse("garage:bike-list"), {"state": "active"}).content.decode()
        assert "Sillín" in rows(client.get(reverse("garage:item-list"), {"state": "active"}).content.decode())


class TestOtherScreens:
    def test_item_screen_lede(self, life, client, now):
        client.force_login(life.owner)

        def lede(item):
            html = client.get(reverse("garage:item-detail", args=[item.pk])).content.decode()
            return re.sub(r"\s+", " ", re.search(r'<p class="lede">(.*?)</p>', html, re.S).group(1)).strip()
        assert lede(life.new_chain) == "Sin estrenar · Cadenas"
        assert lede(life.chain) == "Disponible · Cadenas"
        assert lede(life.helmet) == "En uso · Cualquier bici, Gravel · MTB · Cascos"
        assert lede(life.rear) == "En Gravel desde el 8 jul 2026 · Ruedas"
        # R042-4: the same words as the Material list for a part inside another one.
        assert lede(life.tube) == "Sobre Rueda trasera · Gravel desde el 28 jul 2026 · Cámaras"
        assert lede(life.valve) == "Sobre Cámara · Gravel desde el 17 ago 2026 · Válvulas"
        assert lede(life.old_cassette) == "Sobre Rueda de repuesto desde el 6 sep 2026 · Casetes"
        assert lede(life.tyre) == "Retirado el 6 oct 2026 · Cubiertas"
        # R042-2: a retirement still to come is not «Retirado el …»; the line keeps its state and says when.
        assert lede(life.saddle) == "Sin estrenar · se retira el 21 oct 2026 · Sillines"
        def state(item):
            html = client.get(reverse("garage:item-detail", args=[item.pk])).content.decode()
            return re.sub(r"<[^>]+>", "", re.search(r"<dt>Estado</dt><dd>(.*?)</dd>", html).group(1))
        assert state(life.saddle) == "Activo · se retira: 21 oct 2026, 14:00"
        assert state(life.tyre) == "Retirado: 6 oct 2026, 14:00" and state(life.chain) == "Activo"

    def test_a_mounted_item_retired_ahead(self, life, client, now):
        # R042-2: retiring for a later day keeps it mounted until then, on every screen.
        wheel = create_inventory(life.owner, Item, name="Rueda delantera", category=life.cats["Ruedas"])
        create_installation(life.owner, item=wheel, bike=life.gravel, parent_item=None, started_at=ago(10), ended_at=None, slot="front_wheel")
        retire_inventory(life.owner, Item, wheel.pk, at=NOW + timedelta(days=3))
        wheel.refresh_from_db()
        client.force_login(life.owner)
        expected = "En Gravel desde el 6 oct 2026 · se retira el 19 oct 2026"
        assert rows(client.get(reverse("garage:item-list"), {"state": "mounted"}).content.decode())["Rueda delantera"] == f"Ruedas · {expected}"
        html = client.get(reverse("garage:item-detail", args=[wheel.pk])).content.decode()
        assert f'<p class="lede">{expected} · Ruedas</p>' in html and "Retirado el" not in html
        assert item_lifecycles(life.owner, [wheel], at=NOW + timedelta(days=3))[wheel.pk].state == RETIRED

    def test_screen_of_a_loose_item_has_a_bounded_number_of_queries(self, life, client, now):
        # R042-8: the only item screen that runs the three reads of the state; they do not grow with the garage.
        client.force_login(life.owner)
        url = reverse("garage:item-detail", args=[life.new_chain.pk])
        with CaptureQueriesContext(connection) as queries:
            assert client.get(url).status_code == 200
        few = len(queries)
        assert few <= 44, few
        assert not any(q["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"} for q in queries)
        for number in range(10):  # more parts, profiles and readings elsewhere
            extra = create_inventory(life.owner, Item, name=f"Otra {number}", category=life.cats["Cadenas"])
            if number % 3 == 0:
                create_installation(life.owner, item=extra, bike=None, parent_item=life.tube, started_at=ago(3), ended_at=None, slot=None)
            elif number % 3 == 1:
                create_profile_history(life.owner, name=f"R{number}", started_at=ago(3), items=[extra])
            else:
                record_baseline(life.owner, item=extra, metric="distance_m", scope="lifetime", cut_at=ago(3), value=Decimal(1000))
        with CaptureQueriesContext(connection) as queries:
            assert client.get(url).status_code == 200
        assert len(queries) == few
        with CaptureQueriesContext(connection) as queries:
            assert client.get(reverse("garage:item-detail", args=[life.helmet.pk])).status_code == 200
        assert len(queries) <= few  # in use: nothing earlier to look up

    def test_home_gear(self, life, client, now):
        home = home_snapshot(life.owner, at=NOW)
        texts = {entry.item.name: entry.life.text for entry in home.gear}
        assert texts == {"Casco": "En uso · Cualquier bici, Gravel · MTB", "Bidón": "Disponible", "Cadena nueva": "Sin estrenar",
                         "Cadena usada": "Disponible", "Pastillas": "Disponible", "Rueda de repuesto": "Sin estrenar",
                         "Sillín": "Sin estrenar", "Zapatillas": "Disponible"}
        assert [entry.item.name for entry in home.gear][0] == "Casco" and home.gear[0].in_use
        client.force_login(life.owner)
        html = client.get(reverse("garage:index")).content.decode()
        assert "Equipación y material sin montar" in html and "Guardado" not in html
        for text in ("En uso · Cualquier bici, Gravel · MTB", "Sin estrenar", "Disponible"):
            assert text in html, text

    def test_category_lives_use_the_state_of_the_list(self, life, client, now):
        # R042-3: «Cuánto dura cada uno» says «En uso», «Disponible» or «Sin estrenar» like the Material list.
        client.force_login(life.owner)

        def lives_of(name):
            return rows(client.get(reverse("garage:category-detail", args=[life.cats[name].pk])).content.decode())
        assert lives_of("Cascos") == {"Casco": "En uso · Cualquier bici, Gravel · MTB"}
        chains = lives_of("Cadenas")
        assert chains["Cadena nueva"] == "Sin estrenar" and chains["Cadena usada"].startswith("Disponible · 180")
        assert lives_of("Ruedas") == {"Rueda trasera": "Montado · 100 días montado", "Rueda de repuesto": "Sin estrenar"}
        assert lives_of("Sillines") == {"Sillín": "Sin estrenar · se retira el 21 oct 2026"}
        assert lives_of("Cubiertas") == {"Cubierta vieja": "Retirado el 6 oct 2026"}
        assert lives_of("Zapatillas") == {"Zapatillas": "Disponible"}
        parts = {part.item.name: part for part in category_comparison(life.owner, life.cats["Cadenas"], zone=ZoneInfo("Europe/Madrid"), at=NOW)}
        assert parts["Cadena usada"].lifecycle == ItemLifecycle(AVAILABLE, "Disponible")

    def test_category_screen_queries_do_not_grow(self, life, client, now):
        client.force_login(life.owner)
        url = reverse("garage:category-detail", args=[life.cats["Cascos"].pk])

        def add(numbers):  # loose gear of every kind in the same category: in use, read before, never used
            for number in numbers:
                extra = create_inventory(life.owner, Item, name=f"Casco {number}", category=life.cats["Cascos"])
                if number % 3 == 0:
                    create_profile_history(life.owner, name=f"S{number}", started_at=ago(3), items=[extra])
                elif number % 3 == 1:
                    record_baseline(life.owner, item=extra, metric="distance_m", scope="lifetime", cut_at=ago(3), value=Decimal(1000))
        add(range(3))
        with CaptureQueriesContext(connection) as queries:
            assert client.get(url).status_code == 200
        few = len(queries)
        add(range(3, 9))
        with CaptureQueriesContext(connection) as queries:
            assert client.get(url).status_code == 200
        assert len(queries) == few <= 28, few  # garage-036 kept it under 27; the state of the loose ones adds two reads at most
