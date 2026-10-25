from datetime import datetime, timezone as utc_timezone
from decimal import Decimal
import uuid

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from .forms import ItemForm, UsageBaselineForm
from .models import Category, Item, UsageBaseline
from .services.baselines import record_baseline
from .services.ownership import InventoryNotFound, create_inventory


@pytest.fixture
def inventory(db, django_user_model):
    owner = django_user_model.objects.create_user(username="reading-form-owner")
    other = django_user_model.objects.create_user(username="reading-form-other")
    category = create_inventory(owner, Category, name="Parts")
    item = create_inventory(owner, Item, name="Helmet", category=category,
                            acquisition_anchor_at=datetime(2026, 1, 1, tzinfo=utc_timezone.utc))
    foreign = create_inventory(other, Item, name="SECRET", category=create_inventory(other, Category, name="Parts"))
    return owner, other, item, foreign


def payload(item, **changes):
    return {"item": str(item.pk), "metric": "distance_m", "scope": "lifetime", "cut_at": "2026-01-02",
            "time_zone": "UTC", "value": "1000000", "source": "manual", **changes}


@pytest.mark.parametrize("zone,wall,expected", [
    ("Europe/Madrid", "2026-01-02", datetime(2026, 1, 1, 23, tzinfo=utc_timezone.utc)),
    ("Europe/Madrid", "2026-07-02", datetime(2026, 7, 1, 22, tzinfo=utc_timezone.utc)),
    ("America/New_York", "2026-01-02", datetime(2026, 1, 2, 5, tzinfo=utc_timezone.utc)),
    ("UTC", "2026-01-02", datetime(2026, 1, 2, tzinfo=utc_timezone.utc)),
])
def test_local_reading_date_means_midnight_in_explicit_zone(inventory, zone, wall, expected):
    owner, _, item, _ = inventory
    with timezone.override("Asia/Tokyo"):
        form = UsageBaselineForm(data=payload(item, time_zone=zone, cut_at=wall), user=owner)
        assert form.is_valid(), form.errors
        result = form.save()
    result.refresh_from_db()
    assert result.cut_at == expected


@pytest.mark.parametrize("zone,wall,field,code", [
    ("Europe/Madrid", "2026-03-29 02:30:00", "cut_at", "nonexistent_local_time"),
    ("Europe/Madrid", "2026-10-25 02:30:00", "cut_at", "ambiguous_local_time"),
    ("Pacific/Apia", "2011-12-30", "cut_at", "nonexistent_local_time"),
    ("Not/AZone", "2026-01-02", "time_zone", "invalid_time_zone"),
    ("", "2026-01-02", "time_zone", "required"),
    ("Europe/Madrid", "2026-01-02T00:00:00+01:00", "cut_at", "invalid_local_time"),
])
def test_reading_form_rejects_ambiguous_missing_or_implicit_zone(inventory, zone, wall, field, code):
    owner, _, item, _ = inventory
    form = UsageBaselineForm(data=payload(item, time_zone=zone, cut_at=wall), user=owner)
    assert not form.is_valid()
    assert form.errors.as_data()[field][0].code == code
    assert not UsageBaseline.objects.exists()


def test_edit_render_and_save_preserve_instant_independent_of_active_zone(inventory):
    owner, _, item, _ = inventory
    instant = datetime(2026, 1, 2, 10, tzinfo=utc_timezone.utc)
    reading = record_baseline(owner, item=item, metric="distance_m", scope="lifetime", cut_at=instant, value=Decimal("1"))
    with timezone.override("America/New_York"):
        initial = UsageBaselineForm(user=owner, instance=reading, time_zone="Europe/Madrid")
        assert 'value="2026-01-02 11:00:00"' in str(initial["cut_at"])
        form = UsageBaselineForm(data=payload(item, cut_at="2026-01-02 11:00:00", time_zone="Europe/Madrid", value="2"), user=owner, instance=reading)
        assert form.is_valid(), form.errors
        edited = form.save()
    assert edited.pk == reading.pk and edited.cut_at == instant and edited.value == Decimal("2")
    form = UsageBaselineForm(data=payload(item, cut_at="2026-01-02 11:00:00", time_zone="UTC", value="3"), user=owner, instance=edited)
    assert form.is_valid(), form.errors
    assert form.save().cut_at == datetime(2026, 1, 2, 11, tzinfo=utc_timezone.utc)


@pytest.mark.parametrize("metric,value,valid", [("moving_time_s", "1.2300", True), ("distance_m", "1.2345", False),
                                               ("ride_count", "1.250", False), ("ride_count", "0", True)])
def test_reading_form_preserves_exact_precision_and_integral_ride_counts(inventory, metric, value, valid):
    owner, _, item, _ = inventory
    form = UsageBaselineForm(data=payload(item, metric=metric, value=value), user=owner)
    assert form.is_valid() is valid, form.errors
    if valid:
        assert form.save().value == Decimal(value)
    else:
        assert "value" in form.errors and not UsageBaseline.objects.exists()


def test_reading_form_actor_scope_commit_false_and_forged_fields(inventory):
    owner, other, item, foreign = inventory
    fake = uuid.uuid4()
    form = UsageBaselineForm(data=payload(item, owner=other.pk, id=str(fake)), user=owner)
    assert form.is_valid(), form.errors
    candidate = form.save(commit=False)
    assert candidate.owner_id == owner.pk and candidate.pk != fake and not UsageBaseline.objects.exists()
    saved = form.save()
    foreign_form = UsageBaselineForm(data=payload(foreign), user=owner)
    assert not foreign_form.is_valid() and "item" in foreign_form.errors
    assert "SECRET" not in str(form["item"])
    saved.owner = other
    with pytest.raises(InventoryNotFound):
        UsageBaselineForm(user=other, instance=saved)
    with pytest.raises(PermissionDenied):
        UsageBaselineForm(user=AnonymousUser())
    owner.is_active = False
    owner.save(update_fields=["is_active"])
    with pytest.raises(PermissionDenied):
        UsageBaselineForm(user=owner)


@pytest.mark.parametrize("anchor", ["", "2026-01-03 00:00:00"])
def test_item_form_anchor_correction_cannot_invalidate_existing_reading(inventory, anchor):
    owner, _, item, _ = inventory
    reading = record_baseline(owner, item=item, metric="distance_m", scope="acquisition",
                              cut_at=datetime(2026, 1, 2, tzinfo=utc_timezone.utc), value=Decimal("0"))
    form = ItemForm(data={"name": "Forbidden edit", "category": str(item.category_id), "acquisition_anchor_at": anchor}, user=owner, instance=item)
    assert form.is_valid(), form.errors
    with pytest.raises(ValidationError):
        form.save()
    assert "acquisition_anchor_at" in form.errors
    item.refresh_from_db()
    reading.refresh_from_db()
    assert item.name == "Helmet" and item.acquisition_anchor_at == datetime(2026, 1, 1, tzinfo=utc_timezone.utc)
    assert reading.value == Decimal("0")


@pytest.mark.parametrize("scope,cut", [("acquisition", "2025-12-31"), ("acquisition", "2026-01-02")])
def test_reading_form_validates_acquisition_anchor(inventory, scope, cut):
    owner, _, item, _ = inventory
    if cut == "2026-01-02":
        item.acquisition_anchor_at = None
        item.save(update_fields=["acquisition_anchor_at"])
    form = UsageBaselineForm(data=payload(item, scope=scope, cut_at=cut), user=owner)
    assert not form.is_valid()
    assert ("scope" if cut == "2026-01-02" else "cut_at") in form.errors
    assert not UsageBaseline.objects.exists()


@pytest.mark.parametrize("zone,cut", [("Asia/Tokyo", "0001-01-01 00:00:00"), ("America/New_York", "9999-12-31 23:59:59")])
def test_extreme_civil_dates_return_form_errors_instead_of_utc_overflow(inventory, zone, cut):
    owner, _, item, _ = inventory
    form = UsageBaselineForm(data=payload(item, time_zone=zone, cut_at=cut), user=owner)
    assert not form.is_valid()
    assert form.errors.as_data()["cut_at"][0].code == "invalid_local_time"
    assert not UsageBaseline.objects.exists()


def test_duplicate_new_reading_form_requires_explicit_edit_for_correction(inventory):
    owner, _, item, _ = inventory
    first = UsageBaselineForm(data=payload(item), user=owner)
    assert first.is_valid(), first.errors
    original = first.save()
    duplicate = UsageBaselineForm(data=payload(item, value="900000"), user=owner)
    assert not duplicate.is_valid() and "__all__" in duplicate.errors
    original.refresh_from_db()
    assert original.value == Decimal("1000000") and UsageBaseline.objects.count() == 1
    correction = UsageBaselineForm(data=payload(item, value="900000"), user=owner, instance=original)
    assert correction.is_valid(), correction.errors
    saved = correction.save()
    assert saved.pk == original.pk and saved.value == Decimal("900000") and UsageBaseline.objects.count() == 1
