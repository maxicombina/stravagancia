"""garage-047 F10: names sort as in Spanish everywhere, as PostgreSQL's ICU Spanish collation sorts them.

Accents and case do not lead, «ñ» comes after «n», and a name that differs from another only in case is still told
apart. The expected sequences are written out: they were checked in the local cluster with `COLLATE "es-x-icu"`.
The byte order of the local databases (collation C) and Python's own sort give other sequences for all of them.
"""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import SystemCheckError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from .models import Bike, Category, Item, MaintenanceRule, ServiceType, StravaGear
from .services.installations import create_installation
from .services.maintenance import save_maintenance
from .services.ownership import create_inventory
from .services.rides import create_manual_ride
from .services.usage import rebuild_usage
from .services.usage_profiles import create_profile_history, set_usage_override
from .test_html import find_all, parse, visible_text

# Sorted with ICU: «absoluteBLACK < Cámara < Cubierta < Ébano < Nube < Ñandú < Zapatillas».
# Byte order (collation C) gives «Cubierta < Cámara < Zapatillas < absoluteBLACK < Ébano < ...».
SPANISH = ["absoluteBLACK", "Cámara", "Cubierta", "Ébano", "Nube", "Ñandú", "Zapatillas"]
CREATION = ["Ñandú", "Zapatillas", "Cámara", "absoluteBLACK", "Nube", "Ébano", "Cubierta"]  # neither of those orders
# ICU puts lowercase first among case variants; the byte order puts uppercase first.
CASE_VARIANTS = ["sram gx", "Sram GX", "SRAM GX"]


def past(days):
    return timezone.now() - timedelta(days=days)


def uuid(number):
    return UUID(f"00000000-0000-4000-8000-{number:012d}")


def owner_named(name):
    return get_user_model().objects.create_user(name, password="test-only-password")


def row_names(html, among):
    """The names of the rows of a page (`.entry-name`), in order, that are in `among`."""
    names = (visible_text(node).strip() for node in find_all(parse(html), cls="entry-name"))
    return [name for name in names if name in among]


def option_names(html, field, names):
    """The names of the options of `field` (a select, or checkboxes and radios), in order; `names` maps pk to name."""
    root = parse(html)
    values = [option.attrs.get("value", "") for select in find_all(root, "select", name=field) for option in find_all(select, "option")]
    values += [box.attrs.get("value", "") for box in find_all(root, "input", name=field) if box.attrs.get("type") in ("checkbox", "radio")]
    return [names[value] for value in values if value in names]


def section(html, title_id):
    """The card whose heading has `title_id`."""
    return next(node for node in find_all(parse(html), "section") if node.attrs.get("aria-labelledby") == title_id)


@pytest.fixture
def spanish(db, client):
    """An owner whose bikes, items, categories and types all have the seven names, created in neither sorted order."""
    owner = owner_named("orden-es")
    categories = {name: create_inventory(owner, Category, name=name) for name in CREATION}
    bikes = {name: create_inventory(owner, Bike, name=name) for name in CREATION}
    items = {name: create_inventory(owner, Item, name=name, category=categories[name]) for name in CREATION}
    types = {name: save_maintenance(owner, ServiceType, name=name) for name in CREATION}
    # Mounted on a bike: it moves, takes parts and is replaced. Its name is not one of the seven.
    mover = create_inventory(owner, Item, name="Pieza que se monta", category=categories["Nube"])
    mount = create_installation(owner, item=mover, bike=bikes["Nube"], parent_item=None, started_at=past(30), ended_at=None, slot=None)
    ride = create_manual_ride(owner, started_at=past(2), name="Salida", distance_m=Decimal(1000))
    names = {str(obj.pk): obj.name for group in (categories, bikes, items, types) for obj in group.values()}
    client.force_login(owner)
    return SimpleNamespace(owner=owner, categories=categories, bikes=bikes, items=items, types=types, mover=mover,
                           mount=mount, ride=ride, names=names, client=client)


SELECTS = [
    ("item-create", None, ("category",)),
    ("installation-create", "mover", ("bike", "parent_item")),
    ("installation-replace", "mount", ("incoming_item",)),
    ("installation-transfer", "mount", ("bike", "parent_item")),
    ("item-part-create", "mover", ("item",)),
    ("baseline-create", "mover", ("item",)),
    ("maintenance-rule-create", None, ("item", "bike", "service_type")),
    ("service-event-create", None, ("item", "bike", "service_type")),
    ("statistics", None, ("bike", "category", "item")),
    ("usage-profile-create", None, ("bike", "items")),
    ("usage-ride-detail", "ride", ("item",)),
    ("history-manual-create", None, ("bike",)),
    ("history-bike-batch", None, ("bike",)),
]


class TestSelects:
    @pytest.mark.parametrize("route,arg,fields", SELECTS, ids=[route for route, *_ in SELECTS])
    def test_selects_sort_as_in_spanish(self, spanish, route, arg, fields):
        url = reverse("garage:" + route, args=[getattr(spanish, arg).pk] if arg else [])
        response = spanish.client.get(url)
        assert response.status_code == 200
        html = response.content.decode()
        assert {field: option_names(html, field, spanish.names) for field in fields} == {field: SPANISH for field in fields}

    def test_the_bikes_of_the_strava_page_sort_as_in_spanish(self, spanish):
        from .strava_forms import owner_bikes
        assert [bike.name for bike in owner_bikes(spanish.owner)] == SPANISH

    def test_the_bikes_and_the_gear_of_a_ride_review_sort_as_in_spanish(self, spanish):
        from .services.ride_review import review_state
        create_profile_history(spanish.owner, name="Siempre", started_at=past(10), items=list(spanish.items.values()))
        state = review_state(spanish.owner, spanish.ride.pk)
        # Leaving all of them out changes every one: the effects list them in the same order.
        effects = review_state(spanish.owner, spanish.ride.pk, gear=[]).effects
        assert {"bikes": [bike.name for bike in state.bikes], "gear": [candidate.item.name for candidate in state.candidates],
                "effects": [effect.target.name for effect in effects if effect.icon == "item"]} == \
            {"bikes": SPANISH, "gear": SPANISH, "effects": SPANISH}


class TestHome:
    def test_home_gear_sorts_as_in_spanish(self, spanish):
        from .services.home import home_snapshot
        # In use first, then the rest; each group in Spanish order.
        create_profile_history(spanish.owner, name="Siempre", started_at=past(10),
                               items=[spanish.items["Zapatillas"], spanish.items["Cubierta"]])
        home = home_snapshot(spanish.owner)
        expected = ["Cubierta", "Zapatillas", "absoluteBLACK", "Cámara", "Ébano", "Nube", "Ñandú"]
        html = spanish.client.get(reverse("garage:index")).content.decode()
        page = [visible_text(node).strip() for node in find_all(section(html, "gear-title"), cls="entry-name")]
        assert {"gear": [entry.item.name for entry in home.gear], "page": page, "bikes": [entry.bike.name for entry in home.bikes]} == \
            {"gear": expected, "page": expected, "bikes": SPANISH}


@pytest.fixture
def variants(db, client):
    """«sram gx», «Sram GX» and «SRAM GX», with ids in an order that is neither ICU's nor the bytes'."""
    owner = owner_named("variantes")
    category = create_inventory(owner, Category, name="Cassettes")
    created = {}
    for number, name in ((1, "Sram GX"), (2, "SRAM GX"), (3, "sram gx")):
        created[name] = Item.objects.create(id=uuid(number), owner=owner, name=name, category=category)
    client.force_login(owner)
    return SimpleNamespace(owner=owner, items=created, names={str(item.pk): item.name for item in created.values()}, client=client)


class TestCaseVariants:
    def test_case_variants_sort_the_same_everywhere(self, variants):
        from .services.home import home_snapshot
        listed = row_names(variants.client.get(reverse("garage:item-list")).content.decode(), CASE_VARIANTS)
        home = [entry.item.name for entry in home_snapshot(variants.owner).gear]
        rule = variants.client.get(reverse("garage:maintenance-rule-create")).content.decode()
        assert {"list": listed, "home": home, "select": option_names(rule, "item", variants.names)} == \
            {"list": CASE_VARIANTS, "home": CASE_VARIANTS, "select": CASE_VARIANTS}
        from .ordering import by_name
        assert [item.name for item in by_name(Item.objects.filter(owner=variants.owner))] == CASE_VARIANTS

    def test_equal_names_keep_a_stable_order(self, db, client):
        # Guard: the same name twice is ordered by id, on every page and every time.
        owner = owner_named("iguales")
        category = create_inventory(owner, Category, name="Cadenas")
        second = Item.objects.create(id=uuid(2), owner=owner, name="Cadena", category=category)
        first = Item.objects.create(id=uuid(1), owner=owner, name="Cadena", category=category)
        client.force_login(owner)
        for _ in range(2):
            html = client.get(reverse("garage:item-list")).content.decode()
            hrefs = [node.attrs["href"] for node in find_all(parse(html), "a", cls="entry") if "/items/" in node.attrs.get("href", "")]
            assert hrefs == [reverse("garage:item-detail", args=[first.pk]), reverse("garage:item-detail", args=[second.pk])]
            rule = client.get(reverse("garage:maintenance-rule-create")).content.decode()
            values = [option.attrs["value"] for select in find_all(parse(rule), "select", name="item")
                      for option in find_all(select, "option") if option.attrs.get("value")]
            assert values == [str(first.pk), str(second.pk)]


class TestNameKey:
    def test_name_key_agrees_with_the_database_at_base_letters(self, db):
        from .ordering import by_name, name_key
        owner = owner_named("letras")
        names = [*CREATION, "nzz", "Ñu", "Ábaco", "abeja", "29er", "lona", "Llanta"]
        for name in names:
            create_inventory(owner, Category, name=name)
        expected = ["29er", "Ábaco", "abeja", "absoluteBLACK", "Cámara", "Cubierta", "Ébano", "Llanta", "lona", "Nube", "nzz",
                    "Ñandú", "Ñu", "Zapatillas"]
        assert [category.name for category in by_name(Category.objects.filter(owner=owner))] == expected
        assert sorted(names, key=name_key) == expected

    def test_name_key_ties_case_variants_by_pk(self, db):
        # The documented approximation: ICU still tells «camara», «Camara» and «Cámara» apart; name_key does not,
        # so the caller's tie-break (the id) decides.
        from .ordering import by_name, name_key
        assert name_key("camara") == name_key("Camara") == name_key("Cámara") == name_key("CÁMARA")
        assert name_key("Ñandu") == name_key("Ñandú") != name_key("Nandu")
        assert sorted(["b", "", "a"], key=name_key) == ["", "a", "b"]
        owner = owner_named("aproximacion")
        for number, name in ((1, "Cámara"), (2, "camara"), (3, "Camara")):
            Bike.objects.create(id=uuid(number), owner=owner, name=name)
        bikes = list(Bike.objects.filter(owner=owner))
        assert [bike.name for bike in by_name(Bike.objects.filter(owner=owner))] == ["camara", "Camara", "Cámara"]
        assert [bike.name for bike in sorted(bikes, key=lambda bike: (name_key(bike.name), str(bike.pk)))] == ["Cámara", "camara", "Camara"]

    def test_name_key_sorts_letters_that_do_not_decompose_after_z(self, db):
        # The documented approximation: Unicode does not write ø, ł, æ or œ as a base letter plus an accent, so name_key
        # sorts them by code point, after «z». ICU puts them with «o», «l», «ae» and «oe».
        from .ordering import by_name, name_key
        owner = owner_named("sin-descomponer")
        names = ["Peter", "Øyvind", "Madrid", "Łódź", "Bici", "Æro", "Pedal", "Œuvre", "Zapatillas"]
        for name in names:
            create_inventory(owner, Category, name=name)
        assert [category.name for category in by_name(Category.objects.filter(owner=owner))] == \
            ["Æro", "Bici", "Łódź", "Madrid", "Œuvre", "Øyvind", "Pedal", "Peter", "Zapatillas"]
        assert sorted(names, key=name_key) == ["Bici", "Madrid", "Pedal", "Peter", "Zapatillas", "Æro", "Øyvind", "Łódź", "Œuvre"]


class TestInUse:
    def test_in_use_contexts_sort_as_in_spanish(self, db, client):
        owner = owner_named("en-uso")
        helmet = create_inventory(owner, Item, name="Casco", category=create_inventory(owner, Category, name="Cascos"))
        for name in ("Gravel", "Ébano"):
            bike = create_inventory(owner, Bike, name=name)
            create_profile_history(owner, name=f"Perfil {name}", bike=bike, started_at=past(10), items=[helmet])
        client.force_login(owner)
        pages = {route: visible_text(parse(client.get(reverse(route, args=args)).content.decode()))
                 for route, args in (("garage:item-list", []), ("garage:index", []), ("garage:item-detail", [helmet.pk]))}
        assert {route: "En uso · Ébano, Gravel" in text for route, text in pages.items()} == dict.fromkeys(pages, True)

    def test_in_use_case_variants_follow_the_bike_order(self, db, client):
        # Two bikes whose names differ only in case: ICU puts lowercase first, as the bikes of Inicio do. The ids and
        # the code point order both go the other way, so neither can decide it.
        from .services.home import home_snapshot
        owner = owner_named("en-uso-variantes")
        helmet = create_inventory(owner, Item, name="Casco", category=create_inventory(owner, Category, name="Cascos"))
        for number, name in ((1, "Gravel"), (2, "gravel")):
            bike = Bike.objects.create(id=uuid(number), owner=owner, name=name)
            create_profile_history(owner, name=f"Perfil {number}", bike=bike, started_at=past(10), items=[helmet])
        client.force_login(owner)
        pages = {route: visible_text(parse(client.get(reverse(route, args=args)).content.decode()))
                 for route, args in (("garage:item-list", []), ("garage:index", []), ("garage:item-detail", [helmet.pk]))}
        assert [entry.bike.name for entry in home_snapshot(owner).bikes] == ["gravel", "Gravel"]
        assert {route: "En uso · gravel, Gravel" in text for route, text in pages.items()} == dict.fromkeys(pages, True)

    def test_in_use_keeps_any_bike_and_sports_in_spanish_order(self, db, client):
        # «Cualquier bici» (a profile without a bike) sorts among the bike names, not after them; a bike with a sport
        # right after the same bike without one.
        owner = owner_named("en-uso-contextos")
        helmet = create_inventory(owner, Item, name="Casco", category=create_inventory(owner, Category, name="Cascos"))
        bikes = {name: create_inventory(owner, Bike, name=name) for name in ("Gravel", "Ébano", "Bmx")}
        for index, (bike, sport) in enumerate(((bikes["Gravel"], ""), (None, ""), (bikes["Ébano"], "mountain_bike_ride"),
                                              (bikes["Bmx"], ""), (bikes["Ébano"], ""))):
            create_profile_history(owner, name=f"Perfil {index}", bike=bike, sport_type=sport, started_at=past(10), items=[helmet])
        from .services.lifecycle import item_lifecycles
        assert item_lifecycles(owner, [helmet])[helmet.pk].contexts == ("Bmx", "Cualquier bici", "Ébano", "Ébano · MTB", "Gravel")


@pytest.fixture
def pair(db, client):
    """Two of everything named «Gravel» and «Ébano»: byte order and Python's lower() put Gravel first, Spanish does not."""
    owner = owner_named("pareja")
    category = create_inventory(owner, Category, name="Cubiertas")
    bikes = {name: create_inventory(owner, Bike, name=name) for name in ("Gravel", "Ébano")}
    items = {name: create_inventory(owner, Item, name=name, category=category) for name in ("Gravel", "Ébano")}
    client.force_login(owner)
    return SimpleNamespace(owner=owner, category=category, bikes=bikes, items=items, client=client)


class TestEverySortedPlace:
    def test_equal_wear_sorts_targets_as_in_spanish(self, pair):
        from .services.workshop import workshop_snapshot
        kind = save_maintenance(pair.owner, ServiceType, name="Revisión")
        for name in ("Gravel", "Ébano"):  # no reference: both «sin datos», same state and same ratio
            save_maintenance(pair.owner, MaintenanceRule, item=pair.items[name], service_type=kind, calendar_days=365)
        shop = workshop_snapshot(pair.owner)
        html = pair.client.get(reverse("garage:maintenance")).content.decode()
        nodata = [visible_text(node).strip() for node in find_all(section(html, "nodata-title"), cls="entry-name")]
        rules = [visible_text(node).strip() for node in find_all(section(html, "rules-title"), cls="entry-name")]
        assert {"nodata": [alert.wear.target.name for alert in shop.nodata], "rules": [rule.item.name for rule in shop.rules],
                "nodata page": nodata, "rules page": rules} == \
            {"nodata": ["Ébano", "Gravel"], "rules": ["Ébano", "Gravel"], "nodata page": ["Ébano · Revisión", "Gravel · Revisión"],
             "rules page": ["Revisión · Ébano", "Revisión · Gravel"]}

    def test_types_and_due_rules_sort_as_in_spanish(self, pair):
        from .services.maintenance_due import maintenance_due
        from .services.parts import scope_rules
        from .services.workshop import workshop_snapshot
        kinds = {name: save_maintenance(pair.owner, ServiceType, name=name) for name in ("Gravel", "Ébano")}
        for name in ("Gravel", "Ébano"):
            save_maintenance(pair.owner, MaintenanceRule, item=pair.items["Gravel"], service_type=kinds[name], calendar_days=365)
        assert {"types": [kind.name for kind in workshop_snapshot(pair.owner).types],
                "due": [due.rule.service_type.name for due in maintenance_due(pair.owner)],
                "scope": [rule.service_type.name for rule, _ in scope_rules(pair.owner, pair.items["Gravel"])]} == \
            dict.fromkeys(("types", "due", "scope"), ["Ébano", "Gravel"])

    def test_parts_inside_sort_as_in_spanish(self, pair):
        from .services.parts import scope
        wheel = create_inventory(pair.owner, Item, name="Rueda", category=pair.category)
        for name in ("Gravel", "Ébano"):
            create_installation(pair.owner, item=pair.items[name], bike=None, parent_item=wheel, started_at=past(5), ended_at=None, slot=None)
        retire = visible_text(parse(pair.client.get(reverse("garage:item-retire", args=[wheel.pk])).content.decode()))
        assert {"scope": [obj.name for obj, _ in scope(pair.owner, wheel)], "retire": "Ahora: Ébano, Gravel." in retire} == \
            {"scope": ["Rueda", "Ébano", "Gravel"], "retire": True}

    def test_a_category_lists_its_items_as_in_spanish(self, pair):
        from .services.service_usage import category_comparison
        parts = category_comparison(pair.owner, pair.category, zone=timezone.get_current_timezone())
        assert [part.item.name for part in parts] == ["Ébano", "Gravel"]

    def test_statistics_ties_sort_as_in_spanish(self, pair):
        create_profile_history(pair.owner, name="Siempre", started_at=past(10), items=list(pair.items.values()))
        for name in ("Gravel", "Ébano"):
            create_manual_ride(pair.owner, started_at=past(2), bike=pair.bikes[name], name=f"Con {name}", distance_m=Decimal(20000))
        rebuild_usage(pair.owner)
        context = pair.client.get(reverse("garage:statistics")).context
        assert {"bikes": [row["row"].target.name for row in context["bikes"]], "items": [row.target.name for row in context["items"]]} == \
            {"bikes": ["Ébano", "Gravel"], "items": ["Ébano", "Gravel"]}

    def test_observed_by_bike_sorts_as_in_spanish(self, db, client):
        # «Observado por bici» of an item: one block per bike, by name, and the rides without a bike last. The ids go
        # the other way and start with letters, so neither the id order nor its text can decide it.
        from .services.statistics import statistics
        owner = owner_named("por-bici")
        chain = create_inventory(owner, Item, name="Cadena", category=create_inventory(owner, Category, name="Cadenas"))
        bikes = {name: Bike.objects.create(id=UUID(f"{prefix}0000000-0000-4000-8000-000000000001"), owner=owner, name=name)
                 for prefix, name in (("a", "Gravel"), ("b", "Ébano"))}
        create_profile_history(owner, name="Siempre", started_at=past(10), items=[chain])
        for bike in (*bikes.values(), None):
            create_manual_ride(owner, started_at=past(2), bike=bike, name="Salida", distance_m=Decimal(1000))
        rebuild_usage(owner)
        row = next(row for row in statistics(owner, item=chain).rows if row.kind == "item")
        assert [block.label for block in row.bikes] == ["Ébano", "Gravel", "Bici desconocida"]
        client.force_login(owner)
        html = client.get(reverse("garage:statistics"), {"item": chain.pk, "time_zone": "UTC"}).content.decode()
        text = visible_text(parse(html))
        blocks = text[text.index("Observado por bici"):]
        assert blocks.index("Ébano") < blocks.index("Gravel") < blocks.index("Bici desconocida"), blocks

    def test_the_gear_of_rides_sorts_as_in_spanish(self, pair):
        create_profile_history(pair.owner, name="Siempre", started_at=past(10), items=list(pair.items.values()))
        ride = create_manual_ride(pair.owner, started_at=past(2), name="Salida", distance_m=Decimal(1000))
        rows = pair.client.get(reverse("garage:usage-ride-list")).context["rows"]
        detail = pair.client.get(reverse("garage:usage-ride-detail", args=[ride.pk])).context["items"]
        found = {"list": [item.name for item in rows[0]["items"]], "detail": [item.name for item in detail]}
        for name in ("Gravel", "Ébano"):
            set_usage_override(pair.owner, ride=ride, item=pair.items[name], action="exclude")
        overrides = pair.client.get(reverse("garage:usage-ride-detail", args=[ride.pk])).context["overrides"]
        found["overrides"] = [override.item.name for override in overrides]
        assert found == dict.fromkeys(("list", "detail", "overrides"), ["Ébano", "Gravel"])

    def test_profiles_list_their_items_as_in_spanish(self, pair):
        profile = create_profile_history(pair.owner, name="Siempre", started_at=past(10), items=list(pair.items.values()))
        pages = {route: visible_text(parse(pair.client.get(reverse(route, args=args)).content.decode()))
                 for route, args in (("garage:usage-profile-list", []), ("garage:usage-profile-detail", [profile.pk]))}
        assert {route: "Ébano, Gravel" in text for route, text in pages.items()} == dict.fromkeys(pages, True)

    def test_the_bikes_of_strava_sort_as_in_spanish(self, pair):
        for gear_id, name in (("b1", "Gravel"), ("b2", "Ébano")):
            StravaGear.objects.create(owner=pair.owner, gear_id=gear_id, name=name)
        rows = pair.client.get(reverse("garage:strava")).context["gear_rows"]
        assert [row["gear"].name for row in rows] == ["Ébano", "Gravel"]


class TestCollationCheck:
    def test_a_missing_collation_is_a_system_error(self, db, monkeypatch):
        from . import checks
        assert checks.collation_check(databases=["default"]) == []
        monkeypatch.setattr(checks, "COLLATION", "xx-garage-missing-icu")  # what the query looks for: no row
        errors = checks.collation_check(databases=["default"])
        assert [error.id for error in errors] == ["garage.E001"]
        assert "xx-garage-missing-icu" in errors[0].msg and "default" in errors[0].msg
        # Without databases (runserver, a plain `check`) it reads nothing.
        with CaptureQueriesContext(connection) as queries:
            assert checks.collation_check(databases=None) == []
        assert len(queries) == 0
        # Registered: `check --database default` (and so `migrate`) stops on it.
        with pytest.raises(SystemCheckError, match="garage.E001"):
            call_command("check", "--database", "default")

    def test_the_local_cluster_passes_the_collation_check(self, db):
        # Guard: the test cluster has es-x-icu; the command does not fail, before and after the check exists.
        call_command("check", "--database", "default")
