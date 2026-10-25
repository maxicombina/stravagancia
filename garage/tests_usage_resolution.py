from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone as datetime_timezone
from decimal import Decimal
from threading import Event
from types import SimpleNamespace
import uuid

import pytest
from django.db import close_old_connections

from .models import Bike, Category, Installation, Item, UsageOverride, UsageProfile, UsageProfileItem
from .services import usage_profiles
from .services.installations import create_installation
from .services.ownership import InventoryNotFound, create_inventory, retire_inventory
from .services.rides import create_manual_ride, import_fit_session, withdraw_source
from .services.usage_profiles import (create_profile_history, resolve_ride_usage, set_usage_override,
                                    update_profile_history)


def instant(day=1):
    return datetime(2026, 1, day, tzinfo=datetime_timezone.utc)


@pytest.fixture
def garage(db, django_user_model):
    owner = django_user_model.objects.create_user(username="resolver-owner")
    other = django_user_model.objects.create_user(username="resolver-other")
    category = create_inventory(owner, Category, name="Parts")
    items = {name: create_inventory(owner, Item, name=name, category=category) for name in
             ("helmet", "shoes", "cleat", "wheel", "tyre", "disc", "leaf")}
    bike = create_inventory(owner, Bike, name="Bike1")
    second_bike = create_inventory(owner, Bike, name="Bike2")
    return SimpleNamespace(owner=owner, other=other, bike=bike, second_bike=second_bike, **items)


def profile(garage, items, *, bike=None, sport_type="", started_at=None, ended_at=None):
    return create_profile_history(garage.owner, name="Equipment", items=items, bike=bike, sport_type=sport_type,
                                  started_at=started_at or instant(), ended_at=ended_at)


def ride(garage, *, day=5, bike=None, sport_type="cycling", **values):
    return create_manual_ride(garage.owner, started_at=instant(day), bike=bike, sport_type=sport_type, **values)


@pytest.mark.django_db
def test_general_bike_and_modality_profiles_union_without_precedence(garage):
    general = profile(garage, [garage.helmet])
    specific = profile(garage, [garage.shoes], bike=garage.bike, sport_type="cycling")
    profile(garage, [garage.wheel], bike=garage.second_bike)
    profile(garage, [garage.disc], sport_type="running")
    cycling = ride(garage, bike=garage.bike, sport_type="CYCLING")
    resolved = resolve_ride_usage(garage.owner, cycling.pk)
    assert resolved.item_ids == {garage.helmet.pk, garage.shoes.pk}
    assert {reason.resource_id for reason in resolved.provenance[garage.helmet.pk]} == {general.pk}
    assert {reason.resource_id for reason in resolved.provenance[garage.shoes.pk]} == {specific.pk}
    running = ride(garage, bike=garage.bike, sport_type="running")
    assert resolve_ride_usage(garage.owner, running.pk).item_ids == {garage.helmet.pk, garage.disc.pk}


@pytest.mark.django_db
def test_unknown_bike_uses_general_profiles_and_explicit_includes_without_guessing_roots(garage):
    profile(garage, [garage.helmet])
    profile(garage, [garage.shoes], bike=garage.bike)
    create_installation(garage.owner, item=garage.wheel, bike=garage.bike, started_at=instant())
    create_installation(garage.owner, item=garage.cleat, parent_item=garage.shoes, started_at=instant())
    own = ride(garage)
    assert resolve_ride_usage(garage.owner, own.pk).item_ids == {garage.helmet.pk}
    set_usage_override(garage.owner, ride=own, item=garage.shoes, action="include")
    resolved = resolve_ride_usage(garage.owner, own.pk)
    assert resolved.item_ids == {garage.helmet.pk, garage.shoes.pk, garage.cleat.pk}
    assert not resolved.unknown_started_at and garage.wheel.pk not in resolved.item_ids


@pytest.mark.django_db
def test_shared_helmet_two_bikes_and_duplicate_paths_use_one_uuid_per_ride(garage):
    profile(garage, [garage.helmet], bike=garage.bike)
    profile(garage, [garage.helmet], bike=garage.second_bike)
    first = ride(garage, bike=garage.bike, distance_m=Decimal("20000"))
    second = ride(garage, bike=garage.second_bike, distance_m=Decimal("35000"))
    set_usage_override(garage.owner, ride=first, item=garage.helmet, action="include")
    totals = []
    for own in (first, second):
        result = resolve_ride_usage(garage.owner, own.pk)
        assert result.item_ids == {garage.helmet.pk}
        totals.append(own.distance_m)
    assert sum(totals) == Decimal("55000") and Item.objects.filter(pk=garage.helmet.pk).count() == 1


@pytest.mark.django_db
def test_nested_shoes_and_cleats_remain_mounted_but_only_accumulate_when_root_is_used(garage):
    create_installation(garage.owner, item=garage.cleat, parent_item=garage.shoes, started_at=instant())
    profile(garage, [garage.shoes], started_at=instant(10))
    prior = ride(garage, day=5)
    after = ride(garage, day=10)
    assert not resolve_ride_usage(garage.owner, prior.pk).item_ids
    assert resolve_ride_usage(garage.owner, after.pk).item_ids == {garage.shoes.pk, garage.cleat.pk}
    assert Installation.objects.get().ended_at is None


@pytest.mark.django_db
def test_installations_and_profiles_both_obey_half_open_boundaries(garage):
    create_installation(garage.owner, item=garage.wheel, bike=garage.bike, started_at=instant(), ended_at=instant(10))
    create_installation(garage.owner, item=garage.tyre, parent_item=garage.wheel, started_at=instant(), ended_at=instant(5))
    create_installation(garage.owner, item=garage.disc, bike=garage.bike, started_at=instant(10))
    profile(garage, [garage.helmet], started_at=instant(), ended_at=instant(10))
    profile(garage, [garage.shoes], started_at=instant(10))
    assert resolve_ride_usage(garage.owner, ride(garage, day=4, bike=garage.bike).pk).item_ids == {garage.wheel.pk, garage.tyre.pk, garage.helmet.pk}
    assert resolve_ride_usage(garage.owner, ride(garage, day=5, bike=garage.bike).pk).item_ids == {garage.wheel.pk, garage.helmet.pk}
    assert resolve_ride_usage(garage.owner, ride(garage, day=10, bike=garage.bike).pk).item_ids == {garage.disc.pk, garage.shoes.pk}


@pytest.mark.django_db
def test_profile_installation_and_manual_include_deduplicate_and_preserve_all_reasons(garage):
    profile(garage, [garage.wheel, garage.tyre])
    create_installation(garage.owner, item=garage.wheel, bike=garage.bike, started_at=instant())
    create_installation(garage.owner, item=garage.tyre, parent_item=garage.wheel, started_at=instant())
    own = ride(garage, bike=garage.bike)
    set_usage_override(garage.owner, ride=own, item=garage.wheel, action="include")
    result = resolve_ride_usage(garage.owner, own.pk)
    assert result.item_ids == {garage.wheel.pk, garage.tyre.pk}
    assert {reason.kind for reason in result.provenance[garage.tyre.pk]} == {"profile", "bike_installation", "manual_include"}
    assert len(result.provenance[garage.tyre.pk]) == 4


@pytest.mark.django_db
def test_exclusion_of_set_removes_subtree_even_when_child_arrives_through_another_profile(garage):
    create_installation(garage.owner, item=garage.cleat, parent_item=garage.shoes, started_at=instant())
    profile(garage, [garage.shoes])
    profile(garage, [garage.cleat])
    own = ride(garage)
    set_usage_override(garage.owner, ride=own, item=garage.shoes, action="exclude")
    result = resolve_ride_usage(garage.owner, own.pk)
    assert not result.item_ids and result.excluded_item_ids == {garage.shoes.pk, garage.cleat.pk}
    set_usage_override(garage.owner, ride=own, item=garage.cleat, action="include")
    assert resolve_ride_usage(garage.owner, own.pk).item_ids == {garage.cleat.pk}


@pytest.mark.django_db
def test_nested_exclude_include_exclude_include_respects_each_subtree(garage):
    for child, parent in [(garage.shoes, garage.wheel), (garage.cleat, garage.shoes),
                          (garage.tyre, garage.cleat), (garage.leaf, garage.tyre), (garage.disc, garage.shoes)]:
        create_installation(garage.owner, item=child, parent_item=parent, started_at=instant())
    profile(garage, [garage.wheel, garage.cleat])
    own = ride(garage)
    for item, action in [(garage.wheel, "exclude"), (garage.shoes, "include"), (garage.cleat, "exclude"), (garage.tyre, "include")]:
        set_usage_override(garage.owner, ride=own, item=item, action=action)
    result = resolve_ride_usage(garage.owner, own.pk)
    assert result.item_ids == {garage.shoes.pk, garage.disc.pk, garage.tyre.pk, garage.leaf.pk}
    assert result.excluded_item_ids == {garage.wheel.pk, garage.cleat.pk}


@pytest.mark.django_db
def test_manual_parent_include_does_not_override_explicit_child_exclusion(garage):
    create_installation(garage.owner, item=garage.cleat, parent_item=garage.shoes, started_at=instant())
    create_installation(garage.owner, item=garage.leaf, parent_item=garage.cleat, started_at=instant())
    own = ride(garage)
    set_usage_override(garage.owner, ride=own, item=garage.shoes, action="include")
    set_usage_override(garage.owner, ride=own, item=garage.cleat, action="exclude")
    result = resolve_ride_usage(garage.owner, own.pk)
    assert result.item_ids == {garage.shoes.pk}
    assert garage.leaf.pk in result.excluded_item_ids


@pytest.mark.django_db
def test_excluding_absent_root_still_excludes_child_but_explicit_grandchild_restores_branch(garage):
    create_installation(garage.owner, item=garage.cleat, parent_item=garage.shoes, started_at=instant())
    create_installation(garage.owner, item=garage.leaf, parent_item=garage.cleat, started_at=instant())
    profile(garage, [garage.cleat])
    own = ride(garage)
    set_usage_override(garage.owner, ride=own, item=garage.shoes, action="exclude")
    assert not resolve_ride_usage(garage.owner, own.pk).item_ids
    set_usage_override(garage.owner, ride=own, item=garage.leaf, action="include")
    assert resolve_ride_usage(garage.owner, own.pk).item_ids == {garage.leaf.pk}


@pytest.mark.django_db
def test_retired_equipment_is_filtered_at_ride_start_but_previous_history_remains(garage):
    profile(garage, [garage.helmet])
    retire_inventory(garage.owner, Item, garage.helmet.pk, at=instant(10))
    prior = ride(garage, day=9)
    exact = ride(garage, day=10)
    set_usage_override(garage.owner, ride=exact, item=garage.helmet, action="include")
    assert resolve_ride_usage(garage.owner, prior.pk).item_ids == {garage.helmet.pk}
    result = resolve_ride_usage(garage.owner, exact.pk)
    assert not result.item_ids and result.skipped_retired_item_ids == {garage.helmet.pk}


@pytest.mark.django_db
def test_retired_bike_does_not_supply_specific_roots_but_general_equipment_remains(garage):
    profile(garage, [garage.helmet])
    profile(garage, [garage.shoes], bike=garage.bike)
    create_installation(garage.owner, item=garage.wheel, bike=garage.bike, started_at=instant())
    retire_inventory(garage.owner, Bike, garage.bike.pk, at=instant(10))
    assert resolve_ride_usage(garage.owner, ride(garage, day=9, bike=garage.bike).pk).item_ids == {garage.helmet.pk, garage.shoes.pk, garage.wheel.pk}
    assert resolve_ride_usage(garage.owner, ride(garage, day=10, bike=garage.bike).pk).item_ids == {garage.helmet.pk}


@pytest.mark.django_db
def test_unknown_start_is_pending_without_items_even_when_manual_includes_exist(garage):
    profile(garage, [garage.helmet])
    own, source = import_fit_session(garage.owner, file_hash="a" * 64, session_index=0, parser_version="fixture-1",
                                   observations={"started_at": instant()})
    set_usage_override(garage.owner, ride=own, item=garage.shoes, action="include")
    withdraw_source(garage.owner, source.pk)
    result = resolve_ride_usage(garage.owner, own.pk)
    assert result.unknown_started_at and not result.item_ids and result.provenance == {}


@pytest.mark.django_db
def test_reimport_preserves_exclusions_and_does_not_create_duplicate_usage(garage):
    profile(garage, [garage.helmet])
    own, source = import_fit_session(garage.owner, file_hash="a" * 64, session_index=0, parser_version="fixture-1",
                                   observations={"started_at": instant(), "distance_m": "100"})
    override = set_usage_override(garage.owner, ride=own, item=garage.helmet, action="exclude")
    repeated, _ = import_fit_session(garage.owner, file_hash="a" * 64, session_index=0, parser_version="fixture-2",
                                    observations={"started_at": instant(), "distance_m": "200"})
    assert repeated.pk == own.pk and UsageOverride.objects.get().pk == override.pk
    assert not resolve_ride_usage(garage.owner, repeated.pk).item_ids


@pytest.mark.django_db
def test_resolver_reads_do_not_mutate_memberships_installations_or_overrides(garage):
    profile(garage, [garage.shoes])
    create_installation(garage.owner, item=garage.cleat, parent_item=garage.shoes, started_at=instant())
    own = ride(garage)
    set_usage_override(garage.owner, ride=own, item=garage.helmet, action="include")
    models = (UsageProfile, UsageProfileItem, Installation, UsageOverride)
    before = {model: list(model.objects.order_by("pk").values()) for model in models}
    first = resolve_ride_usage(garage.owner, own.pk)
    second = resolve_ride_usage(garage.owner, own.pk)
    assert first == second
    assert before == {model: list(model.objects.order_by("pk").values()) for model in models}


@pytest.mark.parametrize("kind", ["foreign", "missing", "malformed"])
@pytest.mark.django_db
def test_resolver_hides_other_owners_ride_and_defaults(kind, garage):
    foreign = create_manual_ride(garage.other, started_at=instant())
    ride_id = foreign.pk if kind == "foreign" else uuid.uuid4() if kind == "missing" else "bad"
    with pytest.raises(InventoryNotFound):
        resolve_ride_usage(garage.owner, ride_id)


@pytest.mark.django_db(transaction=True)
def test_resolver_snapshot_owner_lock_blocks_membership_change_until_all_reads_finish(garage, monkeypatch):
    own_profile = profile(garage, [garage.helmet])
    own_ride = ride(garage)
    resolver_locked = Event()
    release_resolver = Event()
    writer_started = Event()
    writer_finished = Event()
    original = usage_profiles._resolve
    def paused_resolve(owner, own):
        resolver_locked.set()
        assert release_resolver.wait(timeout=10)
        return original(owner, own)
    monkeypatch.setattr(usage_profiles, "_resolve", paused_resolve)
    def read():
        close_old_connections()
        try:
            return resolve_ride_usage(garage.owner, own_ride.pk)
        finally:
            close_old_connections()
    def write():
        close_old_connections()
        try:
            writer_started.set()
            return update_profile_history(garage.owner, own_profile.pk, items=[garage.shoes])
        finally:
            writer_finished.set()
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        reading = pool.submit(read)
        assert resolver_locked.wait(timeout=10)
        writing = pool.submit(write)
        assert writer_started.wait(timeout=10)
        try:
            assert not writer_finished.wait(timeout=0.1)
        finally:
            release_resolver.set()
        resolved = reading.result(timeout=20)
        writing.result(timeout=20)
    assert resolved.item_ids == {garage.helmet.pk}
    assert resolve_ride_usage(garage.owner, own_ride.pk).item_ids == {garage.shoes.pk}
