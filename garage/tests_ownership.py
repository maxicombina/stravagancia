from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone as datetime_timezone
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch
import uuid

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, close_old_connections, connection
from django.utils import timezone

from .models import Bike, Category, Item
from .services import ownership
from .services.ownership import (CategoryNameConflict, InventoryNotFound, create_inventory, delete_inventory,
                                 get_inventory, reactivate_inventory, require_actor, retire_inventory,
                                 scoped_inventory, update_inventory)


@pytest.fixture
def users(db, django_user_model):
    return [django_user_model.objects.create_user(username=name) for name in ("service-alice", "service-bob")]


def values_for(model, owner, name="Equipment"):
    values = {"name": name}
    if model is Item:
        values["category"] = create_inventory(owner, Category, name=name + " category")
    return values


@pytest.mark.parametrize("model", [Bike, Category, Item])
@pytest.mark.django_db
def test_service_scoped_crud_keeps_other_users_inventory_private(model, users):
    own = create_inventory(users[0], model, **values_for(model, users[0], "Own resource"))
    foreign = create_inventory(users[1], model, **values_for(model, users[1], "Foreign resource"))
    assert list(scoped_inventory(users[0], model)) == [own]
    assert get_inventory(users[0], model, str(own.pk)) == own
    updated = update_inventory(users[0], model, own.pk, name="  Edited resource  ", notes="Personal")
    assert updated.pk == own.pk and updated.name == "Edited resource" and updated.owner == users[0]
    foreign.refresh_from_db()
    assert foreign.name == "Foreign resource"
    delete_inventory(users[0], model, own.pk)
    assert not scoped_inventory(users[0], model).exists()
    assert scoped_inventory(users[1], model).get() == foreign


@pytest.mark.parametrize("model", [Bike, Item])
@pytest.mark.django_db
def test_service_commercial_model_field_does_not_collide_with_resource_type(model, users):
    obj = create_inventory(users[0], model, **values_for(model, users[0]), brand="Example brand", model="Road 100")
    assert obj.model == "Road 100"
    obj = update_inventory(users[0], model, obj.pk, model="Road 200")
    obj.refresh_from_db()
    assert obj.model == "Road 200" and obj.brand == "Example brand"


@pytest.mark.parametrize("model", [Bike, Category, Item])
@pytest.mark.parametrize("operation", ["get", "update", "delete"])
@pytest.mark.django_db
def test_service_foreign_unknown_and_invalid_ids_have_same_not_found_error(model, operation, users):
    foreign = create_inventory(users[1], model, **values_for(model, users[1], "SECRET"))
    messages = []
    for resource_id in (foreign.pk, uuid.uuid4(), "bad-uuid", None):
        with pytest.raises(InventoryNotFound) as error:
            if operation == "get":
                get_inventory(users[0], model, resource_id)
            elif operation == "update":
                update_inventory(users[0], model, resource_id, name="FORGED")
            else:
                delete_inventory(users[0], model, resource_id)
        assert error.value.code == "resource_not_found"
        messages.append(str(error.value))
    assert len(set(messages)) == 1
    foreign.refresh_from_db()
    assert foreign.name == "SECRET" and foreign.owner == users[1]


@pytest.mark.parametrize("kind", ["none", "anonymous", "unsaved", "inactive", "deleted", "stale_inactive"])
@pytest.mark.parametrize("operation", ["list", "get", "create", "update", "delete", "retire", "reactivate"])
@pytest.mark.django_db
def test_service_rejects_missing_unknown_or_inactive_actor(kind, operation, users, django_user_model):
    obj = create_inventory(users[0], Bike, name="Existing")
    if kind == "none":
        actor = None
    elif kind == "anonymous":
        actor = AnonymousUser()
    elif kind == "unsaved":
        actor = django_user_model(username="Unsaved")
    else:
        actor = django_user_model.objects.create_user(username="invalid-actor", is_active=kind != "inactive")
        if kind == "deleted":
            pk = actor.pk
            actor.delete()
            actor.pk = pk
        elif kind == "stale_inactive":
            django_user_model.objects.filter(pk=actor.pk).update(is_active=False)
    with pytest.raises(PermissionDenied):
        if operation == "list":
            scoped_inventory(actor, Bike)
        elif operation == "get":
            get_inventory(actor, Bike, obj.pk)
        elif operation == "create":
            create_inventory(actor, Bike, name="Forbidden")
        elif operation == "update":
            update_inventory(actor, Bike, obj.pk, name="Forbidden")
        elif operation == "delete":
            delete_inventory(actor, Bike, obj.pk)
        elif operation == "retire":
            retire_inventory(actor, Bike, obj.pk, at=timezone.now())
        else:
            reactivate_inventory(actor, Bike, obj.pk)
    obj.refresh_from_db()
    assert obj.name == "Existing" and obj.retired_at is None
    assert not Bike.objects.filter(name="Forbidden").exists()


@pytest.mark.django_db
def test_unauthenticated_actor_is_rejected_before_any_queries(django_assert_num_queries):
    with django_assert_num_queries(0), pytest.raises(PermissionDenied):
        scoped_inventory(AnonymousUser(), Bike)


@pytest.mark.django_db
def test_superuser_uses_same_scope_as_every_other_actor(users):
    users[0].is_superuser = True
    users[0].save()
    own = create_inventory(users[0], Bike, name="Own")
    foreign = create_inventory(users[1], Bike, name="Foreign")
    assert list(scoped_inventory(users[0], Bike)) == [own]
    with pytest.raises(InventoryNotFound):
        update_inventory(users[0], Bike, foreign.pk, name="Forbidden")


@pytest.mark.parametrize("field", ["owner", "owner_id", "id", "pk", "created_at", "updated_at", "__dict__"])
@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.django_db
def test_service_rejects_identity_owner_and_arbitrary_attribute_assignment(field, operation, users):
    obj = create_inventory(users[0], Bike, name="Original")
    supplied = users[1] if field == "owner" else str(uuid.uuid4())
    with pytest.raises(ValidationError) as error:
        if operation == "create":
            create_inventory(users[0], Bike, name="Forged", **{field: supplied})
        else:
            update_inventory(users[0], Bike, obj.pk, name="Forged", **{field: supplied})
    code = "invalid_field" if field == "__dict__" else "immutable_field"
    assert error.value.error_dict[field][0].code == code
    obj.refresh_from_db()
    assert obj.name == "Original" and obj.owner == users[0]
    assert not Bike.objects.filter(name="Forged").exists()


@pytest.mark.parametrize("representation", ["object", "uuid", "string"])
@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.django_db
def test_service_category_is_resolved_by_actor_and_not_client_object_state(representation, operation, users):
    foreign = create_inventory(users[1], Category, name="SECRET foreign category")
    own = create_inventory(users[0], Item, **values_for(Item, users[0]))
    reference = foreign if representation == "object" else foreign.pk if representation == "uuid" else str(foreign.pk)
    if representation == "object":
        foreign.owner = users[0]  # A forged in-memory owner does not authorize its UUID.
    for category in (reference, uuid.uuid4(), "invalid"):
        with pytest.raises(ValidationError) as error:
            if operation == "create":
                create_inventory(users[0], Item, name="Forbidden", category=category)
            else:
                update_inventory(users[0], Item, own.pk, name="Forbidden", category=category)
        assert error.value.error_dict["category"][0].code == "invalid_reference"
    own.refresh_from_db()
    assert own.name == "Equipment" and own.category.owner == users[0]
    assert not Item.objects.filter(name="Forbidden").exists()


@pytest.mark.django_db
def test_service_uses_real_category_values_and_allows_owned_category_changes(users):
    category = create_inventory(users[0], Category, name="First")
    second = create_inventory(users[0], Category, name="Second")
    category.owner = users[1]  # Stale object attributes cannot transfer a relationship.
    item = create_inventory(users[0], Item, name="Owned", category=category)
    assert item.category.owner == users[0]
    item = update_inventory(users[0], Item, item.pk, category=str(second.pk))
    assert item.category == second


@pytest.mark.parametrize("model", [Bike, Item])
@pytest.mark.parametrize("amount,currency", [(Decimal("-1"), "EUR"), (Decimal("1"), None),
                                           (None, "EUR"), (Decimal("1"), "ZZZ"), (1.23, "EUR")])
@pytest.mark.django_db
def test_service_validation_precedes_writes_and_atomic_update_preserves_old_values(model, amount, currency, users):
    obj = create_inventory(users[0], model, **values_for(model, users[0]), notes="Original")
    with pytest.raises(ValidationError):
        update_inventory(users[0], model, obj.pk, name="Forbidden", notes="Changed",
                         purchase_amount=amount, purchase_currency=currency)
    obj.refresh_from_db()
    assert obj.name == "Equipment" and obj.notes == "Original"
    assert obj.purchase_amount is None and obj.purchase_currency is None


@pytest.mark.parametrize("model", [Bike, Item])
@pytest.mark.django_db
def test_service_retirement_reactivation_and_acquisition_correction_preserve_identity(model, users):
    anchor = datetime(2025, 1, 1, tzinfo=datetime_timezone.utc)
    obj = create_inventory(users[0], model, **values_for(model, users[0]), acquisition_anchor_at=anchor)
    identity, created_at = obj.pk, obj.created_at
    at = timezone.now()
    retired = retire_inventory(users[0], model, identity, at=at)
    assert retired.pk == identity and retired.retired_at == at and retired.created_at == created_at
    restored = reactivate_inventory(users[0], model, identity)
    assert restored.pk == identity and restored.retired_at is None and restored.acquisition_anchor_at == anchor
    with pytest.raises(InventoryNotFound):
        retire_inventory(users[1], model, identity, at=at)
    with pytest.raises(InventoryNotFound):
        reactivate_inventory(users[1], model, identity)


@pytest.mark.parametrize("at", [None, "2026-01-01", datetime(2026, 1, 1)])
@pytest.mark.django_db
def test_service_retirement_rejects_unknown_or_naive_instant(at, users):
    obj = create_inventory(users[0], Bike, name="Owned")
    with pytest.raises(ValidationError) as error:
        retire_inventory(users[0], Bike, obj.pk, at=at)
    assert error.value.error_dict["retired_at"][0].code == "invalid_instant"
    obj.refresh_from_db()
    assert obj.retired_at is None


@pytest.mark.parametrize("field", ["retired_at", "acquisition_anchor_at"])
@pytest.mark.parametrize("value", [date(2026, 1, 1), datetime(2026, 1, 1), "2026-01-01", "2026-01-01T12:00:00+02:00"])
@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.django_db
def test_service_requires_datetime_instants_before_django_field_coercion(field, value, operation, users):
    obj = create_inventory(users[0], Bike, name="Existing")
    with pytest.raises(ValidationError) as error:
        if operation == "create":
            create_inventory(users[0], Bike, name="Forbidden", **{field: value})
        else:
            update_inventory(users[0], Bike, obj.pk, name="Forbidden", **{field: value})
    assert error.value.error_dict[field][0].code == "invalid_instant"
    obj.refresh_from_db()
    assert obj.name == "Existing" and obj.retired_at is None and obj.acquisition_anchor_at is None
    assert not Bike.objects.filter(name="Forbidden").exists()


@pytest.mark.django_db
def test_service_protected_delete_is_safe_and_does_not_expose_referenced_objects(users):
    category = create_inventory(users[0], Category, name="Owned category")
    item = create_inventory(users[0], Item, name="Secret item", category=category)
    with pytest.raises(ValidationError) as error:
        delete_inventory(users[0], Category, category.pk)
    assert error.value.code == "resource_protected"
    assert "Secret item" not in str(error.value)
    assert get_inventory(users[0], Category, category.pk) == category
    assert get_inventory(users[0], Item, item.pk) == item


@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.django_db
def test_service_category_duplicate_error_is_consistent_and_does_not_mutate(operation, users):
    first = create_inventory(users[0], Category, name=" Wheels ")
    second = create_inventory(users[0], Category, name="Other")
    with pytest.raises(CategoryNameConflict) as error:
        if operation == "create":
            create_inventory(users[0], Category, name="WHEELS")
        else:
            update_inventory(users[0], Category, second.pk, name="wHeElS", notes="Forbidden")
    assert error.value.error_dict["name"][0].code == "category_name_conflict"
    second.refresh_from_db()
    assert second.name == "Other" and second.notes == ""
    assert first.name == "Wheels"
    create_inventory(users[1], Category, name="wheels")


@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.django_db
def test_database_category_race_translates_named_constraint_outside_savepoint(operation, users, monkeypatch):
    first = create_inventory(users[0], Category, name="Wheels")
    second = create_inventory(users[0], Category, name="Other")
    # Emulate a duplicate committed after optimistic validation: exercise the
    # actual PostgreSQL constraint rather than fabricate an IntegrityError.
    monkeypatch.setattr(ownership, "_validate_inventory", lambda obj: obj.full_clean(validate_constraints=False))
    with pytest.raises(CategoryNameConflict):
        if operation == "create":
            create_inventory(users[0], Category, name="WHEELS")
        else:
            update_inventory(users[0], Category, second.pk, name="WHEELS", notes="Forbidden")
    assert not connection.needs_rollback
    second.refresh_from_db()
    assert second.name == "Other" and second.notes == ""
    assert get_inventory(users[0], Category, first.pk) == first
    create_inventory(users[0], Bike, name="Transaction still usable")


@pytest.mark.django_db
def test_unrecognized_integrity_error_is_not_hidden_and_transaction_remains_usable(users):
    error = IntegrityError("synthetic unexpected constraint")
    with patch.object(Bike, "save", side_effect=error), pytest.raises(IntegrityError) as raised:
        create_inventory(users[0], Bike, name="Failed")
    assert raised.value is error
    assert not connection.needs_rollback and not Bike.objects.filter(name="Failed").exists()
    create_inventory(users[0], Bike, name="After failure")


@pytest.mark.django_db(transaction=True)
def test_concurrent_category_creation_serializes_owner_and_returns_one_consistent_conflict(django_user_model):
    actor = django_user_model.objects.create_user(username="concurrent-owner")
    barrier = Barrier(2)

    def worker(name):
        close_old_connections()
        try:
            local_actor = django_user_model.objects.get(pk=actor.pk)
            barrier.wait(timeout=10)
            try:
                return create_inventory(local_actor, Category, name=name).pk
            except CategoryNameConflict:
                return "category_name_conflict"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker, name) for name in ("Wheels", "wheels")]
        outcomes = [future.result(timeout=15) for future in futures]
    assert outcomes.count("category_name_conflict") == 1
    assert Category.objects.filter(owner=actor).count() == 1
    assert any(isinstance(result, uuid.UUID) for result in outcomes)
