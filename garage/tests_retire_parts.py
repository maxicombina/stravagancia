"""garage-038: retire the outgoing part when replacing, and retire together with what is mounted."""
import re
from datetime import timedelta
import pytest
from django.contrib.messages import get_messages
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .models import Bike, ImportRun, Installation, Item, MaintenanceRule
from .services.installations import create_installation
from .services.lifespan import lifespan_rule, set_lifespan
from .services.ownership import InventoryWriteError, create_inventory, update_inventory
from .services.retirement import mounted_in, retire_with_parts
from .test_html import find_all, parse, visible_text
from .tests_mobile_home import NOW, at, garage  # noqa: F401 (fixture)
from .tests_parts import wheel  # noqa: F401 (fixture)
from .tests_strava_client import connected, strava  # noqa: F401 (fixture)

WRITES = {"INSERT", "UPDATE", "DELETE"}


@pytest.fixture
def now(monkeypatch):
    monkeypatch.setattr("django.utils.timezone.now", lambda: NOW)
    return NOW


def fresh(obj):
    return type(obj).objects.get(pk=obj.pk)


class TestService:
    def test_mounted_in(self, garage, wheel):
        assert [obj.name for obj in mounted_in(garage.owner, garage.road, at=NOW)] == ["Cadena 11v", "Rueda trasera", "Casete 11-34", "Disco 160"]
        assert [obj.name for obj in mounted_in(garage.owner, wheel.rear, at=NOW)] == ["Casete 11-34", "Disco 160"]

    def test_retire_with_and_without_parts(self, garage, wheel):
        assert retire_with_parts(garage.owner, wheel.rear, at=at(1)) == []
        assert fresh(wheel.rear).retired_at == at(1) and fresh(wheel.cassette).retired_at is None
        assert Installation.objects.get(item=wheel.cassette).ended_at == at(1)  # unmounted, still available
        retired = retire_with_parts(garage.owner, garage.road, at=at(1) + (NOW - at(1)) / 2, parts=True)
        assert [obj.name for obj in retired] == ["Cadena 11v"]  # the wheel was already retired: not mounted any more

    def test_bike_with_nested_parts_all_or_nothing(self, garage, wheel):
        retired = retire_with_parts(garage.owner, garage.road, at=at(1), parts=True)
        assert {obj.name for obj in retired} == {"Cadena 11v", "Rueda trasera", "Casete 11-34", "Disco 160"}
        assert all(fresh(obj).retired_at == at(1) for obj in (garage.road, garage.chain, wheel.rear, wheel.cassette, wheel.disc))

    def test_an_error_undoes_everything(self, garage, wheel):
        # A mount of the disc that starts after the retirement cannot be closed by it.
        create_installation(garage.owner, item=wheel.spare, bike=None, parent_item=wheel.disc, started_at=at(1), ended_at=None, slot=None)
        with pytest.raises(InventoryWriteError) as error:
            retire_with_parts(garage.owner, wheel.rear, at=at(2), parts=True)
        assert "No se puede retirar Disco 160" in " ".join(error.value.messages)
        assert all(fresh(obj).retired_at is None for obj in (wheel.rear, wheel.cassette, wheel.disc))


class TestScreens:
    def test_retire_page_offers_the_parts(self, garage, wheel, client, now):
        client.force_login(garage.owner)
        url = reverse("garage:item-retire", args=[wheel.rear.pk])
        with CaptureQueriesContext(connection) as queries:
            html = client.get(url).content.decode()
        assert not [q for q in queries if q["sql"].split()[0] in WRITES]
        assert "Retirar también lo que lleva montado (2)" in html and "Ahora: Casete 11-34, Disco 160." in html
        loose = client.get(reverse("garage:item-retire", args=[garage.light.pk])).content.decode()
        assert 'name="with_parts"' not in loose
        response = client.post(url, {"at": "2026-10-16T10:00", "time_zone": "UTC", "with_parts": "on"}, follow=True)
        assert "Retirado. El historial se conserva. También retirados: Casete 11-34, Disco 160." in response.content.decode()
        assert fresh(wheel.disc).retired_at is not None

    def test_retire_bike_without_parts_keeps_them(self, garage, wheel, client, now):
        client.force_login(garage.owner)
        client.post(reverse("garage:bike-retire", args=[garage.road.pk]), {"at": "2026-10-16T10:00", "time_zone": "UTC"})
        assert fresh(garage.road).retired_at is not None and fresh(wheel.rear).retired_at is None and fresh(garage.chain).retired_at is None

    def test_replace_and_retire_the_outgoing(self, garage, wheel, client, now):
        set_lifespan(garage.owner, garage.chain, calendar_days=365, start=at(200))
        spare = create_inventory(garage.owner, Item, name="Cadena nueva", category=garage.chain.category)
        mount = Installation.objects.get(item=garage.chain, ended_at__isnull=True)
        client.force_login(garage.owner)
        url = reverse("garage:installation-replace", args=[mount.pk])
        html = client.get(url).content.decode()
        assert "Retirar lo que sale (Cadena 11v)" in html
        response = client.post(url, {"incoming_item": str(spare.pk), "at": "2026-10-16T10:00", "time_zone": "UTC",
                                     "inherit_lifespan": "on", "retire_outgoing": "on"})
        texts = [str(message) for message in get_messages(response.wsgi_request)]
        assert "Cadena 11v: retirado desde el reemplazo. Se puede reactivar desde su ficha." in texts
        assert not any("sigue contando días" in text for text in texts)  # retired: it no longer warns
        assert fresh(garage.chain).retired_at is not None and lifespan_rule(garage.owner, spare) is not None

    def test_replace_without_retiring_is_unchanged(self, garage, client, now):
        spare = create_inventory(garage.owner, Item, name="Cadena nueva", category=garage.chain.category)
        mount = Installation.objects.get(item=garage.chain, ended_at__isnull=True)
        client.force_login(garage.owner)
        client.post(reverse("garage:installation-replace", args=[mount.pk]), {"incoming_item": str(spare.pk), "at": "2026-10-16T10:00", "time_zone": "UTC"})
        assert fresh(garage.chain).retired_at is None and Installation.objects.get(item=spare).ended_at is None

    def test_foreign(self, garage, client):
        client.force_login(garage.owner)
        foreign = Bike.objects.get(owner=garage.other)
        assert client.get(reverse("garage:bike-retire", args=[foreign.pk])).status_code == 404


class TestReviewFixes:
    def test_conflict_is_spanish_and_names_the_part(self, garage, wheel, client, now):
        create_installation(garage.owner, item=wheel.spare, bike=None, parent_item=wheel.disc, started_at=at(1), ended_at=None, slot=None)
        client.force_login(garage.owner)
        url = reverse("garage:item-retire", args=[wheel.rear.pk])
        html = client.post(url, {"at": at(2).strftime("%Y-%m-%dT%H:%M"), "time_zone": "UTC", "with_parts": "on",
                                 "shown_parts": ",".join(str(obj.pk) for obj in mounted_in(garage.owner, wheel.rear, at=at(2)))}).content.decode()
        assert "No se puede retirar Disco 160 en esa fecha" in html and "Correct later" not in html
        assert fresh(wheel.rear).retired_at is None

    def test_changed_list_is_confirmed_by_saving_again(self, garage, wheel, client, now):
        from .services.installations import close_installation
        close_installation(garage.owner, Installation.objects.get(item=wheel.disc).pk, at=NOW + timedelta(days=5))
        client.force_login(garage.owner)
        url = reverse("garage:item-retire", args=[wheel.rear.pk])
        data = {"at": (NOW + timedelta(days=10)).strftime("%Y-%m-%dT%H:%M"), "time_zone": "UTC", "with_parts": "on",
                "shown_parts": ",".join(str(obj.pk) for obj in mounted_in(garage.owner, wheel.rear))}
        html = client.post(url, data).content.decode()  # by then the disc is out of the wheel
        assert "En esa fecha lo montado es: Casete 11-34." in html and fresh(wheel.rear).retired_at is None
        confirmed = re.search(r'name="shown_parts" value="([^"]*)"', html).group(1)
        response = client.post(url, {**data, "shown_parts": confirmed}, follow=True)
        assert "Retirado. El historial se conserva. También retirado: Casete 11-34." in response.content.decode()
        assert fresh(wheel.cassette).retired_at is not None and fresh(wheel.disc).retired_at is None

    def test_bike_wording_and_plural(self, garage, wheel, client, now):
        client.force_login(garage.owner)
        url = reverse("garage:bike-retire", args=[garage.road.pk])
        shown = ",".join(str(obj.pk) for obj in mounted_in(garage.owner, garage.road))
        response = client.post(url, {"at": "2026-10-16T10:00", "time_zone": "UTC", "with_parts": "on", "shown_parts": shown}, follow=True)
        assert "Retirada. El historial se conserva. También retirados: Cadena 11v, Rueda trasera, Casete 11-34, Disco 160." in response.content.decode()

    def test_replace_retiring_a_part_with_parts_and_future_dates(self, garage, wheel, client, now):
        new_wheel = create_inventory(garage.owner, Item, name="Rueda nueva", category=wheel.cats["Ruedas"])
        mount = Installation.objects.get(item=wheel.rear, ended_at__isnull=True)
        client.force_login(garage.owner)
        url = reverse("garage:installation-replace", args=[mount.pk])
        assert "Sus piezas (Casete 11-34, Disco 160) se desmontan y quedan disponibles; lo que llevan dentro sigue en ellas." in client.get(url).content.decode()
        future = client.post(url, {"incoming_item": str(new_wheel.pk), "at": "2026-10-20T10:00", "time_zone": "UTC", "retire_outgoing": "on"})
        texts = [str(message) for message in get_messages(future.wsgi_request)]
        assert "Reemplazo futuro: lo que sale no se retira. Retíralo cuando ocurra." in texts and fresh(wheel.rear).retired_at is None

    def test_replace_now_releases_the_parts(self, garage, wheel, client, now):
        new_wheel = create_inventory(garage.owner, Item, name="Rueda nueva", category=wheel.cats["Ruedas"])
        mount = Installation.objects.get(item=wheel.rear, ended_at__isnull=True)
        client.force_login(garage.owner)
        response = client.post(reverse("garage:installation-replace", args=[mount.pk]),
                               {"incoming_item": str(new_wheel.pk), "at": "2026-10-16T10:00", "time_zone": "UTC", "retire_outgoing": "on"})
        texts = [str(message) for message in get_messages(response.wsgi_request)]
        assert any("Sus piezas quedan desmontadas y disponibles: Casete 11-34, Disco 160." in text for text in texts)
        assert fresh(wheel.rear).retired_at is not None and fresh(wheel.cassette).retired_at is None

    def test_failed_retirement_undoes_the_replacement_and_inheritance(self, garage, wheel, client, now):
        set_lifespan(garage.owner, wheel.rear, calendar_days=365, start=at(100))
        create_installation(garage.owner, item=wheel.spare, bike=None, parent_item=wheel.rear, started_at=at(1), ended_at=None, slot=None)
        new_wheel = create_inventory(garage.owner, Item, name="Rueda nueva", category=wheel.cats["Ruedas"])
        mount = Installation.objects.get(item=wheel.rear, bike=garage.road)
        client.force_login(garage.owner)
        html = client.post(reverse("garage:installation-replace", args=[mount.pk]),
                           {"incoming_item": str(new_wheel.pk), "at": at(2).strftime("%Y-%m-%dT%H:%M"), "time_zone": "UTC",
                            "inherit_lifespan": "on", "retire_outgoing": "on"}).content.decode()
        assert "No se puede retirar Rueda trasera en esa fecha" in html
        assert Installation.objects.get(pk=mount.pk).ended_at is None and lifespan_rule(garage.owner, new_wheel) is None
        assert not Installation.objects.filter(item=new_wheel).exists()

    def test_scheduled_target_offers_nothing_that_cannot_work(self, garage, wheel, client, now):
        from .services.ownership import update_inventory
        update_inventory(garage.owner, Item, wheel.rear.pk, retired_at=NOW + timedelta(days=30))
        client.force_login(garage.owner)
        assert 'name="with_parts"' not in client.get(reverse("garage:item-retire", args=[wheel.rear.pk])).content.decode()
        mount = Installation.objects.get(item=wheel.rear, bike=garage.road)
        assert 'name="retire_outgoing"' not in client.get(reverse("garage:installation-replace", args=[mount.pk])).content.decode()

    def test_only_direct_parts_are_released(self, garage, wheel, client, now):
        inner = create_inventory(garage.owner, Item, name="Rotor interior", category=wheel.cats["Discos"])
        create_installation(garage.owner, item=inner, bike=None, parent_item=wheel.disc, started_at=at(50), ended_at=None, slot=None)
        mount = Installation.objects.get(item=wheel.rear, bike=garage.road)
        client.force_login(garage.owner)
        html = client.get(reverse("garage:installation-replace", args=[mount.pk])).content.decode()
        assert "Sus piezas (Casete 11-34, Disco 160) se desmontan" in html and "Rotor interior)" not in html

    def test_overlap_is_spanish_too(self, garage, wheel):
        from .services.retirement import retire_one
        from .services.ownership import reactivate_inventory
        retire_one(garage.owner, garage.light, at=at(20))
        reactivate_inventory(garage.owner, Item, garage.light.pk, at=at(10))
        with pytest.raises(InventoryWriteError) as error:
            retire_one(garage.owner, garage.light, at=at(15))
        assert "No se puede retirar Luz en esa fecha" in " ".join(error.value.messages)


class TestWhatRetiringCloses:
    """garage-047 F04: the retire page says which mount it closes and the earliest instant its history allows.

    The viewer's zone is UTC here, so `at(100)` (8 Jul 2026, 12:00 UTC) reads «8 jul 2026, 12:00».
    """

    @staticmethod
    def open(client, owner, obj):
        client.force_login(owner)
        client.cookies["garage_tz"] = "UTC"
        return client.get(reverse(f"garage:{'bike' if isinstance(obj, Bike) else 'item'}-retire", args=[obj.pk]))

    @staticmethod
    def lede(html):
        ledes = find_all(parse(html), "p", cls="lede")
        assert len(ledes) == 1, ledes
        return visible_text(ledes[0])

    def test_retiring_names_the_mount_it_closes(self, garage, wheel, client, now):
        on_bike = self.lede(self.open(client, garage.owner, wheel.rear).content.decode())
        assert "Se cerrará su montaje actual: en Carretera desde el 8 jul 2026, 12:00." in on_bike
        assert "Se cerrarán los montajes abiertos compatibles" not in on_bike and "El historial permanece disponible." in on_bike
        nested = self.lede(self.open(client, garage.owner, wheel.cassette).content.decode())
        assert "Se cerrará su montaje actual: sobre Rueda trasera desde el 18 jul 2026, 12:00." in nested
        loose = self.lede(self.open(client, garage.owner, garage.light).content.decode())
        assert loose.startswith("No está montado: no se cierra ningún montaje.") and "Se cerrará" not in loose

    def test_a_name_in_the_sentence_is_escaped(self, garage, client, now):
        odd = create_inventory(garage.owner, Bike, name="Pista <b>")
        create_installation(garage.owner, item=garage.light, bike=odd, parent_item=None, started_at=at(5), ended_at=None, slot=None)
        html = self.open(client, garage.owner, garage.light).content.decode()
        assert "en Pista &lt;b&gt; desde el 11 oct 2026, 12:00." in html and "Pista <b>" not in html

    def test_retiring_states_the_earliest_instant(self, garage, wheel, client, now):
        # One open mount: its start.
        chain = self.lede(self.open(client, garage.owner, garage.chain).content.decode())
        assert "Tiene que ser posterior al 30 mar 2026, 12:00: antes choca con su historial de montajes." in chain
        # A closed mount that ended after the open ones began: its end, not the latest start.
        create_installation(garage.owner, item=wheel.spare, bike=None, parent_item=wheel.rear, started_at=at(80), ended_at=at(20), slot=None)
        rear = self.lede(self.open(client, garage.owner, wheel.rear).content.decode())
        assert "Tiene que ser posterior al 26 sep 2026, 12:00: antes choca con su historial de montajes." in rear
        # Only closed mounts: nothing closes, and still a limit.
        create_installation(garage.owner, item=garage.light, bike=garage.gravel, parent_item=None, started_at=at(60), ended_at=at(30), slot=None)
        light = self.lede(self.open(client, garage.owner, garage.light).content.decode())
        assert light.startswith("No está montado: no se cierra ningún montaje.")
        assert "Tiene que ser posterior al 16 sep 2026, 12:00: antes choca con su historial de montajes." in light
        # The limit is the server's: a minute before it is refused, a minute after it is saved.
        url = reverse("garage:item-retire", args=[wheel.rear.pk])
        refused = client.post(url, {"at": "2026-09-26T11:59", "time_zone": "UTC"}).content.decode()
        assert "No se puede retirar Rueda trasera en esa fecha" in refused and fresh(wheel.rear).retired_at is None
        client.post(url, {"at": "2026-09-26T12:01", "time_zone": "UTC"})
        assert fresh(wheel.rear).retired_at == at(20) + timedelta(minutes=1)

    def test_without_history_no_limit_is_stated(self, garage, client, now):
        for obj in (garage.light, garage.gravel):
            text = self.lede(self.open(client, garage.owner, obj).content.decode())
            assert "posterior" not in text and "historial de montajes" not in text, obj.name

    def test_the_limit_counts_what_goes_inside(self, garage, wheel, client, now):
        # A second-level part mounted after the wheel's own limit (its cassette, 18 jul): retiring the disc with it fails.
        create_installation(garage.owner, item=wheel.spare, bike=None, parent_item=wheel.disc, started_at=at(10), ended_at=None, slot=None)
        html = self.open(client, garage.owner, wheel.rear).content.decode()
        assert "Retirar también lo que lleva montado (3)" in html
        text = self.lede(html)
        assert "Tiene que ser posterior al 18 jul 2026, 12:00: antes choca con su historial de montajes." in text
        assert "Si retiras también lo que lleva montado, posterior al 6 oct 2026, 12:00." in text
        url = reverse("garage:item-retire", args=[wheel.rear.pk])
        between = "2026-08-27T12:00"  # at(50)
        shown = ",".join(str(obj.pk) for obj in mounted_in(garage.owner, wheel.rear, at=at(50)))
        response = client.post(url, {"at": between, "time_zone": "UTC", "with_parts": "on", "shown_parts": shown})
        refused = response.content.decode()
        assert response.status_code in (200, 400) and "No se puede retirar Disco 160 en esa fecha" in refused
        assert all(fresh(obj).retired_at is None for obj in (wheel.rear, wheel.cassette, wheel.disc, wheel.spare))
        assert "Si retiras también lo que lleva montado, posterior al 6 oct 2026, 12:00." in self.lede(refused)
        # Alone, the wheel's own limit is the one that counts.
        client.post(url, {"at": between, "time_zone": "UTC"})
        assert fresh(wheel.rear).retired_at == at(50) and fresh(wheel.disc).retired_at is None

    def test_the_preview_survives_a_rejected_post(self, garage, wheel, client, now):
        self.open(client, garage.owner, wheel.rear)
        response = client.post(reverse("garage:item-retire", args=[wheel.rear.pk]), {"at": "2026-07-13T12:00", "time_zone": "UTC"})
        html = response.content.decode()
        assert response.status_code in (200, 400) and "No se puede retirar Rueda trasera en esa fecha" in html
        assert "Correct later" not in html and fresh(wheel.rear).retired_at is None
        text = self.lede(html)
        assert "Se cerrará su montaje actual: en Carretera desde el 8 jul 2026, 12:00." in text
        assert "Tiene que ser posterior al 18 jul 2026, 12:00: antes choca con su historial de montajes." in text
        # What goes inside adds nothing later than the wheel's own limit: no second sentence.
        assert "Si retiras también" not in text and "Retirar también lo que lleva montado (2)" in html

    def test_a_bike_lists_nothing_of_its_own(self, garage, wheel, client, now):
        html = self.open(client, garage.owner, garage.road).content.decode()
        text = self.lede(html)
        assert text.startswith("Una bici no tiene montaje propio.") and "No está montad" not in text and "Se cerrará" not in text
        assert "Tiene que ser posterior al 8 jul 2026, 12:00: antes choca con su historial de montajes." in text
        assert "Si retiras también lo que lleva montado, posterior al 18 jul 2026, 12:00." in text
        assert "Ahora: Cadena 11v, Rueda trasera, Casete 11-34, Disco 160." in html  # its parts, in the help of with_parts
        empty = self.lede(self.open(client, garage.owner, garage.gravel).content.decode())
        assert empty.startswith("Una bici no tiene montaje propio: no se cierra ningún montaje.")

    def test_a_loose_item_with_parts_does_not_say_nothing_closes(self, garage, wheel, client, now):
        # Unmounted, its own parts still unmount: «no se cierra ningún montaje» would be false.
        from .services.installations import close_installation
        close_installation(garage.owner, Installation.objects.get(item=wheel.rear, ended_at__isnull=True).pk, at=at(5))
        html = self.open(client, garage.owner, wheel.rear).content.decode()
        text = self.lede(html)
        assert text.startswith("No está montado.") and "no se cierra ningún montaje" not in text
        assert "Tiene que ser posterior al 11 oct 2026, 12:00" in text and "Ahora: Casete 11-34, Disco 160." in html

    def test_a_scheduled_retirement_names_no_mount(self, garage, wheel, client, now):
        # Its mounts already end on that date: nothing open to name, and moving it earlier would clash with them.
        update_inventory(garage.owner, Item, wheel.rear.pk, retired_at=NOW + timedelta(days=30))
        text = self.lede(self.open(client, garage.owner, wheel.rear).content.decode())
        assert "Se cerrará" not in text and "No está montado" not in text
        assert "Tiene que ser posterior al 15 nov 2026, 12:00: antes choca con su historial de montajes." in text

    def test_an_item_mounted_until_a_later_date_is_not_said_to_be_unmounted(self, garage, client, now):
        # Its item screen says «Montado»; retiring closes none of that mount, which already ends later.
        from .services.lifecycle import MOUNTED, item_lifecycles
        create_installation(garage.owner, item=garage.light, bike=garage.gravel, parent_item=None, started_at=at(5),
                            ended_at=NOW + timedelta(days=10), slot=None)
        # Retiring the bike from its page ten days ahead, without its parts: the chain stays on it until then.
        client.force_login(garage.owner)
        client.cookies["garage_tz"] = "UTC"
        response = client.post(reverse("garage:bike-retire", args=[garage.road.pk]), {"at": "2026-10-26T12:00", "time_zone": "UTC"})
        assert response.status_code == 302 and fresh(garage.road).retired_at == NOW + timedelta(days=10)
        for item in (garage.light, garage.chain):
            assert item_lifecycles(garage.owner, [fresh(item)], at=NOW)[item.pk].state == MOUNTED, item.name
            text = self.lede(self.open(client, garage.owner, item).content.decode())
            assert "No está montado" not in text and "Se cerrará" not in text, text
            assert "Tiene que ser posterior al 26 oct 2026, 12:00: antes choca con su historial de montajes." in text, text
            assert text.endswith("El historial permanece disponible."), text

    def test_a_mount_that_ended_at_this_instant_is_no_longer_mounted(self, garage, client, now):
        # An end at the instant is already closed (as on the item screen): not mounted, and nothing to close.
        from .services.lifecycle import MOUNTED, item_lifecycles
        create_installation(garage.owner, item=garage.light, bike=garage.gravel, parent_item=None, started_at=at(5), ended_at=NOW, slot=None)
        assert item_lifecycles(garage.owner, [garage.light], at=NOW)[garage.light.pk].state != MOUNTED
        text = self.lede(self.open(client, garage.owner, garage.light).content.decode())
        assert text.startswith("No está montado: no se cierra ningún montaje.")
        assert "Tiene que ser posterior al 16 oct 2026, 12:00: antes choca con su historial de montajes." in text

    def test_a_refused_save_states_its_hours_in_the_zone_the_form_was_sent_with(self, garage, wheel, client, now):
        # The cookie says UTC; the form went with New York's hours (EDT in July, UTC-4), and the page keeps them.
        self.open(client, garage.owner, wheel.rear)
        url = reverse("garage:item-retire", args=[wheel.rear.pk])
        html = client.post(url, {"at": "2026-07-13T12:00", "time_zone": "America/New_York"}).content.decode()
        assert "No se puede retirar Rueda trasera en esa fecha" in html and fresh(wheel.rear).retired_at is None
        assert "Horas en America/New_York" in visible_text(parse(html))
        text = self.lede(html)
        assert "Se cerrará su montaje actual: en Carretera desde el 8 jul 2026, 8:00." in text, text
        assert "Tiene que ser posterior al 18 jul 2026, 8:00: antes choca con su historial de montajes." in text, text
        # A minute after the hour it names, in that same zone, is saved.
        client.post(url, {"at": "2026-07-18T08:01", "time_zone": "America/New_York"})
        assert fresh(wheel.rear).retired_at == at(90) + timedelta(minutes=1)

    def test_the_zone_of_the_form_also_east_of_the_cookie_and_with_what_goes_inside(self, garage, wheel, client, now):
        create_installation(garage.owner, item=wheel.spare, bike=None, parent_item=wheel.disc, started_at=at(10), ended_at=None, slot=None)
        self.open(client, garage.owner, wheel.rear)
        client.cookies["garage_tz"] = "America/New_York"
        url = reverse("garage:item-retire", args=[wheel.rear.pk])
        # A missing instant: the form is refused before the service, and still sent in Tokyo's hours (UTC+9).
        text = self.lede(client.post(url, {"at": "", "time_zone": "Asia/Tokyo"}).content.decode())
        assert "Tiene que ser posterior al 18 jul 2026, 21:00: antes choca con su historial de montajes." in text, text
        assert "Si retiras también lo que lleva montado, posterior al 6 oct 2026, 21:00." in text, text
        # A zone that is none: the form says so, and the page's hours stay the viewer's.
        html = client.post(url, {"at": "2026-07-13T12:00", "time_zone": "Marte/Olimpo"}).content.decode()
        assert "Elige una zona horaria IANA válida." in html and fresh(wheel.rear).retired_at is None
        assert "Tiene que ser posterior al 18 jul 2026, 8:00: antes choca con su historial de montajes." in self.lede(html)


class TestBusyMarks:
    """garage-047 F04 (R2-07): POST forms without `form.form` where a second tap does harm carry `data-busy`."""

    @staticmethod
    def forms(html):
        return [form for form in find_all(parse(html), "form") if form.attrs.get("method", "").lower() == "post"]

    def test_slow_or_repeating_posts_are_marked_busy(self, strava, garage, client):
        connected(strava)
        client.force_login(strava.owner)
        page = client.get(reverse("garage:strava")).content.decode()
        sync = [form for form in self.forms(page) if form.attrs.get("action") == reverse("garage:strava-sync")]
        assert len(sync) == 1 and "data-busy" in sync[0].attrs
        run = ImportRun.objects.create(owner=strava.owner, source_kind="strava", items_imported=0, items_skipped=0, requested_from=at(30))
        page = client.get(reverse("garage:history-run", args=[run.pk])).content.decode()
        resume = [form for form in self.forms(page) if "Continuar importación" in visible_text(form)]
        cancel = [form for form in self.forms(page) if form.attrs.get("action") == reverse("garage:history-cancel", args=[run.pk])]
        assert len(resume) == 1 and "data-busy" in resume[0].attrs
        assert len(cancel) == 1 and "data-busy" not in cancel[0].attrs
        client.force_login(garage.owner)
        rule = MaintenanceRule.objects.get(owner=garage.owner, item=garage.chain)
        page = client.get(reverse("garage:maintenance-rule-snooze", args=[rule.pk])).content.decode()
        presets = [form for form in self.forms(page) if "presets" in form.attrs.get("class", "").split()]
        assert len(presets) == 1 and "data-busy" in presets[0].attrs
