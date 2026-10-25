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

from .models import Bike, Category, Item, UsageOverride, UsageProfile, UsageProfileItem
from .services import usage_profiles
from .services.ownership import InventoryNotFound, create_inventory, get_inventory, scoped_inventory
from .services.rides import create_manual_ride
from .services.usage_profiles import (create_profile, create_profile_history, delete_profile_history,
                                    delete_usage_override, resolve_ride_usage, revise_profile, revise_profile_history,
                                    set_usage_override, update_profile_history)


def instant(day=1):
    return datetime(2026, 1, day, tzinfo=datetime_timezone.utc)


@pytest.fixture
def inventory(db, django_user_model):
    owner = django_user_model.objects.create_user(username="profile-owner")
    other = django_user_model.objects.create_user(username="profile-other")
    category = create_inventory(owner, Category, name="Parts")
    helmet = create_inventory(owner, Item, name="Helmet", category=category)
    shoes = create_inventory(owner, Item, name="Shoes", category=category)
    foreign = create_inventory(other, Item, name="SECRET", category=create_inventory(other, Category, name="Parts"))
    return SimpleNamespace(owner=owner, other=other, helmet=helmet, shoes=shoes, foreign=foreign,
                           bike=create_inventory(owner, Bike, name="Bike"),
                           foreign_bike=create_inventory(other, Bike, name="SECRET bike"))


@pytest.fixture
def clock(monkeypatch):
    monkeypatch.setattr(usage_profiles.timezone, "now", lambda: instant(10))
    return instant(10)


def profile(inventory, **values):
    return create_profile_history(inventory.owner, name="Shared equipment", items=[inventory.helmet], started_at=instant(), **values)


@pytest.mark.django_db
def test_ordinary_creation_and_revision_capture_clock_and_preserve_past_membership(inventory, clock):
    previous = create_profile_history(inventory.owner, name="Old", items=[inventory.helmet], started_at=instant())
    old_ride = create_manual_ride(inventory.owner, started_at=instant(5))
    before = resolve_ride_usage(inventory.owner, old_ride.pk)
    revised = revise_profile(inventory.owner, previous.pk, items=[inventory.shoes], name="New")
    previous.refresh_from_db()
    assert revised.series_id == previous.series_id and revised.pk != previous.pk
    assert previous.ended_at == revised.started_at == clock
    assert list(previous.items.all()) == [inventory.helmet] and list(revised.items.all()) == [inventory.shoes]
    assert resolve_ride_usage(inventory.owner, old_ride.pk).item_ids == before.item_ids == {inventory.helmet.pk}
    at_boundary = create_manual_ride(inventory.owner, started_at=clock)
    assert resolve_ride_usage(inventory.owner, at_boundary.pk).item_ids == {inventory.shoes.pk}
    new = create_profile(inventory.owner, name="Another independent series", items=[])
    assert new.started_at == clock and new.series_id != revised.series_id


@pytest.mark.django_db
def test_future_revision_keeps_original_bounded_end_and_unchanged_memberships(inventory, clock):
    previous = profile(inventory, ended_at=instant(20), bike=inventory.bike, sport_type=" Cycling ", notes="Original notes")
    revised = revise_profile(inventory.owner, previous.pk, at=instant(15), name="Future")
    assert revised.ended_at == instant(20) and revised.bike == inventory.bike and revised.sport_type == "cycling"
    assert revised.notes == "Original notes" and list(revised.items.all()) == [inventory.helmet]


@pytest.mark.parametrize("operation", ["create", "revise"])
@pytest.mark.django_db
def test_ordinary_changes_reject_past_dates_and_require_explicit_historical_boundary(operation, inventory, clock):
    previous = profile(inventory)
    with pytest.raises(ValidationError) as error:
        create_profile(inventory.owner, name="Past", items=[], at=instant(9)) if operation == "create" else revise_profile(inventory.owner, previous.pk, at=instant(9), items=[])
    assert error.value.error_dict["started_at"][0].code == "historical_change_required"
    assert UsageProfile.objects.count() == 1 and previous.items.count() == 1
    revised = revise_profile_history(inventory.owner, previous.pk, at=instant(9), items=[])
    assert revised.started_at == instant(9)


@pytest.mark.parametrize("at", [instant(), instant(20), instant(21)])
@pytest.mark.django_db
def test_revision_split_must_be_strictly_inside_current_interval(at, inventory):
    previous = profile(inventory, ended_at=instant(20))
    with pytest.raises(ValidationError):
        revise_profile_history(inventory.owner, previous.pk, at=at, items=[])
    previous.refresh_from_db()
    assert previous.ended_at == instant(20) and UsageProfile.objects.count() == UsageProfileItem.objects.count() == 1


@pytest.mark.django_db
def test_explicit_historical_update_can_change_resolution_and_preserves_profile_uuid(inventory):
    previous = profile(inventory)
    ride = create_manual_ride(inventory.owner, started_at=instant(5))
    assert resolve_ride_usage(inventory.owner, ride.pk).item_ids == {inventory.helmet.pk}
    corrected = update_profile_history(inventory.owner, previous.pk, items=[inventory.shoes], name="Corrected")
    assert corrected.pk == previous.pk and corrected.series_id == previous.series_id
    assert resolve_ride_usage(inventory.owner, ride.pk).item_ids == {inventory.shoes.pk}


@pytest.mark.django_db
def test_historical_overlap_failure_rolls_back_fields_memberships_and_adjacent_version(inventory):
    first = profile(inventory)
    second = revise_profile_history(inventory.owner, first.pk, at=instant(10), items=[inventory.shoes])
    with pytest.raises(ValidationError) as error:
        update_profile_history(inventory.owner, first.pk, ended_at=instant(11), items=[], name="Forbidden")
    assert error.value.error_dict["started_at"][0].code == "profile_overlap"
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.ended_at == second.started_at == instant(10) and first.name == "Shared equipment"
    assert list(first.items.all()) == [inventory.helmet] and list(second.items.all()) == [inventory.shoes]


@pytest.mark.parametrize("field,value", [("owner", 2), ("owner_id", 2), ("id", uuid.uuid4()),
                                         ("series_id", uuid.uuid4()), ("started_at", instant())])
@pytest.mark.django_db
def test_ordinary_creation_does_not_accept_immutable_payload_fields(field, value, inventory, clock):
    with pytest.raises(ValidationError):
        create_profile(inventory.owner, name="Forbidden", items=[], **{field: value})
    assert not UsageProfile.objects.exists()


@pytest.mark.django_db
def test_profile_memberships_are_deduplicated_and_fresh_foreign_instances_rejected(inventory):
    own = create_profile_history(inventory.owner, name="Dedup", items=[inventory.helmet, inventory.helmet.pk], started_at=instant())
    assert own.items.count() == 1 and UsageProfileItem.objects.get().owner == inventory.owner
    inventory.foreign.owner = inventory.owner
    with pytest.raises(ValidationError):
        create_profile_history(inventory.owner, name="Forged", items=[inventory.foreign], started_at=instant())
    with pytest.raises(ValidationError):
        update_profile_history(inventory.owner, own.pk, items=[inventory.foreign], name="Forbidden")
    own.refresh_from_db()
    assert own.name == "Dedup" and own.items.get() == inventory.helmet
    inventory.foreign_bike.owner = inventory.owner
    with pytest.raises(ValidationError):
        update_profile_history(inventory.owner, own.pk, bike=inventory.foreign_bike)


@pytest.mark.parametrize("items", ["not-a-list", None, [uuid.uuid4()], [[]], [{}]])
@pytest.mark.django_db
def test_structurally_invalid_or_unknown_membership_input_has_domain_error(items, inventory):
    with pytest.raises(ValidationError):
        create_profile_history(inventory.owner, name="Invalid", items=items, started_at=instant())
    assert not UsageProfile.objects.exists()


@pytest.mark.parametrize("field,value", [("started_at", date(2026, 1, 1)), ("started_at", datetime(2026, 1, 1)),
                                         ("ended_at", datetime(2026, 1, 2)), ("ended_at", instant()),
                                         ("sport_type", []), ("sport_type", "road cycling"), ("name", "  ")])
@pytest.mark.django_db
def test_profile_dates_names_and_modality_keys_are_validated_before_save(field, value, inventory):
    values = {"name": "Profile", "items": [inventory.helmet], "started_at": instant(), field: value}
    with pytest.raises(ValidationError):
        create_profile_history(inventory.owner, **values)
    assert not UsageProfile.objects.exists()


@pytest.mark.django_db
def test_override_upsert_keeps_uuid_and_delete_restores_defaults(inventory):
    profile(inventory)
    ride = create_manual_ride(inventory.owner, started_at=instant(5))
    first = set_usage_override(inventory.owner, ride=ride, item=inventory.helmet, action="exclude")
    assert not resolve_ride_usage(inventory.owner, ride.pk).item_ids
    updated = set_usage_override(inventory.owner, ride=ride.pk, item=inventory.helmet.pk, action="include")
    assert updated.pk == first.pk and UsageOverride.objects.count() == 1
    delete_usage_override(inventory.owner, updated.pk)
    assert resolve_ride_usage(inventory.owner, ride.pk).item_ids == {inventory.helmet.pk}


@pytest.mark.parametrize("action", [None, [], {}, "invalid"])
@pytest.mark.django_db
def test_override_action_is_closed_and_typed(action, inventory):
    ride = create_manual_ride(inventory.owner, started_at=instant())
    with pytest.raises(ValidationError):
        set_usage_override(inventory.owner, ride=ride, item=inventory.helmet, action=action)
    assert not UsageOverride.objects.exists()


@pytest.mark.django_db
def test_override_references_are_requeried_and_foreign_forgery_cannot_succeed(inventory):
    own = create_manual_ride(inventory.owner, started_at=instant())
    foreign = create_manual_ride(inventory.other, started_at=instant())
    foreign.owner = inventory.owner
    inventory.foreign.owner = inventory.owner
    for ride, item in ((foreign, inventory.helmet), (own, inventory.foreign)):
        with pytest.raises(ValidationError):
            set_usage_override(inventory.owner, ride=ride, item=item, action="include")
    assert not UsageOverride.objects.exists()


@pytest.mark.parametrize("kind", ["foreign", "missing", "malformed"])
@pytest.mark.django_db
def test_profile_and_override_resource_operations_hide_foreign_ids(kind, inventory):
    foreign = create_profile_history(inventory.other, name="Foreign", items=[inventory.foreign], started_at=instant())
    foreign_ride = create_manual_ride(inventory.other, started_at=instant())
    foreign_override = set_usage_override(inventory.other, ride=foreign_ride, item=inventory.foreign, action="include")
    profile_id = foreign.pk if kind == "foreign" else uuid.uuid4() if kind == "missing" else "bad"
    override_id = foreign_override.pk if kind == "foreign" else uuid.uuid4() if kind == "missing" else "bad"
    for operation in [lambda: get_inventory(inventory.owner, UsageProfile, profile_id),
                      lambda: revise_profile_history(inventory.owner, profile_id, at=instant(2)),
                      lambda: update_profile_history(inventory.owner, profile_id, name="Forbidden"),
                      lambda: delete_profile_history(inventory.owner, profile_id),
                      lambda: delete_usage_override(inventory.owner, override_id)]:
        with pytest.raises(InventoryNotFound):
            operation()
    assert not scoped_inventory(inventory.owner, UsageProfile).exists()
    assert UsageOverride.objects.count() == 1 and UsageProfile.objects.get().name == "Foreign"


@pytest.mark.parametrize("actor_kind", ["anonymous", "inactive", "unknown"])
@pytest.mark.django_db
def test_all_profile_override_and_resolver_paths_reject_untrusted_actor(actor_kind, inventory, django_user_model):
    own = profile(inventory)
    ride = create_manual_ride(inventory.owner, started_at=instant())
    override = set_usage_override(inventory.owner, ride=ride, item=inventory.helmet, action="include")
    if actor_kind == "anonymous":
        actor = AnonymousUser()
    elif actor_kind == "unknown":
        actor = django_user_model(username="unsaved")
    else:
        actor = inventory.owner
        django_user_model.objects.filter(pk=actor.pk).update(is_active=False)
    operations = [lambda: create_profile(actor, name="Forbidden", items=[]),
                  lambda: create_profile_history(actor, name="Forbidden", items=[], started_at=instant()),
                  lambda: revise_profile_history(actor, own.pk, at=instant(2)),
                  lambda: revise_profile(actor, own.pk), lambda: update_profile_history(actor, own.pk, items=[]),
                  lambda: delete_profile_history(actor, own.pk),
                  lambda: set_usage_override(actor, ride=ride, item=inventory.helmet, action="exclude"),
                  lambda: delete_usage_override(actor, override.pk), lambda: resolve_ride_usage(actor, ride.pk)]
    for operation in operations:
        with pytest.raises(PermissionDenied):
            operation()
    assert UsageProfile.objects.count() == 1 and UsageOverride.objects.get().action == "include"


@pytest.mark.parametrize("changes,constraint", [({"name": "  "}, "garage_usageprofile_name_nonblank"),
                                                ({"sport_type": "CYCLING"}, "garage_usageprofile_sport_canonical"),
                                                ({"ended_at": instant()}, "garage_usageprofile_interval_positive")])
@pytest.mark.django_db
def test_profile_sql_checks_are_real(changes, constraint, inventory):
    own = profile(inventory)
    with pytest.raises(IntegrityError) as error:
        with transaction.atomic():
            UsageProfile.objects.filter(pk=own.pk).update(**changes)
    assert error.value.__cause__.diag.constraint_name == constraint


@pytest.mark.django_db
def test_sql_series_exclusion_adjacent_versions_and_independent_series(inventory):
    first = profile(inventory, ended_at=instant(10))
    second = UsageProfile.objects.create(owner=inventory.owner, series_id=first.series_id, name="Next", started_at=instant(10))
    independent = profile(inventory)
    assert independent.series_id != first.series_id
    with pytest.raises(IntegrityError) as error:
        with transaction.atomic():
            UsageProfile.objects.create(owner=inventory.owner, series_id=first.series_id, name="Overlap", started_at=instant(9), ended_at=instant(11))
    assert error.value.__cause__.diag.constraint_name == "garage_usageprofile_series_no_overlap"
    assert second.started_at == first.ended_at


@pytest.mark.django_db
def test_sql_membership_override_identity_action_and_uuid_uniqueness(inventory):
    own = profile(inventory)
    ride = create_manual_ride(inventory.owner, started_at=instant())
    override = set_usage_override(inventory.owner, ride=ride, item=inventory.helmet, action="include")
    for operation, constraint in [
        (lambda: UsageProfileItem.objects.create(owner=inventory.owner, profile=own, item=inventory.helmet), "garage_usageprofileitem_unique"),
        (lambda: UsageOverride.objects.create(owner=inventory.owner, ride=ride, item=inventory.helmet, action="exclude"), "garage_usageoverride_unique"),
        (lambda: UsageOverride.objects.filter(pk=override.pk).update(action="invalid"), "garage_usageoverride_action_valid")]:
        with pytest.raises(IntegrityError) as error:
            with transaction.atomic():
                operation()
        assert error.value.__cause__.diag.constraint_name == constraint
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            UsageProfile.objects.create(id=own.pk, owner=inventory.owner, name="Duplicate UUID", started_at=instant())


@pytest.mark.django_db
def test_history_references_protect_items_and_bikes_but_explicit_profile_delete_removes_only_memberships(inventory):
    own = profile(inventory, bike=inventory.bike)
    with pytest.raises(ProtectedError):
        inventory.helmet.delete()
    with pytest.raises(ProtectedError):
        inventory.bike.delete()
    delete_profile_history(inventory.owner, own.pk)
    assert not UsageProfileItem.objects.exists() and Item.objects.filter(pk=inventory.helmet.pk).exists()
    ride = create_manual_ride(inventory.owner, started_at=instant())
    override = set_usage_override(inventory.owner, ride=ride, item=inventory.helmet, action="exclude")
    with pytest.raises(ProtectedError):
        inventory.helmet.delete()
    ride.delete()
    assert not UsageOverride.objects.filter(pk=override.pk).exists() and Item.objects.filter(pk=inventory.helmet.pk).exists()


@pytest.mark.django_db
def test_model_validation_rejects_owner_series_and_membership_override_retagging(inventory):
    own = profile(inventory)
    own.series_id = uuid.uuid4()
    with pytest.raises(ValidationError):
        own.full_clean()
    own.refresh_from_db()
    own.owner = inventory.other
    with pytest.raises(ValidationError):
        own.full_clean()
    membership = UsageProfileItem.objects.get()
    membership.item = inventory.foreign
    with pytest.raises(ValidationError):
        membership.full_clean()
    ride = create_manual_ride(inventory.owner, started_at=instant())
    override = set_usage_override(inventory.owner, ride=ride, item=inventory.helmet, action="include")
    override.item = inventory.shoes
    with pytest.raises(ValidationError):
        override.full_clean()


@pytest.mark.django_db
def test_unexpected_integrity_error_rolls_back_profile_split_and_does_not_hide_bug(monkeypatch, inventory):
    own = profile(inventory)
    failure = IntegrityError("synthetic unexpected constraint")
    def fail(*args, **kwargs):
        raise failure
    monkeypatch.setattr(UsageProfileItem, "save", fail)
    with pytest.raises(IntegrityError) as error:
        revise_profile_history(inventory.owner, own.pk, at=instant(2), items=[inventory.shoes])
    own.refresh_from_db()
    assert error.value is failure and own.ended_at is None and UsageProfile.objects.count() == 1
    assert list(own.items.all()) == [inventory.helmet] and not connection.needs_rollback


def parallel(operations):
    barrier = Barrier(2)
    def run(operation):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                return operation()
            except ValidationError as error:
                return error
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, operation) for operation in operations]
        return [future.result(timeout=20) for future in futures]


@pytest.mark.django_db(transaction=True)
def test_concurrent_revision_same_boundary_creates_only_one_valid_successor(inventory):
    own = profile(inventory)
    results = parallel([lambda: revise_profile_history(inventory.owner, own.pk, at=instant(10), items=[inventory.helmet]),
                        lambda: revise_profile_history(inventory.owner, own.pk, at=instant(10), items=[inventory.shoes])])
    assert sum(isinstance(result, UsageProfile) for result in results) == 1
    errors = [result for result in results if isinstance(result, ValidationError)]
    assert len(errors) == 1 and errors[0].error_dict["started_at"][0].code == "invalid_interval"
    versions = list(UsageProfile.objects.order_by("started_at"))
    assert len(versions) == 2 and versions[0].ended_at == versions[1].started_at == instant(10)
    assert UsageProfileItem.objects.count() == 2


@pytest.mark.django_db(transaction=True)
def test_concurrent_override_upsert_uses_one_uuid_and_one_action(inventory):
    ride = create_manual_ride(inventory.owner, started_at=instant())
    results = parallel([lambda: set_usage_override(inventory.owner, ride=ride, item=inventory.helmet, action=action)
                        for action in ("include", "exclude")])
    assert all(isinstance(result, UsageOverride) for result in results)
    assert results[0].pk == results[1].pk and UsageOverride.objects.count() == 1
