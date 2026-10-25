from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone as datetime_timezone
from decimal import Decimal
from threading import Barrier
from types import SimpleNamespace
import uuid

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.models.deletion import ProtectedError

from .models import Bike, Category, Installation, Item, ItemUsage, Ride, UsageProfile
from .services.installations import (create_installation, delete_installation, replace_installation, transfer_installation,
                                     update_installation)
from .services.ownership import (InventoryNotFound, correct_retirement, create_inventory, get_inventory,
                                 reactivate_inventory, retire_inventory, scoped_inventory)
from .services.rides import (correct_ride, create_manual_ride, delete_ride, import_fit_session, withdraw_source)
from .services.usage import rebuild_ride_usage, rebuild_usage
from .services.usage_profiles import (create_profile_history, delete_profile_history, delete_usage_override,
                                      revise_profile, revise_profile_history, set_usage_override, update_profile_history)
from .validators import MAX_USAGE_VALUE


def instant(day=1):
    return datetime(2026, 1, day, tzinfo=datetime_timezone.utc)


@pytest.fixture
def usage(db, django_user_model):
    owner = django_user_model.objects.create_user(username="usage-owner")
    other = django_user_model.objects.create_user(username="usage-other")
    category = create_inventory(owner, Category, name="Parts")
    items = {name: create_inventory(owner, Item, name=name, category=category) for name in ("helmet", "shoes", "cleat", "a", "b")}
    return SimpleNamespace(owner=owner, other=other, bike=create_inventory(owner, Bike, name="Bike1"),
                           second_bike=create_inventory(owner, Bike, name="Bike2"), **items)


def profile(usage, items=None, **values):
    return create_profile_history(usage.owner, name="Default", items=items or [usage.helmet], started_at=instant(), **values)


def ride(usage, day=5, **values):
    return create_manual_ride(usage.owner, started_at=instant(day), distance_m=Decimal("25000"), **values)


@pytest.mark.django_db
def test_effective_usage_is_one_row_per_item_ride_with_exact_metrics_and_resolution(usage):
    profile(usage, [usage.shoes, usage.cleat])
    create_installation(usage.owner, item=usage.cleat, parent_item=usage.shoes, started_at=instant())
    own = ride(usage, moving_time_s="120.123", timer_time_s="130.456", elapsed_time_s="150.001", bike=usage.bike)
    set_usage_override(usage.owner, ride=own, item=usage.shoes, action="include")
    facts = list(ItemUsage.objects.filter(ride=own))
    assert {fact.item_id for fact in facts} == {usage.shoes.pk, usage.cleat.pk} and len(facts) == 2
    for fact in facts:
        assert fact.owner == usage.owner and fact.started_at == own.started_at and fact.bike == usage.bike
        assert fact.distance_m == Decimal("25000") and fact.ride_count == 1
        assert fact.moving_time_s == Decimal("120.123") and fact.timer_time_s == Decimal("130.456")
        assert fact.elapsed_time_s == Decimal("150.001") and fact.field_provenance == own.field_provenance
        assert {reason["kind"] for reason in fact.resolution} == {"profile", "manual_include"}
    assert len(ItemUsage.objects.get(item=usage.cleat).resolution) == 3


@pytest.mark.django_db
def test_a_b_a_installation_history_accumulates_once_and_unmounted_gap_does_not_count(usage):
    create_installation(usage.owner, item=usage.a, bike=usage.bike, started_at=instant(), ended_at=instant(10))
    create_installation(usage.owner, item=usage.b, bike=usage.bike, started_at=instant(10), ended_at=instant(20))
    create_installation(usage.owner, item=usage.a, bike=usage.bike, started_at=instant(20))
    for day, distance in [(5, "30000"), (10, "40000"), (20, "50000")]:
        create_manual_ride(usage.owner, started_at=instant(day), bike=usage.bike, distance_m=Decimal(distance))
    assert sum(fact.distance_m for fact in ItemUsage.objects.filter(item=usage.a)) == Decimal("80000")
    assert sum(fact.distance_m for fact in ItemUsage.objects.filter(item=usage.b)) == Decimal("40000")
    assert ItemUsage.objects.filter(item=usage.a).count() == 2 and ItemUsage.objects.filter(item=usage.b).count() == 1
    create_manual_ride(usage.owner, started_at=instant(19), bike=usage.second_bike, distance_m="90000")
    assert ItemUsage.objects.count() == 3


@pytest.mark.django_db
def test_shared_helmet_two_bikes_is_one_object_and_two_uses_even_with_manual_include(usage):
    profile(usage, bike=usage.bike)
    profile(usage, bike=usage.second_bike)
    first = ride(usage, bike=usage.bike)
    second = create_manual_ride(usage.owner, started_at=instant(6), bike=usage.second_bike, distance_m="35000")
    set_usage_override(usage.owner, ride=first, item=usage.helmet, action="include")
    assert ItemUsage.objects.filter(item=usage.helmet).count() == 2
    assert sum(fact.distance_m for fact in ItemUsage.objects.all()) == Decimal("60000")
    assert set(ItemUsage.objects.values_list("ride_id", flat=True)) == {first.pk, second.pk}


@pytest.mark.django_db
def test_reimport_and_rebuild_noop_preserve_usage_uuid_and_updated_at(usage):
    profile(usage)
    own, source = import_fit_session(usage.owner, file_hash="a" * 64, session_index=0, parser_version="fixture-1",
        observations={"started_at": instant(5), "distance_m": "1.2300", "timer_time_s": "2.345"})
    fact = ItemUsage.objects.get()
    identity, updated = fact.pk, fact.updated_at
    for _ in range(2):
        repeated, _ = import_fit_session(usage.owner, file_hash="a" * 64, session_index=0, parser_version="fixture-1",
            observations={"started_at": instant(5), "distance_m": "1.230", "timer_time_s": "2.345"})
        result = rebuild_usage(usage.owner)
        assert result.created == result.updated == result.deleted == 0 and result.unchanged == 1
    fact.refresh_from_db()
    assert fact.pk == identity and fact.updated_at == updated
    assert fact.timer_time_s == Decimal("2.345") and fact.moving_time_s is None


@pytest.mark.django_db
def test_ride_date_bike_metric_and_modality_changes_rebuild_whole_effective_set(usage):
    profile(usage, [usage.helmet])
    profile(usage, [usage.shoes], bike=usage.bike, sport_type="cycling")
    create_installation(usage.owner, item=usage.a, bike=usage.bike, started_at=instant(), ended_at=instant(10))
    own = ride(usage, bike=usage.bike, sport_type="cycling")
    helmet_id = ItemUsage.objects.get(item=usage.helmet).pk
    corrected = correct_ride(usage.owner, own.pk, started_at=instant(15), bike=usage.second_bike,
                             distance_m=None, sport_type="running", moving_time_s="3.210")
    fact = ItemUsage.objects.get()
    assert fact.pk == helmet_id and fact.item == usage.helmet and fact.ride_id == own.pk
    assert fact.started_at == instant(15) and fact.bike == usage.second_bike and fact.distance_m is None
    assert fact.moving_time_s == Decimal("3.210") and fact.field_provenance == corrected.field_provenance


@pytest.mark.django_db
def test_source_withdrawal_removes_retired_provenance_and_unknown_start_residue(usage):
    profile(usage)
    own, first = import_fit_session(usage.owner, file_hash="a" * 64, session_index=0, parser_version="fixture-1",
                                  observations={"started_at": instant(5), "distance_m": "100"})
    own, second = import_fit_session(usage.owner, file_hash="b" * 64, session_index=0, parser_version="fixture-1", ride_id=own.pk,
                                   observations={"started_at": instant(6), "distance_m": "200", "moving_time_s": "1.001"})
    withdraw_source(usage.owner, second.pk)
    fact = ItemUsage.objects.get()
    assert fact.distance_m == Decimal("100") and fact.moving_time_s is None and fact.started_at == instant(5)
    assert str(second.pk) not in str(fact.field_provenance)
    withdraw_source(usage.owner, first.pk)
    assert not ItemUsage.objects.exists() and Ride.objects.get().started_at is None


@pytest.mark.django_db
def test_manual_known_start_and_null_metric_survive_source_withdrawal(usage):
    profile(usage)
    own, source = import_fit_session(usage.owner, file_hash="a" * 64, session_index=0, parser_version="fixture-1",
                                   observations={"started_at": instant(5), "distance_m": "100"})
    correct_ride(usage.owner, own.pk, started_at=instant(5), distance_m=None)
    withdraw_source(usage.owner, source.pk)
    fact = ItemUsage.objects.get()
    assert fact.started_at == instant(5) and fact.distance_m is None and fact.ride_count == 1
    assert fact.field_provenance["distance_m"]["kind"] == "manual"


@pytest.mark.django_db
def test_installation_replace_transfer_edit_delete_hooks_refresh_usage_after_complete_mutation(usage):
    first = create_installation(usage.owner, item=usage.a, bike=usage.bike, started_at=instant())
    before = ride(usage, 4, bike=usage.bike)
    after = ride(usage, 6, bike=usage.bike)
    assert ItemUsage.objects.filter(item=usage.a).count() == 2
    _, successor = replace_installation(usage.owner, first.pk, incoming_item=usage.b, at=instant(5))
    assert ItemUsage.objects.get(ride=before).item == usage.a and ItemUsage.objects.get(ride=after).item == usage.b
    _, transferred = transfer_installation(usage.owner, successor.pk, at=instant(7), bike=usage.second_bike)
    at_other = ride(usage, 8, bike=usage.second_bike)
    assert ItemUsage.objects.get(ride=at_other).item == usage.b
    update_installation(usage.owner, transferred.pk, started_at=instant(9))
    assert not ItemUsage.objects.filter(ride=at_other).exists()
    delete_installation(usage.owner, successor.pk)
    assert not ItemUsage.objects.filter(ride=after).exists() and ItemUsage.objects.get(ride=before).item == usage.a


@pytest.mark.django_db
def test_profile_revision_update_delete_and_override_reset_hooks_preserve_ordinary_past(usage):
    original = profile(usage)
    before, after = ride(usage, 4), ride(usage, 6)
    old_id = ItemUsage.objects.get(ride=before).pk
    successor = revise_profile_history(usage.owner, original.pk, at=instant(5), items=[usage.shoes])
    assert ItemUsage.objects.get(ride=before).pk == old_id and ItemUsage.objects.get(ride=after).item == usage.shoes
    update_profile_history(usage.owner, successor.pk, items=[usage.cleat])
    assert ItemUsage.objects.get(ride=after).item == usage.cleat
    override = set_usage_override(usage.owner, ride=after, item=usage.cleat, action="exclude")
    assert not ItemUsage.objects.filter(ride=after).exists()
    delete_usage_override(usage.owner, override.pk)
    assert ItemUsage.objects.get(ride=after).item == usage.cleat
    delete_profile_history(usage.owner, successor.pk)
    assert not ItemUsage.objects.filter(ride=after).exists() and ItemUsage.objects.get(ride=before).pk == old_id


@pytest.mark.django_db
def test_ordinary_profile_revision_refreshes_future_usage_without_rewriting_past_snapshot(usage, monkeypatch):
    from .services import usage_profiles

    monkeypatch.setattr(usage_profiles.timezone, "now", lambda: instant(10))
    original = profile(usage)
    before, after = ride(usage, 5), ride(usage, 12)
    previous_fact = ItemUsage.objects.get(ride=before)
    previous_identity, previous_updated_at = previous_fact.pk, previous_fact.updated_at

    revise_profile(usage.owner, original.pk, items=[usage.shoes])

    previous_fact.refresh_from_db()
    assert previous_fact.pk == previous_identity and previous_fact.updated_at == previous_updated_at
    assert ItemUsage.objects.get(ride=before).item == usage.helmet
    assert ItemUsage.objects.get(ride=after).item == usage.shoes


@pytest.mark.django_db
def test_retirement_reactivation_gap_and_explicit_correction_hooks_keep_history_reproducible(usage):
    profile(usage)
    before, during, after = [ride(usage, day) for day in (4, 6, 10)]
    retire_inventory(usage.owner, Item, usage.helmet.pk, at=instant(5))
    assert set(ItemUsage.objects.values_list("ride_id", flat=True)) == {before.pk}
    reactivate_inventory(usage.owner, Item, usage.helmet.pk, at=instant(10))
    assert set(ItemUsage.objects.values_list("ride_id", flat=True)) == {before.pk, after.pk}
    correct_retirement(usage.owner, Item, usage.helmet.pk, retired_at=instant(10))
    assert set(ItemUsage.objects.values_list("ride_id", flat=True)) == {before.pk}
    correct_retirement(usage.owner, Item, usage.helmet.pk, retired_at=None)
    assert set(ItemUsage.objects.values_list("ride_id", flat=True)) == {before.pk, after.pk}
    assert not ItemUsage.objects.filter(ride=during).exists()


@pytest.mark.django_db
def test_delete_ride_cascades_only_its_usages_and_never_deletes_inventory_or_foreign_data(usage):
    profile(usage)
    own = ride(usage)
    foreign_category = create_inventory(usage.other, Category, name="Parts")
    foreign_item = create_inventory(usage.other, Item, name="Foreign", category=foreign_category)
    create_profile_history(usage.other, name="Foreign", items=[foreign_item], started_at=instant())
    foreign_ride = create_manual_ride(usage.other, started_at=instant(5), distance_m="500")
    delete_ride(usage.owner, own.pk)
    assert not ItemUsage.objects.filter(ride=own).exists() and ItemUsage.objects.get().ride_id == foreign_ride.pk
    assert Item.objects.filter(pk=usage.helmet.pk).exists()


@pytest.mark.parametrize("field", ["distance_m", "moving_time_s", "timer_time_s", "elapsed_time_s"])
@pytest.mark.parametrize("value", [Decimal("-1"), Decimal("NaN")])
@pytest.mark.django_db
def test_usage_database_metric_checks_reject_negative_and_nan(field, value, usage):
    profile(usage)
    own = ride(usage)
    with pytest.raises(IntegrityError) as error:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(f'UPDATE garage_itemusage SET "{field}" = %s WHERE ride_id = %s', [value, own.pk])
    assert error.value.__cause__.diag.constraint_name == f"garage_itemusage_{field}_valid"


@pytest.mark.django_db
def test_usage_database_uniqueness_one_ride_count_and_uuid_identity(usage):
    profile(usage)
    own = ride(usage)
    fact = ItemUsage.objects.get()
    values = {field.name: getattr(fact, field.name) for field in fact._meta.fields if field.name not in {"id", "created_at", "updated_at"}}
    with pytest.raises(IntegrityError) as error:
        with transaction.atomic():
            ItemUsage.objects.create(**values)
    assert error.value.__cause__.diag.constraint_name == "garage_itemusage_unique"
    for count in (0, 2):
        with pytest.raises(IntegrityError) as error:
            with transaction.atomic():
                ItemUsage.objects.filter(pk=fact.pk).update(ride_count=count)
        assert error.value.__cause__.diag.constraint_name == "garage_itemusage_one_ride"
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ItemUsage.objects.create(id=fact.pk, **values)


@pytest.mark.parametrize("mutation", ["foreign_item", "foreign_bike", "owner", "naive_start", "float", "inexact", "bad_resolution", "bad_provenance", "fractional_count"])
@pytest.mark.django_db
def test_usage_model_validation_enforces_owner_types_precision_and_closed_provenance(mutation, usage):
    profile(usage)
    ride(usage)
    fact = ItemUsage.objects.get()
    if mutation == "foreign_item":
        category = create_inventory(usage.other, Category, name="Parts")
        fact.item = create_inventory(usage.other, Item, name="Foreign", category=category)
    elif mutation == "foreign_bike":
        fact.bike = create_inventory(usage.other, Bike, name="Foreign")
    elif mutation == "owner":
        fact.owner = usage.other
    elif mutation == "naive_start":
        fact.started_at = datetime(2026, 1, 5)
    elif mutation == "float":
        fact.distance_m = 1.2
    elif mutation == "inexact":
        fact.moving_time_s = Decimal("1.2345")
    elif mutation == "bad_resolution":
        fact.resolution = [{"gps": []}]
    elif mutation == "bad_provenance":
        fact.field_provenance = {"token": "secret"}
    else:
        fact.ride_count = Decimal("1.5")
    with pytest.raises(ValidationError):
        fact.full_clean()


@pytest.mark.django_db
def test_usage_item_is_protected_and_scoped_read_hides_foreign_owner(usage):
    profile(usage)
    ride(usage)
    fact = ItemUsage.objects.get()
    with pytest.raises(ProtectedError):
        usage.helmet.delete()
    with pytest.raises(InventoryNotFound):
        get_inventory(usage.other, ItemUsage, fact.pk)
    assert not scoped_inventory(usage.other, ItemUsage).exists()


@pytest.mark.parametrize("actor_kind", ["anonymous", "inactive", "unknown"])
@pytest.mark.django_db
def test_materialization_requires_active_persisted_authenticated_actor(actor_kind, usage, django_user_model):
    own = ride(usage)
    if actor_kind == "anonymous":
        actor = AnonymousUser()
    elif actor_kind == "unknown":
        actor = django_user_model(username="unsaved")
    else:
        actor = usage.owner
        django_user_model.objects.filter(pk=actor.pk).update(is_active=False)
    for operation in [lambda: rebuild_ride_usage(actor, own.pk), lambda: rebuild_usage(actor)]:
        with pytest.raises(PermissionDenied):
            operation()


@pytest.mark.django_db
def test_rebuild_failure_rolls_back_domain_metric_profile_and_usage_changes(monkeypatch, usage):
    own_profile = profile(usage)
    own = ride(usage)
    fact = ItemUsage.objects.get()
    failure = IntegrityError("synthetic unexpected write failure")
    def fail(*args, **kwargs):
        raise failure
    monkeypatch.setattr(ItemUsage.objects, "bulk_create", fail)
    monkeypatch.setattr(ItemUsage.objects, "bulk_update", fail)
    with pytest.raises(IntegrityError) as error:
        correct_ride(usage.owner, own.pk, distance_m="30000")
    assert error.value is failure
    own.refresh_from_db()
    fact.refresh_from_db()
    assert own.distance_m == fact.distance_m == Decimal("25000")
    with pytest.raises(IntegrityError):
        update_profile_history(usage.owner, own_profile.pk, items=[usage.shoes], name="Forbidden")
    own_profile.refresh_from_db()
    assert own_profile.name == "Default" and list(own_profile.items.all()) == [usage.helmet]
    assert ItemUsage.objects.get().pk == fact.pk and not connection.needs_rollback


@pytest.mark.django_db(transaction=True)
def test_concurrent_ride_correction_and_rebuild_use_one_fact_with_current_values(usage):
    profile(usage)
    own = ride(usage)
    initial_id = ItemUsage.objects.get().pk
    barrier = Barrier(2)
    def operate(correct):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return correct_ride(usage.owner, own.pk, distance_m="30000") if correct else rebuild_usage(usage.owner)
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(operate, correct) for correct in (True, False)]
        [future.result(timeout=20) for future in futures]
    fact = ItemUsage.objects.get()
    assert fact.pk == initial_id and fact.distance_m == Decimal("30000")


@pytest.mark.django_db(transaction=True)
def test_concurrent_override_and_rebuild_do_not_leave_excluded_usage(usage):
    profile(usage)
    own = ride(usage)
    barrier = Barrier(2)
    def operate(exclude):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return set_usage_override(usage.owner, ride=own, item=usage.helmet, action="exclude") if exclude else rebuild_ride_usage(usage.owner, own.pk)
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(operate, exclude) for exclude in (True, False)]
        [future.result(timeout=20) for future in futures]
    assert not ItemUsage.objects.exists()
