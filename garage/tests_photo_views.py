from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import Client, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
import pytest

from .models import Bike, Item, Photo, PhotoStorageObject
from .services import photos
from .services.ownership import create_inventory
from .storage import PhotoStorageConfigError
from .test_html import find_all, parse, visible_text
from .tests_photos_domain import backend, image_bytes, inventory, upload


pytestmark = pytest.mark.django_db(transaction=True)


def route(name, *args):
    return reverse("garage:" + name, args=args)


@pytest.fixture
def client(inventory):
    client = Client()
    client.force_login(inventory[0])
    return client


@pytest.fixture(autouse=True)
def simulated_transport(backend, monkeypatch):
    monkeypatch.setattr(photos, "get_photo_storage", lambda: backend)


@pytest.mark.parametrize("kind,index", [("bike", 2), ("item", 3)])
def test_multipart_upload_private_detail_replace_and_delete(client, inventory, backend, kind, index):
    target = inventory[index]
    url = route(kind + "-photo-create", target.pk)
    response = client.get(url)
    assert response.status_code == 200 and b'enctype="multipart/form-data"' in response.content
    response = client.post(url, {"photo": SimpleUploadedFile("DO_NOT_PERSIST.jpg", image_bytes(), content_type="image/png"),
                                 "owner": inventory[1].pk, "key": "foreign/key"})
    assert response.status_code == 302
    photo = Photo.objects.get()
    assert photo.owner == inventory[0] and getattr(photo, kind) == target
    detail = client.get(route(kind + "-detail", target.pk))
    assert route("photo-content", photo.pk).encode() in detail.content
    assert b"DO_NOT_PERSIST" not in detail.content and photo.storage_object.key.encode() not in detail.content
    assert b"synthetic-storage.example.invalid" not in detail.content
    response = client.post(route("photo-replace", photo.pk), {"photo": SimpleUploadedFile("replacement.png", image_bytes("blue"))})
    assert response.status_code == 302 and Photo.objects.get().pk == photo.pk
    assert client.post(route("photo-delete", photo.pk)).status_code == 302
    assert not Photo.objects.exists() and not PhotoStorageObject.objects.exists()


def test_content_authorizes_then_redirects_with_no_cache_or_referrer(client, inventory, backend):
    photo = upload(inventory, backend)
    backend.calls.clear()
    response = client.get(route("photo-content", photo.pk))
    assert response.status_code == 302
    assert response["Location"] == "https://synthetic-storage.example.invalid/signed-download"
    assert "private" in response["Cache-Control"] and "no-store" in response["Cache-Control"]
    assert response["Referrer-Policy"] == "no-referrer"
    assert backend.calls == [("sign", photo.storage_object.key)]


def test_foreign_user_and_superuser_cannot_sign_replace_delete_or_upload(client, inventory, backend, django_user_model):
    photo = upload(inventory, backend)
    admin = django_user_model.objects.create_superuser("photo-admin", "synthetic@example.invalid", "synthetic-password")
    for actor in (inventory[1], admin):
        client.force_login(actor)
        backend.calls.clear()
        for name, args, method in [("photo-content", [photo.pk], "get"), ("photo-replace", [photo.pk], "get"),
            ("photo-replace", [photo.pk], "post"), ("photo-delete", [photo.pk], "post"),
            ("bike-photo-create", [inventory[2].pk], "get"), ("bike-photo-create", [inventory[2].pk], "post")]:
            assert getattr(client, method)(route(name, *args)).status_code == 404
        assert not backend.calls


def test_anonymous_photo_routes_require_login(client, inventory, backend):
    photo = upload(inventory, backend)
    client.logout()
    backend.calls.clear()
    for name, args, method in [("photo-content", [photo.pk], "get"), ("photo-replace", [photo.pk], "get"),
        ("photo-delete", [photo.pk], "post"), ("bike-photo-create", [inventory[2].pk], "get")]:
        response = getattr(client, method)(route(name, *args))
        assert response.status_code == 302 and response["Location"].startswith("/accounts/login/")
    assert not backend.calls


def test_photo_post_requires_csrf_and_get_cannot_delete(inventory, backend):
    photo = upload(inventory, backend)
    client = Client(enforce_csrf_checks=True)
    client.force_login(inventory[0])
    backend.calls.clear()
    for name, args in [("photo-delete", [photo.pk]), ("photo-replace", [photo.pk]), ("bike-photo-create", [inventory[2].pk])]:
        assert client.post(route(name, *args)).status_code == 403
    assert client.get(route("photo-delete", photo.pk)).status_code == 405
    assert client.post(route("photo-content", photo.pk)).status_code == 403
    assert Photo.objects.exists() and not backend.calls


def test_invalid_image_shows_safe_error_without_filename_or_reference(client, inventory, backend):
    response = client.post(route("bike-photo-create", inventory[2].pk),
        {"photo": SimpleUploadedFile("DO_NOT_DISCLOSE.html", b"bad image", content_type="text/html")})
    assert response.status_code == 200
    assert response.context["form"].errors
    assert b"DO_NOT_DISCLOSE" not in response.content
    assert not PhotoStorageObject.objects.exists() and not backend.calls


def test_missing_file_is_a_bound_form_error(client, inventory):
    response = client.post(route("bike-photo-create", inventory[2].pk), {})
    assert response.status_code == 200
    assert response.context["form"].is_bound and response.context["form"].errors.get("photo")


def photo_control(root):
    return find_all(root, "input", type="file", name="photo")[0]


def test_the_photo_field_has_the_label_of_every_other_field(client, inventory):
    root = parse(client.get(route("bike-photo-create", inventory[2].pk)).content.decode())
    assert [visible_text(label) for label in find_all(root, "label", **{"for": photo_control(root).attrs["id"]})] == ["Foto"]


def test_the_help_of_the_photo_field_is_read_with_it(client, inventory):
    root = parse(client.get(route("bike-photo-create", inventory[2].pk)).content.decode())
    helps = find_all(root, cls="help")
    assert len(helps) == 1 and "15 MiB" in visible_text(helps[0])
    assert helps[0].attrs.get("id") == photo_control(root).attrs["aria-describedby"]


def test_a_photo_error_marks_its_field(client, inventory):
    root = parse(client.post(route("bike-photo-create", inventory[2].pk), {}).content.decode())
    fields = find_all(root, "div", cls="field has-error")
    assert len(fields) == 1 and find_all(fields[0], "ul", cls="errorlist") and find_all(fields[0], "input", name="photo")


def test_an_error_of_the_whole_upload_is_still_shown(client, inventory, backend):
    """`form.add_error(None, …)` from the view: it belongs to no field, and only the form can show it."""
    with patch.object(photos, "get_photo_storage", side_effect=PhotoStorageConfigError("DO_NOT_DISCLOSE config")):
        root = parse(client.post(route("bike-photo-create", inventory[2].pk),
                                 {"photo": SimpleUploadedFile("a.png", image_bytes(), content_type="image/png")}).content.decode())
    assert [visible_text(found) for found in find_all(root, "ul", cls="errorlist nonfield")]


def test_unavailable_storage_shows_safe_upload_error_and_content_503(client, inventory, backend):
    photo = upload(inventory, backend)
    with patch.object(photos, "get_photo_storage", side_effect=PhotoStorageConfigError("DO_NOT_DISCLOSE config")):
        response = client.post(route("photo-replace", photo.pk), {"photo": SimpleUploadedFile("private.png", image_bytes("blue"))})
        assert response.status_code == 200 and b"DO_NOT_DISCLOSE" not in response.content
        content = client.get(route("photo-content", photo.pk))
        assert content.status_code == 503 and b"DO_NOT_DISCLOSE" not in content.content
    assert Photo.objects.count() == PhotoStorageObject.objects.count() == 1


def test_failed_replacement_ui_retains_existing_photo(client, inventory, backend):
    photo = upload(inventory, backend)
    key = photo.storage_object.key
    backend.fail_upload = True
    response = client.post(route("photo-replace", photo.pk), {"photo": SimpleUploadedFile("private.png", image_bytes("blue"))})
    assert response.status_code == 200 and response.context["form"].errors
    assert Photo.objects.get().storage_object.key == key


def test_invalid_quota_configuration_renders_safe_get_and_post(client, inventory, backend):
    url = route("bike-photo-create", inventory[2].pk)
    with override_settings(GARAGE_PHOTO_OWNER_QUOTA_BYTES="DO_NOT_DISCLOSE-invalid"):
        assert client.get(url).status_code == 200
        response = client.post(url, {"photo": SimpleUploadedFile("private.png", image_bytes())})
    assert response.status_code == 200 and response.context["form"].errors
    assert response.context["usage"] is None and b"DO_NOT_DISCLOSE" not in response.content
    assert not Photo.objects.exists() and not PhotoStorageObject.objects.exists() and not backend.calls


def test_form_and_photo_attributes_escape_inventory_name(client, inventory, backend):
    name = '<script>DO_NOT_EXECUTE</script>" onerror="alert(1)'
    bike = create_inventory(inventory[0], Bike, name=name)
    upload(inventory, backend, target_id=bike.pk)
    response = client.get(route("bike-detail", bike.pk))
    assert b"<script>DO_NOT_EXECUTE" not in response.content
    assert b"&lt;script&gt;DO_NOT_EXECUTE" in response.content
    assert b'" onerror="' not in response.content


def bike_hero(client, bike):
    """The header of the bike's screen (spec §4.6), and the whole page."""
    response = client.get(route("bike-detail", bike.pk))
    assert response.status_code == 200
    root = parse(response.content.decode())
    headers = find_all(root, "header", cls="hero bike-hero card")
    assert len(headers) == 1, headers
    return headers[0], root


def cover_src(client, bike):
    images = find_all(bike_hero(client, bike)[0], "img", cls="cover")
    assert len(images) == 1, images
    return images[0].attrs["src"]


class TestBikeCover:
    """Spec F3b, D2 and D3: the first photo of the bike at the top of its screen, or a tile and «Añadir foto»."""

    def test_with_a_photo_the_header_shows_it(self, client, inventory, backend):
        photo = upload(inventory, backend)
        header, _ = bike_hero(client, inventory[2])
        image = find_all(header, "img", cls="cover")[0]
        assert image.attrs["src"] == f"/garage/photos/{photo.pk}/content/"
        assert image.attrs["alt"] == "Foto de Synthetic bike"
        assert image.attrs["referrerpolicy"] == "no-referrer"

    def test_the_cover_declares_its_size_and_is_not_lazy(self, client, inventory, backend):
        upload(inventory, backend)
        image = find_all(bike_hero(client, inventory[2])[0], "img", cls="cover")[0]
        assert (image.attrs["width"], image.attrs["height"]) == ("80", "60")  # Without them the page would jump when it arrives.
        assert "loading" not in image.attrs  # It is seen on opening: lazy would only delay it.

    def test_with_a_photo_there_is_no_tile_nor_second_link(self, client, inventory, backend):
        upload(inventory, backend)
        header, root = bike_hero(client, inventory[2])
        create = route("bike-photo-create", inventory[2].pk)
        assert not find_all(header, cls="cover-empty") and not find_all(header, "a", href=create)
        assert len(find_all(root, "a", href=create)) == 1  # The one of «Fotos privadas» stays.

    def test_with_two_photos_the_cover_is_the_first_uploaded(self, client, inventory, backend):
        first = upload(inventory, backend)
        second = upload(inventory, backend, source=image_bytes("blue"))
        assert cover_src(client, inventory[2]) == route("photo-content", first.pk)
        gallery = find_all(bike_hero(client, inventory[2])[1], "img", cls="photo")
        assert [image.attrs["src"] for image in gallery] == [route("photo-content", first.pk), route("photo-content", second.pk)]

    def test_deleting_the_cover_gives_way_to_the_next(self, client, inventory, backend):
        first = upload(inventory, backend)
        second = upload(inventory, backend, source=image_bytes("blue"))
        assert client.post(route("photo-delete", first.pk)).status_code == 302
        assert cover_src(client, inventory[2]) == route("photo-content", second.pk)

    def test_replacing_the_cover_keeps_it_first(self, client, inventory, backend):
        first = upload(inventory, backend)
        upload(inventory, backend, source=image_bytes("blue"))
        assert client.post(route("photo-replace", first.pk), {"photo": SimpleUploadedFile("new.png", image_bytes("green"))}).status_code == 302
        assert cover_src(client, inventory[2]) == route("photo-content", first.pk)

    def test_deleting_the_only_photo_brings_the_tile_back(self, client, inventory, backend):
        photo = upload(inventory, backend)
        assert client.post(route("photo-delete", photo.pk)).status_code == 302
        header, _ = bike_hero(client, inventory[2])
        assert not find_all(header, "img") and find_all(header, cls="cover-empty")

    def test_without_a_photo_a_tile_and_the_link(self, client, inventory):
        header, root = bike_hero(client, inventory[2])
        tiles = find_all(header, "span", cls="cover cover-empty")
        assert len(tiles) == 1 and tiles[0].attrs["aria-hidden"] == "true"
        assert [use.attrs["href"] for use in find_all(tiles[0], "use")] == ["#i-bike"]
        create = route("bike-photo-create", inventory[2].pk)
        links = find_all(header, "a", href=create)
        assert len(links) == 1 and visible_text(links[0]) == "Añadir foto"
        assert [use.attrs["href"] for use in find_all(links[0], "use")] == ["#i-camera"]
        assert not find_all(header, "img")
        assert len(find_all(root, "a", href=create)) == 2  # D3: the same text and destination, in the header and in «Fotos privadas».

    def test_another_users_photo_never_appears(self, client, inventory, backend):
        _, other, bike, _ = inventory
        foreign_bike = create_inventory(other, Bike, name="SECRET bike")
        foreign = photos.upload_photo(other, target_model=Bike, target_id=foreign_bike.pk, source=image_bytes(), storage=backend)
        # Not even a row of theirs that points at this bike: the screen only reads the photos of who is looking.
        Photo.objects.filter(pk=foreign.pk).update(bike=bike)
        header, root = bike_hero(client, bike)
        assert not find_all(root, "img") and find_all(header, cls="cover-empty")

    def test_another_bikes_photo_and_a_pieces_are_not_the_cover(self, client, inventory, backend):
        user, _, bike, item = inventory
        upload(inventory, backend, target_id=create_inventory(user, Bike, name="Synthetic other bike").pk)
        upload(inventory, backend, target_model=Item, target_id=item.pk)
        header, _ = bike_hero(client, bike)
        assert not find_all(header, "img") and find_all(header, cls="cover-empty")

    def test_the_name_is_escaped_in_the_alt(self, client, inventory, backend):
        name = '<b>Bici</b> "x" onerror=alert(1)'
        bike = create_inventory(inventory[0], Bike, name=name)
        upload(inventory, backend, target_id=bike.pk)
        response = client.get(route("bike-detail", bike.pk))
        image = find_all(parse(response.content.decode()), "img", cls="cover")[0]
        assert image.attrs["alt"] == f"Foto de {name}" and set(image.attrs) == {"class", "src", "alt", "width", "height", "referrerpolicy", "decoding"}
        assert b"<b>Bici</b>" not in response.content

    def test_with_the_storage_down_the_screen_answers_and_keeps_its_secrets(self, client, inventory, backend):
        photo = upload(inventory, backend)
        backend.calls.clear()
        with patch.object(photos, "get_photo_storage", side_effect=PhotoStorageConfigError("SECRET config")):
            response = client.get(route("bike-detail", inventory[2].pk))
            content = client.get(route("photo-content", photo.pk))  # What the browser then asks for: it shows the alt inside the tile.
        assert response.status_code == 200 and find_all(parse(response.content.decode()), "img", cls="cover")
        assert photo.storage_object.key.encode() not in response.content and b"SECRET" not in response.content
        assert content.status_code == 503 and b"SECRET" not in content.content
        assert not backend.calls  # The screen itself never talks to the storage.

    def test_the_cover_costs_no_query_of_its_own(self, client, inventory, backend):
        """D2: one read of the photos, also with several, and no extra for the size of the cover."""
        def queries():
            with CaptureQueriesContext(connection) as captured:
                assert client.get(route("bike-detail", inventory[2].pk)).status_code == 200
            return [query["sql"] for query in captured]
        queries()  # What a first visit caches.
        before = queries()
        upload(inventory, backend)
        upload(inventory, backend, source=image_bytes("blue"))
        upload(inventory, backend, source=image_bytes("green"))
        after = queries()
        assert len(after) == len(before)
        assert sum('FROM "garage_photo"' in sql for sql in after) == 1
        assert not any('FROM "garage_photostorageobject"' in sql for sql in after)

    def test_a_piece_keeps_its_tile(self, client, inventory, backend):
        """D2: only for the bike."""
        item = inventory[3]
        photo = upload(inventory, backend, target_model=Item, target_id=item.pk)
        response = client.get(route("item-detail", item.pk))
        root = parse(response.content.decode())
        assert response.status_code == 200 and not find_all(root, cls="cover")
        assert [image.attrs["src"] for image in find_all(root, "img")] == [route("photo-content", photo.pk)]
