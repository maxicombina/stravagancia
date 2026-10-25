from datetime import datetime, timezone as datetime_timezone
from decimal import Decimal
import uuid

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError

from .models import Category, Item, ItemUsage, UsageMaterializationState
from .services.baselines import record_baseline
from .services.ownership import InventoryNotFound, create_inventory, update_inventory
from .services.rides import correct_ride, create_manual_ride, import_fit_session, withdraw_source
from .services.usage import summarize_item_usage
from .tests_usage_materialization import instant, profile, ride, usage
from .validators import MAX_USAGE_VALUE


def baseline(usage, metric="distance_m", scope="lifetime", cut=None, value="1000000", **values):
    return record_baseline(usage.owner, item=usage.helmet, metric=metric, scope=scope,
                           cut_at=cut or instant(5), value=Decimal(value), **values)


def total(usage, *, metric="distance_m", scope="lifetime", at=None):
    return summarize_item_usage(usage.owner, usage.helmet.pk, metric=metric, scope=scope, at=at or instant(20))


@pytest.mark.django_db
def test_baseline_1000km_cut_excludes_older_usages_and_counts_cut_exactly_once(usage):
    profile(usage)
    create_manual_ride(usage.owner, started_at=instant(4), distance_m="70000")
    create_manual_ride(usage.owner, started_at=instant(5), distance_m="20000")
    create_manual_ride(usage.owner, started_at=instant(6), distance_m="30000")
    create_manual_ride(usage.owner, started_at=instant(20), distance_m="90000")
    baseline(usage)
    result = total(usage).reading
    assert result.observed == Decimal("120000") and result.total == Decimal("1050000")
    assert result.missing_values == 0 and not result.coverage_complete
    assert ItemUsage.objects.count() == 4


@pytest.mark.django_db
def test_latest_cut_is_metric_specific_two_readings_are_not_added_and_future_is_ignored(usage):
    profile(usage)
    create_manual_ride(usage.owner, started_at=instant(6), distance_m="10000", moving_time_s="1.234")
    create_manual_ride(usage.owner, started_at=instant(10), distance_m="20000", moving_time_s="2.345")
    baseline(usage, cut=instant(5), value="1000000")
    latest = baseline(usage, cut=instant(8), value="800000")
    baseline(usage, cut=instant(25), value="900000")
    baseline(usage, metric="moving_time_s", cut=instant(5), value="100.001")
    assert total(usage).reading.baseline.pk == latest.pk and total(usage).reading.total == Decimal("820000")
    assert total(usage, metric="moving_time_s").reading.total == Decimal("103.580")
    corrected = baseline(usage, cut=instant(8), value="700000")
    assert corrected.pk == latest.pk and total(usage).reading.total == Decimal("720000")


@pytest.mark.django_db
def test_exact_baseline_cut_has_empty_contribution_window_and_estimation_is_separate(usage):
    profile(usage)
    create_manual_ride(usage.owner, started_at=instant(4), moving_time_s=None)
    create_manual_ride(usage.owner, started_at=instant(5), moving_time_s="1.234")
    reading = baseline(usage, metric="moving_time_s", value="100.123", is_estimated=True)
    result = total(usage, metric="moving_time_s", at=instant(5)).reading
    assert result.total == reading.value == Decimal("100.123") and result.coverage_complete and result.is_estimated
    assert result.missing_values == 0 and result.observed_missing_values == 1


@pytest.mark.django_db
def test_unknown_metrics_and_confirmed_zero_are_distinct_and_ride_count_is_integer(usage):
    profile(usage)
    first = create_manual_ride(usage.owner, started_at=instant(6), distance_m="0", timer_time_s="9.876")
    second = create_manual_ride(usage.owner, started_at=instant(7), distance_m=None, moving_time_s=None)
    baseline(usage, metric="moving_time_s", value="0")
    baseline(usage, value="0")
    baseline(usage, metric="ride_count", value="0")
    distance, moving, rides = [total(usage, metric=metric).reading for metric in ("distance_m", "moving_time_s", "ride_count")]
    assert distance.observed == distance.total == Decimal("0") and distance.missing_values == 1
    assert moving.observed == moving.total == Decimal("0") and moving.missing_values == 2
    assert not distance.coverage_complete and not moving.coverage_complete
    assert rides.observed == rides.total == Decimal("2") and rides.missing_values == 0 and not rides.coverage_complete
    assert ItemUsage.objects.get(ride=first).moving_time_s is None


@pytest.mark.django_db
def test_no_baseline_means_observed_not_lifetime_total_and_missing_baseline_per_metric(usage):
    profile(usage)
    create_manual_ride(usage.owner, started_at=instant(6), distance_m="123.456", moving_time_s="1.234")
    distance = total(usage).reading
    assert distance.observed == Decimal("123.456") and distance.total is None and not distance.known
    baseline(usage, metric="distance_m", value="0")
    assert total(usage, metric="moving_time_s").reading.total is None
    assert total(usage, metric="moving_time_s").reading.observed == Decimal("1.234")


@pytest.mark.django_db
def test_acquisition_anchor_bounds_observed_window_and_never_relabels_lifetime(usage):
    profile(usage)
    create_manual_ride(usage.owner, started_at=instant(4), distance_m="100")
    create_manual_ride(usage.owner, started_at=instant(6), distance_m="200")
    assert total(usage, scope="acquisition").reading.observed is None
    assert total(usage, scope="acquisition").reading.total is None
    update_inventory(usage.owner, Item, usage.helmet.pk, acquisition_anchor_at=instant(5))
    baseline(usage, scope="acquisition", value="1000")
    assert total(usage, scope="acquisition").reading.observed == Decimal("200")
    assert total(usage, scope="acquisition").reading.total == Decimal("1200")
    assert total(usage).reading.observed == Decimal("300")


@pytest.mark.django_db
def test_totals_can_exceed_individual_decimal_field_without_rounding_or_overflow(usage):
    profile(usage)
    for day in (6, 7, 8):
        create_manual_ride(usage.owner, started_at=instant(day), distance_m=MAX_USAGE_VALUE, moving_time_s=MAX_USAGE_VALUE)
    baseline(usage, value=str(MAX_USAGE_VALUE))
    baseline(usage, metric="moving_time_s", value=str(MAX_USAGE_VALUE))
    expected_observed = Decimal("299999999999999999.997")
    expected_total = Decimal("399999999999999999.996")
    for metric in ("distance_m", "moving_time_s"):
        result = total(usage, metric=metric).reading
        assert result.observed == expected_observed and result.total == expected_total
        assert result.total > MAX_USAGE_VALUE


@pytest.mark.django_db
def test_pending_start_and_unknown_bike_are_separate_owner_context_not_fabricated_usage(usage):
    profile(usage)
    own = create_manual_ride(usage.owner, started_at=instant(6), distance_m="100")
    pending, source = import_fit_session(usage.owner, file_hash="a" * 64, session_index=0, parser_version="fixture-1",
                                       observations={"started_at": instant(7), "distance_m": "200"})
    withdraw_source(usage.owner, source.pk)
    foreign, foreign_source = import_fit_session(usage.other, file_hash="b" * 64, session_index=0, parser_version="fixture-1",
                                               observations={"started_at": instant(7)})
    withdraw_source(usage.other, foreign_source.pk)
    result = total(usage)
    assert result.owner_pending_started_rides == result.owner_unknown_bike_rides == 1
    assert result.reading.observed == Decimal("100") and result.reading.total is None
    assert not ItemUsage.objects.filter(ride=pending).exists()


@pytest.mark.parametrize("field,value", [("metric", "timer_time_s"), ("scope", "service"),
                                         ("at", datetime(2026, 1, 20)), ("metric", [])])
@pytest.mark.django_db
def test_summary_rejects_unsupported_metrics_scopes_and_naive_instants(field, value, usage):
    values = {"metric": "distance_m", "scope": "lifetime", "at": instant(20), field: value}
    with pytest.raises(ValidationError):
        summarize_item_usage(usage.owner, usage.helmet.pk, **values)


@pytest.mark.django_db
def test_summary_has_no_arbitrary_complete_flag_or_synthetic_observation_override(usage):
    with pytest.raises(TypeError):
        summarize_item_usage(usage.owner, usage.helmet.pk, metric="distance_m", scope="lifetime", at=instant(20), observations_complete=True)


@pytest.mark.django_db
def test_summary_requires_active_owner_and_uniform_item_lookup(usage, django_user_model):
    category = create_inventory(usage.other, Category, name="Parts")
    foreign = create_inventory(usage.other, Item, name="Foreign", category=category)
    for item_id in (foreign.pk, uuid.uuid4(), "bad"):
        with pytest.raises(InventoryNotFound):
            summarize_item_usage(usage.owner, item_id, metric="distance_m", scope="lifetime", at=instant(20))
    for actor in (AnonymousUser(), django_user_model(username="unsaved")):
        with pytest.raises(PermissionDenied):
            summarize_item_usage(actor, usage.helmet.pk, metric="distance_m", scope="lifetime", at=instant(20))


@pytest.mark.django_db
def test_preexisting_ride_empty_materialization_is_unknown_until_explicit_rebuild(usage):
    profile(usage)
    own = create_manual_ride(usage.owner, started_at=instant(6), distance_m="123.456")
    ItemUsage.objects.filter(ride=own).delete()
    UsageMaterializationState.objects.filter(owner=usage.owner).delete()
    baseline(usage, value="1000")
    pending = total(usage)
    assert not pending.materialization_current and pending.reading.observed is None and pending.reading.total is None
    assert not pending.reading.coverage_complete and not ItemUsage.objects.exists()
    from .services.usage import rebuild_usage
    rebuilt = rebuild_usage(usage.owner)
    assert rebuilt.created == 1
    ready = total(usage)
    assert ready.materialization_current and ready.reading.observed == Decimal("123.456")
    assert ready.reading.total == Decimal("1123.456") and not ready.reading.coverage_complete


@pytest.mark.django_db
def test_exact_cut_keeps_baseline_reading_but_empty_preexisting_cache_is_still_unknown_observed(usage):
    profile(usage)
    own = create_manual_ride(usage.owner, started_at=instant(4), distance_m="123.456")
    ItemUsage.objects.filter(ride=own).delete()
    UsageMaterializationState.objects.filter(owner=usage.owner).delete()
    baseline(usage, value="1000")
    result = total(usage, at=instant(5))
    assert not result.materialization_current and result.reading.observed is None
    assert result.reading.total == Decimal("1000") and result.reading.coverage_complete
