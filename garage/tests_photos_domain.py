from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from io import BytesIO
from threading import Barrier
import hashlib
import traceback
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, IntegrityError, close_old_connections, transaction
from django.db.models.deletion import ProtectedError
from django.test import override_settings
from django.utils import timezone
from PIL import Image
import pytest

from .models import Bike, Category, Item, Photo, PhotoStorageObject
from .photos import process_photo
from .services import photos
from .services.ownership import InventoryNotFound, create_inventory, delete_inventory
from .storage import PhotoStorageError, UploadedPhoto, new_photo_key


pytestmark = pytest.mark.django_db(transaction=True)


def image_bytes(color="red", size=(80, 60)):
    stream = BytesIO()
    with Image.new("RGB", size, color) as image:
        image.save(stream, "PNG")
    return stream.getvalue()


class MemoryPhotoStorage:
    """Synthetic transport with failures before/after external persistence."""
    def __init__(self):
        self.objects, self.calls = {}, []
        self.fail_upload = self.fail_delete = self.fail_read = self.fail_sign = False
        self.on_upload = None

    def upload(self, photo, *, key):
        self.calls.append(("upload", key))
        self.objects[key] = photo.data
        if self.on_upload:
            self.on_upload(key)
        if self.fail_upload:
            raise PhotoStorageError()
        return UploadedPhoto(key, len(photo.data), hashlib.sha256(photo.data).hexdigest())

    def delete(self, key):
        self.calls.append(("delete", key))
        if self.fail_delete:
            raise PhotoStorageError()
        self.objects.pop(key, None)

    def read(self, key):
        self.calls.append(("read", key))
        if self.fail_read:
            raise PhotoStorageError()
        return self.objects[key]

    def signed_download_url(self, key):
        self.calls.append(("sign", key))
        if self.fail_sign:
            raise PhotoStorageError()
        return "https://synthetic-storage.example.invalid/signed-download"

    def close(self):
        pass


@pytest.fixture
def inventory():
    user = get_user_model().objects.create_user("photo-owner")
    other = get_user_model().objects.create_user("photo-other")
    category = create_inventory(user, Category, name="Synthetic accessories")
    return user, other, create_inventory(user, Bike, name="Synthetic bike"), create_inventory(user, Item, name="Synthetic item", category=category)


@pytest.fixture
def backend():
    return MemoryPhotoStorage()


def upload(inventory, backend, **changes):
    user, _, bike, _ = inventory
    params = {"target_model": Bike, "target_id": bike.pk, "source": image_bytes(), "storage": backend}
    params.update(changes)
    return photos.upload_photo(user, **params)


def due(blob):
    PhotoStorageObject.objects.filter(pk=blob.pk).update(cleanup_after=timezone.now() - timedelta(seconds=1))


def pending(user, *, size=100, state="cleanup"):
    return PhotoStorageObject.objects.create(owner=user, key=new_photo_key(), size_bytes=size,
        width=10, height=10, sha256="a" * 64, state=state, cleanup_after=timezone.now() - timedelta(seconds=1))


@pytest.mark.parametrize("kind", ["bike", "item"])
def test_upload_processed_reference_read_sign_and_no_original_name(inventory, backend, kind):
    user, _, bike, item = inventory
    target = bike if kind == "bike" else item
    stream = BytesIO(image_bytes())
    stream.name = "../../DO_NOT_PERSIST-original-name.jpg"
    photo = upload(inventory, backend, target_model=type(target), target_id=target.pk, source=stream)
    blob = photo.storage_object
    assert photo.owner == user and getattr(photo, kind) == target
    assert blob.state == "live" and blob.cleanup_after is None
    assert (blob.width, blob.height) == (80, 60)
    assert photos.read_photo(user, photo.pk, storage=backend) == backend.objects[blob.key]
    assert photos.signed_photo_url(user, photo.pk, storage=backend).startswith("https://synthetic-")
    assert blob.size_bytes == len(backend.objects[blob.key])
    assert blob.sha256 == hashlib.sha256(backend.objects[blob.key]).hexdigest()
    assert "DO_NOT_PERSIST" not in repr(Photo.objects.values().get()) + repr(PhotoStorageObject.objects.values().get())


def test_reservation_is_visible_from_another_connection_before_put(inventory, backend):
    def observe(key):
        def read_reservation():
            close_old_connections()
            try:
                blob = PhotoStorageObject.objects.get(key=key)
                return blob.state, blob.cleanup_after is not None, Photo.objects.count()
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(read_reservation).result(timeout=10) == ("reserved", True, 0)
    backend.on_upload = observe
    upload(inventory, backend)


@pytest.mark.parametrize("operation", ["upload", "read", "sign", "delete", "replace"])
def test_foreign_actors_are_denied_before_processing_or_transport(inventory, backend, operation):
    user, other, bike, _ = inventory
    photo = upload(inventory, backend)
    backend.calls.clear()
    with patch.object(photos, "process_photo", side_effect=AssertionError("must authorize first")):
        with pytest.raises(InventoryNotFound):
            {"upload": lambda: photos.upload_photo(other, target_model=Bike, target_id=bike.pk, source=b"bad", storage=backend),
             "replace": lambda: photos.upload_photo(other, target_model=Bike, target_id=bike.pk, source=b"bad", replace_id=photo.pk, storage=backend),
             "read": lambda: photos.read_photo(other, photo.pk, storage=backend),
             "sign": lambda: photos.signed_photo_url(other, photo.pk, storage=backend),
             "delete": lambda: photos.delete_photo(other, photo.pk, storage=backend)}[operation]()
    assert not backend.calls


@pytest.mark.parametrize("actor_kind", ["anonymous", "inactive", "unsaved"])
def test_invalid_actor_cannot_use_photos(inventory, backend, actor_kind):
    user, _, bike, _ = inventory
    if actor_kind == "anonymous":
        user = AnonymousUser()
    elif actor_kind == "inactive":
        get_user_model().objects.filter(pk=user.pk).update(is_active=False)
    else:
        user = get_user_model()(username="unsaved")
    with pytest.raises(PermissionDenied):
        photos.upload_photo(user, target_model=Bike, target_id=bike.pk, source=image_bytes(), storage=backend)
    assert not backend.calls


def test_replacement_preserves_photo_uuid_and_cleans_old_after_commit(inventory, backend):
    first = upload(inventory, backend)
    old_key = first.storage_object.key
    second = upload(inventory, backend, replace_id=first.pk, source=image_bytes("blue"))
    assert second.pk == first.pk and second.storage_object.key != old_key
    assert old_key not in backend.objects
    assert Photo.objects.count() == PhotoStorageObject.objects.count() == len(backend.objects) == 1


@pytest.mark.parametrize("failure", ["upload", "database"])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_failed_replacement_retains_old_reference_and_durable_new_cleanup(inventory, backend, failure, cleanup_fails, caplog):
    old = upload(inventory, backend)
    old_blob = old.storage_object
    backend.fail_delete = cleanup_fails
    backend.fail_upload = failure == "upload"
    context = patch.object(Photo, "save", side_effect=DatabaseError("DO_NOT_DISCLOSE DB details")) if failure == "database" else patch.object(backend, "close")
    with context, pytest.raises(ValidationError) as error:
        upload(inventory, backend, replace_id=old.pk, source=image_bytes("blue"))
    assert error.value.code == "photo_write_failed"
    assert "DO_NOT_DISCLOSE" not in "".join(traceback.format_exception(error.value)) + caplog.text
    old.refresh_from_db()
    old_blob.refresh_from_db()
    assert old.storage_object_id == old_blob.pk and old_blob.state == "live"
    assert old_blob.key in backend.objects
    assert all(key != old_blob.key for method, key in backend.calls if method == "delete")
    if cleanup_fails or failure == "upload":
        leftover = PhotoStorageObject.objects.exclude(pk=old_blob.pk).get()
        assert leftover.state == "cleanup"
        assert leftover.cleanup_attempts == (0 if failure == "upload" else 1)
        assert leftover.cleanup_error_code == ("photo_upload_unconfirmed" if failure == "upload" else "photo_storage_failed")
        assert photos.photo_usage(inventory[0])["used_bytes"] == old_blob.size_bytes + leftover.size_bytes
        backend.fail_delete = False
        due(leftover)
        assert photos.retry_photo_cleanup(storage=backend).deleted == 1
    assert PhotoStorageObject.objects.count() == len(backend.objects) == 1


def test_ambiguous_put_persisting_after_early_delete_remains_tracked_and_is_deleted_later(inventory, backend):
    backend.fail_upload = True
    with pytest.raises(ValidationError):
        upload(inventory, backend)
    blob = PhotoStorageObject.objects.get()
    assert not backend.objects and blob.cleanup_error_code == "photo_upload_unconfirmed"
    assert blob.cleanup_after > timezone.now()
    assert photos.photo_usage(inventory[0])["used_bytes"] == blob.size_bytes
    # Simulate the timed-out PUT completing after the first acknowledged DELETE.
    backend.objects[blob.key] = process_photo(image_bytes()).data
    assert photos.retry_photo_cleanup(storage=backend).scanned == 0
    assert PhotoStorageObject.objects.filter(pk=blob.pk).exists() and blob.key in backend.objects
    due(blob)
    assert photos.retry_photo_cleanup(storage=backend).deleted == 1
    assert not backend.objects and not PhotoStorageObject.objects.exists()
    assert [method for method, key in backend.calls] == ["upload", "delete", "delete"]
    assert photos.photo_usage(inventory[0])["used_bytes"] == 0


def test_db_failure_before_reservation_never_uploads(inventory, backend):
    with patch.object(PhotoStorageObject, "save", side_effect=DatabaseError("synthetic DB failure")):
        with pytest.raises(ValidationError):
            upload(inventory, backend)
    assert not PhotoStorageObject.objects.exists() and not backend.calls


def test_compensation_db_outage_preserves_original_reservation_for_expiry_recovery(inventory, backend):
    backend.fail_upload = True
    with patch.object(photos, "_enqueue", side_effect=DatabaseError("synthetic outage")):
        with pytest.raises(ValidationError):
            upload(inventory, backend)
    blob = PhotoStorageObject.objects.get()
    assert blob.state == "reserved" and blob.cleanup_after > timezone.now()
    assert not Photo.objects.exists() and blob.key in backend.objects
    due(blob)
    assert photos.retry_photo_cleanup(storage=backend).deferred == 1
    assert PhotoStorageObject.objects.filter(pk=blob.pk).exists()
    due(blob)
    assert photos.retry_photo_cleanup(storage=backend).deleted == 1
    assert not backend.objects and not PhotoStorageObject.objects.exists()


def test_successful_replacement_keeps_pending_old_bytes_when_delete_fails(inventory, backend):
    first = upload(inventory, backend)
    backend.fail_delete = True
    second = upload(inventory, backend, replace_id=first.pk, source=image_bytes("blue"))
    assert second.pk == first.pk and Photo.objects.count() == 1
    assert PhotoStorageObject.objects.count() == 2 and len(backend.objects) == 2
    assert photos.photo_usage(inventory[0])["pending_bytes"] > 0


def test_delete_reference_commits_before_external_cleanup_and_keeps_failed_bytes(inventory, backend):
    photo = upload(inventory, backend)
    backend.fail_delete = True
    photos.delete_photo(inventory[0], photo.pk, storage=backend)
    assert not Photo.objects.exists()
    blob = PhotoStorageObject.objects.get()
    assert blob.state == "cleanup" and photos.photo_usage(inventory[0])["used_bytes"] == blob.size_bytes
    assert blob.key in backend.objects
    backend.fail_delete = False
    due(blob)
    assert photos.retry_photo_cleanup(storage=backend).deleted == 1
    assert photos.photo_usage(inventory[0])["used_bytes"] == 0


def test_delete_db_failure_retains_live_reference_without_external_delete(inventory, backend):
    photo = upload(inventory, backend)
    backend.calls.clear()
    with patch.object(Photo, "delete", side_effect=DatabaseError("synthetic DB failure")):
        with pytest.raises(ValidationError):
            photos.delete_photo(inventory[0], photo.pk, storage=backend)
    assert Photo.objects.get().storage_object.state == "live" and not backend.calls


@pytest.mark.parametrize("limit_name", ["GARAGE_PHOTO_OWNER_QUOTA_BYTES", "GARAGE_PHOTO_PROJECT_QUOTA_BYTES"])
def test_exact_quota_boundary_then_rejection_before_storage(inventory, backend, limit_name):
    size = len(process_photo(image_bytes()).data)
    with override_settings(**{limit_name: size}):
        upload(inventory, backend)
        backend.calls.clear()
        with pytest.raises(ValidationError) as error:
            upload(inventory, backend)
    assert error.value.code == "photo_quota_exceeded" and not backend.calls
    assert PhotoStorageObject.objects.count() == 1


def test_pending_reservations_and_failed_deletions_keep_counting_towards_quota(inventory, backend):
    user = inventory[0]
    size = len(process_photo(image_bytes()).data)
    pending(user, size=size, state="reserved")
    with override_settings(GARAGE_PHOTO_OWNER_QUOTA_BYTES=size):
        with pytest.raises(ValidationError) as error:
            upload(inventory, backend)
    assert error.value.code == "photo_quota_exceeded" and not backend.calls


def test_project_limit_counts_other_users_and_owner_report_remains_scoped(inventory, backend):
    user, other, _, _ = inventory
    size = len(process_photo(image_bytes()).data)
    pending(other, size=size)
    assert photos.photo_usage(user)["used_bytes"] == 0
    with override_settings(GARAGE_PHOTO_PROJECT_QUOTA_BYTES=size):
        with pytest.raises(ValidationError):
            upload(inventory, backend)
    assert not backend.calls


@pytest.mark.parametrize("value", [0, -1, True, "not-a-number", 4_000_000_001])
def test_invalid_quota_config_is_safe(inventory, backend, value):
    with override_settings(GARAGE_PHOTO_OWNER_QUOTA_BYTES=value):
        with pytest.raises(ValidationError) as error:
            upload(inventory, backend)
    assert error.value.code == "photo_storage_unavailable" and not backend.calls


def test_quota_concurrency_has_single_winner_under_owner_lock(inventory):
    user, _, bike, _ = inventory
    size = len(process_photo(image_bytes()).data)
    barrier = Barrier(2)
    def write():
        close_old_connections()
        try:
            actor = get_user_model().objects.get(pk=user.pk)
            barrier.wait(timeout=10)
            try:
                photos.upload_photo(actor, target_model=Bike, target_id=bike.pk, source=image_bytes(), storage=MemoryPhotoStorage())
                return "saved"
            except ValidationError as error:
                return error.code
        finally:
            close_old_connections()
    with override_settings(GARAGE_PHOTO_OWNER_QUOTA_BYTES=size), ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result(timeout=20) for future in [pool.submit(write), pool.submit(write)]]
    assert sorted(results) == ["photo_quota_exceeded", "saved"]
    assert Photo.objects.count() == PhotoStorageObject.objects.count() == 1


def test_project_quota_concurrency_has_single_winner_across_distinct_owner_locks(inventory):
    user, other, bike, _ = inventory
    foreign = create_inventory(other, Bike, name="Other quota bike")
    size = len(process_photo(image_bytes()).data)
    barrier = Barrier(2)
    def write(owner_id, target_id):
        close_old_connections()
        try:
            actor = get_user_model().objects.get(pk=owner_id)
            barrier.wait(timeout=10)
            try:
                photos.upload_photo(actor, target_model=Bike, target_id=target_id, source=image_bytes(), storage=MemoryPhotoStorage())
                return "saved"
            except ValidationError as error:
                return error.code
        finally:
            close_old_connections()
    with override_settings(GARAGE_PHOTO_PROJECT_QUOTA_BYTES=size), ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(write, user.pk, bike.pk), pool.submit(write, other.pk, foreign.pk)]
        results = [future.result(timeout=20) for future in futures]
    assert sorted(results) == ["photo_quota_exceeded", "saved"]
    assert Photo.objects.count() == PhotoStorageObject.objects.count() == 1


@pytest.mark.parametrize("operation", ["read", "sign"])
def test_read_and_sign_storage_errors_are_sanitized(inventory, backend, operation):
    photo = upload(inventory, backend)
    if operation == "read":
        backend.fail_read = True
    else:
        backend.fail_sign = True
    with pytest.raises(ValidationError) as error:
        (photos.read_photo if operation == "read" else photos.signed_photo_url)(inventory[0], photo.pk, storage=backend)
    assert error.value.code == "photo_storage_unavailable"


def test_read_validates_persisted_checksum(inventory, backend):
    photo = upload(inventory, backend)
    backend.objects[photo.storage_object.key] = b"tampered"
    with pytest.raises(ValidationError):
        photos.read_photo(inventory[0], photo.pk, storage=backend)


def test_nested_transaction_rejected_before_any_upload_or_reservation(inventory, backend):
    with transaction.atomic(), pytest.raises(ValidationError) as error:
        upload(inventory, backend)
    assert error.value.code == "photo_transaction_boundary" and not backend.calls


def test_inventory_and_account_deletion_protect_references_and_cleanup_metadata(inventory, backend):
    user, _, bike, _ = inventory
    upload(inventory, backend)
    with pytest.raises(ValidationError):
        delete_inventory(user, Bike, bike.pk)
    with pytest.raises(ProtectedError):
        user.delete()
    assert Photo.objects.count() == PhotoStorageObject.objects.count() == 1


def test_photo_model_validates_cross_owner_targets_and_object(inventory, backend):
    user, other, bike, _ = inventory
    photo = upload(inventory, backend)
    for changes in [{"owner": other}, {"bike": create_inventory(other, Bike, name="Other")},
                    {"storage_object": pending(other)}]:
        invalid = Photo(owner=user, bike=bike, storage_object=photo.storage_object)
        for name, value in changes.items():
            setattr(invalid, name, value)
        with pytest.raises(ValidationError):
            invalid.full_clean()


@pytest.mark.parametrize("changes", [{"bike": None}, {"item": "own"}])
def test_sql_requires_exactly_one_photo_target(inventory, backend, changes):
    photo = upload(inventory, backend)
    if changes.get("item") == "own":
        changes = {"item": inventory[3]}
    with pytest.raises(IntegrityError), transaction.atomic():
        Photo.objects.filter(pk=photo.pk).update(**changes)


@pytest.mark.parametrize("changes", [{"size_bytes": 0}, {"size_bytes": 15 * 1024 * 1024 + 1},
    {"width": 2001}, {"height": 0}, {"key": "foreign/object.webp"}, {"sha256": "not-a-hash"},
    {"state": "unknown"}, {"cleanup_after": None}])
def test_sql_rejects_invalid_reservation_metadata(inventory, changes):
    blob = pending(inventory[0])
    with pytest.raises(IntegrityError), transaction.atomic():
        PhotoStorageObject.objects.filter(pk=blob.pk).update(**changes)


def test_object_identity_and_photo_target_are_immutable_in_model_validation(inventory, backend):
    photo = upload(inventory, backend)
    photo.bike = create_inventory(inventory[0], Bike, name="Another own bike")
    with pytest.raises(ValidationError):
        photo.full_clean()
    blob = photo.storage_object
    blob.key = new_photo_key()
    with pytest.raises(ValidationError):
        blob.full_clean()
