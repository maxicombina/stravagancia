"""Owner-bound photo persistence with durable byte reservations and cleanup.

Writes must start in autocommit: committing the reservation before PUT is
essential to recovering a process crash or an ambiguous external write.
All photo writes/cleanup lock the owner; project reservations also lock one
singleton budget row. External calls are bounded by the transport settings.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
import hashlib
import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, connection, transaction
from django.db.models import Q, Sum
from django.utils import timezone

from garage.models import Bike, Item, Photo, PhotoStorageBudget, PhotoStorageObject, ServiceEvent
from garage.photos import process_photo
from garage.storage import (PhotoStorageConfig, PhotoStorageConfigError, PhotoStorageError,
                            PrivatePhotoStorage, new_photo_key)
from .ownership import InventoryNotFound, _lock_owner, get_inventory, require_actor


# Reserve 1 GB of the documented 5 GB provider allowance as headroom. This is a
# project application ceiling, not a measurement of provider usage/versioning.
DEFAULT_PROJECT_QUOTA_BYTES = 4_000_000_000
DEFAULT_OWNER_QUOTA_BYTES = 250 * 1024 * 1024
RESERVATION_TIMEOUT = timedelta(minutes=10)


def _error(code="photo_write_failed"):
    messages = {"photo_quota_exceeded": "No queda espacio disponible para guardar la foto.",
                "photo_changed": "La foto cambió durante la operación. Vuelve a intentarlo.",
                "photo_storage_unavailable": "El almacenamiento de fotos no está disponible.",
                "photo_transaction_boundary": "La operación de fotos requiere una transacción independiente."}
    return ValidationError(messages.get(code, "No se pudo completar la operación de la foto."), code=code)


def _limits():
    values = []
    for name, default in (("GARAGE_PHOTO_OWNER_QUOTA_BYTES", DEFAULT_OWNER_QUOTA_BYTES),
                          ("GARAGE_PHOTO_PROJECT_QUOTA_BYTES", DEFAULT_PROJECT_QUOTA_BYTES)):
        value = getattr(settings, name, os.environ.get(name, default))
        if isinstance(value, str) and value.isascii() and value.isdecimal() and len(value) <= 10:
            value = int(value)
        if type(value) is not int or not 0 < value <= DEFAULT_PROJECT_QUOTA_BYTES:
            raise _error("photo_storage_unavailable")
        values.append(value)
    return values


def _independent_write():
    if not connection.get_autocommit() or connection.in_atomic_block:
        raise _error("photo_transaction_boundary")


def get_photo_storage():
    return PrivatePhotoStorage(PhotoStorageConfig.from_environment())


@contextmanager
def _storage(injected=None):
    own = injected is None
    try:
        backend = get_photo_storage() if own else injected
    except PhotoStorageConfigError:
        raise _error("photo_storage_unavailable") from None
    try:
        yield backend
    finally:
        if own:
            backend.close()


def _target(actor, model, target_id):
    if model not in (Bike, Item, ServiceEvent):
        raise TypeError("Only bikes, items and interventions can have photos.")
    return get_inventory(actor, model, target_id)


def owned_photos(actor):
    owner = require_actor(actor)
    return Photo.objects.filter(owner_id=owner.pk, storage_object__owner_id=owner.pk,
        storage_object__state="live").filter(Q(bike__owner_id=owner.pk) | Q(item__owner_id=owner.pk) | Q(service_event__owner_id=owner.pk))


def get_photo(actor, photo_id):
    try:
        return owned_photos(actor).select_related("storage_object", "bike", "item", "service_event").get(pk=photo_id)
    except (Photo.DoesNotExist, ValidationError, ValueError, TypeError):
        raise InventoryNotFound() from None


def photo_usage(actor):
    owner = require_actor(actor)
    total = PhotoStorageObject.objects.filter(owner=owner).aggregate(total=Sum("size_bytes"))["total"] or 0
    limit, _ = _limits()
    return {"used_bytes": total, "limit_bytes": limit,
            "pending_bytes": PhotoStorageObject.objects.filter(owner=owner).exclude(state="live")
                .aggregate(total=Sum("size_bytes"))["total"] or 0}


def _replacement(actor, photo_id, target):
    if photo_id is None:
        return None
    photo = get_photo(actor, photo_id)
    field = "bike_id" if isinstance(target, Bike) else "item_id" if isinstance(target, Item) else "service_event_id"
    if getattr(photo, field) != target.pk:
        raise InventoryNotFound()
    return photo


def _reserve(actor, target_model, target_id, processed, replace_id):
    with transaction.atomic(durable=True):
        owner = _lock_owner(actor)
        target = _target(owner, target_model, target_id)
        previous = _replacement(owner, replace_id, target)
        PhotoStorageBudget.objects.get_or_create(pk=1)
        PhotoStorageBudget.objects.select_for_update().get(pk=1)
        owner_limit, project_limit = _limits()
        own_bytes = PhotoStorageObject.objects.filter(owner=owner).aggregate(total=Sum("size_bytes"))["total"] or 0
        project_bytes = PhotoStorageObject.objects.aggregate(total=Sum("size_bytes"))["total"] or 0
        size = len(processed.data)
        if own_bytes + size > owner_limit or project_bytes + size > project_limit:
            raise _error("photo_quota_exceeded")
        blob = PhotoStorageObject(owner=owner, key=new_photo_key(), size_bytes=size,
            width=processed.width, height=processed.height, sha256=hashlib.sha256(processed.data).hexdigest(),
            state="reserved", cleanup_after=timezone.now() + RESERVATION_TIMEOUT)
        blob.full_clean()
        blob.save(force_insert=True)
        return blob, previous.storage_object_id if previous else None


def _enqueue(blob, *, settle=False):
    blob.state = "cleanup"
    now = timezone.now()
    # An unconfirmed PUT may still finish after an early DELETE. Keep its key
    # and byte reservation until a later DELETE after the settle window.
    blob.cleanup_after = max(blob.cleanup_after or now, now + RESERVATION_TIMEOUT) if settle else now
    blob.cleanup_error_code = "photo_upload_unconfirmed" if settle else ""
    blob.save(update_fields=["state", "cleanup_after", "cleanup_error_code", "updated_at"])


def _cleanup_one(blob_id, backend):
    """Trusted maintenance only; never delete an object with any DB reference."""
    candidate = PhotoStorageObject.objects.filter(pk=blob_id).values("owner_id").first()
    if candidate is None:
        return "skipped"
    with transaction.atomic(durable=True):
        # Cleanup remains possible when the user has been deactivated.
        get_user_model().objects.select_for_update().get(pk=candidate["owner_id"])
        blob = PhotoStorageObject.objects.filter(pk=blob_id).first()
        now = timezone.now()
        if blob is None or blob.state == "live" or blob.cleanup_after is None or blob.cleanup_after > now:
            return "skipped"
        if Photo.objects.filter(storage_object_id=blob.pk).exists():
            code = "photo_still_referenced"
        else:
            try:
                backend.delete(blob.key)
            except PhotoStorageError:
                code = "photo_storage_failed"
            else:
                if blob.state == "reserved":
                    # A crashed uploader may have started PUT just before its
                    # lease expired. An absent key after DELETE is not proof
                    # that the in-flight PUT cannot still persist afterward.
                    _enqueue(blob, settle=True)
                    return "deferred"
                blob.delete()
                return "deleted"
        blob.cleanup_attempts += 1
        blob.cleanup_error_code = code
        blob.cleanup_after = now + timedelta(seconds=min(3600, 60 * 2 ** min(blob.cleanup_attempts - 1, 6)))
        blob.save(update_fields=["cleanup_attempts", "cleanup_error_code", "cleanup_after", "updated_at"])
        return "failed"


def _best_effort_cleanup(blob_id, backend, *, enqueue=False, settle=False):
    try:
        early_delete_key = None
        if enqueue:
            with transaction.atomic(durable=True):
                candidate = PhotoStorageObject.objects.filter(pk=blob_id).values("owner_id").first()
                if candidate:
                    get_user_model().objects.select_for_update().get(pk=candidate["owner_id"])
                    blob = PhotoStorageObject.objects.filter(pk=blob_id).first()
                    if blob and blob.state != "live" and not Photo.objects.filter(storage_object=blob).exists():
                        _enqueue(blob, settle=settle)
                        early_delete_key = blob.key
        if settle:
            if early_delete_key:
                try:
                    backend.delete(early_delete_key)
                except PhotoStorageError:
                    pass
            return
        _cleanup_one(blob_id, backend)
    except DatabaseError:
        # The reservation was already committed. Even when DB compensation is
        # unavailable, the deadline lets maintenance recover it after a crash.
        pass


def upload_photo(actor, *, target_model, target_id, source, replace_id=None, storage=None):
    _independent_write()
    target = _target(actor, target_model, target_id)
    _replacement(actor, replace_id, target)
    processed = process_photo(source)  # Only after authorization; no filenames retained.
    with _storage(storage) as backend:
        try:
            blob, previous_id = _reserve(actor, target_model, target_id, processed, replace_id)
        except DatabaseError:
            raise _error() from None
        reservation_id = blob.pk
        put_started = put_confirmed = False
        try:
            with transaction.atomic(durable=True):
                owner = _lock_owner(actor)
                blob = PhotoStorageObject.objects.filter(pk=reservation_id, owner=owner).first()
                if blob is None or blob.state != "reserved" or blob.cleanup_after <= timezone.now():
                    raise _error("photo_changed")
                target = _target(owner, target_model, target_id)
                previous = _replacement(owner, replace_id, target)
                if (previous.storage_object_id if previous else None) != previous_id:
                    raise _error("photo_changed")
                put_started = True
                backend.upload(processed, key=blob.key)
                put_confirmed = True
                blob.state, blob.cleanup_after = "live", None
                blob.save(update_fields=["state", "cleanup_after", "updated_at"])
                photo = previous or Photo(owner=owner, **{"bike" if target_model is Bike else "item" if target_model is Item else "service_event": target})
                old_blob = previous.storage_object if previous else None
                photo.storage_object = blob
                photo.full_clean()
                photo.save()
                if old_blob:
                    _enqueue(old_blob)
        except Exception as error:
            _best_effort_cleanup(reservation_id, backend, enqueue=True, settle=put_started and not put_confirmed)
            if isinstance(error, (DatabaseError, PhotoStorageError)):
                raise _error() from None
            raise
        if previous_id:
            _best_effort_cleanup(previous_id, backend)
        return photo


def delete_photo(actor, photo_id, *, storage=None):
    _independent_write()
    get_photo(actor, photo_id)  # Deny access before constructing the transport.
    with _storage(storage) as backend:
        try:
            with transaction.atomic(durable=True):
                owner = _lock_owner(actor)
                photo = get_photo(owner, photo_id)
                blob = photo.storage_object
                photo.delete()
                _enqueue(blob)
        except DatabaseError:
            raise _error() from None
        _best_effort_cleanup(blob.pk, backend)


def signed_photo_url(actor, photo_id, *, storage=None):
    get_photo(actor, photo_id)
    with _storage(storage) as backend, transaction.atomic():
        owner = _lock_owner(actor)
        photo = get_photo(owner, photo_id)
        try:
            return backend.signed_download_url(photo.storage_object.key)
        except PhotoStorageError:
            raise _error("photo_storage_unavailable") from None


def read_photo(actor, photo_id, *, storage=None):
    get_photo(actor, photo_id)
    with _storage(storage) as backend, transaction.atomic():
        owner = _lock_owner(actor)
        photo = get_photo(owner, photo_id)
        blob = photo.storage_object
        try:
            data = backend.read(blob.key)
            if len(data) != blob.size_bytes or hashlib.sha256(data).hexdigest() != blob.sha256:
                raise _error("photo_storage_unavailable")
            return data
        except PhotoStorageError:
            raise _error("photo_storage_unavailable") from None


@dataclass(frozen=True)
class CleanupResult:
    scanned: int = 0
    deleted: int = 0
    failed: int = 0
    skipped: int = 0
    deferred: int = 0


def retry_photo_cleanup(*, owner_id=None, limit=100, dry_run=False, storage=None):
    """Trusted CLI maintenance; scoped to due tracked keys, never bucket listing."""
    _independent_write()
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValidationError("Choose a cleanup batch size between 1 and 1000.", code="invalid_limit")
    candidates = PhotoStorageObject.objects.exclude(state="live").filter(cleanup_after__lte=timezone.now())
    if owner_id is not None:
        candidates = candidates.filter(owner_id=owner_id)
    ids = list(candidates.order_by("cleanup_after", "pk").values_list("pk", flat=True)[:limit])
    if dry_run or not ids:
        return CleanupResult(scanned=len(ids))
    counts = {"deleted": 0, "failed": 0, "skipped": 0, "deferred": 0}
    with _storage(storage) as backend:
        for blob_id in ids:
            try:
                counts[_cleanup_one(blob_id, backend)] += 1
            except DatabaseError:
                counts["failed"] += 1
    return CleanupResult(scanned=len(ids), **counts)
