from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone as datetime_timezone
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch
import uuid

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, IntegrityError, OperationalError, close_old_connections, connection, transaction

from .models import Bike, Category, Installation, Item
from .services.installations import (close_installation, create_installation, delete_installation,
                                    replace_installation, transfer_installation, update_installation)
from .services.ownership import (InventoryNotFound, InventoryWriteError, create_inventory, delete_inventory,
                                 get_inventory, reactivate_inventory, retire_inventory, scoped_inventory,
                                 update_inventory)


def instant(day, hour=0):
    return datetime(2026, 1, day, hour, tzinfo=datetime_timezone.utc)


@pytest.fixture
def garage(db, django_user_model):
    owner = django_user_model.objects.create_user(username="installation-owner")
    other = django_user_model.objects.create_user(username="installation-other")
    category = create_inventory(owner, Category, name="Components")
    bikes = [create_inventory(owner, Bike, name=f"Bike {n}") for n in range(2)]
    items = [create_inventory(owner, Item, name=f"Item {n}", category=category) for n in range(6)]
    foreign_category = create_inventory(other, Category, name="Components")
    foreign_bike = create_inventory(other, Bike, name="SECRET bike")
    foreign_item = create_inventory(other, Item, name="SECRET item", category=foreign_category)
    return SimpleNamespace(owner=owner, other=other, category=category, bikes=bikes, items=items,
                           foreign_bike=foreign_bike, foreign_item=foreign_item)


def values(garage, *, item=0, bike=0, parent=None, start=1, end=None, slot=None):
    return {"item": garage.items[item], "bike": garage.bikes[bike] if bike is not None else None,
            "parent_item": garage.items[parent] if parent is not None else None,
            "started_at": instant(start), "ended_at": instant(end) if end is not None else None, "slot": slot}


def mount(garage, **kwargs):
    return create_installation(garage.owner, **values(garage, **kwargs))


def error_code(error, field):
    return error.value.error_dict[field][0].code


@pytest.mark.django_db
def test_a_b_a_replacements_and_adjacent_boundaries_preserve_physical_identity(garage):
    first = mount(garage, item=0, slot="main_saddle")
    closed, second = replace_installation(garage.owner, first.pk, incoming_item=garage.items[1], at=instant(10))
    closed_second, third = replace_installation(garage.owner, second.pk, incoming_item=garage.items[0], at=instant(20))
    assert closed.pk == first.pk and closed.ended_at == instant(10)
    assert closed_second.ended_at == instant(20)
    assert second.started_at == instant(10) and third.started_at == instant(20) and third.ended_at is None
    assert len({first.pk, second.pk, third.pk}) == 3
    assert list(Installation.objects.filter(item=garage.items[0]).values_list("started_at", "ended_at")) == [
        (instant(1), instant(10)), (instant(20), None)]
    assert Item.objects.filter(pk__in=[garage.items[0].pk, garage.items[1].pk]).count() == 2


@pytest.mark.django_db
def test_front_rear_and_unslotted_items_are_independent_of_shared_category(garage):
    front = mount(garage, item=0, slot="front_wheel")
    rear = mount(garage, item=1, slot="rear_wheel")
    unslotted = mount(garage, item=2)
    another_unslotted = mount(garage, item=3, slot="")
    assert another_unslotted.slot is None and unslotted.slot is None
    assert front.item.category == rear.item.category
    assert Installation.objects.count() == 4
    with pytest.raises(InventoryWriteError) as error:
        mount(garage, item=4, slot="front_wheel")
    assert error_code(error, "slot") == "slot_occupied"
    assert not connection.needs_rollback


@pytest.mark.parametrize("destination", ["bike", "parent"])
@pytest.mark.django_db
def test_slot_exclusivity_is_local_to_destination_and_half_open_period(garage, destination):
    destination_values = {"bike": 0} if destination == "bike" else {"bike": None, "parent": 2}
    first = mount(garage, item=0, end=3, slot="front", **destination_values)
    adjacent = mount(garage, item=1, start=3, end=5, slot="front", **destination_values)
    elsewhere = {"bike": 1} if destination == "bike" else {"bike": None, "parent": 3}
    mount(garage, item=4, end=3, slot="front", **elsewhere)
    assert first.ended_at == adjacent.started_at
    with pytest.raises(InventoryWriteError) as error:
        mount(garage, item=5, start=2, end=4, slot="front", **destination_values)
    assert error_code(error, "slot") == "slot_occupied"


@pytest.mark.django_db
def test_item_cannot_overlap_across_bike_and_parent_destinations(garage):
    original = mount(garage, item=0, end=4)
    with pytest.raises(InventoryWriteError) as error:
        mount(garage, item=0, bike=None, parent=2, start=3, end=5)
    assert error_code(error, "item") == "installation_overlap"
    adjacent = mount(garage, item=0, bike=None, parent=2, start=4, end=5)
    assert adjacent.started_at == original.ended_at


@pytest.mark.parametrize("violation,constraint", [
    ("neither", "garage_installation_one_destination"),
    ("both", "garage_installation_one_destination"),
    ("self", "garage_installation_not_own_parent"),
    ("empty_interval", "garage_installation_positive_interval"),
    ("reverse_interval", None), ("blank_slot", "garage_installation_canonical_slot"),
    ("uppercase_slot", "garage_installation_canonical_slot"),
    ("newline_slot", "garage_installation_canonical_slot"),
])
@pytest.mark.django_db
def test_sql_row_constraints_reject_direct_orm_bypass(garage, violation, constraint):
    data = values(garage, start=2, end=4)
    if violation == "neither":
        data["bike"] = None
    elif violation == "both":
        data["parent_item"] = garage.items[2]
    elif violation == "self":
        data.update(bike=None, parent_item=garage.items[0])
    elif violation == "empty_interval":
        data["ended_at"] = instant(2)
    elif violation == "reverse_interval":
        data["ended_at"] = instant(1)
    else:
        data["slot"] = {"blank_slot": "", "uppercase_slot": "Front", "newline_slot": "front\n"}[violation]
    with pytest.raises(DatabaseError) as error, transaction.atomic():
        Installation.objects.create(owner=garage.owner, **data)
    if constraint:
        assert isinstance(error.value, IntegrityError)
        assert error.value.__cause__.diag.constraint_name == constraint
    assert not Installation.objects.exists()


@pytest.mark.parametrize("kind,constraint", [
    ("item", "garage_installation_item_no_overlap"),
    ("bike_slot", "garage_installation_bike_slot_no_overlap"),
    ("parent_slot", "garage_installation_parent_slot_no_overlap"),
])
@pytest.mark.django_db
def test_sql_exclusions_enforce_real_ranges_without_model_clean(garage, kind, constraint):
    first = values(garage, item=0, start=1, end=3, slot="position")
    second = values(garage, item=1, start=2, end=4, slot="position")
    if kind == "item":
        second.update(item=garage.items[0], bike=garage.bikes[1], slot="other")
    elif kind == "parent_slot":
        first.update(bike=None, parent_item=garage.items[2])
        second.update(bike=None, parent_item=garage.items[2])
    Installation.objects.create(owner=garage.owner, **first)
    with pytest.raises(IntegrityError) as error, transaction.atomic():
        Installation.objects.create(owner=garage.owner, **second)
    assert error.value.__cause__.diag.constraint_name == constraint
    assert Installation.objects.count() == 1


@pytest.mark.parametrize("slot", ["Front", "front wheel", "ñ", "front\n", "a" * 81, 123])
@pytest.mark.django_db
def test_service_rejects_noncanonical_slots_before_write(garage, slot):
    with pytest.raises(InventoryWriteError) as error:
        create_installation(garage.owner, **(values(garage) | {"slot": slot}))
    assert error_code(error, "slot") == "invalid_slot"
    assert not Installation.objects.exists()


@pytest.mark.parametrize("field", ["started_at", "ended_at"])
@pytest.mark.parametrize("value", [datetime(2026, 1, 1), date(2026, 1, 1), "2026-01-01T00:00:00Z"])
@pytest.mark.django_db
def test_installation_instants_require_aware_datetimes(garage, field, value):
    with pytest.raises(InventoryWriteError) as error:
        create_installation(garage.owner, **(values(garage) | {field: value}))
    assert error_code(error, field) == "invalid_instant"


@pytest.mark.parametrize("destination", ["none", "both", "self"])
@pytest.mark.django_db
def test_service_rejects_invalid_destinations_and_self_parent(garage, destination):
    data = values(garage, bike=None if destination != "both" else 0,
                  parent=0 if destination == "self" else 2 if destination == "both" else None)
    with pytest.raises(InventoryWriteError) as error:
        create_installation(garage.owner, **data)
    field = "parent_item" if destination == "self" else "bike"
    assert error_code(error, field) == ("installation_cycle" if destination == "self" else "invalid_destination")
    assert not Installation.objects.exists()


@pytest.mark.parametrize("end", [instant(1), datetime(2025, 12, 31, tzinfo=datetime_timezone.utc)])
@pytest.mark.django_db
def test_zero_interval_rejected_with_service_error(garage, end):
    with pytest.raises(InventoryWriteError) as error:
        create_installation(garage.owner, **(values(garage) | {"ended_at": end}))
    assert error_code(error, "ended_at") == "invalid_interval"


@pytest.mark.django_db
def test_close_and_explicit_edit_preserve_identity_and_reject_bad_history(garage):
    original = mount(garage)
    closed = close_installation(garage.owner, original.pk, at=instant(3))
    assert closed.pk == original.pk and closed.ended_at == instant(3)
    assert close_installation(garage.owner, original.pk, at=instant(3)).pk == original.pk
    with pytest.raises(InventoryWriteError) as error:
        close_installation(garage.owner, original.pk, at=instant(4))
    assert error_code(error, "ended_at") == "installation_closed"
    updated = update_installation(garage.owner, original.pk, ended_at=instant(4), notes="Corrected")
    assert updated.pk == original.pk and updated.ended_at == instant(4) and updated.notes == "Corrected"
    with pytest.raises(InventoryWriteError):
        update_installation(garage.owner, original.pk, ended_at=instant(1), notes="Forbidden")
    updated.refresh_from_db()
    assert updated.notes == "Corrected" and updated.ended_at == instant(4)


@pytest.mark.django_db
def test_two_edge_cycles_rejected_only_when_periods_overlap(garage):
    mount(garage, item=0, bike=None, parent=1, start=1, end=2)
    historical = mount(garage, item=1, bike=None, parent=0, start=2, end=3)
    assert historical.pk is not None
    with pytest.raises(InventoryWriteError) as error:
        update_installation(garage.owner, historical.pk, started_at=instant(1, 12))
    assert error_code(error, "parent_item") == "installation_cycle"
    historical.refresh_from_db()
    assert historical.started_at == instant(2)


@pytest.mark.parametrize("overlap", [False, True])
@pytest.mark.django_db
def test_three_edge_cycle_requires_common_intersection_along_entire_path(garage, overlap):
    mount(garage, item=1, bike=None, parent=2, start=1, end=5 if overlap else 4)
    mount(garage, item=2, bike=None, parent=0, start=4, end=8)
    if overlap:
        with pytest.raises(InventoryWriteError) as error:
            mount(garage, item=0, bike=None, parent=1, start=1, end=10)
        assert error_code(error, "parent_item") == "installation_cycle"
        assert Installation.objects.count() == 2
    else:
        assert mount(garage, item=0, bike=None, parent=1, start=1, end=10).pk


@pytest.mark.django_db
def test_cycle_edit_excludes_old_edge_before_validating_new_graph(garage):
    original = mount(garage, item=0, bike=None, parent=1, start=1, end=3)
    mount(garage, item=1, bike=None, parent=0, start=3, end=5)
    changed = update_installation(garage.owner, original.pk, item=garage.items[1], parent_item=garage.items[0])
    assert changed.pk == original.pk and changed.item == garage.items[1] and changed.parent_item == garage.items[0]


@pytest.mark.django_db
def test_children_stay_mounted_on_detached_parent(garage):
    root = mount(garage, item=2)
    child = mount(garage, item=0, bike=None, parent=2)
    close_installation(garage.owner, root.pk, at=instant(3))
    child.refresh_from_db()
    assert child.ended_at is None and child.parent_item == garage.items[2]


@pytest.mark.parametrize("operation", ["replace", "transfer"])
@pytest.mark.django_db
def test_bounded_transitions_keep_future_history_instead_of_extending_to_infinity(garage, operation):
    first = mount(garage, item=0, end=4, slot="position")
    mount(garage, item=0 if operation == "transfer" else 1, bike=1, start=4, end=6)
    if operation == "replace":
        closed, incoming = replace_installation(garage.owner, first.pk, incoming_item=garage.items[1], at=instant(2))
    else:
        closed, incoming = transfer_installation(garage.owner, first.pk, bike=garage.bikes[1], at=instant(2))
    assert closed.ended_at == instant(2) and incoming.ended_at == instant(4)
    assert incoming.started_at == instant(2) and incoming.slot == "position"
    assert incoming.item == garage.items[1 if operation == "replace" else 0]


@pytest.mark.parametrize("operation", ["replace", "transfer"])
@pytest.mark.django_db
def test_transition_error_rolls_back_outgoing_close(garage, operation):
    original = mount(garage, item=0, slot="position")
    if operation == "replace":
        mount(garage, item=1, bike=1)
        invoke = lambda: replace_installation(garage.owner, original.pk, incoming_item=garage.items[1], at=instant(2))
    else:
        mount(garage, item=1, bike=1, slot="position")
        invoke = lambda: transfer_installation(garage.owner, original.pk, bike=garage.bikes[1], at=instant(2))
    with pytest.raises(InventoryWriteError):
        invoke()
    original.refresh_from_db()
    assert original.ended_at is None and Installation.objects.count() == 2
    assert not connection.needs_rollback


@pytest.mark.django_db
def test_transfer_forming_temporal_cycle_rolls_back_both_steps(garage):
    original = mount(garage, item=0)
    mount(garage, item=1, bike=None, parent=0)
    with pytest.raises(InventoryWriteError) as error:
        transfer_installation(garage.owner, original.pk, at=instant(2), parent_item=garage.items[1])
    assert error_code(error, "parent_item") == "installation_cycle"
    original.refresh_from_db()
    assert original.ended_at is None and Installation.objects.count() == 2


@pytest.mark.parametrize("incoming", ["foreign", "retired"])
@pytest.mark.django_db
def test_replacement_invalid_incoming_resource_rolls_back_closed_period(garage, incoming):
    original = mount(garage)
    item = garage.foreign_item if incoming == "foreign" else garage.items[1]
    if incoming == "retired":
        retire_inventory(garage.owner, Item, item.pk, at=instant(2))
    with pytest.raises(InventoryWriteError) as error:
        replace_installation(garage.owner, original.pk, incoming_item=item, at=instant(2))
    assert error_code(error, "item") == ("invalid_reference" if incoming == "foreign" else "resource_retired")
    original.refresh_from_db()
    assert original.ended_at is None and Installation.objects.count() == 1


@pytest.mark.django_db
def test_explicit_infinite_transfer_conflicting_with_future_history_is_rolled_back(garage):
    original = mount(garage, item=0, end=4)
    mount(garage, item=0, bike=1, start=4, end=6)
    with pytest.raises(InventoryWriteError) as error:
        transfer_installation(garage.owner, original.pk, bike=garage.bikes[1], at=instant(2), ended_at=None)
    assert error_code(error, "item") == "installation_overlap"
    original.refresh_from_db()
    assert original.ended_at == instant(4)


@pytest.mark.django_db
def test_replace_same_physical_item_creates_adjacent_periods_without_new_item(garage):
    original = mount(garage, item=0)
    closed, incoming = replace_installation(garage.owner, original.pk, incoming_item=garage.items[0], at=instant(2))
    assert closed.item_id == incoming.item_id == garage.items[0].pk
    assert closed.ended_at == incoming.started_at and closed.pk != incoming.pk


@pytest.mark.parametrize("at", [instant(1), instant(4), instant(5)])
@pytest.mark.django_db
def test_transition_rejects_empty_or_out_of_period_split(garage, at):
    original = mount(garage, end=4)
    with pytest.raises(InventoryWriteError) as error:
        transfer_installation(garage.owner, original.pk, at=at, bike=garage.bikes[1])
    assert error_code(error, "started_at") == "invalid_transition"
    original.refresh_from_db()
    assert original.ended_at == instant(4) and Installation.objects.count() == 1


@pytest.mark.parametrize("field", ["item", "bike", "parent_item"])
@pytest.mark.django_db
def test_foreign_related_uuid_or_forged_object_rejected(garage, field):
    reference = garage.foreign_bike if field == "bike" else garage.foreign_item
    reference.owner = garage.owner
    data = values(garage)
    if field == "parent_item":
        data["bike"] = None
    for value in (reference, reference.pk, str(reference.pk), uuid.uuid4()):
        with pytest.raises(InventoryWriteError) as error:
            create_installation(garage.owner, **(data | {field: value}))
        assert error_code(error, field) == "invalid_reference"
    assert not Installation.objects.exists()


@pytest.mark.parametrize("operation", ["update", "close", "delete", "replace", "transfer"])
@pytest.mark.django_db
def test_every_mutation_hides_foreign_and_unknown_installation_ids(garage, operation):
    original = mount(garage)
    errors = []
    for resource_id in (original.pk, uuid.uuid4(), "invalid"):
        with pytest.raises(InventoryNotFound) as error:
            if operation == "update":
                update_installation(garage.other, resource_id, notes="Forged")
            elif operation == "close":
                close_installation(garage.other, resource_id, at=instant(2))
            elif operation == "delete":
                delete_installation(garage.other, resource_id)
            elif operation == "replace":
                replace_installation(garage.other, resource_id, incoming_item=garage.foreign_item, at=instant(2))
            else:
                transfer_installation(garage.other, resource_id, bike=garage.foreign_bike, at=instant(2))
        errors.append(str(error.value))
    assert len(set(errors)) == 1
    original.refresh_from_db()
    assert original.notes == "" and original.ended_at is None


@pytest.mark.parametrize("field", ["owner", "owner_id", "id", "pk"])
@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.django_db
def test_installation_identity_and_owner_cannot_be_written(garage, field, operation):
    original = mount(garage)
    with pytest.raises(InventoryWriteError) as error:
        if operation == "create":
            create_installation(garage.owner, **(values(garage, item=1) | {field: str(uuid.uuid4())}))
        else:
            update_installation(garage.owner, original.pk, **{field: str(uuid.uuid4())})
    assert error_code(error, field) == "immutable_field"
    original.refresh_from_db()
    assert original.owner == garage.owner and Installation.objects.count() == 1


@pytest.mark.django_db
def test_installation_model_clean_rejects_owner_change_and_cross_owner_relationships(garage):
    original = mount(garage)
    original.owner = garage.other
    with pytest.raises(ValidationError) as error:
        original.full_clean()
    assert "owner" in error.value.message_dict
    original.refresh_from_db()
    original.bike = garage.foreign_bike
    with pytest.raises(ValidationError) as error:
        original.full_clean()
    assert error.value.error_dict["bike"][0].code == "invalid_reference"


@pytest.mark.parametrize("operation", ["create", "update", "close", "delete", "replace", "transfer"])
@pytest.mark.django_db
def test_installation_writes_reject_anonymous_actor_before_data_access(garage, operation):
    original = mount(garage)
    actor = AnonymousUser()
    with pytest.raises(PermissionDenied):
        if operation == "create":
            create_installation(actor, **values(garage))
        elif operation == "update":
            update_installation(actor, original.pk, notes="Forged")
        elif operation == "close":
            close_installation(actor, original.pk, at=instant(2))
        elif operation == "delete":
            delete_installation(actor, original.pk)
        elif operation == "replace":
            replace_installation(actor, original.pk, incoming_item=garage.items[1], at=instant(2))
        else:
            transfer_installation(actor, original.pk, bike=garage.bikes[1], at=instant(2))
    original.refresh_from_db()
    assert original.ended_at is None and original.notes == ""


@pytest.mark.django_db
def test_scoped_installation_reads_and_generic_inventory_write_bypass_rejected(garage):
    original = mount(garage)
    assert list(scoped_inventory(garage.owner, Installation)) == [original]
    assert not scoped_inventory(garage.other, Installation).exists()
    with pytest.raises(InventoryNotFound):
        get_inventory(garage.other, Installation, original.pk)
    with pytest.raises(TypeError):
        create_inventory(garage.owner, Installation, **values(garage))
    with pytest.raises(TypeError):
        update_inventory(garage.owner, Installation, original.pk, ended_at=instant(2))
    delete_installation(garage.owner, original.pk)
    assert not Installation.objects.exists()


@pytest.mark.parametrize("resource", ["bike", "item", "parent_item"])
@pytest.mark.parametrize("period", ["historical", "open", "late_end", "at_retirement"])
@pytest.mark.django_db
def test_retired_resources_accept_only_history_strictly_before_retirement(garage, resource, period):
    model = Bike if resource == "bike" else Item
    obj = garage.bikes[0] if resource == "bike" else garage.items[0] if resource == "item" else garage.items[2]
    retire_inventory(garage.owner, model, obj.pk, at=instant(4))
    data = values(garage, parent=2 if resource == "parent_item" else None,
                  bike=None if resource == "parent_item" else 0,
                  start=4 if period == "at_retirement" else 1,
                  end=4 if period == "historical" else 5 if period in ("late_end", "at_retirement") else None)
    if period == "historical":
        historical = create_installation(garage.owner, **data)
        assert get_inventory(garage.owner, Installation, historical.pk).ended_at == instant(4)
    else:
        with pytest.raises(InventoryWriteError) as error:
            create_installation(garage.owner, **data)
        assert error_code(error, resource) == "resource_retired"


@pytest.mark.django_db
def test_retiring_parent_closes_own_installation_and_direct_children_without_erasing_grandchildren(garage):
    parent = mount(garage, item=2)
    child = mount(garage, item=0, bike=None, parent=2)
    grandchild = mount(garage, item=4, bike=None, parent=0)
    retired = update_inventory(garage.owner, Item, garage.items[2].pk, retired_at=instant(3))
    assert retired.pk == garage.items[2].pk and retired.retired_at == instant(3)
    for installation in (parent, child):
        installation.refresh_from_db()
        assert installation.ended_at == instant(3)
    grandchild.refresh_from_db()
    assert grandchild.ended_at is None
    reactivate_inventory(garage.owner, Item, retired.pk)
    child.refresh_from_db()
    assert child.ended_at == instant(3)


@pytest.mark.django_db
def test_retiring_bike_closes_roots_but_children_remain_on_detached_parent(garage):
    root = mount(garage, item=2)
    child = mount(garage, item=0, bike=None, parent=2)
    retire_inventory(garage.owner, Bike, garage.bikes[0].pk, at=instant(3))
    root.refresh_from_db()
    child.refresh_from_db()
    assert root.ended_at == instant(3) and child.ended_at is None


@pytest.mark.django_db
def test_retirement_correction_keeps_earlier_history_and_rejects_truncation(garage):
    original = mount(garage, end=3)
    retire_inventory(garage.owner, Bike, garage.bikes[0].pk, at=instant(4))
    with pytest.raises(InventoryWriteError) as error:
        update_inventory(garage.owner, Bike, garage.bikes[0].pk, retired_at=instant(2))
    assert error_code(error, "retired_at") == "retirement_conflict"
    original.refresh_from_db()
    garage.bikes[0].refresh_from_db()
    assert original.ended_at == instant(3) and garage.bikes[0].retired_at == instant(4)
    corrected = update_inventory(garage.owner, Bike, garage.bikes[0].pk, retired_at=instant(3))
    assert corrected.retired_at == instant(3) and original.ended_at == instant(3)


@pytest.mark.parametrize("history", ["at_start", "future_open", "future_closed", "closed_spanning"])
@pytest.mark.django_db
def test_retroactive_retirement_rejects_history_and_rolls_back_every_open_installation(garage, history):
    ongoing = mount(garage, item=0, start=1)
    if history == "at_start":
        conflicting = mount(garage, item=1, start=3)
    elif history == "future_open":
        conflicting = mount(garage, item=1, start=4)
    elif history == "future_closed":
        conflicting = mount(garage, item=1, start=4, end=5)
    else:
        conflicting = mount(garage, item=1, start=1, end=4)
    with pytest.raises(InventoryWriteError) as error:
        update_inventory(garage.owner, Bike, garage.bikes[0].pk, retired_at=instant(3), name="Forbidden")
    assert error_code(error, "retired_at") == "retirement_conflict"
    ongoing.refresh_from_db()
    conflicting.refresh_from_db()
    garage.bikes[0].refresh_from_db()
    assert ongoing.ended_at is None
    assert conflicting.ended_at == (instant(5) if history == "future_closed" else instant(4) if history == "closed_spanning" else None)
    assert garage.bikes[0].retired_at is None and garage.bikes[0].name == "Bike 0"


@pytest.mark.django_db
def test_retirement_unexpected_failure_after_closing_rolls_back_inventory_and_history(garage):
    original = mount(garage)
    with patch.object(Bike, "save", side_effect=IntegrityError("unexpected failure")), pytest.raises(IntegrityError):
        retire_inventory(garage.owner, Bike, garage.bikes[0].pk, at=instant(3))
    original.refresh_from_db()
    garage.bikes[0].refresh_from_db()
    assert original.ended_at is None and garage.bikes[0].retired_at is None
    assert not connection.needs_rollback


@pytest.mark.parametrize("model,resource", [(Bike, "bike"), (Item, "item"), (Item, "parent")])
@pytest.mark.django_db
def test_installation_history_protects_inventory_from_physical_deletion(garage, model, resource):
    installation = mount(garage, bike=None if resource == "parent" else 0,
                         parent=2 if resource == "parent" else None, end=3)
    obj = garage.bikes[0] if resource == "bike" else garage.items[2] if resource == "parent" else garage.items[0]
    with pytest.raises(ValidationError) as error:
        delete_inventory(garage.owner, model, obj.pk)
    assert error.value.code == "resource_protected"
    assert get_inventory(garage.owner, Installation, installation.pk)


def parallel(garage, operations):
    barrier = Barrier(len(operations))

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

    with ThreadPoolExecutor(max_workers=len(operations)) as executor:
        futures = [executor.submit(worker, operation) for operation in operations]
        return [future.result(timeout=15) for future in futures]


@pytest.mark.parametrize("conflict", ["cycle", "slot", "item", "replacement"])
@pytest.mark.django_db(transaction=True)
def test_two_connections_serialize_cycle_slot_item_and_replacement_mutations(garage, conflict):
    if conflict == "cycle":
        operations = [lambda: mount(garage, item=0, bike=None, parent=1),
                      lambda: mount(garage, item=1, bike=None, parent=0)]
        expected = "installation_cycle"
    elif conflict == "slot":
        operations = [lambda: mount(garage, item=0, slot="position"), lambda: mount(garage, item=1, slot="position")]
        expected = "slot_occupied"
    elif conflict == "item":
        operations = [lambda: mount(garage, item=0, bike=0), lambda: mount(garage, item=0, bike=1)]
        expected = "installation_overlap"
    else:
        original = mount(garage, item=0)
        operations = [lambda: replace_installation(garage.owner, original.pk, incoming_item=garage.items[1], at=instant(2)),
                      lambda: replace_installation(garage.owner, original.pk, incoming_item=garage.items[2], at=instant(2))]
        expected = "invalid_transition"
    outcomes = parallel(garage, operations)
    assert outcomes.count(expected) == 1
    assert Installation.objects.count() == (2 if conflict == "replacement" else 1)
    assert sum(isinstance(result, (Installation, tuple)) for result in outcomes) == 1


@pytest.mark.parametrize("conflict", ["item", "bike_slot", "parent_slot"])
@pytest.mark.django_db(transaction=True)
def test_two_connections_sql_exclusions_protect_writers_without_service_owner_lock(garage, conflict):
    barrier = Barrier(2)
    first = values(garage, item=0, slot="position")
    second = values(garage, item=1, slot="position")
    if conflict == "item":
        second.update(item=garage.items[0], bike=garage.bikes[1])
    elif conflict == "parent_slot":
        first.update(bike=None, parent_item=garage.items[2])
        second.update(bike=None, parent_item=garage.items[2])

    def writer(data):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                with transaction.atomic():
                    return Installation.objects.create(owner=garage.owner, **data).pk
            except IntegrityError as error:
                return error.__cause__.diag.constraint_name
            except OperationalError as error:
                # Simultaneous raw GiST exclusion checks can deadlock: PostgreSQL
                # aborts one transaction with 40P01. Authorized writes avoid this
                # through the owner lock; this test also verifies the raw rule.
                if getattr(error.__cause__, "pgcode", None) != "40P01":
                    raise
                return "raw_deadlock_40P01"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(writer, data) for data in (first, second)]
        outcomes = [future.result(timeout=15) for future in futures]
    expected = {"item": "garage_installation_item_no_overlap", "bike_slot": "garage_installation_bike_slot_no_overlap",
                "parent_slot": "garage_installation_parent_slot_no_overlap"}[conflict]
    assert Installation.objects.count() == 1
    assert sum(isinstance(outcome, uuid.UUID) for outcome in outcomes) == 1
    failures = [outcome for outcome in outcomes if not isinstance(outcome, uuid.UUID)]
    assert len(failures) == 1 and failures[0] in (expected, "raw_deadlock_40P01")
    # Both transactions have finished. Retrying the loser must now report the
    # named exclusion constraint, proving the rule even when GiST chose 40P01.
    losing_data = (first, second)[next(index for index, outcome in enumerate(outcomes) if not isinstance(outcome, uuid.UUID))]
    with pytest.raises(IntegrityError) as error, transaction.atomic():
        Installation.objects.create(owner=garage.owner, **losing_data)
    assert error.value.__cause__.diag.constraint_name == expected
    assert Installation.objects.count() == 1
