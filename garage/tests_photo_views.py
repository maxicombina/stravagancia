from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from django.urls import reverse
import pytest

from .models import Bike, Photo, PhotoStorageObject
from .services import photos
from .services.ownership import create_inventory
from .storage import PhotoStorageConfigError
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
