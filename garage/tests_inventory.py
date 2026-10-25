from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
import uuid

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import ProtectedError
from django.urls import resolve, reverse
from django.utils import timezone

from .models import Bike, Category, Item
from .validators import validate_currency


@pytest.fixture
def owners(db, django_user_model):
    return [django_user_model.objects.create_user(username=name) for name in ("garage-alice", "garage-bob")]


def inventory(model, owner, **values):
    if model is Item and "category" not in values:
        values["category"] = Category.objects.create(owner=owner, name="Equipment")
    return model(owner=owner, name="Road gear", **values)


@pytest.mark.django_db
def test_independent_inventory_and_standalone_equipment(owners):
    records = []
    for owner in owners:
        category = Category(owner=owner, name="  Shoes  ", notes="Personal equipment")
        category.full_clean()
        category.save()
        item = Item(owner=owner, category=category, name="Shoes", notes="No bike required")
        item.full_clean()
        item.save()
        bike = Bike(owner=owner, name="Road", serial_number="same-serial")
        bike.full_clean()
        bike.save()
        records.extend((category, item, bike))
        assert category.name == "Shoes"
        assert list(Item.objects.filter(owner=owner)) == [item]
        assert list(Bike.objects.filter(owner=owner)) == [bike]
    assert len({record.pk for record in records}) == 6
    assert all(isinstance(record.pk, uuid.UUID) for record in records)


@pytest.mark.parametrize("model", [Bike, Item, Category])
@pytest.mark.django_db
def test_uuid_collision_cannot_overwrite_identity(model, owners):
    first = inventory(model, owners[0])
    first.save()
    second = inventory(model, owners[1])
    second.pk = first.pk
    with pytest.raises(IntegrityError), transaction.atomic():
        second.save(force_insert=True)
    first.refresh_from_db()
    assert first.owner == owners[0]


@pytest.mark.parametrize("model", [Bike, Item, Category])
@pytest.mark.django_db
def test_owner_change_rejected_by_model_validation(model, owners):
    obj = inventory(model, owners[0])
    obj.save()
    obj.owner = owners[1]
    with pytest.raises(ValidationError) as error:
        obj.full_clean()
    assert "owner" in error.value.message_dict
    obj.refresh_from_db()
    assert obj.owner == owners[0]


@pytest.mark.django_db
def test_category_unique_per_owner_case_insensitive_and_trimmed(owners):
    original = Category.objects.create(owner=owners[0], name="Wheels")
    duplicate = Category(owner=owners[0], name=" wheels ")
    with pytest.raises(ValidationError):
        duplicate.full_clean()
    assert duplicate.name == "wheels"
    with pytest.raises(IntegrityError), transaction.atomic():
        Category.objects.create(owner=owners[0], name="WHEELS")
    Category.objects.create(owner=owners[1], name="WHEELS")
    original.name = "wheelsets"
    original.full_clean()
    original.save()
    original.refresh_from_db()
    assert original.name == "wheelsets"


@pytest.mark.django_db
def test_category_archive_and_rename_preserve_item_identity_and_protect_delete(owners):
    category = Category.objects.create(owner=owners[0], name="Shoe")
    item = Item.objects.create(owner=owners[0], name="Left and right shoes", category=category)
    identity = item.pk
    category.name = "Shoes"
    category.is_archived = True
    category.full_clean()
    category.save()
    item.refresh_from_db()
    assert item.pk == identity
    assert item.category.name == "Shoes"
    with pytest.raises(ProtectedError):
        category.delete()
    assert Item.objects.filter(pk=identity).exists()


@pytest.mark.django_db
def test_item_cross_owner_category_rejected(owners):
    category = Category.objects.create(owner=owners[1], name="Foreign")
    item = Item(owner=owners[0], name="Helmet", category=category)
    with pytest.raises(ValidationError) as error:
        item.full_clean()
    assert "category" in error.value.message_dict
    assert not Item.objects.exists()


@pytest.mark.parametrize("model", [Bike, Item, Category])
@pytest.mark.parametrize("name", ["", "   ", "\t\n"])
@pytest.mark.django_db
def test_blank_names_rejected_in_validation_and_database(model, name, owners):
    obj = inventory(model, owners[0])
    obj.name = name
    with pytest.raises(ValidationError):
        obj.full_clean()
    obj.name = name
    with pytest.raises(IntegrityError), transaction.atomic():
        obj.save(force_insert=True)


@pytest.mark.parametrize("model", [Bike, Item])
@pytest.mark.django_db
def test_repeated_physical_names_and_serials_are_not_identity(model, owners):
    category = Category.objects.create(owner=owners[0], name="Repeated")
    extra = {"category": category} if model is Item else {}
    first = inventory(model, owners[0], serial_number="identical", **extra)
    second = inventory(model, owners[0], serial_number="identical", **extra)
    for obj in (first, second):
        obj.full_clean()
        obj.save()
    assert first.pk != second.pk


@pytest.mark.parametrize("model", [Bike, Item])
@pytest.mark.django_db
def test_retirement_and_reactivation_keep_identity_and_purchase_anchor(model, owners):
    anchor = datetime(2025, 1, 1, 5, tzinfo=dt_timezone(timedelta(hours=2)))
    obj = inventory(model, owners[0], acquired_on=date(2025, 1, 1), acquisition_anchor_at=anchor,
                    purchase_amount=Decimal("12.34"), purchase_currency="EUR", notes="Used equipment")
    obj.full_clean()
    obj.save()
    identity, created_at = obj.pk, obj.created_at
    for retired_at in (timezone.now(), None):
        obj.retired_at = retired_at
        obj.acquired_on = date(2026, 2, 2)
        obj.full_clean()
        obj.save()
        obj.refresh_from_db()
        assert obj.pk == identity and obj.created_at == created_at
        assert obj.retired_at == retired_at
        assert obj.acquisition_anchor_at == anchor
        assert obj.acquisition_anchor_at.utcoffset() == timedelta(0)
        assert obj.purchase_amount == Decimal("12.34")
        assert obj.notes == "Used equipment"
    assert obj.updated_at >= created_at


@pytest.mark.parametrize("model", [Bike, Item])
@pytest.mark.django_db
def test_purchase_date_alone_does_not_fabricate_usage_anchor(model, owners):
    obj = inventory(model, owners[0], acquired_on=date(2026, 1, 1))
    obj.full_clean()
    obj.save()
    obj.refresh_from_db()
    assert obj.acquisition_anchor_at is None


@pytest.mark.parametrize("model", [Bike, Item])
@pytest.mark.parametrize("field", ["acquisition_anchor_at", "retired_at"])
@pytest.mark.django_db
def test_naive_instants_rejected(model, field, owners):
    obj = inventory(model, owners[0], **{field: datetime(2026, 1, 1)})
    with pytest.raises(ValidationError) as error:
        obj.full_clean()
    assert field in error.value.message_dict


@pytest.mark.parametrize("model", [Bike, Item])
@pytest.mark.parametrize("amount,currency", [(None, None), (Decimal("0"), "EUR"),
                                           (Decimal("9999999999.99"), "USD"), (Decimal("1.23"), "XCG")])
@pytest.mark.django_db
def test_valid_decimal_money_roundtrip(model, amount, currency, owners):
    obj = inventory(model, owners[0], purchase_amount=amount, purchase_currency=currency)
    obj.full_clean()
    obj.save()
    obj.refresh_from_db()
    assert obj.purchase_amount == amount and obj.purchase_currency == currency


@pytest.mark.parametrize("model", [Bike, Item])
@pytest.mark.parametrize("amount,currency", [(Decimal("-0.01"), "EUR"), (None, "EUR"),
                                           (Decimal("1"), None), (Decimal("1"), ""),
                                           (Decimal("1"), "eur"), (Decimal("1"), "ZZZ"),
                                           (None, "")])
@pytest.mark.django_db
def test_invalid_money_rejected_by_db(model, amount, currency, owners):
    obj = inventory(model, owners[0], purchase_amount=amount, purchase_currency=currency)
    with pytest.raises(IntegrityError), transaction.atomic():
        obj.save(force_insert=True)


@pytest.mark.parametrize("model", [Bike, Item])
@pytest.mark.django_db
def test_database_rejects_nonfinite_numeric_bypassing_python_field_validation(model, owners):
    obj = inventory(model, owners[0], purchase_amount=Decimal("1"), purchase_currency="EUR")
    obj.save()
    table = connection.ops.quote_name(model._meta.db_table)
    with pytest.raises(IntegrityError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(f"UPDATE {table} SET purchase_amount = %s::numeric WHERE id = %s", ["NaN", obj.pk])
    obj.refresh_from_db()
    assert obj.purchase_amount == Decimal("1")


@pytest.mark.parametrize("model", [Bike, Item, Category])
@pytest.mark.django_db
def test_malformed_name_returns_validation_error(model, owners):
    obj = inventory(model, owners[0])
    obj.name = None
    with pytest.raises(ValidationError) as error:
        obj.full_clean()
    assert "name" in error.value.message_dict


@pytest.mark.parametrize("model", [Bike, Item])
@pytest.mark.django_db
def test_malformed_instant_returns_validation_error(model, owners):
    obj = inventory(model, owners[0], acquisition_anchor_at="invalid")
    with pytest.raises(ValidationError) as error:
        obj.full_clean()
    assert "acquisition_anchor_at" in error.value.message_dict


@pytest.mark.parametrize("model", [Bike, Item])
@pytest.mark.parametrize("amount,currency", [(Decimal("-0.01"), "EUR"), (None, "EUR"),
                                           (Decimal("1"), None), (Decimal("1"), "eur"),
                                           (Decimal("1"), "ZZZ"), (Decimal("1.234"), "EUR"),
                                           (Decimal("10000000000"), "EUR"), (Decimal("NaN"), "EUR")])
@pytest.mark.django_db
def test_invalid_money_rejected_by_validation(model, amount, currency, owners):
    obj = inventory(model, owners[0], purchase_amount=amount, purchase_currency=currency)
    with pytest.raises(ValidationError):
        obj.full_clean()


@pytest.mark.parametrize("model", [Bike, Item])
@pytest.mark.django_db
def test_blank_currency_normalizes_to_absence(model, owners):
    obj = inventory(model, owners[0], purchase_currency="")
    obj.full_clean()
    obj.save()
    obj.refresh_from_db()
    assert obj.purchase_amount is None and obj.purchase_currency is None


@pytest.mark.parametrize("currency", ["", "eur", " EURO ", "ZZZ", "123", "EU"])
def test_iso_currency_validator_rejects_invalid_codes(currency):
    with pytest.raises(ValidationError) as error:
        validate_currency(currency)
    assert error.value.code == "invalid_currency"


@pytest.mark.django_db
def test_private_landing_and_legacy_routes_preserved(client, owners):
    url = reverse("garage:index")
    response = client.get(url)
    assert response.status_code == 302 and response.url == "/accounts/login/?next=/garage/"
    client.force_login(owners[0])
    response = client.get(url)
    assert response.status_code == 200 and b"Garage" in response.content
    assert resolve("/").url_name == "dashboard"
    assert resolve("/activities/").url_name == "activity-list"
    assert resolve("/activities/42/").url_name == "activity-detail"
    assert resolve("/healthz/").url_name == "healthz"
    assert resolve("/archive/strava/dashboard/").url_name == "strava_dashboard"
