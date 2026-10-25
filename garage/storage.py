"""Private S3 transport for processed Garage photos.

This module does not authorize users or persist database references. Callers must
authorize the owner/target before every operation, including signed downloads.
Replacement, quotas and durable compensation belong to the domain service.
Importing this module never reads environment configuration or creates a client.
"""
from dataclasses import dataclass, field
import hashlib
import os
import re
from urllib.parse import urlsplit
import uuid

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from botocore.loaders import Loader
import botocore.session

from .photos import MAX_LONG_EDGE, MAX_UPLOAD_BYTES, ProcessedPhoto


KEY_PREFIX = "garage/photos/"
MAX_STORED_PHOTO_BYTES = MAX_UPLOAD_BYTES
MAX_SIGNED_URL_SECONDS = 300
_KEY_PATTERN = re.compile(r"garage/photos/[0-9a-f]{32}\.webp\Z")


class PhotoStorageConfigError(ValueError):
    """Incomplete or invalid operator configuration, with no values exposed."""


class PhotoStorageError(Exception):
    """Sanitized storage failure suitable for translation at a domain boundary."""

    def __init__(self, code="photo_storage_failed"):
        self.code = code
        super().__init__("La foto no está disponible." if code == "photo_storage_missing"
                         else "No se pudo completar la operación de almacenamiento de fotos.")


@dataclass(frozen=True)
class PhotoStorageConfig:
    endpoint_url: str = field(repr=False)
    region_name: str
    bucket_name: str
    access_key_id: str = field(repr=False)
    secret_access_key: str = field(repr=False)

    def __post_init__(self):
        values = (self.endpoint_url, self.region_name, self.bucket_name,
                  self.access_key_id, self.secret_access_key)
        if any(not isinstance(value, str) or not value or value != value.strip()
               or any(ord(char) < 32 or ord(char) == 127 for char in value) for value in values):
            raise PhotoStorageConfigError("Garage S3 requires explicit, nonempty configuration.")
        try:
            endpoint = urlsplit(self.endpoint_url)
            valid_endpoint = (endpoint.scheme == "https" and endpoint.hostname
                              and endpoint.username is None and endpoint.password is None
                              and endpoint.port in (None, 443) and endpoint.path in ("", "/")
                              and not endpoint.query and not endpoint.fragment
                              and re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?", endpoint.hostname))
        except ValueError:
            valid_endpoint = False
        if not valid_endpoint:
            raise PhotoStorageConfigError("Garage S3 requires an HTTPS endpoint without URL credentials or parameters.")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", self.region_name):
            raise PhotoStorageConfigError("Garage S3 requires a valid explicit region.")
        if (not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", self.bucket_name)
                or ".." in self.bucket_name or ".-" in self.bucket_name or "-." in self.bucket_name
                or re.fullmatch(r"[0-9]+(?:\.[0-9]+){3}", self.bucket_name)):
            raise PhotoStorageConfigError("Garage S3 requires a plain bucket name.")

    @classmethod
    def from_environment(cls, environ=None):
        """Read only explicit Garage variables; no dotenv or AWS fallback."""
        env = os.environ if environ is None else environ
        return cls(endpoint_url=env.get("GARAGE_S3_ENDPOINT_URL", ""),
                   region_name=env.get("GARAGE_S3_REGION", ""),
                   bucket_name=env.get("GARAGE_S3_BUCKET", ""),
                   access_key_id=env.get("GARAGE_S3_ACCESS_KEY_ID", ""),
                   secret_access_key=env.get("GARAGE_S3_SECRET_ACCESS_KEY", ""))


@dataclass(frozen=True)
class UploadedPhoto:
    key: str
    size_bytes: int
    sha256: str


def _validate_key(key):
    if not isinstance(key, str) or not _KEY_PATTERN.fullmatch(key):
        raise ValueError("An internal Garage photo key is required.")


def new_photo_key():
    """Allocate before upload so callers can persist a cleanup reservation."""
    return f"{KEY_PREFIX}{uuid.uuid4().hex}.webp"


def _validate_length(length):
    if type(length) is not int or not 0 < length <= MAX_STORED_PHOTO_BYTES:
        raise PhotoStorageError("photo_storage_invalid_object")


class PrivatePhotoStorage:
    """Explicit private transport; object keys are never client filenames.

    Bucket visibility must be private in the provider control plane. S3 ACLs,
    policies, lifecycle and versioning are deliberately not configured here.
    Inject a simulated client for tests; no default Django storage is changed.
    """

    def __init__(self, config, *, client=None):
        if not isinstance(config, PhotoStorageConfig):
            raise TypeError("PhotoStorageConfig is required.")
        self._config = config
        if client is None:
            # Prevent local AWS profiles, files and ambient endpoint overrides
            # from changing Garage's operator-supplied configuration.
            try:
                sdk_session = botocore.session.Session(session_vars={
                    "config_file": (None, None, os.devnull, None),
                    "credentials_file": (None, None, os.devnull, None),
                    "profile": (None, None, None, None),
                    "data_path": (None, None, None, None),
                })
                # Disabling AWS_DATA_PATH alone retains ~/.aws/models in the
                # SDK default loader. Load only models shipped with the SDK.
                sdk_session.register_component("data_loader", Loader(
                    extra_search_paths=[Loader.BUILTIN_DATA_PATH],
                    include_default_search_paths=False))
                session = boto3.session.Session(botocore_session=sdk_session,
                    aws_access_key_id=config.access_key_id,
                    aws_secret_access_key=config.secret_access_key,
                    region_name=config.region_name)
                client = session.client("s3", endpoint_url=config.endpoint_url, verify=True,
                    config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                        defaults_mode="legacy",
                        connect_timeout=3, read_timeout=10, proxies={},
                        retries={"mode": "standard", "total_max_attempts": 2},
                        ignore_configured_endpoint_urls=True,
                        request_checksum_calculation="when_required",
                        response_checksum_validation="when_required"))
            except BotoCoreError:
                raise PhotoStorageConfigError("Garage S3 client configuration failed.") from None
        self._client = client

    def _request(self, operation, **params):
        try:
            return getattr(self._client, operation)(Bucket=self._config.bucket_name, **params)
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code")
            raise PhotoStorageError("photo_storage_missing" if code in {"NoSuchKey", "NotFound", "404"}
                                    else "photo_storage_failed") from None
        except (BotoCoreError, OSError):
            raise PhotoStorageError() from None

    def upload(self, photo, *, key):
        """Upload to a freshly reserved key, known even if the request fails.

        The caller must use new_photo_key(), reserve its reference/cleanup and
        quota before this call, and must never reuse an existing photo key.
        """
        _validate_key(key)
        if (not isinstance(photo, ProcessedPhoto) or not isinstance(photo.data, bytes)
                or photo.content_type != "image/webp"
                or type(photo.width) is not int or type(photo.height) is not int
                or not 0 < photo.width <= MAX_LONG_EDGE or not 0 < photo.height <= MAX_LONG_EDGE
                or not photo.data.startswith(b"RIFF") or photo.data[8:12] != b"WEBP"):
            raise ValueError("A processed Garage WebP photo is required.")
        _validate_length(len(photo.data))
        self._request("put_object", Key=key, Body=photo.data,
                      ContentLength=len(photo.data), ContentType="image/webp",
                      CacheControl="private, no-store")
        return UploadedPhoto(key, len(photo.data), hashlib.sha256(photo.data).hexdigest())

    def read(self, key):
        """Read a bounded object and always release its HTTP response body."""
        _validate_key(key)
        response = self._request("get_object", Key=key)
        body = response["Body"]
        try:
            length = response.get("ContentLength")
            _validate_length(length)
            if response.get("ContentType") != "image/webp":
                raise PhotoStorageError("photo_storage_invalid_object")
            data = body.read(length + 1)
            if not isinstance(data, bytes) or len(data) != length:
                raise PhotoStorageError("photo_storage_invalid_object")
            return data
        except (BotoCoreError, OSError):
            raise PhotoStorageError() from None
        finally:
            try:
                body.close()
            except (BotoCoreError, OSError):
                raise PhotoStorageError() from None

    def size(self, key):
        """Return stored bytes for a known reference; no bucket-wide listing."""
        _validate_key(key)
        response = self._request("head_object", Key=key)
        length = response.get("ContentLength")
        _validate_length(length)
        return length

    def delete(self, key):
        """Delete one authorized key; S3 deletion of an absent key is idempotent."""
        _validate_key(key)
        self._request("delete_object", Key=key)

    def signed_download_url(self, key, *, expires_seconds=60):
        """Sign GET only, after caller authorization; never log or persist URL."""
        _validate_key(key)
        if type(expires_seconds) is not int or not 1 <= expires_seconds <= MAX_SIGNED_URL_SECONDS:
            raise ValueError("Photo URL expiry must be between 1 and 300 seconds.")
        try:
            return self._client.generate_presigned_url("get_object",
                Params={"Bucket": self._config.bucket_name, "Key": key,
                        "ResponseContentType": "image/webp",
                        "ResponseCacheControl": "private, no-store"},
                ExpiresIn=expires_seconds, HttpMethod="GET")
        except (BotoCoreError, ClientError):
            raise PhotoStorageError() from None

    def close(self):
        self._client.close()
