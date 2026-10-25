from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone as datetime_timezone
from threading import Barrier
from types import SimpleNamespace
import uuid

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.models.deletion import ProtectedError

from .models import Bike, Category, Installation, Item, RetirementInterval
from .services import ownership
from .services.installations import create_installation, update_installation
from .services.ownership import (InventoryNotFound, correct_retirement, create_inventory, get_inventory,
                                 reactivate_inventory, retire_inventory, scoped_inventory, update_inventory)
from .services.rides import create_manual_ride
from .services.usage_profiles import create_profile_history, resolve_ride_usage, set_usage_override


def instant(day=1):
    return datetime(2026, 1, day, tzinfo=datetime_timezone.utc)


@pytest.fixture
def garage(db, django_user_model, monkeypatch):
    monkeypatch.setattr(ownership.timezone, "now", lambda: instant(20))
    owner = django_user_model.objects.create_user(username="retirement-owner")
    other = django_user_model.objects.create_user(username="retirement-other")
    category = create_inventory(owner, Category, name="Parts")
    helmet = create_inventory(owner, Item, name="Helmet", category=category)
    shoes = create_inventory(owner, Item, name="Shoes", category=category)
    cleat = create_inventory(owner, Item, name="Cleat", category=category)
    bike = create_inventory(owner, Bike, name="Bike")
    return SimpleNamespace(owner=owner, other=other, helmet=helmet, shoes=shoes, cleat=cleat, bike=bike)


def retire_resume(garage, resource, start=5, end=10):
    retire_inventory(garage.owner, type(resource), resource.pk, at=instant(start))
    return reactivate_inventory(garage.owner, type(resource), resource.pk, at=instant(end))


def ride(garage, day, *, bike=None):
    return create_manual_ride(garage.owner, started_at=instant(day), bike=bike)


@pytest.mark.parametrize("root", ["profile", "manual", "child"])
@pytest.mark.django_db
def test_reactivation_keeps_real_inactive_gap_for_profile_manual_and_child_history(root, garage):
    if root == "profile":
        create_profile_history(garage.owner, name="Helmet", items=[garage.helmet], started_at=instant())
    elif root == "child":
        create_profile_history(garage.owner, name="Shoes", items=[garage.shoes], started_at=instant())
        create_installation(garage.owner, item=garage.helmet, parent_item=garage.shoes, started_at=instant())
    before, during, after = [ride(garage, day) for day in (4, 5, 10)]
    if root == "manual":
        for own in (before, during, after):
            set_usage_override(garage.owner, ride=own, item=garage.helmet, action="include")
    restored = retire_resume(garage, garage.helmet)
    assert restored.retired_at is None
    period = RetirementInterval.objects.get()
    assert period.started_at == instant(5) and period.ended_at == instant(10)
    assert garage.helmet.pk in resolve_ride_usage(garage.owner, before.pk).item_ids
    assert garage.helmet.pk not in resolve_ride_usage(garage.owner, during.pk).item_ids
    if root == "child":
        # Closed physical mount is not resurrected; only an explicit remount
        # at the resume boundary can make this child part of the root again.
        assert garage.helmet.pk not in resolve_ride_usage(garage.owner, after.pk).item_ids
        create_installation(garage.owner, item=garage.helmet, parent_item=garage.shoes, started_at=instant(10))
    assert garage.helmet.pk in resolve_ride_usage(garage.owner, after.pk).item_ids
    assert garage.helmet.pk not in resolve_ride_usage(garage.owner, during.pk).item_ids


@pytest.mark.django_db
def test_two_real_cycles_keep_both_gaps_and_explicit_correction_does_not_erase_them(garage):
    create_profile_history(garage.owner, name="Helmet", items=[garage.helmet], started_at=instant())
    retire_resume(garage, garage.helmet, 3, 6)
    retire_resume(garage, garage.helmet, 10, 12)
    corrected = correct_retirement(garage.owner, Item, garage.helmet.pk, retired_at=None)
    assert corrected.retired_at is None and RetirementInterval.objects.count() == 2
    for day, included in [(2, True), (3, False), (5, False), (6, True), (9, True), (10, False), (11, False), (12, True)]:
        assert (garage.helmet.pk in resolve_ride_usage(garage.owner, ride(garage, day).pk).item_ids) is included


@pytest.mark.django_db
def test_bike_gap_blocks_specific_profiles_and_mounts_but_general_equipment_remains(garage):
    create_profile_history(garage.owner, name="Helmet general", items=[garage.helmet], started_at=instant())
    create_profile_history(garage.owner, name="Shoes specific", items=[garage.shoes], bike=garage.bike, started_at=instant())
    create_installation(garage.owner, item=garage.cleat, bike=garage.bike, started_at=instant())
    retire_resume(garage, garage.bike)
    assert resolve_ride_usage(garage.owner, ride(garage, 4, bike=garage.bike).pk).item_ids == {garage.helmet.pk, garage.shoes.pk, garage.cleat.pk}
    assert resolve_ride_usage(garage.owner, ride(garage, 5, bike=garage.bike).pk).item_ids == {garage.helmet.pk}
    assert resolve_ride_usage(garage.owner, ride(garage, 10, bike=garage.bike).pk).item_ids == {garage.helmet.pk, garage.shoes.pk}


@pytest.mark.parametrize("model", [Bike, Item])
@pytest.mark.django_db
def test_default_resume_captures_now_and_active_noop_does_not_add_period(model, garage):
    resource = garage.bike if model is Bike else garage.helmet
    retire_inventory(garage.owner, model, resource.pk, at=instant(5))
    restored = reactivate_inventory(garage.owner, model, resource.pk)
    assert restored.retired_at is None and RetirementInterval.objects.get().ended_at == instant(20)
    previous_updated = restored.updated_at
    no_op = reactivate_inventory(garage.owner, model, resource.pk)
    assert no_op.updated_at == previous_updated and RetirementInterval.objects.count() == 1


@pytest.mark.django_db
def test_scheduled_future_retirement_can_be_cancelled_without_fabricating_inactivity(garage):
    retire_inventory(garage.owner, Item, garage.helmet.pk, at=instant(25))
    restored = reactivate_inventory(garage.owner, Item, garage.helmet.pk)
    assert restored.retired_at is None and not RetirementInterval.objects.exists()


@pytest.mark.django_db
def test_equal_retirement_resume_boundary_creates_no_empty_period(garage):
    retire_inventory(garage.owner, Item, garage.helmet.pk, at=instant(10))
    reactivate_inventory(garage.owner, Item, garage.helmet.pk, at=instant(10))
    assert not RetirementInterval.objects.exists()


@pytest.mark.parametrize("at", [instant(21), instant(4), date(2026, 1, 10), datetime(2026, 1, 10), "2026-01-10T00:00:00Z"])
@pytest.mark.django_db
def test_resume_rejects_future_before_retirement_and_untyped_instants(at, garage):
    retire_inventory(garage.owner, Item, garage.helmet.pk, at=instant(5))
    with pytest.raises(ValidationError):
        reactivate_inventory(garage.owner, Item, garage.helmet.pk, at=at)
    garage.helmet.refresh_from_db()
    assert garage.helmet.retired_at == instant(5) and not RetirementInterval.objects.exists()


@pytest.mark.parametrize("field", ["item", "bike", "parent_item"])
@pytest.mark.parametrize("start,end", [(4, 6), (5, 10), (6, 9), (9, 11), (4, None)])
@pytest.mark.django_db
def test_installation_cannot_overlap_closed_gap_for_item_bike_or_parent(field, start, end, garage):
    target = garage.bike if field == "bike" else garage.helmet
    retire_resume(garage, target)
    values = {"item": garage.helmet if field == "item" else garage.cleat,
              "bike": garage.bike, "started_at": instant(start), "ended_at": instant(end) if end else None}
    if field == "parent_item":
        values.pop("bike")
        values["parent_item"] = garage.helmet
    with pytest.raises(ValidationError) as error:
        create_installation(garage.owner, **values)
    assert error.value.error_dict[field][0].code == "resource_retired"
    assert not Installation.objects.exists()


@pytest.mark.parametrize("field", ["item", "bike", "parent_item"])
@pytest.mark.django_db
def test_adjacent_installations_are_allowed_but_edit_into_gap_rolls_back(field, garage):
    target = garage.bike if field == "bike" else garage.helmet
    retire_resume(garage, target)
    values = {"item": garage.helmet if field == "item" else garage.cleat, "bike": garage.bike,
              "started_at": instant(), "ended_at": instant(5)}
    if field == "parent_item":
        values.pop("bike")
        values["parent_item"] = garage.helmet
    prior = create_installation(garage.owner, **values)
    after = create_installation(garage.owner, **(values | {"started_at": instant(10), "ended_at": None}))
    with pytest.raises(ValidationError):
        update_installation(garage.owner, prior.pk, ended_at=instant(6), notes="Forbidden edit")
    prior.refresh_from_db()
    assert prior.ended_at == instant(5) and prior.notes == "" and after.started_at == instant(10)


@pytest.mark.parametrize("at", [instant(4), instant(5), instant(9)])
@pytest.mark.django_db
def test_new_open_retirement_must_not_overlap_recorded_gap_and_rolls_back_name(at, garage):
    retire_resume(garage, garage.helmet)
    with pytest.raises(ValidationError) as error:
        update_inventory(garage.owner, Item, garage.helmet.pk, retired_at=at, name="Forbidden")
    assert error.value.error_dict["retired_at"][0].code == "retirement_overlap"
    garage.helmet.refresh_from_db()
    assert garage.helmet.retired_at is None and garage.helmet.name == "Helmet"
    retire_inventory(garage.owner, Item, garage.helmet.pk, at=instant(10))


@pytest.mark.django_db
def test_explicit_current_flag_correction_has_historical_meaning_without_a_fake_resume(garage):
    retire_inventory(garage.owner, Item, garage.helmet.pk, at=instant(5))
    corrected = correct_retirement(garage.owner, Item, garage.helmet.pk, retired_at=None)
    assert corrected.retired_at is None and not RetirementInterval.objects.exists()


@pytest.mark.django_db
def test_resume_rejects_corrupt_installation_during_gap_and_preserves_current_retirement(garage):
    retire_inventory(garage.owner, Item, garage.helmet.pk, at=instant(5))
    # Raw saves are outside the authorized API; detecting this pre-existing
    # contradiction prevents a resume from certifying incompatible history.
    Installation.objects.create(owner=garage.owner, item=garage.helmet, bike=garage.bike, started_at=instant(6), ended_at=instant(7))
    with pytest.raises(ValidationError):
        reactivate_inventory(garage.owner, Item, garage.helmet.pk, at=instant(10))
    garage.helmet.refresh_from_db()
    assert garage.helmet.retired_at == instant(5) and not RetirementInterval.objects.exists()


@pytest.mark.parametrize("actor_kind", ["anonymous", "inactive", "unknown"])
@pytest.mark.django_db
def test_resume_and_correction_require_trusted_actor(actor_kind, garage, django_user_model):
    retire_inventory(garage.owner, Item, garage.helmet.pk, at=instant(5))
    if actor_kind == "anonymous":
        actor = AnonymousUser()
    elif actor_kind == "unknown":
        actor = django_user_model(username="unsaved")
    else:
        actor = garage.owner
        django_user_model.objects.filter(pk=actor.pk).update(is_active=False)
    for operation in [lambda: reactivate_inventory(actor, Item, garage.helmet.pk),
                      lambda: correct_retirement(actor, Item, garage.helmet.pk, retired_at=None),
                      lambda: scoped_inventory(actor, RetirementInterval)]:
        with pytest.raises(PermissionDenied):
            operation()
    garage.helmet.refresh_from_db()
    assert garage.helmet.retired_at == instant(5) and not RetirementInterval.objects.exists()


@pytest.mark.parametrize("kind", ["foreign", "missing", "malformed"])
@pytest.mark.django_db
def test_resume_and_correction_hide_other_owner_resources(kind, garage):
    resource_id = garage.helmet.pk if kind == "foreign" else uuid.uuid4() if kind == "missing" else "bad"
    for operation in [lambda: reactivate_inventory(garage.other, Item, resource_id),
                      lambda: correct_retirement(garage.other, Item, resource_id, retired_at=None)]:
        with pytest.raises(InventoryNotFound):
            operation()
    assert not RetirementInterval.objects.exists()


@pytest.mark.parametrize("changes,constraint", [({"item": None, "bike": None}, "garage_retirementinterval_destination_xor"),
                                                ({"bike": "own"}, "garage_retirementinterval_destination_xor"),
                                                ({"ended_at": instant(5)}, "garage_retirementinterval_positive")])
@pytest.mark.django_db
def test_closed_retirement_sql_xor_and_positive_constraints(changes, constraint, garage):
    retire_resume(garage, garage.helmet)
    interval = RetirementInterval.objects.get()
    if changes.get("bike") == "own":
        changes = changes | {"bike": garage.bike}
    with pytest.raises(IntegrityError) as error:
        with transaction.atomic():
            RetirementInterval.objects.filter(pk=interval.pk).update(**changes)
    assert error.value.__cause__.diag.constraint_name == constraint


@pytest.mark.parametrize("field", ["item", "bike"])
@pytest.mark.django_db
def test_closed_retirement_sql_exclusions_allow_adjacent_but_reject_overlap(field, garage):
    resource = garage.helmet if field == "item" else garage.bike
    retire_resume(garage, resource)
    RetirementInterval.objects.create(owner=garage.owner, **{field: resource}, started_at=instant(10), ended_at=instant(12))
    with pytest.raises(IntegrityError) as error:
        with transaction.atomic():
            RetirementInterval.objects.create(owner=garage.owner, **{field: resource}, started_at=instant(9), ended_at=instant(11))
    assert error.value.__cause__.diag.constraint_name == f"garage_retirementinterval_{field}_no_overlap"


@pytest.mark.django_db
def test_retirement_model_owner_reference_validation_and_protection(garage):
    retire_resume(garage, garage.helmet)
    interval = RetirementInterval.objects.get()
    interval.owner = garage.other
    with pytest.raises(ValidationError):
        interval.full_clean()
    with pytest.raises(ProtectedError):
        garage.helmet.delete()
    with pytest.raises(InventoryNotFound):
        get_inventory(garage.other, RetirementInterval, interval.pk)


@pytest.mark.django_db
def test_unexpected_retirement_save_failure_rolls_back_resume_and_leaves_database_usable(monkeypatch, garage):
    retire_inventory(garage.owner, Item, garage.helmet.pk, at=instant(5))
    failure = IntegrityError("synthetic unexpected constraint")
    def fail(*args, **kwargs):
        raise failure
    monkeypatch.setattr(RetirementInterval, "save", fail)
    with pytest.raises(IntegrityError) as error:
        reactivate_inventory(garage.owner, Item, garage.helmet.pk, at=instant(10))
    garage.helmet.refresh_from_db()
    assert error.value is failure and garage.helmet.retired_at == instant(5)
    assert not RetirementInterval.objects.exists() and not connection.needs_rollback


@pytest.mark.django_db(transaction=True)
def test_concurrent_reactivation_is_one_real_gap_followed_by_active_noop(garage):
    retire_inventory(garage.owner, Item, garage.helmet.pk, at=instant(5))
    barrier = Barrier(2)
    def reactivate():
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return reactivate_inventory(garage.owner, Item, garage.helmet.pk, at=instant(10))
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(reactivate), pool.submit(reactivate)]
        results = [future.result(timeout=20) for future in futures]
    assert all(result.retired_at is None for result in results)
    assert RetirementInterval.objects.count() == 1
