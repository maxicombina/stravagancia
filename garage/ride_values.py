"""Closed, own-data field formats shared by ride models and authorized services."""
from datetime import datetime, timezone as datetime_timezone
from decimal import Decimal
from uuid import UUID

from django.core.exceptions import ValidationError
from django.utils import timezone

from .validators import exact_usage_value

# The four original measurements. The «pending» criterion and history coverage keep
# using only these (garage-030 phase 3): elevation and power never make a ride pending.
CORE_METRICS = ("distance_m", "moving_time_s", "timer_time_s", "elapsed_time_s")
# What flows to each resolved item (ItemUsage), maintenance thresholds included.
USAGE_METRICS = (*CORE_METRICS, "elevation_gain_m")
# Per-ride power and energy: observed and corrected like the others, never materialized.
POWER_METRICS = ("average_power_w", "max_power_w", "weighted_power_w", "energy_kj")
# Every measurement of Ride and ActivitySource (precedence, manual corrections, provenance, export).
RIDE_METRICS = (*USAGE_METRICS, *POWER_METRICS)
# Alias kept for existing imports; it means the usage metrics, not the power ones.
METRIC_FIELDS = USAGE_METRICS
SOURCE_FIELDS = ("started_at", "name", "sport_type", *RIDE_METRICS)
RIDE_FIELDS = (*SOURCE_FIELDS, "bike", "notes")
# Plausibility of the phase-3 observations (FIT parser and Strava adapter): a value
# beyond these is a device or upload glitch and is stored as unknown, never an error.
# Manual corrections are the person's own and only need exact_usage_value.
PLAUSIBLE_MAX = {"elevation_gain_m": Decimal("20000"), "average_power_w": Decimal("2500"), "max_power_w": Decimal("5000"),
                 "weighted_power_w": Decimal("2500"), "energy_kj": Decimal("50000")}
ERROR_CODES = ("invalid_file", "invalid_session", "unsupported_sport", "invalid_metric", "conflict", "unexpected_failure",
               "rate_limited", "unauthorized")
# Classes that reference an ActivitySource; precedence is manual > fit > strava > unknown.
SOURCE_PROVENANCE = ("fit", "strava")


def aware_instant(value):
    if not isinstance(value, datetime) or timezone.is_naive(value):
        raise ValidationError("Enter an instant with an explicit time zone.", code="invalid_instant")
    try:
        return value.astimezone(datetime_timezone.utc)
    except (OverflowError, ValueError):
        raise ValidationError("The instant is outside the supported UTC range.", code="invalid_instant") from None


def plausible(field, value):
    """An exact observed value, or None when it is outside the plausible range of its metric."""
    if value is None:
        return None
    limit = PLAUSIBLE_MAX.get(field)
    return None if limit is not None and value > limit else value


def encode_manual(values):
    """Only key presence denotes a manual correction; NULL is intentional."""
    if not isinstance(values, dict) or not set(values).issubset(RIDE_FIELDS):
        raise ValidationError("Choose supported ride fields.", code="invalid_fields")
    encoded = {}
    for field, value in values.items():
        if value is None:
            encoded[field] = None
        elif field in RIDE_METRICS:
            encoded[field] = str(exact_usage_value(value))
        elif field == "started_at":
            encoded[field] = aware_instant(value).isoformat()
        elif field == "bike":
            try:
                encoded[field] = str(UUID(str(value)))
            except (ValueError, TypeError, AttributeError):
                raise ValidationError("Choose a valid bike.", code="invalid_reference") from None
        elif isinstance(value, str) and (field == "notes" or len(value) <= 150):
            encoded[field] = value
        else:
            raise ValidationError("Enter a supported field value.", code="invalid_value")
    return encoded


def decode_manual(values):
    if not isinstance(values, dict) or not set(values).issubset(RIDE_FIELDS):
        raise ValidationError("Unsupported manual field data.", code="invalid_fields")
    decoded = {}
    for field, value in values.items():
        if value is None:
            decoded[field] = None
        elif field in RIDE_METRICS:
            if not isinstance(value, str):
                raise ValidationError("Stored decimal values must use exact strings.", code="invalid_value")
            decoded[field] = exact_usage_value(value)
        elif field == "started_at":
            if not isinstance(value, str):
                raise ValidationError("Stored instants must use ISO strings.", code="invalid_instant")
            try:
                decoded[field] = aware_instant(datetime.fromisoformat(value))
            except ValueError:
                raise ValidationError("Enter a valid instant.", code="invalid_instant") from None
        elif field == "bike":
            try:
                decoded[field] = UUID(value)
            except (ValueError, TypeError, AttributeError):
                raise ValidationError("Choose a valid bike.", code="invalid_reference") from None
        elif isinstance(value, str) and (field == "notes" or len(value) <= 150):
            decoded[field] = value
        else:
            raise ValidationError("Unsupported stored field value.", code="invalid_value")
    return decoded


def validate_provenance(value):
    if not isinstance(value, dict) or not set(value).issubset(RIDE_FIELDS):
        raise ValidationError("Unsupported provenance fields.", code="invalid_provenance")
    for entry in value.values():
        if not isinstance(entry, dict) or set(entry) != {"kind", "source_id", "updated_at"}:
            raise ValidationError("Unsupported provenance data.", code="invalid_provenance")
        if not isinstance(entry["kind"], str) or entry["kind"] not in {"manual", *SOURCE_PROVENANCE, "unknown"}:
            raise ValidationError("Unsupported provenance kind.", code="invalid_provenance")
        if entry["kind"] in SOURCE_PROVENANCE:
            try:
                UUID(entry["source_id"])
            except (ValueError, TypeError, AttributeError):
                raise ValidationError("Invalid provenance source.", code="invalid_provenance") from None
        elif entry["source_id"] is not None:
            raise ValidationError("Only FIT or Strava provenance has a source.", code="invalid_provenance")
        if entry["updated_at"] is not None:
            try:
                aware_instant(datetime.fromisoformat(entry["updated_at"]))
            except (ValidationError, ValueError, TypeError):
                raise ValidationError("Invalid provenance instant.", code="invalid_provenance") from None


def validate_run_errors(value):
    if not isinstance(value, list) or len(value) > 20:
        raise ValidationError("Keep at most twenty bounded error summaries.", code="invalid_errors")
    for error in value:
        if not isinstance(error, dict) or set(error) != {"code", "session_index"} or error["code"] not in ERROR_CODES:
            raise ValidationError("Use a supported error code without personal data.", code="invalid_errors")
        index = error["session_index"]
        if index is not None and (type(index) is not int or index < 0 or index > 2147483647):
            raise ValidationError("Enter a valid session index.", code="invalid_errors")


def validate_run_manifest(file_hash, session_indices, total):
    """Minimal resumable selection, never file contents, names or paths."""
    import re
    if file_hash == "" and session_indices == []:
        return
    if not isinstance(file_hash, str) or re.fullmatch(r"[0-9a-f]{64}", file_hash) is None:
        raise ValidationError("Enter a SHA256 manifest hash.", code="invalid_manifest")
    if (not isinstance(session_indices, list) or not 1 <= len(session_indices) <= 100
            or any(type(index) is not int or not 0 <= index <= 99 for index in session_indices)
            or session_indices != sorted(set(session_indices))):
        raise ValidationError("Use an ordered unique selection of session indices 0–99.", code="invalid_manifest")
    if type(total) is not int or total != len(session_indices):
        raise ValidationError("The job total must match its session selection.", code="invalid_manifest")
