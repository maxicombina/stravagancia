"""garage-035: parts mounted inside components; servicing a target and its parts in one visit."""
import re
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.messages import get_messages
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .models import Category, Installation, Item, MaintenanceRule, MaintenanceSnooze, ServiceEvent, ServiceType
from .presentation import wear
from .services.installations import close_installation, create_installation
from .services.lifespan import set_lifespan
from .services.maintenance import save_maintenance
from .services.maintenance_due import maintenance_due
from .services.ownership import InventoryWriteError, create_inventory, retire_inventory
from .services.parts import ScopeChanged, add_part, ancestors, part_candidates, register_together, scope, scope_rules
from .services.snoozes import snooze_rule
from .test_html import find_all, parse, visible_text
from .tests_mobile_home import NOW, at, garage  # noqa: F401 (fixture)

WRITES = {"INSERT", "UPDATE", "DELETE"}


def writes(queries):
    return [q["sql"] for q in queries if q["sql"].lstrip().split()[0].upper() in WRITES]


@pytest.fixture
def now(monkeypatch):
    monkeypatch.setattr("django.utils.timezone.now", lambda: NOW)
    return NOW


@pytest.fixture
def wheel(garage):
    owner = garage.owner
    cats = {name: create_inventory(owner, Category, name=name) for name in ("Ruedas", "Casetes", "Discos")}
    rear = create_inventory(owner, Item, name="Rueda trasera", category=cats["Ruedas"])
    cassette = create_inventory(owner, Item, name="Casete 11-34", category=cats["Casetes"])
    disc = create_inventory(owner, Item, name="Disco 160", category=cats["Discos"])
    spare = create_inventory(owner, Item, name="Disco de repuesto", category=cats["Discos"])
    create_installation(owner, item=rear, bike=garage.road, parent_item=None, started_at=at(100), ended_at=None, slot="rear_wheel")
    create_installation(owner, item=cassette, bike=None, parent_item=rear, started_at=at(90), ended_at=None, slot=None)
    create_installation(owner, item=disc, bike=None, parent_item=rear, started_at=at(100), ended_at=None, slot="brake_disc")
    review = save_maintenance(owner, ServiceType, name="Revisión de rueda")
    pads = save_maintenance(owner, ServiceType, name="Cambio de disco")
    rules = SimpleNamespace(
        review=save_maintenance(owner, MaintenanceRule, item=rear, service_type=review, calendar_days=365, anchor_at=at(100)),
        cassette=set_lifespan(owner, cassette, distance_m=Decimal(10000000), start=at(90)),
        disc=save_maintenance(owner, MaintenanceRule, item=disc, service_type=pads, distance_m=Decimal(20000000), anchor_at=at(100)))
    return SimpleNamespace(rear=rear, cassette=cassette, disc=disc, spare=spare, rules=rules, review=review, cats=cats)


def names(places):
    return [(obj.name, parent.name if parent else None) for obj, parent in places]


class TestScope:
    def test_bike_and_item(self, garage, wheel):
        assert names(scope(garage.owner, garage.road, at=NOW)) == [
            ("Carretera", None), ("Cadena 11v", None), ("Rueda trasera", None), ("Casete 11-34", "Rueda trasera"), ("Disco 160", "Rueda trasera")]
        assert names(scope(garage.owner, wheel.rear, at=NOW)) == [("Rueda trasera", None), ("Casete 11-34", "Rueda trasera"), ("Disco 160", "Rueda trasera")]
        assert names(scope(garage.owner, wheel.rear, at=at(95))) == [("Rueda trasera", None), ("Disco 160", "Rueda trasera")]  # before the cassette

    def test_profiles_retired_and_closed_are_out(self, garage, wheel):
        assert "Casco" not in [obj.name for obj, _ in scope(garage.owner, garage.road, at=NOW)]  # only counts through a profile
        retire_inventory(garage.owner, Item, wheel.disc.pk, at=at(5))
        assert [obj.name for obj, _ in scope(garage.owner, wheel.rear, at=NOW)] == ["Rueda trasera", "Casete 11-34"]
        assert [obj.name for obj, _ in scope(garage.owner, wheel.rear, at=at(10))] == ["Rueda trasera", "Casete 11-34", "Disco 160"]

    def test_rules_in_order(self, garage, wheel):
        rules = scope_rules(garage.owner, wheel.rear, at=NOW)
        assert [(rule.pk, parent.name if parent else None) for rule, parent in rules] == [
            (wheel.rules.review.pk, None), (wheel.rules.cassette.pk, "Rueda trasera"), (wheel.rules.disc.pk, "Rueda trasera")]

    def test_candidates_and_ancestors(self, garage, wheel):
        assert ancestors(garage.owner, wheel.cassette, at=NOW) == [wheel.rear.pk]
        names_ = [item.name for item in part_candidates(garage.owner, wheel.cassette, at=NOW)]
        assert "Disco de repuesto" in names_ and "Luz" in names_
        assert not {"Rueda trasera", "Casete 11-34", "Disco 160", "Cadena 11v", "Calas", "SECRET item"} & set(names_)


class TestRegisterTogether:
    def main(self, garage, wheel, **values):
        return save_maintenance(garage.owner, ServiceEvent, **{"item": wheel.rear, "service_type": wheel.review, "performed_at": at(1),
                                                              "notes": "Taller", "amount": Decimal("40"), "currency": "EUR", **values})

    def shown(self, garage, wheel, when=None):
        return [rule.pk for rule, _ in scope_rules(garage.owner, wheel.rear, at=when or at(1))]

    def test_creates_one_per_rule(self, garage, wheel):
        with transaction.atomic():
            main = self.main(garage, wheel)
            created = register_together(garage.owner, main, [wheel.rules.cassette.pk, wheel.rules.disc.pk, wheel.rules.review.pk],
                                        shown=self.shown(garage, wheel))
        assert [(e.item.name, e.service_type.name, e.performed_at, e.notes, e.amount) for e in created] == [
            ("Casete 11-34", "Sustitución", at(1), "Taller", None), ("Disco 160", "Cambio de disco", at(1), "Taller", None)]
        assert ServiceEvent.objects.filter(owner=garage.owner, item=wheel.rear).count() == 1  # the main one only once

    @pytest.mark.parametrize("case", ["changed", "foreign", "future"])
    def test_rejections_undo_everything(self, garage, wheel, case):
        foreign = MaintenanceRule.objects.get(owner=garage.other)
        with pytest.raises(InventoryWriteError) as error, transaction.atomic():
            main = self.main(garage, wheel) if case != "future" else self.main(garage, wheel, performed_at=NOW + timedelta(days=400))
            shown = self.shown(garage, wheel)
            if case == "changed":
                shown = shown[1:]
            register_together(garage.owner, main, [foreign.pk if case == "foreign" else wheel.rules.disc.pk], shown=shown)
        assert isinstance(error.value, ScopeChanged) == (case == "changed")
        assert not ServiceEvent.objects.filter(owner=garage.owner, item__in=[wheel.rear, wheel.disc]).exists()



def create_url(**params):
    return reverse("garage:service-event-create") + "?" + "&".join(f"{key}={value}" for key, value in params.items())


def form_data(**values):
    data = {"service_type": "", "performed_at": "2026-10-15T10:00", "time_zone": "UTC", "notes": "Taller", "amount": "", "currency": ""}
    data.update(values)
    return data


class TestServiceForm:
    def test_get_offers_the_parts_and_fixes_the_target(self, garage, wheel, client, now):
        client.force_login(garage.owner)
        with CaptureQueriesContext(connection) as queries:
            html = client.get(create_url(item=wheel.rear.pk)).content.decode()
        assert not writes(queries)
        assert "También en esta visita" in html and "Casete 11-34" in html and "Disco 160" in html
        assert "Sustitución de Casete 11-34 (misma ficha: reinicia su vida útil)" in html and "Revisión de rueda" in html
        assert '<span class="sr-only">Disco 160: </span>Cambio de disco' in html  # each box names its part
        assert html.count('name="shown_rules"') == 3 and 'name="together" value="1"' in html
        assert re.search(r'<select name="item"[^>]*disabled', html)
        typed = client.get(create_url(item=wheel.rear.pk, type=wheel.review.pk)).content.decode()
        assert f'value="{wheel.rules.review.pk}"' not in typed.split("También en esta visita")[1].split('name="shown_rules"')[-1] \
            and typed.count('name="also"') == 2  # the chosen type is the main intervention
        assert "También en esta visita" not in client.get(reverse("garage:service-event-create")).content.decode()
        plain = client.get(create_url(item=garage.light.pk)).content.decode()
        assert "También en esta visita" not in plain and not re.search(r'<select name="item"[^>]*disabled', plain)

    def test_post_registers_all_at_once(self, garage, wheel, client, now):
        client.force_login(garage.owner)
        shown = [str(rule.pk) for rule, _ in scope_rules(garage.owner, wheel.rear, at=at(1))]
        data = form_data(service_type=str(wheel.review.pk), amount="40", currency="EUR", together="1", shown_rules=shown,
                         also=[str(wheel.rules.cassette.pk), str(wheel.rules.disc.pk)], item=str(garage.light.pk))  # a changed target is ignored
        response = client.post(create_url(item=wheel.rear.pk), data)
        assert response.status_code == 302
        texts = [str(message) for message in get_messages(response.wsgi_request)]
        assert texts == ["Intervención guardada. Registradas también: Sustitución de Casete 11-34 (reinicia su vida útil); Cambio de disco de Disco 160."]
        events = {event.item.name: event for event in ServiceEvent.objects.filter(owner=garage.owner, performed_at=at(1) - timedelta(hours=2))}
        assert set(events) == {"Rueda trasera", "Casete 11-34", "Disco 160"}
        assert (events["Rueda trasera"].amount, events["Casete 11-34"].amount, events["Disco 160"].notes) == (Decimal("40.00"), None, "Taller")

    def test_date_that_changes_the_parts_saves_nothing(self, garage, wheel, client, now):
        client.force_login(garage.owner)
        shown = [str(rule.pk) for rule, _ in scope_rules(garage.owner, wheel.rear, at=NOW)]
        data = form_data(service_type=str(wheel.review.pk), performed_at=(at(95)).strftime("%Y-%m-%dT%H:%M"), together="1",
                         shown_rules=shown, also=[str(wheel.rules.disc.pk)])
        response = client.post(create_url(item=wheel.rear.pk), data)
        html = response.content.decode()
        assert response.status_code == 200 and "Con esa fecha cambian las piezas montadas" in html
        assert "Casete 11-34" not in html.split("También en esta visita")[1]  # the list for that date
        assert re.search(rf'value="{wheel.rules.disc.pk}" checked', html)
        assert not ServiceEvent.objects.filter(owner=garage.owner, item__in=[wheel.rear, wheel.disc]).exists()

    @pytest.mark.parametrize("also", ["not-a-uuid", "foreign"])
    def test_invalid_choice_saves_nothing(self, garage, wheel, client, now, also):
        client.force_login(garage.owner)
        shown = [str(rule.pk) for rule, _ in scope_rules(garage.owner, wheel.rear, at=at(1))]
        value = str(MaintenanceRule.objects.get(owner=garage.other).pk) if also == "foreign" else also
        response = client.post(create_url(item=wheel.rear.pk), form_data(service_type=str(wheel.review.pk), together="1", shown_rules=shown, also=[value]))
        assert response.status_code == 200 and "Elige una opción válida." in response.content.decode()
        assert not ServiceEvent.objects.filter(owner=garage.owner, item=wheel.rear).exists()

    def test_registering_a_part_ends_its_snooze_and_flags_older_ones(self, garage, wheel, client, now):
        save_maintenance(garage.owner, ServiceEvent, item=wheel.disc, service_type=wheel.rules.disc.service_type, performed_at=at(1))
        snooze_rule(garage.owner, wheel.rules.cassette, calendar_days=30, at=at(3))
        client.force_login(garage.owner)
        shown = [str(rule.pk) for rule, _ in scope_rules(garage.owner, wheel.rear, at=at(2))]
        data = form_data(service_type=str(wheel.review.pk), performed_at=at(2).strftime("%Y-%m-%dT%H:%M"), together="1", shown_rules=shown,
                         also=[str(wheel.rules.cassette.pk), str(wheel.rules.disc.pk)])
        response = client.post(create_url(item=wheel.rear.pk), data)
        texts = [str(message) for message in get_messages(response.wsgi_request)]
        assert "Cambio de disco de Disco 160 (hay una posterior: no reinicia la cuenta)" in texts[0]
        due = next(due for due in maintenance_due(garage.owner, at=NOW) if due.rule.pk == wheel.rules.cassette.pk)
        assert due.snooze is None  # its reference changed: the snooze no longer applies
        assert MaintenanceSnooze.objects.get().ended_at is None  # computed, nothing written


class TestScreens:
    def test_item_parts_and_nested_lede(self, garage, wheel, client, now):
        client.force_login(garage.owner)
        html = client.get(reverse("garage:item-detail", args=[wheel.rear.pk])).content.decode()
        parts = html.split('id="parts-title"')[1].split('id="events-title"')[0]
        assert "Casete 11-34" in parts and "Disco 160" in parts and "brake_disc" in parts and "Añadir pieza" in parts
        assert reverse("garage:item-part-create", args=[wheel.rear.pk]) in parts
        nested = client.get(reverse("garage:item-detail", args=[wheel.cassette.pk])).content.decode()
        assert "Sobre Rueda trasera · Carretera desde el" in nested  # garage-042: the words of the Material list
        loose = client.get(reverse("garage:item-detail", args=[garage.light.pk])).content.decode()
        assert "Sin piezas montadas dentro: por ejemplo el casete o el disco de una rueda." in loose

    def test_add_part(self, garage, wheel, client, now):
        client.force_login(garage.owner)
        url = reverse("garage:item-part-create", args=[wheel.rear.pk])
        with CaptureQueriesContext(connection) as queries:
            html = client.get(url).content.decode()
        assert not writes(queries) and "Añadir pieza a Rueda trasera" in html and "Disco de repuesto · Discos" in html
        assert "Casete 11-34 ·" not in html and "Cadena 11v ·" not in html
        response = client.post(url, {"item": str(wheel.spare.pk), "at": "2026-10-16T10:00", "time_zone": "UTC", "slot": "brake_disc"})
        html = response.content.decode()
        assert response.status_code == 200 and "Esa posición ya está ocupada en esas fechas." in html  # the disc holds it
        response = client.post(url, {"item": str(wheel.spare.pk), "at": "2026-10-16T10:00", "time_zone": "UTC", "slot": "spare", "notes": "De viaje"})
        assert response.status_code == 302
        mount = Installation.objects.get(owner=garage.owner, item=wheel.spare)
        assert (mount.parent_item_id, mount.slot, mount.notes, mount.ended_at) == (wheel.rear.pk, "spare", "De viaje", None)

    def test_add_part_errors_are_spanish(self, garage, wheel):
        loose = create_inventory(garage.owner, Item, name="Suelto", category=wheel.cats["Discos"])
        add_part(garage.owner, loose, garage.light, at=at(10))
        with pytest.raises(InventoryWriteError) as error:
            add_part(garage.owner, garage.light, loose, at=at(5))  # the light already contains it: a cycle
        assert "ciclo" in " ".join(error.value.messages)
        with pytest.raises(InventoryWriteError) as error:
            add_part(garage.owner, loose, wheel.disc, at=at(5))  # the disc is mounted in the wheel then
        assert "ya está montada" in " ".join(error.value.messages)

    def test_add_part_ownership_and_retired(self, garage, wheel, client, now):
        client.force_login(garage.owner)
        foreign = Item.objects.get(owner=garage.other)
        assert client.get(reverse("garage:item-part-create", args=[foreign.pk])).status_code == 404
        url = reverse("garage:item-part-create", args=[wheel.rear.pk])
        response = client.post(url, {"item": str(foreign.pk), "at": "2026-10-16T10:00", "time_zone": "UTC"})
        assert "Elige una opción válida." in response.content.decode()
        retire_inventory(garage.owner, Item, garage.light.pk, at=at(1))
        assert garage.light.name + " ·" not in client.get(url).content.decode()
        retired_page = client.get(reverse("garage:item-part-create", args=[garage.light.pk]), follow=True)
        assert "no admite piezas nuevas" in retired_page.content.decode()
        assert "Añadir pieza" not in client.get(reverse("garage:item-detail", args=[garage.light.pk])).content.decode().split('id="parts-title"')[1].split("</div>")[0]
        assert not Installation.objects.filter(owner=garage.owner, item=foreign).exists()

    def test_part_states_come_from_the_due_snapshot(self, garage, wheel, client, now):
        snooze_rule(garage.owner, wheel.rules.disc, calendar_days=3, at=at(1))
        client.force_login(garage.owner)
        html = client.get(reverse("garage:item-detail", args=[wheel.rear.pk])).content.decode()
        disc_wear = wear(next(due for due in maintenance_due(garage.owner, at=NOW) if due.rule.pk == wheel.rules.disc.pk))
        assert f"{disc_wear.word}</span>" in html.split('id="parts-title"')[1]


class TestServiceFormReviewFixes:
    def front(self, garage, wheel):
        front = create_inventory(garage.owner, Item, name="Rueda delantera", category=wheel.cats["Ruedas"])
        create_installation(garage.owner, item=front, bike=garage.road, parent_item=None, started_at=at(100), ended_at=None, slot="front_wheel")
        disc = create_inventory(garage.owner, Item, name="Disco delantero", category=wheel.cats["Discos"])
        create_installation(garage.owner, item=disc, bike=None, parent_item=front, started_at=at(10), ended_at=None, slot=None)
        rule = save_maintenance(garage.owner, MaintenanceRule, item=disc, service_type=wheel.rules.disc.service_type, distance_m=Decimal(1000000), anchor_at=at(10))
        return front, rule

    def test_main_only_on_another_date_is_never_blocked(self, garage, wheel, client, now):
        front, rule = self.front(garage, wheel)
        client.force_login(garage.owner)
        shown = [str(rule.pk)]
        data = form_data(service_type=str(wheel.review.pk), performed_at=at(20).strftime("%Y-%m-%dT%H:%M"), together="1", shown_rules=shown)
        assert client.post(create_url(item=front.pk), data).status_code == 302  # nothing ticked: no comparison
        assert ServiceEvent.objects.filter(owner=garage.owner, item=front).count() == 1

    def test_empty_list_at_that_date_keeps_the_target(self, garage, wheel, client, now):
        front, rule = self.front(garage, wheel)
        client.force_login(garage.owner)
        data = form_data(service_type=str(wheel.review.pk), performed_at=at(20).strftime("%Y-%m-%dT%H:%M"), together="1",
                         shown_rules=[str(rule.pk)], also=[str(rule.pk)])
        html = client.post(create_url(item=front.pk), data).content.decode()
        assert "Con esa fecha cambian las piezas montadas" in html and "En esa fecha no hay otras reglas en lo montado." in html
        assert 'name="together" value="1"' in html and not re.findall(r'name="shown_rules"', html)
        again = form_data(service_type=str(wheel.review.pk), performed_at=at(20).strftime("%Y-%m-%dT%H:%M"), together="1")
        assert client.post(create_url(item=front.pk), again).status_code == 302
        assert ServiceEvent.objects.filter(owner=garage.owner, item=front).count() == 1

    def test_bike_flow_duplicates_and_type_case(self, garage, wheel, client, now):
        client.force_login(garage.owner)
        url = create_url(bike=garage.road.pk)
        html = client.get(url).content.decode()
        assert re.search(r'<select name="bike"[^>]*disabled', html) and '<input type="hidden" name="item"' in html
        upper = client.get(create_url(item=wheel.rear.pk, type=str(wheel.review.pk).upper())).content.decode()
        assert upper.count('name="also"') == 2  # the chosen type, however written, is the main intervention
        shown = [str(rule.pk) for rule, _ in scope_rules(garage.owner, garage.road, at=at(1))]
        data = form_data(service_type=str(wheel.review.pk), together="1", shown_rules=shown,
                         also=[str(wheel.rules.disc.pk), str(wheel.rules.disc.pk)])
        assert client.post(url, data).status_code == 302
        assert ServiceEvent.objects.filter(owner=garage.owner, item=wheel.disc).count() == 1  # a repeated id is one intervention
        assert ServiceEvent.objects.filter(owner=garage.owner, bike=garage.road, service_type=wheel.review).count() == 1

    def test_main_error_keeps_ticks_and_target(self, garage, wheel, client, now):
        client.force_login(garage.owner)
        shown = [str(rule.pk) for rule, _ in scope_rules(garage.owner, wheel.rear, at=at(1))]
        html = client.post(create_url(item=wheel.rear.pk), form_data(together="1", shown_rules=shown, also=[str(wheel.rules.disc.pk)])).content.decode()
        assert re.search(rf'value="{wheel.rules.disc.pk}" checked', html) and re.search(r'<select name="item"[^>]*disabled', html)
        assert not ServiceEvent.objects.filter(owner=garage.owner).exclude(item=garage.chain).filter(item__in=[wheel.rear, wheel.disc]).exists()

    def test_query_budget_does_not_grow_with_parts(self, garage, wheel, client, now):
        client.force_login(garage.owner)
        with CaptureQueriesContext(connection) as before:
            client.get(create_url(item=wheel.rear.pk))
        for index in range(4):
            extra = create_inventory(garage.owner, Item, name=f"Pieza {index}", category=wheel.cats["Discos"])
            create_installation(garage.owner, item=extra, bike=None, parent_item=wheel.rear, started_at=at(50), ended_at=None, slot=None)
            save_maintenance(garage.owner, MaintenanceRule, item=extra, service_type=wheel.review, calendar_days=30, anchor_at=at(50))
        with CaptureQueriesContext(connection) as after:
            client.get(create_url(item=wheel.rear.pk))
        # garage-047 F02: +3 fixed reads (the lifecycle of the whole «Objeto» list, for its labels), whatever its length.
        assert len(after) == len(before) <= 37, (len(before), len(after))


def test_other_target_keeps_the_type_and_part_message(garage, wheel, client, now):
    client.force_login(garage.owner)
    html = client.get(create_url(item=wheel.rear.pk, type=wheel.review.pk)).content.decode()
    assert f'href="{reverse("garage:service-event-create")}?type={wheel.review.pk}"' in html and '<span class="sr-only"> regla</span>' in html
    response = client.post(reverse("garage:item-part-create", args=[wheel.rear.pk]),
                           {"item": str(wheel.spare.pk), "at": "2026-10-16T10:00", "time_zone": "UTC"}, follow=True)
    assert "Pieza añadida: Disco de repuesto en Rueda trasera." in response.content.decode()


class TestPreviousParts:
    """garage-047 F16 (D19): a piece with nothing inside now, but with parts before, names the ones it had."""

    @staticmethod
    def close(owner, item, when):
        mount = Installation.objects.get(owner=owner, item=item, ended_at__isnull=True)
        close_installation(owner, mount.pk, at=when)

    @staticmethod
    def parts(client, item):
        page = parse(client.get(reverse("garage:item-detail", args=[item.pk])).content.decode())
        section = find_all(page, "section", aria_labelledby="parts-title")[0]
        empty = find_all(section, "li", cls="empty")
        assert len(empty) == 1, empty
        return visible_text(empty[0]), [(visible_text(link), link.attrs["href"]) for link in find_all(empty[0], "a")]

    def test_a_parent_without_parts_names_the_ones_it_had(self, garage, wheel, client, now):
        self.close(garage.owner, wheel.cassette, at(20))
        self.close(garage.owner, wheel.disc, at(10))
        client.force_login(garage.owner)
        expected = ("Sin piezas montadas ahora. Antes llevaba: Disco 160 (hasta el 6 oct 2026), Casete 11-34 (hasta el 26 sep 2026).",
                    [("Disco 160", reverse("garage:item-detail", args=[wheel.disc.pk])),
                     ("Casete 11-34", reverse("garage:item-detail", args=[wheel.cassette.pk]))])
        assert self.parts(client, wheel.rear) == expected  # active, still on the bike
        retire_inventory(garage.owner, Item, wheel.rear.pk, at=at(1))
        assert self.parts(client, wheel.rear) == expected  # retired: the case of the friction

    def test_a_part_still_inside_keeps_the_list(self, garage, wheel, client, now):
        self.close(garage.owner, wheel.disc, at(10))  # the cassette stays
        client.force_login(garage.owner)
        html = client.get(reverse("garage:item-detail", args=[wheel.rear.pk])).content.decode()
        parts = html.split('id="parts-title"')[1].split('id="events-title"')[0]
        assert "Casete 11-34" in parts and "Antes llevaba" not in parts and "Sin piezas montadas" not in parts

    def test_a_part_mounted_later_is_not_one_it_had(self, garage, wheel, client, now):
        self.close(garage.owner, wheel.cassette, at(20))
        self.close(garage.owner, wheel.disc, at(10))
        create_installation(garage.owner, item=wheel.spare, bike=None, parent_item=wheel.rear, started_at=NOW + timedelta(days=5),
                            ended_at=NOW + timedelta(days=9), slot=None)  # ahead: neither now nor before
        client.force_login(garage.owner)
        text, links = self.parts(client, wheel.rear)
        assert "Disco de repuesto" not in text and [name for name, _ in links] == ["Disco 160", "Casete 11-34"]

    def test_at_most_five_and_how_many_more(self, garage, client, now):
        parent = create_inventory(garage.owner, Item, name="Caja", category=garage.light.category)
        inner = [create_inventory(garage.owner, Item, name=f"Pieza {number}", category=garage.light.category) for number in range(7)]
        for number, item in enumerate(inner):  # Pieza 0 left first, Pieza 6 last
            create_installation(garage.owner, item=item, bike=None, parent_item=parent, started_at=at(60 - number), ended_at=at(30 - number), slot=None)
        client.force_login(garage.owner)
        text, links = self.parts(client, parent)
        assert [name for name, _ in links] == ["Pieza 6", "Pieza 5", "Pieza 4", "Pieza 3", "Pieza 2"]  # the most recent
        assert text.startswith("Sin piezas montadas ahora. Antes llevaba: Pieza 6 (hasta el 22 sep 2026), Pieza 5 (hasta el 21 sep 2026), ")
        assert text.endswith("Pieza 2 (hasta el 18 sep 2026) y 2 más en Detalles.")
        Installation.objects.filter(item=inner[0]).delete()
        text, links = self.parts(client, parent)
        assert len(links) == 5 and text.endswith("Pieza 2 (hasta el 18 sep 2026) y 1 más en Detalles.")
        Installation.objects.filter(item=inner[1]).delete()
        text, links = self.parts(client, parent)
        assert len(links) == 5 and text.endswith("Pieza 2 (hasta el 18 sep 2026).") and " más en Detalles" not in text  # five: all named

    def test_a_part_that_came_back_is_listed_once(self, garage, wheel, client, now):
        self.close(garage.owner, wheel.disc, at(50))
        create_installation(garage.owner, item=wheel.disc, bike=None, parent_item=wheel.rear, started_at=at(40), ended_at=at(5), slot="brake_disc")
        self.close(garage.owner, wheel.cassette, at(20))
        client.force_login(garage.owner)
        text, links = self.parts(client, wheel.rear)
        assert [name for name, _ in links] == ["Disco 160", "Casete 11-34"]  # by its last time inside
        assert text == "Sin piezas montadas ahora. Antes llevaba: Disco 160 (hasta el 11 oct 2026), Casete 11-34 (hasta el 26 sep 2026)."

    @staticmethod
    def retired_with(owner, category, parts):
        """A parent with `parts` ((name, start), ...) inside, then retired: every part leaves at that same instant."""
        parent = create_inventory(owner, Item, name="Rueda delantera", category=category)
        for name, start in parts:
            part = create_inventory(owner, Item, name=name, category=category)
            create_installation(owner, item=part, bike=None, parent_item=parent, started_at=start, ended_at=None, slot=None)
        retire_inventory(owner, Item, parent.pk, at=at(5))
        return parent

    def test_parts_that_left_together_go_by_name(self, garage, client, now):
        # The case of the friction (B11-R1-01): set up together and closed by the retirement, they share the start and the
        # end. Neither decides, so their names do, in Spanish order (accents and case do not lead), not their ids.
        names = ("Casete", "Cubierta", "Disco", "Rodamiento", "Válvula", "Cámara", "llanta")
        parent = self.retired_with(garage.owner, garage.light.category, [(name, at(60)) for name in names])
        client.force_login(garage.owner)
        text, links = self.parts(client, parent)
        assert [name for name, _ in links] == ["Cámara", "Casete", "Cubierta", "Disco", "llanta"]
        assert text == ("Sin piezas montadas ahora. Antes llevaba: Cámara (hasta el 11 oct 2026), Casete (hasta el 11 oct 2026), "
                        "Cubierta (hasta el 11 oct 2026), Disco (hasta el 11 oct 2026), llanta (hasta el 11 oct 2026) y 2 más en Detalles.")

    def test_on_the_same_end_the_newest_mount_goes_first(self, garage, client, now):
        # Same end, different starts: the one mounted last is the most recent, whatever its name.
        parent = self.retired_with(garage.owner, garage.light.category, [("Aro", at(60)), ("Zapata", at(30)), ("Buje", at(60))])
        client.force_login(garage.owner)
        assert [name for name, _ in self.parts(client, parent)[1]] == ["Zapata", "Aro", "Buje"]

    def test_without_history_the_text_of_today(self, garage, client, now):
        client.force_login(garage.owner)
        assert self.parts(client, garage.light) == ("Sin piezas montadas dentro: por ejemplo el casete o el disco de una rueda.", [])
        retire_inventory(garage.owner, Item, garage.light.pk, at=at(1))
        assert self.parts(client, garage.light) == ("Sin piezas montadas dentro.", [])

    def test_the_dates_are_in_the_viewers_zone(self, garage, wheel, client, now):
        # 23:30 UTC on 30 September is 1 October in Madrid and still 30 September in Buenos Aires.
        self.close(garage.owner, wheel.cassette, at(20))
        self.close(garage.owner, wheel.disc, NOW.replace(month=9, day=30, hour=23, minute=30))
        client.force_login(garage.owner)
        client.cookies["garage_tz"] = "Europe/Madrid"
        assert "Disco 160 (hasta el 1 oct 2026)" in self.parts(client, wheel.rear)[0]
        client.cookies["garage_tz"] = "America/Argentina/Buenos_Aires"
        assert "Disco 160 (hasta el 30 sep 2026)" in self.parts(client, wheel.rear)[0]

    def test_children_are_read_once(self, garage, client, now):
        parent = create_inventory(garage.owner, Item, name="Caja", category=garage.light.category)
        first = create_inventory(garage.owner, Item, name="Pieza", category=garage.light.category)
        create_installation(garage.owner, item=first, bike=None, parent_item=parent, started_at=at(60), ended_at=at(30), slot=None)
        client.force_login(garage.owner)
        url = reverse("garage:item-detail", args=[parent.pk])
        with CaptureQueriesContext(connection) as queries:
            assert client.get(url).status_code == 200
        few = len(queries)
        children = [q["sql"] for q in queries if f'"garage_installation"."parent_item_id" = \'{parent.pk}\'' in q["sql"]]
        assert len(children) == 1, children  # «Piezas» and «Material montado sobre este objeto» share one read
        for number in range(6):
            item = create_inventory(garage.owner, Item, name=f"Otra {number}", category=garage.light.category)
            create_installation(garage.owner, item=item, bike=None, parent_item=parent, started_at=at(29 - number), ended_at=at(20 - number), slot=None)
        with CaptureQueriesContext(connection) as queries:
            assert client.get(url).status_code == 200
        assert len(queries) == few
