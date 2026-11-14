"""garage-047 F02 (D10): the object and bike selectors tell equal names apart.

An item option reads «{name} · {category} · {where it is now}»; a bike option reads «{name}», or «{name} · retirada».
The retired ones go last. Two options that would still read the same get a date in the viewer's zone, and identical
ones are numbered in the order of the list. The value sent does not change.
"""
import unicodedata
from datetime import date, datetime, timedelta, timezone as dt_timezone
from uuid import UUID

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from .models import Bike, Category, Item, ServiceEvent, ServiceType
from .services.installations import create_installation
from .services.maintenance import save_maintenance
from .services.ownership import create_inventory
from .services.usage_profiles import create_profile_history
from .test_html import find_all, parse, visible_text

UTC = dt_timezone.utc


def at(year, month, day, hour=10, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def uuid(number):
    return UUID(f"00000000-0000-4000-8000-{number:012d}")


def options(html, field):
    """(value, text) of the options of the select `field`, without its empty option."""
    selects = find_all(parse(html), "select", name=field)
    assert len(selects) == 1, f"{len(selects)} selects named {field!r}"
    return [(option.attrs.get("value", ""), visible_text(option)) for option in find_all(selects[0], "option")
            if option.attrs.get("value")]


def labels(html, field):
    """{value: text} of the options of `field`."""
    return dict(options(html, field))


def owner_named(name):
    return get_user_model().objects.create_user(name, password="test-only-password")


def registered(objects, when):
    """Sets the instant they were created (auto_now_add) to `when`: «alta del …» then reads a known date."""
    type(objects[0]).objects.filter(pk__in=[obj.pk for obj in objects]).update(created_at=when)


class ChoicesTestCase(TestCase):
    def page(self, route, *args, zone="Europe/Madrid"):
        self.client.cookies["garage_tz"] = zone
        response = self.client.get(reverse("garage:" + route, args=args))
        self.assertEqual(response.status_code, 200)
        return response.content.decode()


class ItemOptionTests(ChoicesTestCase):
    """One owner with an item in each place, and a retired bike."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = owner = owner_named("choices-owner")
        cats = {name: create_inventory(owner, Category, name=name) for name in
                ("Cadenas", "Sillines", "Ruedas", "Cámaras", "Cascos", "Cubiertas", "Bidones", "Luces")}

        def item(name, category, **values):
            return create_inventory(owner, Item, name=name, category=cats[category], **values)
        cls.road = create_inventory(owner, Bike, name="Carretera")
        cls.gravel = create_inventory(owner, Bike, name="Gravel")
        cls.old_bike = create_inventory(owner, Bike, name="Antigua", retired_at=at(2025, 6, 1))
        cls.chain = item("Cadena 11v", "Cadenas")
        cls.wheel = item("Rueda", "Ruedas")
        cls.tube = item("Cámara", "Cámaras")
        cls.saddle = item("Sillín B", "Sillines")
        cls.new_saddle = item("Sillín nuevo", "Sillines")
        cls.helmet = item("Casco", "Cascos")
        cls.tyre = item("Cubierta vieja", "Cubiertas", retired_at=at(2025, 3, 1))
        cls.light = item("Luz", "Luces", retired_at=timezone.now() + timedelta(days=30))  # retires later: not yet
        cls.bottle = item("Bidón", "Bidones")
        create_installation(owner, item=cls.chain, bike=cls.road, parent_item=None, started_at=at(2025, 3, 3), ended_at=None, slot=None)
        create_installation(owner, item=cls.wheel, bike=cls.gravel, parent_item=None, started_at=at(2025, 1, 10), ended_at=None, slot=None)
        create_installation(owner, item=cls.tube, bike=None, parent_item=cls.wheel, started_at=at(2025, 2, 1), ended_at=None, slot=None)
        create_installation(owner, item=cls.saddle, bike=cls.road, parent_item=None, started_at=at(2025, 1, 1),
                            ended_at=at(2025, 2, 1), slot=None)  # used before, loose now
        cls.mount = create_installation(owner, item=cls.bottle, bike=cls.gravel, parent_item=None, started_at=at(2025, 4, 1),
                                        ended_at=None, slot=None)
        create_profile_history(owner, name="Siempre", started_at=at(2025, 1, 1), items=[cls.helmet])
        cls.kind = save_maintenance(owner, ServiceType, name="Revisión")
        cls.expected = {cls.chain: "Cadena 11v · Cadenas · en Carretera", cls.wheel: "Rueda · Ruedas · en Gravel",
                        cls.tube: "Cámara · Cámaras · sobre Rueda", cls.saddle: "Sillín B · Sillines · disponible",
                        cls.new_saddle: "Sillín nuevo · Sillines · sin estrenar", cls.helmet: "Casco · Cascos · en uso",
                        cls.tyre: "Cubierta vieja · Cubiertas · retirado", cls.light: "Luz · Luces · sin estrenar",
                        cls.bottle: "Bidón · Bidones · en Gravel"}

    def setUp(self):
        self.client.force_login(self.owner)

    def item_selects(self):
        """(route, args, field, item left out of the list): the four forms of F02."""
        return [("maintenance-rule-create", (), "item", None), ("service-event-create", (), "item", None),
                ("installation-create", (self.bottle.pk,), "parent_item", self.bottle),
                ("installation-transfer", (self.mount.pk,), "parent_item", self.bottle),
                ("installation-replace", (self.mount.pk,), "incoming_item", self.bottle)]

    def bike_selects(self):
        return [("maintenance-rule-create", (), "bike"), ("service-event-create", (), "bike"),
                ("installation-create", (self.bottle.pk,), "bike"), ("installation-transfer", (self.mount.pk,), "bike")]

    def test_an_item_option_names_its_category_and_place(self):
        for route, args, field, left_out in self.item_selects():
            with self.subTest(page=route, field=field):
                expected = {str(item.pk): text for item, text in self.expected.items() if item != left_out}
                self.assertEqual(labels(self.page(route, *args), field), expected)

    def test_retired_items_go_last_and_say_so(self):
        # The database's Spanish order, «Cubierta vieja» moved to the end; «Luz» retires later and keeps its place.
        order = [self.bottle, self.chain, self.tube, self.helmet, self.light, self.wheel, self.saddle, self.new_saddle, self.tyre]
        for route, args, field, left_out in self.item_selects():
            with self.subTest(page=route, field=field):
                shown = options(self.page(route, *args), field)
                self.assertEqual([value for value, _ in shown], [str(item.pk) for item in order if item != left_out])
                self.assertEqual([text for _, text in shown if "retirad" in text], ["Cubierta vieja · Cubiertas · retirado"])
        for route, args, field in self.bike_selects():
            with self.subTest(page=route, field=field):
                self.assertEqual(options(self.page(route, *args), field),
                                 [(str(self.road.pk), "Carretera"), (str(self.gravel.pk), "Gravel"),
                                  (str(self.old_bike.pk), "Antigua · retirada")])

    def test_a_retired_option_still_saves(self):
        # Guard: history on a retired item is legitimate; its option still sends the item itself.
        response = self.client.post(reverse("garage:service-event-create"), {
            "item": self.tyre.pk, "service_type": self.kind.pk, "performed_at": "2025-02-01T10:00", "time_zone": "UTC"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ServiceEvent.objects.get(owner=self.owner).item, self.tyre)

    def test_editing_keeps_the_stored_choice(self):
        # Guard: an old mount inside an item retired since then still shows that item, selected.
        valve = create_inventory(self.owner, Item, name="Válvula", category=self.tube.category)
        old = create_installation(self.owner, item=valve, bike=None, parent_item=self.tyre, started_at=at(2025, 1, 1),
                                  ended_at=at(2025, 2, 1), slot=None)
        html = self.page("installation-edit", old.pk)
        selected = [option.attrs["value"] for select in find_all(parse(html), "select", name="parent_item")
                    for option in find_all(select, "option") if "selected" in option.attrs]
        self.assertEqual(selected, [str(self.tyre.pk)])
        response = self.client.post(reverse("garage:installation-edit", args=[old.pk]), {
            "parent_item": self.tyre.pk, "started_at": "2025-01-01T10:00", "ended_at": "2025-02-01T10:00",
            "notes": "Cambiada", "time_zone": "UTC"})
        self.assertEqual(response.status_code, 302)
        old.refresh_from_db()
        self.assertEqual((old.parent_item, old.notes), (self.tyre, "Cambiada"))


class EqualLabelTests(ChoicesTestCase):
    def setUp(self):
        self.owner = owner_named("pares")
        self.client.force_login(self.owner)
        self.cats = {name: create_inventory(self.owner, Category, name=name) for name in
                     ("Cubiertas", "Sillines", "Cadenas", "Ruedas", "Repuestos", "Cámaras")}
        self.road = create_inventory(self.owner, Bike, name="Carretera")

    def item(self, name, category, **values):
        return create_inventory(self.owner, Item, name=name, category=self.cats[category], **values)

    def mount(self, item, started_at):
        return create_installation(self.owner, item=item, bike=self.road, parent_item=None, started_at=started_at,
                                   ended_at=None, slot=None)

    def test_two_equal_labels_get_a_date(self):
        front, rear = self.item("Cubierta", "Cubiertas"), self.item("Cubierta", "Cubiertas")
        self.mount(front, at(2025, 3, 3))
        self.mount(rear, at(2025, 4, 5))
        first_saddle = self.item("Sillín", "Sillines", retired_at=at(2025, 3, 3, 12))
        second_saddle = self.item("Sillín", "Sillines", retired_at=at(2025, 5, 5, 12))
        bought = self.item("Cadena", "Cadenas", acquired_on=date(2025, 2, 1))
        unknown = self.item("Cadena", "Cadenas")
        registered([unknown], at(2026, 1, 10, 12))
        # Same name and category, different places: they already read differently, so no date.
        on_bike, retired_wheel = self.item("Rueda", "Ruedas"), self.item("Rueda", "Ruedas", retired_at=at(2025, 1, 1))
        self.mount(on_bike, at(2025, 1, 1))
        spare = self.item("Cadena", "Repuestos")  # same name, another category
        expected = {front: "Cubierta · Cubiertas · en Carretera desde el 3 mar 2025",
                    rear: "Cubierta · Cubiertas · en Carretera desde el 5 abr 2025",
                    first_saddle: "Sillín · Sillines · retirado el 3 mar 2025",
                    second_saddle: "Sillín · Sillines · retirado el 5 may 2025",
                    bought: "Cadena · Cadenas · sin estrenar · comprado el 1 feb 2025",
                    unknown: "Cadena · Cadenas · sin estrenar · alta del 10 ene 2026",
                    on_bike: "Rueda · Ruedas · en Carretera", retired_wheel: "Rueda · Ruedas · retirado",
                    spare: "Cadena · Repuestos · sin estrenar"}
        self.assertEqual(labels(self.page("maintenance-rule-create"), "item"),
                         {str(item.pk): text for item, text in expected.items()})

    def test_two_equal_bike_labels_get_a_date(self):
        bought = create_inventory(self.owner, Bike, name="Gravel", acquired_on=date(2024, 5, 1))
        unknown = create_inventory(self.owner, Bike, name="Gravel")
        registered([unknown], at(2026, 1, 10, 12))
        retired = create_inventory(self.owner, Bike, name="Gravel", retired_at=at(2025, 1, 1))  # reads differently already
        later = create_inventory(self.owner, Bike, name="Plegable", retired_at=timezone.now() + timedelta(days=30))  # not yet
        shown = options(self.page("maintenance-rule-create"), "bike")
        self.assertEqual(dict(shown), {str(self.road.pk): "Carretera", str(bought.pk): "Gravel · comprada el 1 may 2024",
                                       str(unknown.pk): "Gravel · alta del 10 ene 2026", str(later.pk): "Plegable",
                                       str(retired.pk): "Gravel · retirada"})
        self.assertEqual([value for value, _ in shown][-2:], [str(later.pk), str(retired.pk)])

    def test_identical_labels_are_numbered(self):
        # Created in an order that is not the ids': equal names are listed by id, and numbered in that order.
        tubes = [Item.objects.create(id=uuid(number), owner=self.owner, name="Cámara", category=self.cats["Cámaras"])
                 for number in (3, 1, 2)]
        broken = [Item.objects.create(id=uuid(number), owner=self.owner, name="Cámara", category=self.cats["Cámaras"],
                                      retired_at=at(2025, 3, 1, 12)) for number in (5, 4)]
        registered(tubes + broken, at(2026, 1, 10, 12))
        bikes = [Bike.objects.create(id=uuid(number), owner=self.owner, name="Gravel") for number in (7, 6)]
        registered(bikes, at(2026, 1, 10, 12))
        html = self.page("maintenance-rule-create")
        self.assertEqual(options(html, "item"), [
            (str(uuid(1)), "Cámara · Cámaras · sin estrenar · alta del 10 ene 2026"),
            (str(uuid(2)), "Cámara · Cámaras · sin estrenar · alta del 10 ene 2026 (2)"),
            (str(uuid(3)), "Cámara · Cámaras · sin estrenar · alta del 10 ene 2026 (3)"),
            (str(uuid(4)), "Cámara · Cámaras · retirado el 1 mar 2025"),
            (str(uuid(5)), "Cámara · Cámaras · retirado el 1 mar 2025 (2)")])
        self.assertEqual(options(html, "bike"), [(str(self.road.pk), "Carretera"),
                                                 (str(uuid(6)), "Gravel · alta del 10 ene 2026"),
                                                 (str(uuid(7)), "Gravel · alta del 10 ene 2026 (2)")])

    def test_names_that_only_look_equal_get_a_date(self):
        # The browser shows two spaces in a row as one, a letter written whole (NFC «í») like the same letter plus
        # its accent (NFD «i» + U+0301), and a zero-width space as nothing: each pair reads alike, so each gets a date.
        spaced = self.item("Cámara 700c", "Cámaras", acquired_on=date(2025, 2, 1))
        double = self.item("Cámara  700c", "Cámaras", acquired_on=date(2025, 3, 1))
        whole = self.item("Sillín", "Sillines", retired_at=at(2025, 3, 3, 12))
        split = self.item("Sillín", "Sillines", retired_at=at(2025, 5, 5, 12))
        plain = self.item("Cadena", "Cadenas", acquired_on=date(2025, 2, 1))
        hidden = self.item("Cadena​", "Cadenas", acquired_on=date(2025, 3, 1))
        upper, lower = self.item("Rueda", "Ruedas"), self.item("rueda", "Ruedas")  # case can be seen: no date
        for item, name in ((double, "Cámara  700c"), (split, "Sillín"), (hidden, "Cadena​")):
            item.refresh_from_db()
            self.assertEqual(item.name, name)  # stored as typed
        bought = create_inventory(self.owner, Bike, name="Mi Gravel", acquired_on=date(2024, 5, 1))
        later = create_inventory(self.owner, Bike, name="Mi  Gravel", acquired_on=date(2024, 6, 1))
        # visible_text() collapses spaces as the browser does; the other differences stay in the text as stored.
        expected = {spaced: "Cámara 700c · Cámaras · sin estrenar · comprado el 1 feb 2025",
                    double: "Cámara 700c · Cámaras · sin estrenar · comprado el 1 mar 2025",
                    whole: "Sillín · Sillines · retirado el 3 mar 2025",
                    split: "Sillín · Sillines · retirado el 5 may 2025",
                    plain: "Cadena · Cadenas · sin estrenar · comprado el 1 feb 2025",
                    hidden: "Cadena​ · Cadenas · sin estrenar · comprado el 1 mar 2025",
                    upper: "Rueda · Ruedas · sin estrenar", lower: "rueda · Ruedas · sin estrenar"}
        html = self.page("maintenance-rule-create")
        self.assertEqual(labels(html, "item"), {str(item.pk): text for item, text in expected.items()})
        self.assertEqual(labels(html, "bike"), {str(self.road.pk): "Carretera",
                                                str(bought.pk): "Mi Gravel · comprada el 1 may 2024",
                                                str(later.pk): "Mi Gravel · comprada el 1 jun 2024"})

    def test_names_that_only_look_equal_with_the_same_date_are_numbered(self):
        items = [self.item("Cámara 700c", "Cámaras"), self.item("Cámara  700c", "Cámaras"),
                 self.item("Sillín", "Sillines"), self.item("Sillín", "Sillines")]
        registered(items, at(2026, 1, 10, 12))
        # As the eye reads them: either form of «í» first, the pair reads the same but for its number.
        shown = [unicodedata.normalize("NFC", text) for _, text in options(self.page("maintenance-rule-create"), "item")]
        self.assertEqual(shown, ["Cámara 700c · Cámaras · sin estrenar · alta del 10 ene 2026",
                                 "Cámara 700c · Cámaras · sin estrenar · alta del 10 ene 2026 (2)",
                                 "Sillín · Sillines · sin estrenar · alta del 10 ene 2026",
                                 "Sillín · Sillines · sin estrenar · alta del 10 ene 2026 (2)"])

    def test_the_label_dates_follow_the_viewer_zone(self):
        # 23:30 UTC is already the next day in Madrid; a purchase date is a plain date, the same in every zone.
        late = self.item("Sillín", "Sillines", retired_at=at(2025, 3, 2, 23, 30))
        later = self.item("Sillín", "Sillines", retired_at=at(2025, 3, 10, 12))
        front, rear = self.item("Cubierta", "Cubiertas"), self.item("Cubierta", "Cubiertas")
        self.mount(front, at(2025, 3, 2, 23, 30))
        self.mount(rear, at(2025, 4, 5))
        bought = self.item("Cadena", "Cadenas", acquired_on=date(2025, 2, 1))
        unknown = self.item("Cadena", "Cadenas")
        registered([unknown], at(2026, 1, 9, 23, 30))
        cases = {"Europe/Madrid": ("3 mar 2025", "10 ene 2026"), "UTC": ("2 mar 2025", "9 ene 2026")}
        for zone, (day, created) in cases.items():
            with self.subTest(zone=zone):
                shown = labels(self.page("maintenance-rule-create", zone=zone), "item")
                self.assertEqual(shown[str(late.pk)], f"Sillín · Sillines · retirado el {day}")
                self.assertEqual(shown[str(later.pk)], "Sillín · Sillines · retirado el 10 mar 2025")
                self.assertEqual(shown[str(front.pk)], f"Cubierta · Cubiertas · en Carretera desde el {day}")
                self.assertEqual(shown[str(bought.pk)], "Cadena · Cadenas · sin estrenar · comprado el 1 feb 2025")
                self.assertEqual(shown[str(unknown.pk)], f"Cadena · Cadenas · sin estrenar · alta del {created}")
        # A rejected form is drawn again in the viewer's zone too.
        self.client.cookies["garage_tz"] = "UTC"
        response = self.client.post(reverse("garage:maintenance-rule-create"), {"item": late.pk, "time_zone": "UTC"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(labels(response.content.decode(), "item")[str(late.pk)], "Sillín · Sillines · retirado el 2 mar 2025")

    def test_without_items_or_bikes_only_the_empty_option(self):
        empty = owner_named("vacio")
        self.client.force_login(empty)
        html = self.page("maintenance-rule-create")
        for field in ("item", "bike"):
            with self.subTest(field=field):
                self.assertEqual([visible_text(option) for select in find_all(parse(html), "select", name=field)
                                  for option in find_all(select, "option")], ["—"])


class OrderAndCostTests(ChoicesTestCase):
    def test_options_follow_the_material_list_order(self):
        # Guard: case variants that ICU tells apart, created in an order that is neither ICU's nor the bytes'.
        owner = owner_named("orden-material")
        category = create_inventory(owner, Category, name="Varios")
        names = ["Sram GX", "camara", "SRAM GX", "Cámara", "sram gx", "Camara"]
        created = [Item.objects.create(id=uuid(number), owner=owner, name=name, category=category)
                   for number, name in enumerate(names, start=1)]
        retired = Item.objects.create(id=uuid(9), owner=owner, name="Camara rota", category=category, retired_at=at(2025, 1, 1))
        self.client.force_login(owner)
        listed = [node.attrs["href"] for node in find_all(parse(self.page("item-list")), "a", cls="entry")
                  if "/items/" in node.attrs.get("href", "")]
        listed = [str(item.pk) for href in listed for item in created if href == reverse("garage:item-detail", args=[item.pk])]
        self.assertEqual(len(listed), len(created))
        for route in ("maintenance-rule-create", "service-event-create"):
            with self.subTest(page=route):
                values = [value for value, _ in options(self.page(route), "item") if value != str(retired.pk)]
                self.assertEqual(values, listed)

    def test_item_options_cost_the_same_queries_with_5_or_25_items(self):
        # Guard: the labels of the whole list come from a fixed number of reads, whatever its length.
        owner = owner_named("presupuesto")
        self.client.force_login(owner)
        category = create_inventory(owner, Category, name="Piezas")
        bike = create_inventory(owner, Bike, name="Gravel")
        target = create_inventory(owner, Item, name="Objetivo", category=category)
        mount = create_installation(owner, item=target, bike=bike, parent_item=None, started_at=at(2025, 1, 1), ended_at=None, slot=None)

        def add(count, batch):
            """`count` items, one in each place in turn: on the bike, inside another, in use, retired, never used."""
            in_use = []
            for number in range(count):
                place = number % 5
                item = create_inventory(owner, Item, name=f"Pieza {batch}-{number}", category=category,
                                        **({"retired_at": at(2025, 1, 1)} if place == 3 else {}))
                if place == 0:
                    create_installation(owner, item=item, bike=bike, parent_item=None, started_at=at(2025, 1, 2), ended_at=None, slot=None)
                elif place == 1:
                    create_installation(owner, item=item, bike=None, parent_item=target, started_at=at(2025, 1, 2), ended_at=None, slot=None)
                elif place == 2:
                    in_use.append(item)
            create_profile_history(owner, name=f"Perfil {batch}", started_at=at(2025, 1, 1), items=in_use)

        pages = [("maintenance-rule-create", ()), ("service-event-create", ()), ("installation-create", (target.pk,)),
                 ("installation-transfer", (mount.pk,)), ("installation-replace", (mount.pk,))]

        def cost():
            counts = {}
            for route, args in pages:
                with CaptureQueriesContext(connection) as queries:
                    self.page(route, *args)
                counts[route] = len(queries)
            return counts
        add(5, "a")
        few = cost()
        add(20, "b")
        self.assertEqual(Item.objects.filter(owner=owner).count(), 26)
        self.assertEqual(cost(), few)
        self.assertEqual(len(options(self.page("maintenance-rule-create"), "item")), 26)
