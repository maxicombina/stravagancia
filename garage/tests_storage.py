"""Private storage transport tests: synthetic SDK responses, never a bucket."""
from dataclasses import replace
from io import BytesIO
import hashlib
import re
import traceback
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

from botocore.exceptions import ClientError, EndpointConnectionError
from botocore.loaders import Loader
from botocore.response import StreamingBody
from botocore.stub import Stubber
from botocore.utils import IMDSRegionProvider
from PIL import Image
import pytest

from .photos import process_photo
from . import storage


ENV = {"GARAGE_S3_ENDPOINT_URL": "https://synthetic-storage.example.invalid",
       "GARAGE_S3_REGION": "eu-central-1", "GARAGE_S3_BUCKET": "synthetic-garage",
       "GARAGE_S3_ACCESS_KEY_ID": "synthetic-garage-access",
       "GARAGE_S3_SECRET_ACCESS_KEY": "synthetic-garage-secret"}
KEY = "garage/photos/" + "a" * 32 + ".webp"


@pytest.fixture
def config():
    return storage.PhotoStorageConfig.from_environment(ENV)


@pytest.fixture
def backend(config):
    backend = storage.PrivatePhotoStorage(config)
    yield backend
    backend.close()


@pytest.fixture
def photo():
    output = BytesIO()
    with Image.new("RGB", (40, 30), (100, 140, 180)) as image:
        image.save(output, format="PNG")
    return process_photo(output.getvalue())


def test_config_requires_all_garage_values_with_no_aws_fallback():
    inherited = {"AWS_ACCESS_KEY_ID": "DO_NOT_DISCLOSE_ACCESS",
                 "AWS_SECRET_ACCESS_KEY": "DO_NOT_DISCLOSE_SECRET",
                 "AWS_DEFAULT_REGION": "eu-central-1"}
    with pytest.raises(storage.PhotoStorageConfigError) as error:
        storage.PhotoStorageConfig.from_environment(inherited)
    assert "DO_NOT_DISCLOSE" not in repr(error.value)


@pytest.mark.parametrize("name", ENV)
@pytest.mark.parametrize("value", [None, "", " ", "bad\nsecret", " leading", "trailing ", 42])
def test_each_config_value_is_explicit_and_validated(name, value):
    with pytest.raises(storage.PhotoStorageConfigError):
        storage.PhotoStorageConfig.from_environment({**ENV, name: value})


@pytest.mark.parametrize("endpoint", ["http://example.invalid", "https://secret@example.invalid",
    "https://user:secret@example.invalid", "https://example.invalid?secret=123",
    "https://example.invalid#secret", "https://example.invalid/bucket", "https://example.invalid:80",
    "https://example.invalid:wrong", "https://[broken", "https://", "https://evil_name.invalid"])
def test_endpoint_is_fixed_https_without_url_credentials_or_parameters(endpoint):
    with pytest.raises(storage.PhotoStorageConfigError) as error:
        storage.PhotoStorageConfig.from_environment({**ENV, "GARAGE_S3_ENDPOINT_URL": endpoint})
    assert endpoint not in str(error.value)


@pytest.mark.parametrize("bucket", ["ab", "bad/name", "BadName", "bucket..name", "bad.-name",
                                    "bad-.name", "127.0.0.1", "a" * 64, "arn:aws:s3:::bucket"])
def test_bucket_is_plain_name(bucket):
    with pytest.raises(storage.PhotoStorageConfigError):
        storage.PhotoStorageConfig.from_environment({**ENV, "GARAGE_S3_BUCKET": bucket})


@pytest.mark.parametrize("region", ["EU-west-1", "bad/name", "a" * 64])
def test_region_is_explicit_and_plain(region):
    with pytest.raises(storage.PhotoStorageConfigError):
        storage.PhotoStorageConfig.from_environment({**ENV, "GARAGE_S3_REGION": region})


def test_config_representation_does_not_disclose_credentials_or_endpoint(config):
    assert ENV["GARAGE_S3_SECRET_ACCESS_KEY"] not in repr(config)
    assert ENV["GARAGE_S3_ACCESS_KEY_ID"] not in repr(config)
    assert ENV["GARAGE_S3_ENDPOINT_URL"] not in repr(config)


def test_environment_loader_is_lazy_and_reads_only_garage_mapping(monkeypatch):
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    assert storage.PhotoStorageConfig.from_environment() == storage.PhotoStorageConfig.from_environment(ENV)


def test_sdk_ignores_ambient_aws_profiles_endpoints_tokens_and_ca(config, monkeypatch):
    for name, value in {"AWS_PROFILE": "profile-that-does-not-exist",
                        "AWS_CONFIG_FILE": "/must-not-read/.env",
                        "AWS_SHARED_CREDENTIALS_FILE": "/must-not-read/.env",
                        "AWS_ENDPOINT_URL": "https://must-not-connect.example.invalid",
                        "AWS_ENDPOINT_URL_S3": "https://must-not-connect.example.invalid",
                        "AWS_ACCESS_KEY_ID": "AMBIENT_ACCESS", "AWS_SECRET_ACCESS_KEY": "AMBIENT_SECRET",
                        "AWS_SESSION_TOKEN": "AMBIENT_TOKEN", "AWS_CA_BUNDLE": "/must-not-read/.env",
                        "AWS_DEFAULT_REGION": "wrong-region", "HTTPS_PROXY": "https://wrong-proxy.invalid"}.items():
        monkeypatch.setenv(name, value)
    backend = storage.PrivatePhotoStorage(config)
    try:
        client = backend._client
        assert client.meta.endpoint_url == config.endpoint_url
        assert client.meta.region_name == config.region_name
        assert client.meta.config.signature_version == "s3v4"
        assert client.meta.config.s3["addressing_style"] == "path"
        assert client.meta.config.connect_timeout == 3 and client.meta.config.read_timeout == 10
        assert client.meta.config.retries["total_max_attempts"] == 2
        assert client.meta.config.proxies == {}
        assert client.meta.config.request_checksum_calculation == "when_required"
        assert client.meta.config.response_checksum_validation == "when_required"
        assert client._endpoint.http_session._verify is True
        credentials = client._request_signer._credentials.get_frozen_credentials()
        assert credentials.access_key == config.access_key_id and credentials.secret_key == config.secret_access_key
        assert credentials.token is None
    finally:
        backend.close()


def test_sdk_excludes_local_and_ambient_model_overrides(config, monkeypatch, tmp_path):
    local_models = tmp_path / "local-aws-models"
    model_directory = local_models / "s3" / "2006-03-01"
    model_directory.mkdir(parents=True)
    # If the customer model path is searched first, constructing S3 fails while
    # parsing this override. The test never writes to the real ~/.aws directory.
    (model_directory / "service-2.json").write_text("invalid local model override")
    ambient_models = tmp_path / "ambient-models"
    ambient_models.mkdir()
    monkeypatch.setattr(Loader, "CUSTOMER_DATA_PATH", str(local_models))
    monkeypatch.setenv("AWS_DATA_PATH", str(ambient_models))
    observed_paths = []
    original_load = Loader.load_service_model

    def record_model_paths(loader, *args, **kwargs):
        observed_paths.extend(loader.search_paths)
        return original_load(loader, *args, **kwargs)

    monkeypatch.setattr(Loader, "load_service_model", record_model_paths)
    backend = storage.PrivatePhotoStorage(config)
    try:
        assert backend._client.meta.service_model.service_name == "s3"
        assert Loader.BUILTIN_DATA_PATH in observed_paths
        assert str(local_models) not in observed_paths
        assert str(ambient_models) not in observed_paths
        # boto3 adds only its bundled resource models after initialization.
        boto3_models = str(storage.boto3.__path__[0]) + "/data"
        assert set(observed_paths) <= {Loader.BUILTIN_DATA_PATH, boto3_models}
    finally:
        backend.close()


def test_ambient_auto_defaults_never_invoke_metadata_provider(config, monkeypatch):
    monkeypatch.setenv("AWS_DEFAULTS_MODE", "auto")
    monkeypatch.setenv("AWS_EC2_METADATA_SERVICE_ENDPOINT", "http://metadata-must-not-connect.example.invalid")
    monkeypatch.delenv("AWS_EXECUTION_ENV", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    provide = Mock(return_value=config.region_name)
    monkeypatch.setattr(IMDSRegionProvider, "provide", provide)
    backend = storage.PrivatePhotoStorage(config)
    try:
        provide.assert_not_called()
        assert backend._client.meta.region_name == config.region_name
        assert backend._client.meta.endpoint_url == config.endpoint_url
    finally:
        backend.close()


def test_explicit_config_required():
    with pytest.raises(TypeError):
        storage.PrivatePhotoStorage(None)


def test_client_construction_errors_are_sanitized(config, monkeypatch):
    session = Mock()
    session.client.side_effect = EndpointConnectionError(endpoint_url="https://DO_NOT_DISCLOSE.invalid")
    monkeypatch.setattr(storage.boto3.session, "Session", lambda **kwargs: session)
    with pytest.raises(storage.PhotoStorageConfigError) as error:
        storage.PrivatePhotoStorage(config)
    assert "DO_NOT_DISCLOSE" not in "".join(traceback.format_exception(error.value))


def test_generated_keys_are_unique_and_independent_of_client_names():
    keys = [storage.new_photo_key() for _ in range(100)]
    assert len(set(keys)) == 100
    assert all(re.fullmatch(r"garage/photos/[0-9a-f]{32}\.webp", key) for key in keys)


def test_upload_processed_photo_uses_private_headers_no_acl_and_returns_accounting(backend, photo):
    photo = replace(photo, filename="../../secret-client-filename.jpg")
    with Stubber(backend._client) as stub:
        stub.add_response("put_object", {}, {"Bucket": ENV["GARAGE_S3_BUCKET"], "Key": KEY,
            "Body": photo.data, "ContentLength": len(photo.data), "ContentType": "image/webp",
            "CacheControl": "private, no-store"})
        result = backend.upload(photo, key=KEY)
        stub.assert_no_pending_responses()
    assert result.key == KEY and result.size_bytes == len(photo.data)
    assert result.sha256 == hashlib.sha256(photo.data).hexdigest()


@pytest.mark.parametrize("changes", [{"data": b"not webp"}, {"data": "not bytes"},
    {"content_type": "text/html"}, {"width": 2001}, {"height": 0}, {"width": True}])
def test_upload_requires_processed_webp_before_sdk_access(config, photo, changes):
    client = Mock()
    backend = storage.PrivatePhotoStorage(config, client=client)
    with pytest.raises(ValueError):
        backend.upload(replace(photo, **changes), key=KEY)
    client.put_object.assert_not_called()


def test_upload_respects_processed_byte_limit_before_sdk(config, photo, monkeypatch):
    monkeypatch.setattr(storage, "MAX_STORED_PHOTO_BYTES", len(photo.data) - 1)
    client = Mock()
    with pytest.raises(storage.PhotoStorageError) as error:
        storage.PrivatePhotoStorage(config, client=client).upload(photo, key=KEY)
    assert error.value.code == "photo_storage_invalid_object"
    client.put_object.assert_not_called()


@pytest.mark.parametrize("photo", [b"bytes", None, "filename.webp"])
def test_unprocessed_input_rejected_before_upload(config, photo):
    client = Mock()
    with pytest.raises(ValueError):
        storage.PrivatePhotoStorage(config, client=client).upload(photo, key=KEY)
    client.put_object.assert_not_called()


@pytest.mark.parametrize("key", [None, "", "https://other.example.invalid/a", "../secret.webp",
    "garage/photos/../x.webp", "garage/photos/" + "A" * 32 + ".webp", KEY + "\n",
    KEY.replace(".webp", ".html"), "other/" + "a" * 32 + ".webp"])
def test_every_operation_rejects_foreign_or_client_keys_before_sdk(config, photo, key):
    client = Mock()
    backend = storage.PrivatePhotoStorage(config, client=client)
    for operation in [lambda: backend.upload(photo, key=key), lambda: backend.read(key),
                      lambda: backend.size(key), lambda: backend.delete(key),
                      lambda: backend.signed_download_url(key)]:
        with pytest.raises(ValueError):
            operation()
    assert not client.mock_calls


def test_bounded_read_roundtrip_and_stream_closed(backend, photo):
    raw = BytesIO(photo.data)
    with Stubber(backend._client) as stub:
        stub.add_response("get_object", {"Body": StreamingBody(raw, len(photo.data)),
            "ContentLength": len(photo.data), "ContentType": "image/webp"},
            {"Bucket": ENV["GARAGE_S3_BUCKET"], "Key": KEY})
        assert backend.read(KEY) == photo.data
        stub.assert_no_pending_responses()
    assert raw.closed


@pytest.mark.parametrize("length,content_type", [(0, "image/webp"), (True, "image/webp"),
    (-1, "image/webp"), (storage.MAX_STORED_PHOTO_BYTES + 1, "image/webp"), (20, "text/html"),
    (None, "image/webp")])
def test_invalid_download_headers_close_stream_without_reading(config, length, content_type):
    body = Mock()
    client = Mock()
    client.get_object.return_value = {"Body": body, "ContentLength": length, "ContentType": content_type}
    with pytest.raises(storage.PhotoStorageError) as error:
        storage.PrivatePhotoStorage(config, client=client).read(KEY)
    assert error.value.code == "photo_storage_invalid_object"
    body.read.assert_not_called()
    body.close.assert_called_once_with()


@pytest.mark.parametrize("data", [b"short", b"too much data", "not binary"])
def test_read_rejects_truncated_or_excess_bytes_and_always_closes(config, data):
    body = Mock()
    body.read.return_value = data
    client = Mock()
    client.get_object.return_value = {"Body": body, "ContentLength": 10, "ContentType": "image/webp"}
    with pytest.raises(storage.PhotoStorageError):
        storage.PrivatePhotoStorage(config, client=client).read(KEY)
    body.read.assert_called_once_with(11)
    body.close.assert_called_once_with()


@pytest.mark.parametrize("failure", [OSError("DO_NOT_DISCLOSE stream details"),
    EndpointConnectionError(endpoint_url="https://DO_NOT_DISCLOSE.example.invalid")])
def test_stream_failures_are_sanitized_and_closed(config, failure):
    body = Mock()
    body.read.side_effect = failure
    client = Mock()
    client.get_object.return_value = {"Body": body, "ContentLength": 10, "ContentType": "image/webp"}
    with pytest.raises(storage.PhotoStorageError) as error:
        storage.PrivatePhotoStorage(config, client=client).read(KEY)
    assert "DO_NOT_DISCLOSE" not in "".join(traceback.format_exception(error.value))
    body.close.assert_called_once_with()


def test_stream_close_failures_are_sanitized(config):
    body = Mock()
    body.read.return_value = b"content"
    body.close.side_effect = OSError("DO_NOT_DISCLOSE details")
    client = Mock()
    client.get_object.return_value = {"Body": body, "ContentLength": 7, "ContentType": "image/webp"}
    with pytest.raises(storage.PhotoStorageError) as error:
        storage.PrivatePhotoStorage(config, client=client).read(KEY)
    assert "DO_NOT_DISCLOSE" not in "".join(traceback.format_exception(error.value))


def test_head_reports_bytes_and_delete_is_idempotent(backend):
    with Stubber(backend._client) as stub:
        params = {"Bucket": ENV["GARAGE_S3_BUCKET"], "Key": KEY}
        stub.add_response("head_object", {"ContentLength": 12}, params)
        stub.add_response("delete_object", {}, params)
        stub.add_response("delete_object", {}, params)
        assert backend.size(KEY) == 12
        assert backend.delete(KEY) is None and backend.delete(KEY) is None
        stub.assert_no_pending_responses()


@pytest.mark.parametrize("length", [None, 0, -1, True, storage.MAX_STORED_PHOTO_BYTES + 1])
def test_head_rejects_invalid_accounting_lengths(config, length):
    client = Mock()
    client.head_object.return_value = {"ContentLength": length}
    with pytest.raises(storage.PhotoStorageError) as error:
        storage.PrivatePhotoStorage(config, client=client).size(KEY)
    assert error.value.code == "photo_storage_invalid_object"


@pytest.mark.parametrize("operation", ["put_object", "get_object", "head_object", "delete_object"])
@pytest.mark.parametrize("code,expected", [("AccessDenied", "photo_storage_failed"),
    ("NoSuchKey", "photo_storage_missing"), ("NotFound", "photo_storage_missing"),
    ("404", "photo_storage_missing"), ("InternalError", "photo_storage_failed")])
def test_sdk_failures_have_stable_safe_codes_without_provider_text(backend, photo, operation, code, expected, caplog):
    with Stubber(backend._client) as stub:
        stub.add_client_error(operation, service_error_code=code,
            service_message="DO_NOT_DISCLOSE credentials and signed URLs", http_status_code=403)
        call = {"put_object": lambda: backend.upload(photo, key=KEY), "get_object": lambda: backend.read(KEY),
                "head_object": lambda: backend.size(KEY), "delete_object": lambda: backend.delete(KEY)}[operation]
        with pytest.raises(storage.PhotoStorageError) as error:
            call()
        stub.assert_no_pending_responses()
    assert error.value.code == expected
    assert "DO_NOT_DISCLOSE" not in "".join(traceback.format_exception(error.value)) + caplog.text


def test_ambiguous_upload_failure_leaves_caller_known_key_for_cleanup(config, photo):
    client = Mock()
    client.put_object.side_effect = EndpointConnectionError(endpoint_url="https://DO_NOT_DISCLOSE.invalid")
    backend = storage.PrivatePhotoStorage(config, client=client)
    key = storage.new_photo_key()
    with pytest.raises(storage.PhotoStorageError):
        backend.upload(photo, key=key)
    assert client.put_object.call_args.kwargs["Key"] == key
    backend.delete(key)
    client.delete_object.assert_called_once_with(Bucket=config.bucket_name, Key=key)


def test_signed_download_is_local_sigv4_get_with_bounded_expiry(backend):
    url = backend.signed_download_url(KEY, expires_seconds=120)
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "https" and parsed.netloc == "synthetic-storage.example.invalid"
    assert parsed.path == "/synthetic-garage/" + KEY
    assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert query["X-Amz-Expires"] == ["120"]
    assert query["response-content-type"] == ["image/webp"]
    assert query["response-cache-control"] == ["private, no-store"]
    assert ENV["GARAGE_S3_SECRET_ACCESS_KEY"] not in url
    assert "X-Amz-Security-Token" not in query


@pytest.mark.parametrize("expiry", [1, 300])
def test_expiry_boundaries_sign_only_get_with_exact_key(config, expiry):
    client = Mock()
    client.generate_presigned_url.return_value = "synthetic-signed-url"
    result = storage.PrivatePhotoStorage(config, client=client).signed_download_url(KEY, expires_seconds=expiry)
    assert result == "synthetic-signed-url"
    client.generate_presigned_url.assert_called_once_with("get_object",
        Params={"Bucket": config.bucket_name, "Key": KEY,
                "ResponseContentType": "image/webp", "ResponseCacheControl": "private, no-store"},
        ExpiresIn=expiry, HttpMethod="GET")


@pytest.mark.parametrize("expiry", [0, -1, 301, True, 1.5, "60", None])
def test_invalid_expiry_rejected_before_signing(config, expiry):
    client = Mock()
    with pytest.raises(ValueError):
        storage.PrivatePhotoStorage(config, client=client).signed_download_url(KEY, expires_seconds=expiry)
    client.generate_presigned_url.assert_not_called()


def test_signing_errors_are_sanitized(config):
    client = Mock()
    client.generate_presigned_url.side_effect = ClientError(
        {"Error": {"Code": "InvalidAccessKeyId", "Message": "DO_NOT_DISCLOSE secret"}}, "GetObject")
    with pytest.raises(storage.PhotoStorageError) as error:
        storage.PrivatePhotoStorage(config, client=client).signed_download_url(KEY)
    assert "DO_NOT_DISCLOSE" not in "".join(traceback.format_exception(error.value))


def test_client_resources_can_be_closed(config):
    client = Mock()
    storage.PrivatePhotoStorage(config, client=client).close()
    client.close.assert_called_once_with()
