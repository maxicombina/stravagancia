"""garage-032.2: the mobile bike screen and the ride list filtered by bike."""
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .models import Bike, Item, MaintenanceRule, ServiceEvent, ServiceType
from .presentation import STATES
from .services.installations import create_installation
from .services.maintenance import save_maintenance
from .services.ownership import create_inventory
from .services.rides import create_manual_ride
from .services.snoozes import snooze_rule
from .test_html import accessible_text, find_all, parse, visible_text
from .tests_mobile_home import at, days_ago, garage, on_bike  # noqa: F401 (fixture)

WRITES = {"INSERT", "UPDATE", "DELETE"}


def page(client, bike):
    with CaptureQueriesContext(connection) as queries:
        response = client.get(reverse("garage:bike-detail", args=[bike.pk]))
    assert response.status_code == 200
    assert not [q for q in queries if q["sql"].lstrip().split()[0].upper() in WRITES]
    return response.content.decode(), len(queries)


class TestBikeScreen:
    def test_page(self, garage, client):
        kind = save_maintenance(garage.owner, ServiceType, name="Lavado")
        save_maintenance(garage.owner, ServiceEvent, bike=garage.road, service_type=kind, performed_at=at(2), amount=Decimal("5"), currency="EUR")
        create_manual_ride(garage.owner, started_at=at(1), bike=garage.road, name="Sin distancia")
        client.force_login(garage.owner)
        html, count = page(client, garage.road)
        assert count <= 34, count  # garage-034: snoozes in the due snapshot; garage-036: the bike's rides for usage between interventions
        assert "<script>" not in html and ' style="' not in html
        for text in ("<h1>Carretera</h1>", "Registrado en Garage", "<b>400</b>", "<b>5</b>", "1 sin distancia: los km son un mínimo.",
                     "Requiere atención", "Cadena 11v", "Revisar", "Km por mes", "Montado ahora", "chain · desde el",
                     "Últimas salidas", "Sin distancia", "Ruta 10", f'href="{reverse("garage:usage-ride-list")}?bike={garage.road.pk}"',
                     "Intervenciones en la bici", "Lavado", "5,00 EUR", f'href="{reverse("garage:service-event-create")}?bike={garage.road.pk}"',
                     "Fotos privadas", "Historial de montajes directos en la bici", 'aria-label="Volver a Garaje"', "<b>16</b>"):
            assert text in html, text
        rides = [row for row in find_all(parse(html), "a", cls="entry compact") if row.attrs["href"].startswith("/garage/rides/")]
        assert len(rides) == 5  # last five rides only
        for absent in ("SECRET", "Pista", "Calas"):
            assert absent not in html, absent

    def test_nested_mount_and_its_wear(self, garage, client):
        create_installation(garage.owner, item=garage.shoes, bike=garage.road, parent_item=None, started_at=at(1), ended_at=None, slot=None)
        client.force_login(garage.owner)
        html, _ = page(client, garage.road)
        assert any("Sobre Zapatillas" in visible_text(row) for row in find_all(parse(html), "a", cls="entry compact nested"))
        assert "Calas" in html and "Vencido" in html and "Calas · sobre Zapatillas" in html
        assert "Cambio de cadena · Carretera" not in html and "Cambio de cadena</span>" in html
        other, _ = page(client, garage.gravel)
        assert "Calas" not in other and "Nada montado" in other

    def test_query_count_is_constant(self, garage, client):
        client.force_login(garage.owner)
        page(client, garage.road)
        _, before = page(client, garage.road)
        for number in range(8):
            item = create_inventory(garage.owner, Item, name=f"Pieza {number}", category=garage.helmet.category)
            create_installation(garage.owner, item=item, bike=garage.road, parent_item=None, started_at=at(5), ended_at=None, slot=f"s{number}")
            save_maintenance(garage.owner, MaintenanceRule, item=item, service_type=save_maintenance(garage.owner, ServiceType, name=f"T{number}"),
                             calendar_days=10, anchor_at=at(30))
            create_manual_ride(garage.owner, started_at=at(2 + number), bike=garage.road, name=f"Extra {number}", distance_m=Decimal(1000))
        html, after = page(client, garage.road)
        assert after == before, (before, after)
        assert "Pieza 7" in html

    def test_retired_parts_and_missing_time(self, garage, client):
        from .services.ownership import retire_inventory
        create_manual_ride(garage.owner, started_at=at(1), bike=garage.road, name="Sin tiempo", distance_m=Decimal(1000))
        retire_inventory(garage.owner, Item, garage.chain.pk, at=at(0))
        client.force_login(garage.owner)
        html, _ = page(client, garage.road)
        assert "Cadena 11v" not in html.split("Km por mes")[0] and "1 sin tiempo en movimiento: las horas son un mínimo." in html

    def test_retired_foreign_and_empty(self, garage, client):
        client.force_login(garage.owner)
        html, _ = page(client, garage.retired)
        assert "Retirada el" in html and "Sin salidas con esta bici." in html and "Aún no hay salidas con esta bici" in html
        foreign = Bike.objects.get(name="SECRET bike")
        assert client.get(reverse("garage:bike-detail", args=[foreign.pk])).status_code == 404


def classes(node):
    return node.attrs.get("class", "").split()


def uses(node):
    return [use.attrs["href"] for use in find_all(node, "use")]


class TestHeaderBadge:
    """Spec F3b, §4.6 and D17: the same badge as on the bike's row in Garaje."""

    def badge(self, client, g, bike):
        client.force_login(g.owner)
        header = find_all(parse(page(client, bike)[0]), "header", cls="bike-hero")[0]
        chips = find_all(header, "span", cls="chip")
        assert len(chips) == 1, chips
        return chips[0]

    def test_counts_with_the_icon_of_the_gravest(self, garage, client):
        on_bike(garage, garage.gravel, "soon")
        on_bike(garage, garage.gravel, "due")
        badge = self.badge(client, garage, garage.gravel)
        assert visible_text(badge) == "2 avisos" and "st-due" in classes(badge)
        assert uses(badge) == ["#i-octagon"] and len(find_all(badge, "svg", aria_hidden="true")) == 1

    def test_the_gravest_is_heard_and_not_seen(self, garage, client):
        on_bike(garage, garage.gravel, "soon")
        on_bike(garage, garage.gravel, "due")
        badge = self.badge(client, garage, garage.gravel)
        assert accessible_text(badge) == "2 avisos, el más grave: Vencido"
        assert "el más grave" not in visible_text(badge)

    def test_takes_icon_and_word_from_states(self, garage, client):
        on_bike(garage, garage.gravel, "soon")
        on_bike(garage, garage.gravel, "review")
        badge = self.badge(client, garage, garage.gravel)
        word, icon = STATES["review"]
        assert "st-review" in classes(badge) and uses(badge) == [f"#i-{icon}"]
        assert accessible_text(badge) == f"2 avisos, el más grave: {word}"

    def test_one_alert_has_nothing_to_be_the_gravest_of(self, garage, client):
        on_bike(garage, garage.gravel, "due")
        badge = self.badge(client, garage, garage.gravel)
        assert visible_text(badge) == "1 aviso" and accessible_text(badge) == "1 aviso: Vencido"

    def test_no_alerts_is_a_neutral_chip(self, garage, client):
        badge = self.badge(client, garage, garage.gravel)
        assert visible_text(badge) == accessible_text(badge) == "Sin avisos"
        assert classes(badge) == ["chip"] and not find_all(badge, "svg")

    def test_a_snoozed_rule_does_not_count(self, garage, client):
        snooze_rule(garage.owner, on_bike(garage, garage.gravel, "due"), calendar_days=3)
        assert visible_text(self.badge(client, garage, garage.gravel)) == "Sin avisos"

    def test_no_data_and_calm_rules_do_not_count(self, garage, client):
        on_bike(garage, garage.gravel, "nodata")
        on_bike(garage, garage.gravel, "current")
        assert visible_text(self.badge(client, garage, garage.gravel)) == "Sin avisos"

    def test_a_piece_inside_a_mounted_piece_counts(self, garage, client):
        create_installation(garage.owner, item=garage.shoes, bike=garage.gravel, parent_item=None, started_at=at(1), ended_at=None, slot=None)
        assert accessible_text(self.badge(client, garage, garage.gravel)) == "1 aviso: Vencido"

    def test_it_says_the_same_as_the_row_in_garaje(self, garage, client):
        on_bike(garage, garage.gravel, "soon")
        on_bike(garage, garage.gravel, "due")
        create_installation(garage.owner, item=garage.shoes, bike=garage.gravel, parent_item=None, started_at=at(1), ended_at=None, slot=None)
        badge = self.badge(client, garage, garage.gravel)
        section = find_all(parse(client.get(reverse("garage:index")).content.decode()), "section", aria_labelledby="bikes-title")[0]
        row = find_all(section, "a", href=reverse("garage:bike-detail", args=[garage.gravel.pk]))[0]
        other = find_all(row, "span", cls="chip")[0]
        assert accessible_text(badge) == accessible_text(other) == "3 avisos, el más grave: Vencido"
        assert (classes(badge), uses(badge)) == (classes(other), uses(other))


class TestMountedNow:
    """Spec F3b: the ring of a piece with a rule, with what gives its state without color beside it."""

    def row(self, client, g, item, bike=None):
        client.force_login(g.owner)
        section = find_all(parse(page(client, bike or g.road)[0]), "section", aria_labelledby="mounted-title")[0]
        rows = find_all(section, "a", cls="entry compact", href=reverse("garage:item-detail", args=[item.pk]))
        assert len(rows) == 1, rows
        return rows[0]

    def rule(self, g, item, days_past=None, **amounts):
        amounts = amounts or dict(calendar_days=10, anchor_at=days_ago(days_past))
        return save_maintenance(g.owner, MaintenanceRule, item=item, service_type=save_maintenance(g.owner, ServiceType, name=f"Tipo {days_past}"), **amounts)

    def test_a_due_piece_has_the_ring_with_its_icon(self, garage, client):
        self.rule(garage, garage.chain, days_past=11)
        row = self.row(client, garage, garage.chain)
        rings = find_all(row, "svg", cls="ring")
        assert len(rings) == 1 and rings[0].attrs["aria-hidden"] == "true"
        assert uses(rings[0]) == ["#i-chain"]
        assert not find_all(row, cls="glyph")

    def test_a_due_piece_has_the_state_on_the_row(self, garage, client):
        """Without it the arc would come out violet: var(--c, …) falls back to the primary. The chain also has a rule in review: the gravest decides."""
        self.rule(garage, garage.chain, days_past=11)
        row = self.row(client, garage, garage.chain)
        assert "st-due" in classes(row) and "st-review" not in classes(row)
        assert len(find_all(row, "circle", cls="arc")) == 1

    def test_the_chip_gives_the_state_without_color(self, garage, client):
        self.rule(garage, garage.chain, days_past=11)
        row = self.row(client, garage, garage.chain)
        chips = find_all(row, "span", cls="chip st-due")
        assert len(chips) == 1 and uses(chips[0]) == ["#i-octagon"]
        assert visible_text(chips[0]) == "Vencido" and "Vencido" in accessible_text(row)

    def test_a_piece_without_a_rule_keeps_tile_and_chevron(self, garage, client):
        piece = create_inventory(garage.owner, Item, name="Sillín de prueba", category=garage.helmet.category)
        create_installation(garage.owner, item=piece, bike=garage.road, parent_item=None, started_at=at(5), ended_at=None, slot="saddle")
        row = self.row(client, garage, piece)
        assert not find_all(row, "svg", cls="ring") and not find_all(row, cls="chip")
        assert len(find_all(row, "span", cls="glyph")) == 1 and "#i-chev-right" in uses(row)
        assert not [name for name in classes(row) if name.startswith("st-")]

    def test_past_150_the_row_and_its_chip_deepen_together(self, garage, client):
        self.rule(garage, garage.chain, days_past=16)
        row = self.row(client, garage, garage.chain)
        assert {"st-due", "over-150"} <= set(classes(row))
        assert find_all(row, "span", cls="chip st-due over-150")

    def test_past_200_the_row_and_its_chip_deepen_together(self, garage, client):
        self.rule(garage, garage.chain, days_past=30)
        row = self.row(client, garage, garage.chain)
        assert {"st-due", "over-200"} <= set(classes(row))
        assert find_all(row, "span", cls="chip st-due over-200")

    def test_a_snoozed_piece_is_grey_however_far_it_has_gone(self, garage, client):
        rule = self.rule(garage, garage.helmet, days_past=30)
        create_installation(garage.owner, item=garage.helmet, bike=garage.gravel, parent_item=None, started_at=at(5), ended_at=None, slot=None)
        snooze_rule(garage.owner, rule, calendar_days=3)
        row = self.row(client, garage, garage.helmet, bike=garage.gravel)
        assert "st-snoozed" in classes(row) and not {"st-due", "over-200"} & set(classes(row))
        chip = find_all(row, "span", cls="chip st-snoozed")[0]
        assert uses(chip) == ["#i-clock"] and visible_text(chip) == "Pospuesto"

    def test_a_piece_without_data_has_a_ring_without_arc(self, garage, client):
        piece = create_inventory(garage.owner, Item, name="Pieza sin datos", category=garage.helmet.category)
        create_installation(garage.owner, item=piece, bike=garage.gravel, parent_item=None, started_at=at(5), ended_at=None, slot=None)
        self.rule(garage, piece, calendar_days=1000)
        row = self.row(client, garage, piece, bike=garage.gravel)
        assert "st-nodata" in classes(row) and not find_all(row, "circle", cls="arc")
        assert find_all(row, "svg", cls="ring") and uses(find_all(row, "span", cls="chip st-nodata")[0]) == ["#i-help"]

    def test_a_nested_piece_has_its_ring_too(self, garage, client):
        create_installation(garage.owner, item=garage.shoes, bike=garage.gravel, parent_item=None, started_at=at(1), ended_at=None, slot=None)
        row = self.row(client, garage, garage.cleats, bike=garage.gravel)
        assert {"nested", "st-due"} <= set(classes(row)) and find_all(row, "svg", cls="ring")


class TestSectionsInCards:
    """Spec F3b, §4.3: the same sections, in the same order, in cards."""

    TITLES = ["Registrado en Garage", "Requiere atención", "Km por mes", "Montado ahora", "Últimas salidas", "Intervenciones en la bici", "Fotos privadas"]

    def test_each_section_is_a_card(self, garage, client):
        client.force_login(garage.owner)
        root = parse(page(client, garage.road)[0])
        sections = find_all(root, "section", aria_labelledby=True)
        assert [visible_text(find_all(section, "h2")[0]) for section in sections] == self.TITLES
        for section in sections:
            assert {"card", "panel"} & set(classes(section)), classes(section)

    def test_the_headings_keep_their_order(self, garage, client):
        client.force_login(garage.owner)
        headings = [visible_text(heading) for heading in find_all(parse(page(client, garage.road)[0]), "h2")]
        assert headings == [*self.TITLES, "Historial de montajes directos en la bici"]

    def test_the_photos_of_a_piece_stay_as_they_were(self, garage, client):
        client.force_login(garage.owner)
        html = client.get(reverse("garage:item-detail", args=[garage.chain.pk])).content.decode()
        section = find_all(parse(html), "section", aria_labelledby="photos-title")[0]
        assert classes(section) == ["sec"]

    def test_the_action_bar_stays_outside_of_them(self, garage, client):
        """Sticky, it only stays in view within its parent: inside a card it would scroll away with it."""
        client.force_login(garage.owner)
        main = find_all(parse(page(client, garage.road)[0]), "main")[0]
        assert [child for child in main.children if not isinstance(child, str) and "actionbar" in classes(child)]


class TestRidesByBike:
    def test_filter(self, garage, client):
        client.force_login(garage.owner)
        url = reverse("garage:usage-ride-list")
        html = client.get(url, {"bike": garage.gravel.pk}).content.decode()
        assert "Pista" in html and "Ruta 10" not in html and "Quitar el filtro de Gravel" in html
        assert client.get(url, {"bike": Bike.objects.get(name="SECRET bike").pk}).status_code == 404
        assert client.get(url, {"bike": "not-a-uuid"}).status_code == 404
        assert "Pista" not in client.get(url, {"bike": garage.gravel.pk, "pending": "1"}).content.decode()

    def pills(self, client, **query):
        """The filters of Salidas, in order: (classes, href, what it says)."""
        html = client.get(reverse("garage:usage-ride-list"), query).content.decode()
        navs = find_all(parse(html), "nav", cls="chips")
        assert len(navs) == 1 and navs[0].attrs["aria-label"]
        return [(classes(pill), pill.attrs["href"], visible_text(pill)) for pill in find_all(navs[0], "a")]

    def test_the_filters_are_pills_and_say_the_same(self, garage, client):
        client.force_login(garage.owner)
        all_rides = reverse("garage:usage-ride-list")
        assert self.pills(client) == [(["chip-link"], "?pending=1", "Sólo las que están por revisar")]
        assert self.pills(client, pending="1") == [(["chip-link"], all_rides, "Ver todas")]

    def test_the_filter_of_a_bike_is_the_chosen_pill_and_takes_itself_off(self, garage, client):
        client.force_login(garage.owner)
        all_rides = reverse("garage:usage-ride-list")
        chosen, other = self.pills(client, bike=garage.gravel.pk)
        assert chosen == (["chip-link", "on"], all_rides, "Gravel")
        assert (other[0], other[2]) == (["chip-link"], "Sólo las que están por revisar")
        chosen, other = self.pills(client, bike=garage.gravel.pk, pending="1")
        assert chosen == (["chip-link", "on"], f"{all_rides}?pending=1", "Gravel")
        assert (other[0], other[2]) == (["chip-link"], "Ver todas")
        chip = find_all(parse(client.get(all_rides, {"bike": garage.gravel.pk}).content.decode()), "a", cls="chip-link on")[0]
        assert chip.attrs["aria-label"] == "Quitar el filtro de Gravel"
        assert "aria-current" not in chip.attrs, "it goes to another list: it does not name the page we are on"
        assert uses(chip) == ["#i-bike", "#i-x"]

    def test_pagination_keeps_the_bike(self, garage, client):
        for number in range(21):
            create_manual_ride(garage.owner, started_at=at(30 + number), bike=garage.gravel, name=f"G{number}", distance_m=Decimal(1000))
        client.force_login(garage.owner)
        html = client.get(reverse("garage:usage-ride-list"), {"bike": garage.gravel.pk}).content.decode()
        assert f"bike={garage.gravel.pk}&amp;page=2" in html and "Página 1 de 2" in html
