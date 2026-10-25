import uuid
from datetime import datetime, timezone as datetime_timezone

import pytest
from django.contrib import admin
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, connection
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from . import admin as garage_admin
from .models import Bike, Category, Item
from .services.baselines import record_baseline
from .services.installations import create_installation
from .services.ownership import CategoryNameConflict


@pytest.fixture(params=[False, True], ids=["staff", "superuser"])
def actor(request, db, django_user_model, client):
    user = django_user_model.objects.create_user(username="garage-actor", is_staff=True,
                                                is_superuser=request.param)
    user.user_permissions.set(Permission.objects.filter(content_type__app_label="garage"))
    client.force_login(user)
    return user


@pytest.fixture
def other(db, django_user_model):
    return django_user_model.objects.create_user(username="garage-other")


def resource(model, owner, name):
    values = {"owner": owner, "name": name}
    if model is Item:
        values["category"] = Category.objects.create(owner=owner, name=name + " category")
    return model.objects.create(**values)


def admin_url(model, view, obj=None):
    return reverse(f"admin:garage_{model._meta.model_name}_{view}", args=[obj.pk] if obj else None)


@pytest.mark.parametrize("model", [Bike, Item, Category])
@pytest.mark.django_db
def test_admin_list_and_search_scoped_for_every_actor(model, actor, other, client):
    own = resource(model, actor, "OWNVISIBLE")
    foreign = resource(model, other, "FOREIGNSECRET")
    response = client.get(admin_url(model, "changelist"))
    assert response.status_code == 200
    assert list(response.context["cl"].queryset) == [own]
    assert b"FOREIGNSECRET" not in response.content
    response = client.get(admin_url(model, "changelist"), {"q": "FOREIGNSECRET"})
    assert response.status_code == 200 and not response.context["cl"].queryset.exists()
    assert model.objects.filter(pk=foreign.pk).exists()


@pytest.mark.parametrize("model", [Bike, Item, Category])
@pytest.mark.parametrize("view", ["change", "delete", "history"])
@pytest.mark.django_db
def test_admin_foreign_detail_delete_history_hide_object(model, view, actor, other, client):
    foreign = resource(model, other, "FOREIGNSECRET")
    response = client.get(admin_url(model, view, foreign))
    assert response.status_code in (302, 404)
    assert b"FOREIGNSECRET" not in response.content
    foreign.refresh_from_db()
    assert foreign.owner == other


@pytest.mark.parametrize("model", [Bike, Item, Category])
@pytest.mark.parametrize("view", ["change", "delete"])
@pytest.mark.django_db
def test_admin_foreign_forged_post_cannot_change_or_delete(model, view, actor, other, client):
    foreign = resource(model, other, "FOREIGNSECRET")
    data = {"name": "INTRUSION", "owner": actor.pk, "post": "yes", "_save": "Save"}
    if model is Item:
        data["category"] = foreign.category_id
    response = client.post(admin_url(model, view, foreign), data)
    assert response.status_code in (302, 404)
    foreign.refresh_from_db()
    assert foreign.name == "FOREIGNSECRET" and foreign.owner == other


@pytest.mark.parametrize("model", [Bike, Item, Category])
@pytest.mark.django_db
def test_admin_create_assigns_actor_and_ignores_forged_owner_uuid(model, actor, other, client):
    foreign = resource(model, other, "FOREIGNSECRET")
    data = {"name": "OWNCREATED", "owner": other.pk, "id": str(foreign.pk), "_save": "Save"}
    if model in (Bike, Item):
        data.update(brand="Example brand", model="Commercial model")
    if model is Item:
        category = Category.objects.create(owner=actor, name="Own category")
        data["category"] = str(category.pk)
    response = client.post(admin_url(model, "add"), data)
    assert response.status_code == 302
    created = model.objects.get(name="OWNCREATED")
    assert created.owner == actor and created.pk != foreign.pk
    if model in (Bike, Item):
        assert created.brand == "Example brand" and created.model == "Commercial model"
    foreign.refresh_from_db()
    assert foreign.name == "FOREIGNSECRET" and foreign.owner == other


@pytest.mark.parametrize("model", [Bike, Item, Category])
@pytest.mark.django_db
def test_admin_edit_preserves_owner_uuid_and_saves_own_changes(model, actor, other, client):
    own = resource(model, actor, "OWNINITIAL")
    identity = own.pk
    data = {"name": "OWNEDITED", "owner": other.pk, "id": str(uuid.uuid4()), "_save": "Save"}
    if model in (Bike, Item):
        data.update(brand="Edited brand", model="Edited commercial model")
    if model is Item:
        data["category"] = str(own.category_id)
    response = client.post(admin_url(model, "change", own), data)
    assert response.status_code == 302
    own.refresh_from_db()
    assert own.pk == identity and own.owner == actor and own.name == "OWNEDITED"
    if model in (Bike, Item):
        assert own.brand == "Edited brand" and own.model == "Edited commercial model"


@pytest.mark.django_db
def test_admin_category_duplicate_is_form_error_not_server_error(actor, client):
    first = Category.objects.create(owner=actor, name="Wheels")
    for view, data, obj in [("add", {"name": " wheels "}, None),
                             ("change", {"name": "wHeElS"},
                              Category.objects.create(owner=actor, name="Other"))]:
        response = client.post(admin_url(Category, view, obj), {**data, "_save": "Save"})
        assert response.status_code == 200
        assert response.context["adminform"].form.errors
    assert Category.objects.filter(owner=actor).count() == 2
    first.refresh_from_db()
    assert first.name == "Wheels"


@pytest.mark.django_db
def test_admin_foreign_category_choices_and_forged_creation_or_edit(actor, other, client):
    own_category = Category.objects.create(owner=actor, name="Own category")
    foreign = Category.objects.create(owner=other, name="FOREIGNCATEGORYSECRET")
    own = Item.objects.create(owner=actor, category=own_category, name="Own item")
    for view, obj in [("add", None), ("change", own)]:
        response = client.get(admin_url(Item, view, obj))
        assert response.status_code == 200
        field = response.context["adminform"].form.fields["category"]
        assert list(field.queryset) == [own_category]
        assert b"FOREIGNCATEGORYSECRET" not in response.content
        response = client.post(admin_url(Item, view, obj), {
            "name": "FORGED", "category": str(foreign.pk), "owner": other.pk, "_save": "Save"})
        assert response.status_code == 200
        assert "category" in response.context["adminform"].form.errors
    own.refresh_from_db()
    assert own.name == "Own item" and own.category == own_category
    assert not Item.objects.filter(name="FORGED").exists()


@pytest.mark.django_db
def test_admin_autocomplete_scoped_even_for_superusers(actor, other, client):
    own = Category.objects.create(owner=actor, name="Own autocomplete")
    Category.objects.create(owner=other, name="FOREIGNAUTOCOMPLETE")
    response = client.get(reverse("admin:autocomplete"), {
        "app_label": "garage", "model_name": "item", "field_name": "category", "term": ""})
    assert response.status_code == 200
    assert response.json()["results"] == [{"id": str(own.pk), "text": own.name}]


@pytest.mark.parametrize("model", [Bike, Item, Category])
@pytest.mark.django_db
def test_admin_delete_action_forged_selection_scoped(model, actor, other, client):
    own = resource(model, actor, "OWNDELETE")
    foreign = resource(model, other, "FOREIGNDELETESECRET")
    payload = {"action": "delete_selected", "_selected_action": [str(own.pk), str(foreign.pk)]}
    response = client.post(admin_url(model, "changelist"), payload)
    assert response.status_code == 200
    assert b"FOREIGNDELETESECRET" not in response.content
    response = client.post(admin_url(model, "changelist"), {**payload, "post": "yes"})
    assert response.status_code == 302
    assert not model.objects.filter(pk=own.pk).exists()
    assert model.objects.filter(pk=foreign.pk, owner=other).exists()


@pytest.mark.parametrize("model", [Bike, Item, Category])
@pytest.mark.django_db
def test_admin_delete_individual_owned_object_preserves_other_inventory(model, actor, other, client):
    own = resource(model, actor, "OWNDELETEINDIVIDUAL")
    foreign = resource(model, other, "FOREIGNKEEPINDIVIDUAL")
    response = client.post(admin_url(model, "delete", own), {"post": "yes"})
    assert response.status_code == 302
    assert not model.objects.filter(pk=own.pk).exists()
    foreign.refresh_from_db()
    assert foreign.name == "FOREIGNKEEPINDIVIDUAL" and foreign.owner == other


@pytest.mark.parametrize("model", [Bike, Item, Category])
@pytest.mark.django_db
def test_admin_direct_permissions_write_and_delete_hooks_reject_foreign_objects(model, actor, other):
    own = resource(model, actor, "OWNDELETEHOOK")
    foreign = resource(model, other, "FOREIGNHOOK")
    request = RequestFactory().get("/admin/")
    request.user = actor
    model_admin = admin.site._registry[model]
    assert not model_admin.has_view_permission(request, foreign)
    assert not model_admin.has_change_permission(request, foreign)
    assert not model_admin.has_delete_permission(request, foreign)
    with pytest.raises(PermissionDenied):
        model_admin.save_model(request, foreign, None, change=True)
    with pytest.raises(PermissionDenied):
        model_admin.delete_model(request, foreign)
    model_admin.delete_queryset(request, model.objects.filter(pk__in=[own.pk, foreign.pk]))
    assert not model.objects.filter(pk=own.pk).exists()
    assert model.objects.filter(pk=foreign.pk, owner=other).exists()


@pytest.mark.parametrize("model", [Bike, Item])
@pytest.mark.django_db
def test_admin_money_errors_are_visible_and_never_persist(model, actor, client):
    data = {"name": "Invalid money", "purchase_amount": "1", "purchase_currency": "ZZZ", "_save": "Save"}
    if model is Item:
        data["category"] = Category.objects.create(owner=actor, name="Own money category").pk
    response = client.post(admin_url(model, "add"), data)
    assert response.status_code == 200
    assert "purchase_currency" in response.context["adminform"].form.errors
    assert not model.objects.filter(name="Invalid money").exists()


@pytest.mark.django_db
def test_admin_delete_protected_category_preserves_inventory(actor, client):
    category = Category.objects.create(owner=actor, name="Protected")
    item = Item.objects.create(owner=actor, category=category, name="Protected item")
    response = client.post(admin_url(Category, "delete", category), {"post": "yes"})
    assert response.status_code == 200
    assert Category.objects.filter(pk=category.pk).exists()
    assert Item.objects.filter(pk=item.pk).exists()


@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.django_db
def test_admin_category_conflict_after_form_validation_rolls_back_and_renders_errors(operation, actor, client, monkeypatch):
    original = Category.objects.create(owner=actor, name="Original", notes="Original notes")
    calls = []

    def conflict(*args, **kwargs):
        calls.append((args, kwargs))
        # Exercise the outer admin rollback, not only the response code.
        Bike.objects.create(owner=actor, name="Partial side effect")
        raise CategoryNameConflict()

    hook = "create_inventory" if operation == "create" else "update_inventory"
    monkeypatch.setattr(garage_admin, hook, conflict)
    url = admin_url(Category, "add") if operation == "create" else admin_url(Category, "change", original)
    response = client.post(url, {"name": "Raced", "notes": "Changed notes", "_save": "Save"})
    assert response.status_code == 200
    assert response.context["adminform"].form.errors.as_data()["name"][0].code == "category_name_conflict"
    assert len(calls) == 1
    assert not Bike.objects.filter(name="Partial side effect").exists()
    assert not Category.objects.filter(name="Raced").exists()
    original.refresh_from_db()
    assert original.name == "Original" and original.notes == "Original notes"
    assert not connection.needs_rollback


@pytest.mark.django_db
def test_admin_does_not_hide_unexpected_integrity_errors(actor, client, monkeypatch):
    error = IntegrityError("synthetic unexpected constraint")

    def unexpected(*args, **kwargs):
        raise error

    monkeypatch.setattr(garage_admin, "create_inventory", unexpected)
    with pytest.raises(IntegrityError) as raised:
        client.post(admin_url(Category, "add"), {"name": "Failed", "_save": "Save"})
    assert raised.value is error
    assert not Category.objects.filter(name="Failed").exists()
    assert not connection.needs_rollback


@pytest.mark.parametrize("model", [Bike, Item, Category])
@pytest.mark.django_db
def test_admin_forged_saved_instance_cannot_be_used_as_creation(model, actor, other):
    foreign = resource(model, other, "Foreign original")
    foreign.owner = actor
    request = RequestFactory().post("/admin/")
    request.user = actor
    with pytest.raises(PermissionDenied):
        admin.site._registry[model].save_model(request, foreign, None, change=False)
    foreign.refresh_from_db()
    assert foreign.owner == other and foreign.name == "Foreign original"


@pytest.mark.django_db
def test_admin_utc_split_widget_rendering_and_parsing_ignore_active_request_timezone(actor, client):
    initial = datetime(2026, 3, 29, 2, 30, tzinfo=datetime_timezone.utc)
    obj = Bike.objects.create(owner=actor, name="UTC bike", acquisition_anchor_at=initial)
    with timezone.override("Europe/Madrid"):
        response = client.get(admin_url(Bike, "change", obj))
        field = response.context["adminform"].form["acquisition_anchor_at"]
        assert "(UTC)" in field.label
        rendered = str(field)
        assert 'value="2026-03-29"' in rendered and 'value="02:30:00"' in rendered
        response = client.post(admin_url(Bike, "change", obj), {
            "name": "UTC bike", "acquisition_anchor_at_0": "2026-03-29", "acquisition_anchor_at_1": "02:30:00",
            "retired_at_0": "2026-10-25", "retired_at_1": "02:30:00", "_save": "Save"})
        assert response.status_code == 302
    obj.refresh_from_db()
    assert obj.acquisition_anchor_at == initial
    assert obj.retired_at == datetime(2026, 10, 25, 2, 30, tzinfo=datetime_timezone.utc)


@pytest.mark.parametrize("model", [Bike, Item])
@pytest.mark.parametrize("conflict", [False, True])
@pytest.mark.django_db
def test_admin_retirement_closes_history_or_renders_conflict_without_partial_write(model, conflict, actor, client):
    bike = Bike.objects.create(owner=actor, name="Retirement bike")
    item = resource(Item, actor, "Retirement item")
    installation = create_installation(actor, item=item, bike=bike,
        started_at=datetime(2026, 1, 3 if conflict else 1, tzinfo=datetime_timezone.utc))
    obj = bike if model is Bike else item
    data = {"name": "Edited retired resource", "retired_at_0": "2026-01-03", "retired_at_1": "00:00:00", "_save": "Save"}
    if model is Item:
        data["category"] = str(item.category_id)
    response = client.post(admin_url(model, "change", obj), data)
    installation.refresh_from_db()
    obj.refresh_from_db()
    if conflict:
        assert response.status_code == 200
        assert response.context["adminform"].form.errors.as_data()["retired_at"][0].code == "retirement_conflict"
        assert obj.retired_at is None and installation.ended_at is None
        assert obj.name == ("Retirement bike" if model is Bike else "Retirement item")
    else:
        assert response.status_code == 302
        assert obj.retired_at == installation.ended_at == datetime(2026, 1, 3, tzinfo=datetime_timezone.utc)
        assert obj.name == "Edited retired resource"


@pytest.mark.parametrize("anchor_day,expected_code", [(None, "acquisition_anchor_in_use"), (3, "baseline_before_anchor"), (1, None)])
@pytest.mark.django_db
def test_admin_acquisition_anchor_correction_preserves_existing_readings(anchor_day, expected_code, actor, client):
    item = resource(Item, actor, "Anchored item")
    item.acquisition_anchor_at = datetime(2026, 1, 2, tzinfo=datetime_timezone.utc)
    item.save(update_fields=["acquisition_anchor_at"])
    reading = record_baseline(actor, item=item, metric="distance_m", scope="acquisition",
                              cut_at=datetime(2026, 1, 2, tzinfo=datetime_timezone.utc), value="0")
    response = client.post(admin_url(Item, "change", item), {
        "name": "Edited anchored item", "category": str(item.category_id),
        "acquisition_anchor_at_0": f"2026-01-{anchor_day:02}" if anchor_day else "",
        "acquisition_anchor_at_1": "00:00:00" if anchor_day else "", "_save": "Save"})
    item.refresh_from_db()
    reading.refresh_from_db()
    if expected_code:
        assert response.status_code == 200
        assert response.context["adminform"].form.errors.as_data()["acquisition_anchor_at"][0].code == expected_code
        assert item.name == "Anchored item" and item.acquisition_anchor_at == datetime(2026, 1, 2, tzinfo=datetime_timezone.utc)
    else:
        assert response.status_code == 302
        assert item.name == "Edited anchored item" and item.acquisition_anchor_at == datetime(2026, 1, 1, tzinfo=datetime_timezone.utc)
    assert reading.cut_at == datetime(2026, 1, 2, tzinfo=datetime_timezone.utc) and reading.value == 0
