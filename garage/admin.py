"""The admin is private inventory management, including for superusers."""
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponseRedirect
from unfold.admin import ModelAdmin

from .forms import OwnedInventoryForm
from .icons import ICON_CHOICES
from .models import Bike, Category, Item
from .services.ownership import (InventoryWriteError, InventoryNotFound, create_inventory, delete_inventory,
                                 scoped_inventory, update_inventory)


class OwnedInventoryAdmin(ModelAdmin):
    form = OwnedInventoryForm
    exclude = ("owner",)
    readonly_fields = ("id", "created_at", "updated_at")
    search_fields = ("name",)

    def get_queryset(self, request):
        return super().get_queryset(request).filter(pk__in=scoped_inventory(request.user, self.model).values("pk"))

    def get_form(self, request, obj=None, **kwargs):
        base_form = super().get_form(request, obj, **kwargs)

        class ActorForm(base_form):
            def __init__(self, *args, **form_kwargs):
                super().__init__(*args, user=request.user, **form_kwargs)

            def clean(self):
                cleaned = super().clean()
                conflict = getattr(request, "_garage_write_conflict", None)
                if conflict is not None:
                    raise conflict
                return cleaned

        return ActorForm

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "category":
            kwargs["queryset"] = scoped_inventory(request.user, Category)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def _owns(self, request, obj):
        return obj is None or obj.owner_id == request.user.pk

    def has_view_permission(self, request, obj=None):
        return self._owns(request, obj) and super().has_view_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return self._owns(request, obj) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self._owns(request, obj) and super().has_delete_permission(request, obj)

    def save_model(self, request, obj, form, change):
        if not change and (not obj._state.adding or obj.owner_id != request.user.pk):
            raise PermissionDenied
        values = {field.name: getattr(obj, field.name) for field in obj._meta.fields
                  if field.editable and not field.primary_key}
        try:
            if change:
                saved = update_inventory(request.user, self.model, obj.pk, **values)
            else:
                saved = create_inventory(request.user, self.model, **values)
        except InventoryNotFound:
            raise PermissionDenied from None
        # Django uses this exact instance for save_related and the admin log.
        obj.__dict__.update(saved.__dict__)

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        try:
            return super().changeform_view(request, object_id, form_url, extra_context)
        except InventoryWriteError as conflict:
            # The admin's outer atomic() has exited and rolled back here. Bind
            # the same POST as an invalid form, without retrying its write.
            request._garage_write_conflict = conflict
            return super().changeform_view(request, object_id, form_url, extra_context)

    def delete_model(self, request, obj):
        try:
            delete_inventory(request.user, self.model, obj.pk)
        except InventoryNotFound:
            raise PermissionDenied from None

    def delete_queryset(self, request, queryset):
        # Resolve every selected record inside the actor's scope, even if an
        # action supplies a forged queryset; all selected deletes are atomic.
        with transaction.atomic():
            selected = scoped_inventory(request.user, self.model).filter(pk__in=queryset.values("pk"))
            for obj in selected:
                delete_inventory(request.user, self.model, obj.pk)


@admin.register(Category)
class CategoryAdmin(OwnedInventoryAdmin):
    list_display = ("name", "icon", "is_archived", "updated_at")
    list_filter = ("is_archived",)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == "icon":
            # A list rather than free text; Category.clean() still validates the key (garage-041).
            from unfold.widgets import UnfoldAdminSelectWidget
            kwargs["widget"] = UnfoldAdminSelectWidget(choices=[("", "—"), *((key, label) for key, label, _ in ICON_CHOICES)])
        return super().formfield_for_dbfield(db_field, request, **kwargs)


@admin.register(Bike)
class BikeAdmin(OwnedInventoryAdmin):
    list_display = ("name", "brand", "model", "retired_at")


@admin.register(Item)
class ItemAdmin(OwnedInventoryAdmin):
    list_display = ("name", "category", "retired_at")


from .maintenance_forms import MaintenanceRuleForm, ServiceEventForm, ServiceTypeForm
from .models import MaintenanceRule, ServiceEvent, ServiceType
from .services.maintenance import delete_maintenance, save_maintenance


class MaintenanceAdmin(OwnedInventoryAdmin):
    search_fields = ()

    def delete_view(self, request, object_id, extra_context=None):
        try:
            return super().delete_view(request, object_id, extra_context)
        except InventoryWriteError as conflict:
            # Django's deletion transaction (including its admin log) has
            # rolled back. A reference may have arrived after its preflight.
            self.message_user(request, " ".join(conflict.messages), level=messages.ERROR)
            return HttpResponseRedirect(request.get_full_path())

    def response_action(self, request, queryset):
        try:
            # The standard delete_selected action logs before delete_queryset;
            # include that log and every selected deletion in the rollback.
            with transaction.atomic():
                return super().response_action(request, queryset)
        except InventoryWriteError as conflict:
            self.message_user(request, " ".join(conflict.messages), level=messages.ERROR)
            return HttpResponseRedirect(request.get_full_path())

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        model = db_field.remote_field.model
        if model in (Item, Bike, ServiceType):
            kwargs["queryset"] = scoped_inventory(request.user, model)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        values = {field.name: getattr(obj, field.name) for field in obj._meta.fields if field.editable and not field.primary_key}
        saved = save_maintenance(request.user, self.model, obj.pk if change else None, **values)
        obj.__dict__.update(saved.__dict__)

    def delete_model(self, request, obj):
        delete_maintenance(request.user, self.model, obj.pk)

    def delete_queryset(self, request, queryset):
        with transaction.atomic():
            for obj in scoped_inventory(request.user, self.model).filter(pk__in=queryset.values("pk")):
                delete_maintenance(request.user, self.model, obj.pk)


@admin.register(ServiceType)
class ServiceTypeAdmin(MaintenanceAdmin):
    form = ServiceTypeForm
    list_display = ("name", "updated_at")


@admin.register(ServiceEvent)
class ServiceEventAdmin(MaintenanceAdmin):
    form = ServiceEventForm
    list_display = ("service_type", "item", "bike", "performed_at", "amount", "currency")


@admin.register(MaintenanceRule)
class MaintenanceRuleAdmin(MaintenanceAdmin):
    form = MaintenanceRuleForm
    list_display = ("service_type", "item", "bike", "distance_m", "moving_time_s", "ride_count", "calendar_days", "elevation_gain_m")
