from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError
from django.utils import timezone
import pytest

from .models import Photo, PhotoStorageObject
from .services import photos
from .tests_photos_domain import backend, due, image_bytes, inventory, pending, upload


pytestmark = pytest.mark.django_db(transaction=True)


def test_expired_reservation_cleanup_and_recent_reserved_key_is_skipped(inventory, backend):
    old = pending(inventory[0], state="reserved")
    recent = pending(inventory[0], state="reserved")
    PhotoStorageObject.objects.filter(pk=recent.pk).update(cleanup_after=timezone.now() + timedelta(minutes=10))
    backend.objects[old.key] = backend.objects[recent.key] = b"synthetic"
    result = photos.retry_photo_cleanup(storage=backend)
    assert result.scanned == result.deferred == 1 and result.deleted == 0
    assert old.key not in backend.objects and recent.key in backend.objects
    assert PhotoStorageObject.objects.filter(pk=old.pk).exists()
    due(old)
    assert photos.retry_photo_cleanup(storage=backend).deleted == 1
    assert PhotoStorageObject.objects.get().pk == recent.pk


def test_crashed_put_persisting_after_first_expired_reservation_delete_remains_tracked(inventory, backend):
    user = inventory[0]
    blob = pending(user, state="reserved")
    # The uploader began PUT near its lease deadline and crashed; the provider
    # has not stored the object when this first cleanup DELETE is acknowledged.
    result = photos.retry_photo_cleanup(storage=backend)
    assert result.deferred == 1 and result.deleted == 0
    blob.refresh_from_db()
    assert blob.state == "cleanup" and blob.cleanup_after > timezone.now()
    assert photos.photo_usage(user)["used_bytes"] == blob.size_bytes
    # The in-flight request now completes after the first DELETE.
    backend.objects[blob.key] = b"late synthetic object"
    assert photos.retry_photo_cleanup(storage=backend).scanned == 0
    assert PhotoStorageObject.objects.filter(pk=blob.pk).exists() and blob.key in backend.objects
    due(blob)
    assert photos.retry_photo_cleanup(storage=backend).deleted == 1
    assert not PhotoStorageObject.objects.exists() and not backend.objects
    assert [method for method, key in backend.calls] == ["delete", "delete"]
    assert photos.photo_usage(user)["used_bytes"] == 0


def test_cleanup_never_deletes_any_referenced_object_even_if_state_is_corrupted(inventory, backend):
    photo = upload(inventory, backend)
    blob = photo.storage_object
    PhotoStorageObject.objects.filter(pk=blob.pk).update(state="cleanup", cleanup_after=timezone.now() - timedelta(seconds=1))
    backend.calls.clear()
    result = photos.retry_photo_cleanup(storage=backend)
    assert result.failed == 1 and not backend.calls
    blob.refresh_from_db()
    assert blob.cleanup_error_code == "photo_still_referenced" and blob.cleanup_attempts == 1
    assert Photo.objects.exists() and blob.key in backend.objects


def test_cleanup_live_object_is_never_eligible(inventory, backend):
    photo = upload(inventory, backend)
    backend.calls.clear()
    assert photos._cleanup_one(photo.storage_object_id, backend) == "skipped"
    assert not backend.calls and photos.retry_photo_cleanup(storage=backend).scanned == 0


def test_cleanup_missing_job_is_idempotently_skipped(backend):
    import uuid
    assert photos._cleanup_one(uuid.uuid4(), backend) == "skipped"
    assert not backend.calls


def test_cleanup_owner_filter_and_batch_limit(inventory, backend):
    user, other, _, _ = inventory
    own = [pending(user) for _ in range(3)]
    foreign = pending(other)
    result = photos.retry_photo_cleanup(owner_id=user.pk, limit=2, storage=backend)
    assert result.scanned == result.deleted == 2
    assert PhotoStorageObject.objects.filter(owner=user).count() == 1
    assert PhotoStorageObject.objects.filter(pk=foreign.pk).exists()
    assert foreign.key not in [key for _, key in backend.calls]


def test_cleanup_inactive_owner_is_supported(inventory, backend):
    user = inventory[0]
    blob = pending(user)
    user.is_active = False
    user.save(update_fields=["is_active"])
    assert photos.retry_photo_cleanup(storage=backend).deleted == 1
    assert not PhotoStorageObject.objects.filter(pk=blob.pk).exists()


def test_cleanup_retry_has_bounded_backoff_and_safe_error_code(inventory, backend):
    blob = pending(inventory[0])
    backend.fail_delete = True
    assert photos.retry_photo_cleanup(storage=backend).failed == 1
    blob.refresh_from_db()
    first_after = blob.cleanup_after
    assert 50 < (first_after - timezone.now()).total_seconds() <= 60
    assert photos.retry_photo_cleanup(storage=backend).scanned == 0
    due(blob)
    assert photos.retry_photo_cleanup(storage=backend).failed == 1
    blob.refresh_from_db()
    assert 110 < (blob.cleanup_after - timezone.now()).total_seconds() <= 120
    assert blob.cleanup_attempts == 2 and blob.cleanup_error_code == "photo_storage_failed"
    backend.fail_delete = False
    due(blob)
    assert photos.retry_photo_cleanup(storage=backend).deleted == 1


def test_delete_acknowledged_but_db_failure_retains_quota_and_retries_idempotently(inventory, backend):
    blob = pending(inventory[0])
    backend.objects[blob.key] = b"synthetic"
    with patch.object(PhotoStorageObject, "delete", side_effect=DatabaseError("DO_NOT_DISCLOSE")):
        assert photos.retry_photo_cleanup(storage=backend).failed == 1
    assert blob.key not in backend.objects and photos.photo_usage(inventory[0])["used_bytes"] == blob.size_bytes
    assert photos.retry_photo_cleanup(storage=backend).deleted == 1
    assert photos.photo_usage(inventory[0])["used_bytes"] == 0


def test_cleanup_dry_run_does_not_construct_backend(inventory):
    pending(inventory[0])
    with patch.object(photos, "get_photo_storage", side_effect=AssertionError("dry-run must be offline")):
        result = photos.retry_photo_cleanup(dry_run=True)
    assert result.scanned == 1 and result.deleted == result.failed == 0
    assert PhotoStorageObject.objects.count() == 1


@pytest.mark.parametrize("limit", [0, -1, 1001, True, "10"])
def test_cleanup_rejects_invalid_batch_limit(inventory, limit):
    with pytest.raises(ValidationError):
        photos.retry_photo_cleanup(limit=limit)


def test_retry_management_command_reports_only_counts(inventory, backend):
    pending(inventory[0])
    output = StringIO()
    with patch.object(photos, "get_photo_storage", return_value=backend):
        call_command("cleanup_photos", owner=inventory[0].pk, stdout=output)
    assert output.getvalue().strip() == "cleanup: scanned=1 deleted=1 failed=0 skipped=0 deferred=0"
    assert "garage/photos/" not in output.getvalue()


def test_cli_dry_run_and_sanitized_error(inventory):
    pending(inventory[0])
    output = StringIO()
    call_command("cleanup_photos", dry_run=True, stdout=output)
    assert output.getvalue().startswith("dry-run: scanned=1")
    with pytest.raises(CommandError) as error:
        call_command("cleanup_photos", limit=0)
    assert "between" not in str(error.value)


def test_reservation_cleaned_between_commit_and_upload_fails_without_put(inventory, backend):
    original = photos._reserve
    def reserve_and_expire(*args, **kwargs):
        blob, previous_id = original(*args, **kwargs)
        due(blob)
        assert photos.retry_photo_cleanup(storage=backend).deferred == 1
        return blob, previous_id
    with patch.object(photos, "_reserve", reserve_and_expire):
        with pytest.raises(ValidationError) as error:
            upload(inventory, backend)
    assert error.value.code == "photo_changed"
    assert not Photo.objects.exists() and not PhotoStorageObject.objects.exists()
    assert not any(method == "upload" for method, key in backend.calls)


def test_stale_concurrent_replacement_cannot_overwrite_newer_photo(inventory, backend):
    first = upload(inventory, backend)
    original = photos._reserve
    invoked = False
    newer_key = None
    def reserve_with_competing_replacement(*args, **kwargs):
        nonlocal invoked, newer_key
        result = original(*args, **kwargs)
        if not invoked:
            invoked = True
            newer = upload(inventory, backend, replace_id=first.pk, source=image_bytes("blue"))
            newer_key = newer.storage_object.key
        return result
    with patch.object(photos, "_reserve", reserve_with_competing_replacement):
        with pytest.raises(ValidationError) as error:
            upload(inventory, backend, replace_id=first.pk, source=image_bytes("green"))
    assert error.value.code == "photo_changed"
    assert Photo.objects.get().storage_object.key == newer_key
    assert list(backend.objects) == [newer_key]
