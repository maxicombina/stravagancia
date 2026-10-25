from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone as datetime_timezone
from decimal import Decimal
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch
import uuid

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, IntegrityError, close_old_connections, connection, transaction

from .models import Category, Item, UsageBaseline
from .services.baselines import (UsageObservation, correct_acquisition_anchor, delete_baseline, latest_baseline,
                                record_baseline, summarize_usage, update_baseline)
from .services.ownership import (InventoryNotFound, InventoryWriteError, create_inventory, delete_inventory,
                                 get_inventory, scoped_inventory, update_inventory)
from .validators import MAX_USAGE_VALUE


def instant(day=1, month=1, year=2026):
    return datetime(year, month, day, tzinfo=datetime_timezone.utc)


@pytest.fixture
def garage(db, django_user_model):
    owner = django_user_model.objects.create_user(username="baseline-owner")
    other = django_user_model.objects.create_user(username="baseline-other")
    category = create_inventory(owner, Category, name="Equipment")
    item = create_inventory(owner, Item, name="Used helmet", category=category, acquired_on=date(2025, 12, 1),
                            acquisition_anchor_at=instant(1, 12, 2025))
    other_category = create_inventory(other, Category, name="Equipment")
    foreign = create_inventory(other, Item, name="SECRET helmet", category=other_category)
    return SimpleNamespace(owner=owner, other=other, item=item, foreign=foreign, category=category)


def reading_values(garage, *, metric="distance_m", scope="lifetime", cut=None, value="1000000"):
    return {"item": garage.item, "metric": metric, "scope": scope, "cut_at": cut or instant(), "value": Decimal(value)}


def record(garage, **kwargs):
    return record_baseline(garage.owner, **reading_values(garage, **kwargs))


def observation(garage, start, value, metric="distance_m"):
    return UsageObservation(garage.owner.pk, garage.item.pk, metric, start, Decimal(value) if value is not None else None)


def code(error, field):
    return error.value.error_dict[field][0].code


@pytest.mark.django_db
def test_same_cut_correction_keeps_uuid_and_does_not_duplicate_or_erase_provenance(garage):
    first = record_baseline(garage.owner, **reading_values(garage), source="manual_garmin_reading", is_estimated=True,
                            notes="Prior reading")
    corrected = record_baseline(garage.owner, **reading_values(garage, value="990000"))
    assert corrected.pk == first.pk and corrected.created_at == first.created_at
    assert corrected.value == Decimal("990000.000") and corrected.source == "manual_garmin_reading"
    assert corrected.is_estimated and corrected.notes == "Prior reading"
    assert UsageBaseline.objects.count() == 1
    explicit = update_baseline(garage.owner, corrected.pk, notes="Confirmed", is_estimated=False)
    assert explicit.pk == first.pk and not explicit.is_estimated and explicit.notes == "Confirmed"


@pytest.mark.django_db
def test_independent_metrics_scopes_and_owners_never_share_readings(garage):
    distance = record(garage)
    time = record(garage, metric="moving_time_s", value="3600.123")
    acquired = record(garage, scope="acquisition", value="0")
    foreign = record_baseline(garage.other, **(reading_values(garage, value="12") | {"item": garage.foreign}))
    assert len({distance.pk, time.pk, acquired.pk, foreign.pk}) == 4
    assert list(scoped_inventory(garage.other, UsageBaseline)) == [foreign]
    assert latest_baseline(garage.owner, garage.item.pk, metric="distance_m", scope="lifetime", at=instant()) == distance
    assert latest_baseline(garage.owner, garage.item.pk, metric="moving_time_s", scope="lifetime", at=instant()) == time
    assert latest_baseline(garage.owner, garage.item.pk, metric="distance_m", scope="acquisition", at=instant()) == acquired


@pytest.mark.parametrize("metric,value", [("distance_m", "12.345"), ("moving_time_s", "67.891"),
                                         ("ride_count", "2"), ("moving_time_s", "1.2300"),
                                         ("distance_m", "0"), ("moving_time_s", str(MAX_USAGE_VALUE))])
@pytest.mark.django_db
def test_exact_milliunits_roundtrip_and_only_ride_count_is_integral(garage, metric, value):
    baseline = record(garage, metric=metric, value=value)
    baseline.refresh_from_db()
    assert baseline.value == Decimal(value)
    assert baseline.value.as_tuple().exponent == -3


@pytest.mark.parametrize("value,expected", [(Decimal("-1"), "invalid_value"), (None, "invalid_value"),
                                          (float(1.23), "invalid_value"), (True, "invalid_value"),
                                          (Decimal("NaN"), "invalid_value"), (Decimal("Infinity"), "invalid_value"),
                                          (Decimal("100000000000000000"), "invalid_value"),
                                          (Decimal("1.2345"), "invalid_precision")])
@pytest.mark.django_db
def test_service_rejects_nonfinite_float_missing_negative_or_inexact_values(garage, value, expected):
    with pytest.raises(InventoryWriteError) as error:
        record_baseline(garage.owner, **(reading_values(garage) | {"value": value}))
    assert code(error, "value") == expected and not UsageBaseline.objects.exists()


@pytest.mark.django_db
def test_fractional_ride_count_rejected_by_service_model_and_sql(garage):
    with pytest.raises(InventoryWriteError) as error:
        record(garage, metric="ride_count", value="1.5")
    assert code(error, "value") == "invalid_ride_count"
    obj = UsageBaseline(owner=garage.owner, **reading_values(garage, metric="ride_count", value="1.5"))
    with pytest.raises(ValidationError):
        obj.full_clean()
    with pytest.raises(IntegrityError) as error, transaction.atomic():
        obj.save(force_insert=True)
    assert error.value.__cause__.diag.constraint_name == "garage_baseline_integer_ride_count"


@pytest.mark.parametrize("field,value,constraint", [
    ("metric", "timer_time_s", "garage_baseline_valid_metric"),
    ("scope", "unsupported", "garage_baseline_valid_scope"),
    ("scope", "service", "garage_baseline_service_scope"),
    ("value", Decimal("-0.001"), "garage_baseline_finite_nonnegative_value"),
    ("source", " \t\n", "garage_baseline_source_nonblank"),
    ("cut_at", None, None), ("value", None, None),
])
@pytest.mark.django_db
def test_sql_row_constraints_reject_orm_bypass(garage, field, value, constraint):
    with pytest.raises(IntegrityError) as error, transaction.atomic():
        UsageBaseline.objects.create(owner=garage.owner, **(reading_values(garage) | {field: value}))
    if constraint:
        assert error.value.__cause__.diag.constraint_name == constraint
    assert not UsageBaseline.objects.exists()


@pytest.mark.django_db
def test_sql_rejects_numeric_nan_even_when_python_decimal_validation_is_bypassed(garage):
    baseline = record(garage)
    with pytest.raises(IntegrityError) as error, transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("UPDATE garage_usagebaseline SET value = %s::numeric WHERE id = %s", ["NaN", baseline.pk])
    assert error.value.__cause__.diag.constraint_name == "garage_baseline_finite_nonnegative_value"
    baseline.refresh_from_db()
    assert baseline.value == Decimal("1000000")


@pytest.mark.django_db
def test_sql_unique_reading_and_uuid_protect_existing_rows(garage):
    first = record(garage)
    with pytest.raises(IntegrityError) as error, transaction.atomic():
        UsageBaseline.objects.create(owner=garage.owner, **reading_values(garage, value="42"))
    assert error.value.__cause__.diag.constraint_name == "garage_baseline_unique_reading"
    with pytest.raises(IntegrityError), transaction.atomic():
        UsageBaseline.objects.create(id=first.pk, owner=garage.owner,
                                     **reading_values(garage, metric="moving_time_s", value="42"))
    first.refresh_from_db()
    assert first.value == Decimal("1000000") and UsageBaseline.objects.count() == 1


@pytest.mark.django_db
def test_update_into_existing_key_returns_consistent_error_and_rolls_back(garage):
    first = record(garage)
    second = record(garage, cut=instant(2), value="1030000")
    with pytest.raises(InventoryWriteError) as error:
        update_baseline(garage.owner, second.pk, cut_at=first.cut_at, value="42", notes="Forbidden")
    assert code(error, "cut_at") == "baseline_conflict"
    second.refresh_from_db()
    assert second.cut_at == instant(2) and second.value == Decimal("1030000") and second.notes == ""
    assert not connection.needs_rollback


@pytest.mark.parametrize("operation", ["get", "update", "delete"])
@pytest.mark.django_db
def test_foreign_unknown_and_invalid_baseline_ids_are_indistinguishable(garage, operation):
    original = record(garage)
    errors = []
    for resource_id in (original.pk, uuid.uuid4(), "invalid"):
        with pytest.raises(InventoryNotFound) as error:
            if operation == "get":
                get_inventory(garage.other, UsageBaseline, resource_id)
            elif operation == "update":
                update_baseline(garage.other, resource_id, value="42")
            else:
                delete_baseline(garage.other, resource_id)
        errors.append(str(error.value))
    assert len(set(errors)) == 1
    original.refresh_from_db()
    assert original.value == Decimal("1000000") and original.owner == garage.owner


@pytest.mark.parametrize("field", ["owner", "owner_id", "id", "pk"])
@pytest.mark.parametrize("operation", ["record", "update"])
@pytest.mark.django_db
def test_baseline_owner_and_uuid_are_immutable(garage, field, operation):
    original = record(garage)
    with pytest.raises(InventoryWriteError) as error:
        if operation == "record":
            record_baseline(garage.owner, **(reading_values(garage) | {field: uuid.uuid4()}))
        else:
            update_baseline(garage.owner, original.pk, **{field: uuid.uuid4()})
    assert code(error, field) == "immutable_field"
    original.refresh_from_db()
    assert original.owner == garage.owner and UsageBaseline.objects.count() == 1


@pytest.mark.parametrize("operation", ["record", "update"])
@pytest.mark.django_db
def test_foreign_item_object_with_forged_owner_cannot_authorize_reading(garage, operation):
    original = record(garage)
    garage.foreign.owner = garage.owner
    for reference in (garage.foreign, garage.foreign.pk, str(garage.foreign.pk), uuid.uuid4()):
        with pytest.raises(InventoryWriteError) as error:
            if operation == "record":
                record_baseline(garage.owner, **(reading_values(garage) | {"item": reference}))
            else:
                update_baseline(garage.owner, original.pk, item=reference)
        assert code(error, "item") == "invalid_reference"
    original.refresh_from_db()
    assert original.item == garage.item and UsageBaseline.objects.count() == 1


@pytest.mark.parametrize("operation", ["record", "update", "delete", "latest", "summary"])
@pytest.mark.parametrize("actor", ["anonymous", "inactive"])
@pytest.mark.django_db
def test_baseline_operations_require_active_actor(garage, operation, actor):
    original = record(garage)
    principal = AnonymousUser() if actor == "anonymous" else garage.owner
    if actor == "inactive":
        principal.is_active = False
        principal.save()
    with pytest.raises(PermissionDenied):
        if operation == "record":
            record_baseline(principal, **reading_values(garage))
        elif operation == "update":
            update_baseline(principal, original.pk, value="42")
        elif operation == "delete":
            delete_baseline(principal, original.pk)
        elif operation == "latest":
            latest_baseline(principal, garage.item.pk, metric="distance_m", scope="lifetime", at=instant())
        else:
            summarize_usage(principal, garage.item.pk, metric="distance_m", scope="lifetime", at=instant())
    original.refresh_from_db()
    assert original.value == Decimal("1000000")


@pytest.mark.parametrize("cut", [date(2026, 1, 1), datetime(2026, 1, 1), "2026-01-01T00:00:00Z"])
@pytest.mark.django_db
def test_reading_cut_requires_explicit_datetime_instant(garage, cut):
    with pytest.raises(InventoryWriteError) as error:
        record_baseline(garage.owner, **(reading_values(garage) | {"cut_at": cut}))
    assert code(error, "cut_at") == "invalid_instant"


@pytest.mark.django_db
def test_acquisition_requires_anchor_and_cut_not_before_it(garage):
    update_inventory(garage.owner, Item, garage.item.pk, acquisition_anchor_at=None)
    with pytest.raises(InventoryWriteError) as error:
        record(garage, scope="acquisition")
    assert code(error, "scope") == "acquisition_anchor_required"
    correct_acquisition_anchor(garage.owner, garage.item.pk, at=instant())
    with pytest.raises(InventoryWriteError) as error:
        record(garage, scope="acquisition", cut=instant(31, 12, 2025))
    assert code(error, "cut_at") == "before_acquisition"
    assert record(garage, scope="acquisition", value="0").value == 0


@pytest.mark.parametrize("anchor", [None, instant(3)])
@pytest.mark.django_db
def test_anchor_correction_rejects_orphaned_acquisition_reading_and_rolls_back_all_item_changes(garage, anchor):
    acquisition = record(garage, scope="acquisition", cut=instant(2), value="0")
    old_anchor = garage.item.acquisition_anchor_at
    with pytest.raises(InventoryWriteError) as error:
        update_inventory(garage.owner, Item, garage.item.pk, acquisition_anchor_at=anchor, name="Forbidden")
    assert code(error, "acquisition_anchor_at") == ("acquisition_anchor_in_use" if anchor is None else "baseline_before_anchor")
    garage.item.refresh_from_db()
    acquisition.refresh_from_db()
    assert garage.item.name == "Used helmet" and garage.item.acquisition_anchor_at == old_anchor
    assert acquisition.value == 0 and acquisition.cut_at == instant(2)
    corrected = correct_acquisition_anchor(garage.owner, garage.item.pk, at=instant())
    assert corrected.acquisition_anchor_at == instant()


@pytest.mark.django_db
def test_purchase_date_and_anchor_correction_do_not_reset_lifetime_or_installations(garage):
    from .models import Bike
    from .services.installations import create_installation
    lifetime = record(garage)
    bike = create_inventory(garage.owner, Bike, name="Bike")
    installation = create_installation(garage.owner, item=garage.item, bike=bike, started_at=instant())
    update_inventory(garage.owner, Item, garage.item.pk, acquired_on=date(2026, 4, 1))
    correct_acquisition_anchor(garage.owner, garage.item.pk, at=None)
    lifetime.refresh_from_db()
    installation.refresh_from_db()
    assert lifetime.value == Decimal("1000000") and lifetime.scope == "lifetime"
    assert installation.ended_at is None and installation.started_at == instant()


@pytest.mark.django_db
def test_1000km_cutoff_keeps_prior_observed_history_without_double_counting(garage):
    baseline = record(garage)
    entries = [observation(garage, instant(31, 12, 2025), "70000"), observation(garage, instant(), "20000"),
               observation(garage, instant(2), "30000"), observation(garage, instant(3), "999000")]
    result = summarize_usage(garage.owner, garage.item.pk, metric="distance_m", scope="lifetime", at=instant(3),
                             observations=entries, observations_complete=True)
    assert result.total == Decimal("1050000") and result.observed == Decimal("120000")
    assert result.baseline == baseline and result.known and result.coverage_complete
    assert result.missing_values == 0
    at_cut = summarize_usage(garage.owner, garage.item.pk, metric="distance_m", scope="lifetime", at=instant(), observations=entries)
    assert at_cut.total == Decimal("1000000") and at_cut.coverage_complete
    assert at_cut.observed == Decimal("70000")


@pytest.mark.django_db
def test_latest_snapshot_is_not_added_to_older_snapshots_and_corrections_may_decrease(garage):
    record(garage)
    latest = record(garage, cut=instant(2), value="1030000")
    future = record(garage, cut=instant(4), value="5000000")
    entries = [observation(garage, instant(), "20000"), observation(garage, instant(2), "30000")]
    result = summarize_usage(garage.owner, garage.item.pk, metric="distance_m", scope="lifetime", at=instant(3), observations=entries)
    assert result.total == Decimal("1060000") and result.baseline == latest and not result.coverage_complete
    lowered = record(garage, cut=instant(2), value="990000")
    result = summarize_usage(garage.owner, garage.item.pk, metric="distance_m", scope="lifetime", at=instant(3), observations=entries)
    assert lowered.pk == latest.pk and result.total == Decimal("1020000") and result.baseline != future


@pytest.mark.django_db
def test_future_reading_does_not_invent_totals_before_cut_and_absence_differs_from_explicit_zero(garage):
    record(garage, cut=instant(2))
    entries = [observation(garage, instant(31, 12, 2025), "70000")]
    result = summarize_usage(garage.owner, garage.item.pk, metric="distance_m", scope="lifetime", at=instant(), observations=entries)
    assert result.total is None and not result.known and result.observed == Decimal("70000")
    time = summarize_usage(garage.owner, garage.item.pk, metric="moving_time_s", scope="lifetime", at=instant())
    assert time.total is None and time.observed == 0 and not time.coverage_complete
    explicit = record(garage, metric="moving_time_s", value="0")
    time = summarize_usage(garage.owner, garage.item.pk, metric="moving_time_s", scope="lifetime", at=instant())
    assert time.total == 0 and time.known and time.baseline == explicit and time.coverage_complete


@pytest.mark.django_db
def test_metrics_have_independent_cuts_fractional_seconds_and_unknown_values(garage):
    record(garage)
    record(garage, metric="moving_time_s", cut=instant(2), value="3600.125")
    entries = [observation(garage, instant(), "1800.500", "moving_time_s"),
               observation(garage, instant(2), "900.250", "moving_time_s"),
               observation(garage, instant(2), None, "moving_time_s")]
    result = summarize_usage(garage.owner, garage.item.pk, metric="moving_time_s", scope="lifetime", at=instant(3),
                             observations=entries, observations_complete=True)
    assert result.total == Decimal("4500.375") and result.observed == Decimal("2700.750")
    assert result.missing_values == 1 and not result.coverage_complete
    assert latest_baseline(garage.owner, garage.item.pk, metric="ride_count", scope="lifetime", at=instant(3)) is None


@pytest.mark.django_db
def test_cut_exactness_estimation_and_pre_cut_unknowns_do_not_reduce_empty_window_coverage(garage):
    baseline = record_baseline(garage.owner, **reading_values(garage), is_estimated=True)
    entries = [observation(garage, instant(31, 12, 2025), None)]
    result = summarize_usage(garage.owner, garage.item.pk, metric="distance_m", scope="lifetime", at=instant(), observations=entries)
    assert result.total == baseline.value and result.coverage_complete and result.is_estimated
    assert result.observed_missing_values == 1 and result.missing_values == 0


@pytest.mark.django_db
def test_acquisition_scope_uses_anchor_and_never_reinterprets_lifetime(garage):
    record(garage)
    correct_acquisition_anchor(garage.owner, garage.item.pk, at=instant())
    entries = [observation(garage, instant(31, 12, 2025), "70000"), observation(garage, instant(), "20000")]
    acquired = summarize_usage(garage.owner, garage.item.pk, metric="distance_m", scope="acquisition", at=instant(2), observations=entries)
    assert acquired.observed == Decimal("20000") and acquired.total is None and not acquired.known
    acquisition = record(garage, scope="acquisition", value="0")
    acquired = summarize_usage(garage.owner, garage.item.pk, metric="distance_m", scope="acquisition", at=instant(2), observations=entries)
    assert acquired.total == Decimal("20000") and acquired.baseline == acquisition
    delete_baseline(garage.owner, acquisition.pk)
    correct_acquisition_anchor(garage.owner, garage.item.pk, at=None)
    acquired = summarize_usage(garage.owner, garage.item.pk, metric="distance_m", scope="acquisition", at=instant(2), observations=entries)
    assert acquired.observed is None and acquired.total is None and not acquired.coverage_complete


@pytest.mark.parametrize("bad", ["owner", "item", "metric", "value", "time", "type"])
@pytest.mark.django_db
def test_summary_rejects_noncanonical_foreign_or_mixed_observations(garage, bad):
    entry = observation(garage, instant(), "1")
    data = entry.__dict__.copy()
    if bad == "owner":
        data["owner_id"] = garage.other.pk
    elif bad == "item":
        data["item_id"] = garage.foreign.pk
    elif bad == "metric":
        data["metric"] = "moving_time_s"
    elif bad == "value":
        data["value"] = Decimal("NaN")
    elif bad == "time":
        data["started_at"] = datetime(2026, 1, 1)
    entry = data if bad == "type" else UsageObservation(**data)
    with pytest.raises((PermissionDenied, InventoryWriteError)):
        summarize_usage(garage.owner, garage.item.pk, metric="distance_m", scope="lifetime", at=instant(2), observations=[entry])


@pytest.mark.django_db
def test_delete_and_model_clean_protect_ownership_item_and_generic_write_boundary(garage):
    baseline = record(garage)
    baseline.owner = garage.other
    with pytest.raises(ValidationError) as error:
        baseline.full_clean()
    assert "owner" in error.value.message_dict
    baseline.refresh_from_db()
    baseline.item = garage.foreign
    with pytest.raises(ValidationError) as error:
        baseline.full_clean()
    assert "item" in error.value.message_dict
    with pytest.raises(ValidationError) as error:
        delete_inventory(garage.owner, Item, garage.item.pk)
    assert error.value.code == "resource_protected"
    with pytest.raises(TypeError):
        create_inventory(garage.owner, UsageBaseline, **reading_values(garage))
    delete_baseline(garage.owner, baseline.pk)
    assert not UsageBaseline.objects.exists()


@pytest.mark.django_db
def test_unrecognized_baseline_integrity_error_is_not_hidden(garage):
    error = IntegrityError("synthetic unexpected constraint")
    with patch.object(UsageBaseline, "save", side_effect=error), pytest.raises(IntegrityError) as raised:
        record(garage)
    assert raised.value is error and not connection.needs_rollback
    assert not UsageBaseline.objects.exists()
    assert record(garage).pk


def parallel(operations):
    barrier = Barrier(2)

    def worker(operation):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                return operation()
            except InventoryWriteError as error:
                return next(iter(error.error_dict.values()))[0].code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker, operation) for operation in operations]
        return [future.result(timeout=15) for future in futures]


@pytest.mark.django_db(transaction=True)
def test_concurrent_same_cut_corrections_keep_one_uuid_and_one_reading(garage):
    outcomes = parallel([lambda: record(garage, value="1000000"), lambda: record(garage, value="990000")])
    assert all(isinstance(result, UsageBaseline) for result in outcomes)
    assert outcomes[0].pk == outcomes[1].pk and UsageBaseline.objects.count() == 1
    assert UsageBaseline.objects.get().value in (Decimal("1000000"), Decimal("990000"))


@pytest.mark.django_db(transaction=True)
def test_concurrent_anchor_correction_and_acquisition_reading_preserve_anchor_invariant(garage):
    correct_acquisition_anchor(garage.owner, garage.item.pk, at=instant())
    outcomes = parallel([
        lambda: correct_acquisition_anchor(garage.owner, garage.item.pk, at=instant(3)),
        lambda: record(garage, scope="acquisition", cut=instant(2), value="0"),
    ])
    assert sum(isinstance(result, (Item, UsageBaseline)) for result in outcomes) == 1
    assert sum(result in ("before_acquisition", "baseline_before_anchor") for result in outcomes if isinstance(result, str)) == 1
    garage.item.refresh_from_db()
    readings = list(scoped_inventory(garage.owner, UsageBaseline))
    assert len(readings) <= 1
    if readings:
        assert garage.item.acquisition_anchor_at == instant() <= readings[0].cut_at
    else:
        assert garage.item.acquisition_anchor_at == instant(3)


@pytest.mark.parametrize("changes", [{"metric": "ride_count"}, {"scope": "acquisition"}])
@pytest.mark.django_db
def test_partial_update_validates_unchanged_value_and_item(garage, changes):
    if "scope" in changes:
        update_inventory(garage.owner, Item, garage.item.pk, acquisition_anchor_at=None)
    reading = record(garage, metric="moving_time_s", value="1.250")
    with pytest.raises(ValidationError):
        update_baseline(garage.owner, reading.pk, **changes)
    reading.refresh_from_db()
    assert reading.metric == "moving_time_s" and reading.scope == "lifetime" and reading.value == Decimal("1.250")
