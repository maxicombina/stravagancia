from datetime import date, datetime
import uuid

import pytest
from django.core.exceptions import ValidationError

from django.db import connection
from .models import ItemUsage, Ride, UsageMaterializationState
from .services.ownership import InventoryNotFound
from .services.rides import correct_ride, create_manual_ride
from .services.usage import rebuild_ride_usage, rebuild_usage
from .services.usage_profiles import set_usage_override
from .tests_usage_materialization import instant, profile, ride, usage


@pytest.mark.django_db
def test_interval_rebuild_selects_union_of_current_and_stored_start_and_removes_all_stale_items(usage):
    own_profile = profile(usage, [usage.helmet, usage.shoes], ended_at=instant(10))
    own = ride(usage, 5)
    unrelated = ride(usage, 6)
    original = {fact.item_id: fact.pk for fact in ItemUsage.objects.filter(ride=own)}
    # Simulate data pending reconstruction rather than using the trusted service,
    # whose explicit hook already fixes this movement in the same transaction.
    Ride.objects.filter(pk=own.pk).update(started_at=instant(15))
    result = rebuild_usage(usage.owner, started_from=instant(4), started_to=instant(6))
    assert len(result.plans) == 1 and result.plans[0].ride_id == own.pk
    assert result.deleted == 2 and not ItemUsage.objects.filter(ride=own).exists()
    assert set(ItemUsage.objects.filter(ride=unrelated).values_list("item_id", flat=True)) == set(original)


@pytest.mark.django_db
def test_moved_outside_window_updates_complete_ride_facts_with_new_start_and_preserves_identity(usage):
    profile(usage)
    own = ride(usage, 5)
    fact = ItemUsage.objects.get()
    initial_id = fact.pk
    Ride.objects.filter(pk=own.pk).update(started_at=instant(15), distance_m="30000")
    result = rebuild_usage(usage.owner, started_from=instant(4), started_to=instant(6))
    fact.refresh_from_db()
    assert result.updated == 1 and fact.started_at == instant(15) and fact.distance_m == 30000 and fact.pk == initial_id
    assert rebuild_usage(usage.owner, started_from=instant(4), started_to=instant(6)).plans == ()


@pytest.mark.django_db
def test_ride_moved_into_window_is_selected_even_when_old_snapshot_is_outside(usage):
    profile(usage)
    own = ride(usage, 15)
    Ride.objects.filter(pk=own.pk).update(started_at=instant(5))
    result = rebuild_usage(usage.owner, started_from=instant(4), started_to=instant(6))
    assert result.updated == 1 and ItemUsage.objects.get().started_at == instant(5)


@pytest.mark.django_db
def test_pending_start_residual_is_cleaned_even_when_its_old_start_is_outside_window(usage):
    profile(usage)
    own = ride(usage, 5)
    Ride.objects.filter(pk=own.pk).update(started_at=None)
    result = rebuild_usage(usage.owner, started_from=instant(15), started_to=instant(16))
    assert result.deleted == 1 and result.plans[0].unknown_started_at and not ItemUsage.objects.exists()
    assert rebuild_usage(usage.owner, started_from=instant(15), started_to=instant(16)).plans == ()


@pytest.mark.django_db
def test_dry_run_plans_create_update_delete_and_leaves_every_row_unchanged(usage, monkeypatch):
    profile(usage)
    first, second, third = ride(usage, 4), ride(usage, 5), ride(usage, 6)
    ItemUsage.objects.filter(ride=first).delete()
    Ride.objects.filter(pk=second.pk).update(distance_m="30000")
    Ride.objects.filter(pk=third.pk).update(started_at=None)
    models = (Ride, ItemUsage, UsageMaterializationState)
    before = {model: list(model.objects.order_by("pk").values()) for model in models}
    def forbidden(*args, **kwargs):
        raise AssertionError("Dry-run called a model write")
    original_save = ItemUsage.save
    monkeypatch.setattr(ItemUsage, "save", forbidden)
    def forbid_sql_write(execute, sql, params, many, context):
        assert sql.lstrip().split()[0].upper() not in {"INSERT", "UPDATE", "DELETE", "MERGE", "TRUNCATE", "ALTER"}, sql
        return execute(sql, params, many, context)
    with connection.execute_wrapper(forbid_sql_write):
        result = rebuild_usage(usage.owner, dry_run=True)
    assert result.created == result.updated == result.deleted == 1 and result.dry_run
    assert before == {model: list(model.objects.order_by("pk").values()) for model in models}
    monkeypatch.setattr(ItemUsage, "save", original_save)
    executed = rebuild_usage(usage.owner)
    assert executed.plans == result.plans and not executed.dry_run
    assert not ItemUsage.objects.filter(ride=third).exists()


@pytest.mark.django_db
def test_single_ride_dry_run_is_read_only_and_repeat_apply_is_noop(usage):
    profile(usage)
    own = ride(usage)
    ItemUsage.objects.filter(ride=own).delete()
    planned = rebuild_ride_usage(usage.owner, own.pk, dry_run=True)
    assert planned.create_item_ids == {usage.helmet.pk} and not ItemUsage.objects.exists()
    applied = rebuild_ride_usage(usage.owner, own.pk)
    assert applied == planned
    fact = ItemUsage.objects.get()
    timestamp = fact.updated_at
    repeated = rebuild_ride_usage(usage.owner, own.pk)
    fact.refresh_from_db()
    assert repeated.unchanged_item_ids == {usage.helmet.pk} and fact.updated_at == timestamp


@pytest.mark.django_db
def test_range_boundaries_select_start_inclusive_end_exclusive(usage):
    profile(usage)
    own_rides = [ride(usage, day) for day in (4, 5, 6)]
    result = rebuild_usage(usage.owner, started_from=instant(5), started_to=instant(6), dry_run=True)
    assert tuple(plan.ride_id for plan in result.plans) == (own_rides[1].pk,)
    lower_only = rebuild_usage(usage.owner, started_from=instant(5), dry_run=True)
    upper_only = rebuild_usage(usage.owner, started_to=instant(5), dry_run=True)
    assert {plan.ride_id for plan in lower_only.plans} == {own.pk for own in own_rides[1:]}
    assert {plan.ride_id for plan in upper_only.plans} == {own_rides[0].pk}


@pytest.mark.parametrize("field,value", [("started_from", date(2026, 1, 1)), ("started_to", datetime(2026, 1, 6)),
                                         ("started_from", "2026-01-01T00:00:00Z"), ("dry_run", "true")])
@pytest.mark.django_db
def test_rebuild_rejects_untyped_naive_instants_and_nonbool_dry_run(field, value, usage):
    with pytest.raises(ValidationError):
        rebuild_usage(usage.owner, **{field: value})
    assert not ItemUsage.objects.exists()


@pytest.mark.parametrize("end", [instant(5), instant(4)])
@pytest.mark.django_db
def test_rebuild_range_must_be_positive(end, usage):
    with pytest.raises(ValidationError):
        rebuild_usage(usage.owner, started_from=instant(5), started_to=end)


@pytest.mark.parametrize("kind", ["foreign", "missing", "malformed"])
@pytest.mark.django_db
def test_single_ride_rebuild_uses_uniform_scoped_lookup(kind, usage):
    foreign = create_manual_ride(usage.other, started_at=instant(5))
    ride_id = foreign.pk if kind == "foreign" else uuid.uuid4() if kind == "missing" else "bad"
    with pytest.raises(InventoryNotFound):
        rebuild_ride_usage(usage.owner, ride_id)
    assert rebuild_usage(usage.owner).plans == ()


@pytest.mark.django_db
def test_rebuild_locks_rides_in_uuid_order_and_never_reads_another_owner(usage, monkeypatch):
    own = [ride(usage, day) for day in (4, 5, 6)]
    foreign = create_manual_ride(usage.other, started_at=instant(5))
    from .services import usage as engine
    observed = []
    original = engine._rebuild_locked
    def capture(owner, own_rides, **kwargs):
        observed.extend(own_ride.pk for own_ride in own_rides)
        assert all(own_ride.owner_id == usage.owner.pk for own_ride in own_rides)
        return original(owner, own_rides, **kwargs)
    monkeypatch.setattr(engine, "_rebuild_locked", capture)
    rebuild_usage(usage.owner)
    assert observed == sorted(own_ride.pk for own_ride in own) and foreign.pk not in observed


@pytest.mark.django_db
def test_partial_and_dry_rebuild_never_initialize_global_marker_even_for_singleton(usage):
    profile(usage)
    own = ride(usage)
    UsageMaterializationState.objects.filter(owner=usage.owner).delete()
    ItemUsage.objects.filter(ride=own).delete()
    for dry_run in (True, False):
        rebuild_usage(usage.owner, started_from=instant(4), started_to=instant(6), dry_run=dry_run)
        assert not UsageMaterializationState.objects.filter(owner=usage.owner).exists()
    rebuild_ride_usage(usage.owner, own.pk, dry_run=True)
    assert not UsageMaterializationState.objects.filter(owner=usage.owner).exists()
    rebuild_ride_usage(usage.owner, own.pk)
    assert UsageMaterializationState.objects.get(owner=usage.owner).initialized_at is not None


@pytest.mark.django_db
def test_single_ride_of_multiple_preexisting_rides_does_not_initialize_owner(usage):
    profile(usage)
    first, second = ride(usage, 4), ride(usage, 6)
    UsageMaterializationState.objects.filter(owner=usage.owner).delete()
    ItemUsage.objects.all().delete()
    rebuild_ride_usage(usage.owner, first.pk)
    assert not UsageMaterializationState.objects.filter(owner=usage.owner).exists()
    rebuild_usage(usage.owner)
    assert UsageMaterializationState.objects.get(owner=usage.owner).initialized_at is not None
    assert ItemUsage.objects.count() == 2


@pytest.mark.django_db
def test_empty_full_rebuild_initializes_owner_and_noop_preserves_marker_timestamp(usage):
    result = rebuild_usage(usage.owner)
    assert result.plans == ()
    marker = UsageMaterializationState.objects.get(owner=usage.owner)
    timestamps = marker.initialized_at, marker.updated_at
    rebuild_usage(usage.owner)
    marker.refresh_from_db()
    assert (marker.initialized_at, marker.updated_at) == timestamps
