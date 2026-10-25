"""garage-038: retire the outgoing part when replacing, and retire together with what is mounted."""
import re
from datetime import timedelta
import pytest
from django.contrib.messages import get_messages
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .models import Bike, Installation, Item
from .services.installations import create_installation
from .services.lifespan import lifespan_rule, set_lifespan
from .services.ownership import InventoryWriteError, create_inventory
from .services.retirement import mounted_in, retire_with_parts
from .tests_mobile_home import NOW, at, garage  # noqa: F401 (fixture)
from .tests_parts import wheel  # noqa: F401 (fixture)

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
