from datetime import datetime, timezone as datetime_timezone
import uuid

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from .forms import BikeForm, CategoryForm, ItemForm
from .models import Bike, Category, Item
from .services.installations import create_installation
from .services.ownership import CategoryNameConflict, InventoryNotFound, create_inventory


@pytest.fixture
def users(db, django_user_model):
    return [django_user_model.objects.create_user(username=name) for name in ("form-alice", "form-bob")]


FORM_MODELS = [(BikeForm, Bike), (CategoryForm, Category), (ItemForm, Item)]


def form_data(model, owner, name="Own resource"):
    data = {"name": name}
    if model is Item:
        data["category"] = str(create_inventory(owner, Category, name=name + " category").pk)
    return data


@pytest.mark.parametrize("form_class,model", FORM_MODELS)
@pytest.mark.django_db
def test_form_creation_ignores_forged_owner_uuid_and_follows_authorized_service(form_class, model, users):
    forged_id = uuid.uuid4()
    data = form_data(model, users[0]) | {"owner": users[1].pk, "id": str(forged_id)}
    if model in (Bike, Item):
        data.update(brand="Example brand", model="Commercial model")
    form = form_class(data=data, user=users[0])
    assert "owner" not in form.fields and "id" not in form.fields
    assert form.is_valid(), form.errors
    result = form.save()
    assert result.owner == users[0] and result.pk != forged_id
    assert model.objects.get(pk=result.pk).name == "Own resource"
    if model in (Bike, Item):
        assert result.brand == "Example brand" and result.model == "Commercial model"


@pytest.mark.parametrize("form_class,model", FORM_MODELS)
@pytest.mark.django_db
def test_form_own_update_uses_original_identity_and_database_owner(form_class, model, users):
    data = form_data(model, users[0])
    values = {"name": data["name"]}
    if model is Item:
        values["category"] = data["category"]
    obj = create_inventory(users[0], model, **values)
    original_id = obj.pk
    form = form_class(data=data | {"name": "Edited", "owner": users[1].pk, "id": str(uuid.uuid4())},
                      user=users[0], instance=obj)
    assert form.is_valid(), form.errors
    form.instance.pk = uuid.uuid4()
    form.instance.owner = users[1]
    result = form.save()
    assert result.pk == original_id and result.owner == users[0] and result.name == "Edited"
    assert model.objects.filter(owner=users[0]).count() == 1


@pytest.mark.parametrize("form_class,model", FORM_MODELS)
@pytest.mark.django_db
def test_form_foreign_persisted_instance_cannot_be_retagged_even_when_owner_forged(form_class, model, users):
    values = {"name": "SECRET"}
    if model is Item:
        values["category"] = create_inventory(users[1], Category, name="Foreign category")
    obj = create_inventory(users[1], model, **values)
    obj.owner = users[0]
    with pytest.raises(InventoryNotFound):
        form_class(data={"name": "Forged"}, user=users[0], instance=obj)
    obj.refresh_from_db()
    assert obj.owner == users[1] and obj.name == "SECRET"


@pytest.mark.parametrize("form_class,model", FORM_MODELS)
@pytest.mark.django_db
def test_form_supplied_unsaved_instance_is_rejected(form_class, model, users):
    obj = model(owner=users[1], name="Forged", pk=uuid.uuid4())
    with pytest.raises(PermissionDenied):
        form_class(user=users[0], instance=obj)
    assert not model.objects.filter(pk=obj.pk).exists()


@pytest.mark.parametrize("form_class,model", FORM_MODELS)
@pytest.mark.parametrize("invalid", ["anonymous", "none", "inactive", "deleted"])
@pytest.mark.django_db
def test_forms_require_authenticated_active_persisted_user(form_class, model, invalid, users, django_user_model):
    if invalid == "anonymous":
        user = AnonymousUser()
    elif invalid == "none":
        user = None
    else:
        user = django_user_model.objects.create_user(username="invalid-form-user", is_active=invalid != "inactive")
        if invalid == "deleted":
            user.delete()
    with pytest.raises(PermissionDenied):
        form_class(data={"name": "Forbidden"}, user=user)
    assert not model.objects.filter(name="Forbidden").exists()


@pytest.mark.parametrize("form_class,model", FORM_MODELS)
@pytest.mark.django_db
def test_form_commit_false_neither_creates_nor_modifies_database(form_class, model, users):
    data = form_data(model, users[0])
    form = form_class(data=data, user=users[0])
    assert form.is_valid(), form.errors
    candidate = form.save(commit=False)
    assert candidate.owner == users[0]
    assert not model.objects.filter(pk=candidate.pk).exists()
    saved = form.save()
    form = form_class(data=data | {"name": "Not yet saved"}, user=users[0], instance=saved)
    assert form.is_valid(), form.errors
    form.save(commit=False)
    saved.refresh_from_db()
    assert saved.name == "Own resource"


@pytest.mark.django_db
def test_item_form_category_choices_and_forged_uuid_scoped(users):
    own = create_inventory(users[0], Category, name="Own category")
    foreign = create_inventory(users[1], Category, name="SECRET category")
    form = ItemForm(data={"name": "Forbidden", "category": str(foreign.pk)}, user=users[0])
    assert list(form.fields["category"].queryset) == [own]
    assert not form.is_valid() and "category" in form.errors
    assert "SECRET category" not in str(form)
    with pytest.raises(ValueError):
        form.save()
    assert not Item.objects.exists()


@pytest.mark.parametrize("form_class,model", [(BikeForm, Bike), (ItemForm, Item)])
@pytest.mark.parametrize("money", [{"purchase_amount": "-1", "purchase_currency": "EUR"},
                                  {"purchase_amount": "1", "purchase_currency": ""},
                                  {"purchase_amount": "", "purchase_currency": "EUR"},
                                  {"purchase_amount": "1", "purchase_currency": "ZZZ"}])
@pytest.mark.django_db
def test_forms_reject_invalid_money_before_persistence(form_class, model, money, users):
    form = form_class(data=form_data(model, users[0]) | money, user=users[0])
    assert not form.is_valid()
    with pytest.raises(ValueError):
        form.save()
    assert not model.objects.filter(name="Own resource").exists()


@pytest.mark.django_db
def test_category_form_duplicate_error_matches_service_code_and_field(users):
    create_inventory(users[0], Category, name="Wheels")
    form = CategoryForm(data={"name": " wheels "}, user=users[0])
    assert not form.is_valid()
    assert form.errors.as_data()["name"][0].code == "category_name_conflict"
    assert Category.objects.filter(owner=users[0]).count() == 1


@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.django_db
def test_form_race_after_validation_attaches_service_error_and_preserves_database(operation, users):
    if operation == "update":
        original = create_inventory(users[0], Category, name="Original")
        form = CategoryForm(data={"name": "Raced", "notes": "Forbidden"}, user=users[0], instance=original)
    else:
        form = CategoryForm(data={"name": "Raced"}, user=users[0])
    assert form.is_valid(), form.errors
    create_inventory(users[0], Category, name="raced")
    with pytest.raises(CategoryNameConflict):
        form.save()
    assert form.errors.as_data()["name"][0].code == "category_name_conflict"
    if operation == "update":
        original.refresh_from_db()
        assert original.name == "Original" and original.notes == ""
    assert Category.objects.filter(owner=users[0], name__iexact="raced").count() == 1


@pytest.mark.parametrize("form_class,model", [(BikeForm, Bike), (ItemForm, Item)])
@pytest.mark.django_db
def test_datetime_form_labels_parsing_and_rendering_are_explicitly_utc(form_class, model, users):
    data = form_data(model, users[0]) | {"acquisition_anchor_at": "2026-03-29 02:30:00",
                                       "retired_at": "2026-10-25 02:30:00"}
    with timezone.override("Europe/Madrid"):
        form = form_class(data=data, user=users[0])
        assert form.is_valid(), form.errors
        assert "(UTC)" in form.fields["acquisition_anchor_at"].label
        assert "interpreted as UTC" in form.fields["acquisition_anchor_at"].help_text
        obj = form.save()
        initial = form_class(user=users[0], instance=obj)
        rendered = str(initial["acquisition_anchor_at"])
        assert 'value="2026-03-29 02:30:00"' in rendered
    assert obj.acquisition_anchor_at == datetime(2026, 3, 29, 2, 30, tzinfo=datetime_timezone.utc)
    assert obj.retired_at == datetime(2026, 10, 25, 2, 30, tzinfo=datetime_timezone.utc)


@pytest.mark.django_db
def test_explicit_offset_is_normalized_to_utc_and_purchase_date_does_not_change_anchor(users):
    form = BikeForm(data={"name": "UTC bike", "acquisition_anchor_at": "2026-10-04T12:00:00+02:00",
                          "acquired_on": "2026-10-04"}, user=users[0])
    assert form.is_valid(), form.errors
    obj = form.save()
    expected = datetime(2026, 10, 4, 10, tzinfo=datetime_timezone.utc)
    assert obj.acquisition_anchor_at == expected
    form = BikeForm(data={"name": "UTC bike", "acquisition_anchor_at": "2026-10-04 10:00:00",
                          "acquired_on": "2025-01-01"}, user=users[0], instance=obj)
    assert form.is_valid(), form.errors
    assert form.save().acquisition_anchor_at == expected


@pytest.mark.parametrize("form_class,model", [(BikeForm, Bike), (ItemForm, Item)])
@pytest.mark.parametrize("conflict", [False, True])
@pytest.mark.django_db
def test_inventory_form_retirement_uses_temporal_service_and_preserves_history(form_class, model, conflict, users):
    category = create_inventory(users[0], Category, name="Retirement components")
    bike = create_inventory(users[0], Bike, name="Retirement bike")
    item = create_inventory(users[0], Item, name="Retirement item", category=category)
    start = datetime(2026, 1, 3 if conflict else 1, tzinfo=datetime_timezone.utc)
    installation = create_installation(users[0], item=item, bike=bike, started_at=start)
    obj = bike if model is Bike else item
    data = {"name": obj.name, "retired_at": "2026-01-03 00:00:00"}
    if model is Item:
        data["category"] = str(category.pk)
    form = form_class(data=data, user=users[0], instance=obj)
    assert form.is_valid(), form.errors
    if conflict:
        with pytest.raises(ValidationError):
            form.save()
        assert form.errors.as_data()["retired_at"][0].code == "retirement_conflict"
        obj.refresh_from_db()
        installation.refresh_from_db()
        assert obj.retired_at is None and installation.ended_at is None
    else:
        retired = form.save()
        installation.refresh_from_db()
        assert installation.ended_at == retired.retired_at == datetime(2026, 1, 3, tzinfo=datetime_timezone.utc)
