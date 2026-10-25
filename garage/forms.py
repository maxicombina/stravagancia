"""Actor-bound ModelForms; commit=True always follows authorized services."""
from datetime import datetime, timezone as datetime_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django import forms
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import Bike, Category, Item, UsageBaseline, ServiceEvent
from .services.baselines import record_baseline, update_baseline
from .validators import exact_usage_value
from .services.ownership import (create_inventory, get_inventory, require_actor, scoped_inventory,
                                 update_inventory, validate_category_name)


class UTCDateTimeField(forms.DateTimeField):
    def to_python(self, value):
        with timezone.override("UTC"):
            value = super().to_python(value)
        return value.astimezone(datetime_timezone.utc) if value is not None else None

    def prepare_value(self, value):
        if isinstance(value, datetime) and timezone.is_aware(value):
            return timezone.make_naive(value, datetime_timezone.utc)
        return super().prepare_value(value)


class UTCSplitDateTimeField(forms.SplitDateTimeField):
    def compress(self, values):
        with timezone.override("UTC"):
            value = super().compress(values)
        return value.astimezone(datetime_timezone.utc) if value is not None else None

    def prepare_value(self, value):
        # MultiWidget.decompress runs after this method, so give it naive UTC
        # rather than letting its timezone conversion use the request's zone.
        if isinstance(value, datetime) and timezone.is_aware(value):
            return timezone.make_naive(value, datetime_timezone.utc)
        return super().prepare_value(value)


class OwnedInventoryForm(forms.ModelForm):
    def __init__(self, *args, user, **kwargs):
        self.actor = require_actor(user)
        instance = kwargs.get("instance")
        self._resource_id = None
        if instance is not None:
            if instance._state.adding:
                # Callers use an empty form for creation, preventing supplied
                # owner/UUID instances from being interpreted as new records.
                raise PermissionDenied("Use an empty inventory form to create a resource.")
            instance = get_inventory(self.actor, self._meta.model, instance.pk)
            kwargs["instance"] = instance
            self._resource_id = instance.pk
        super().__init__(*args, **kwargs)
        self.instance.owner = self.actor
        if "category" in self.fields:
            self.fields["category"].queryset = scoped_inventory(self.actor, Category)
        for name in ("acquisition_anchor_at", "retired_at"):
            if name in self.fields:
                original = self.fields[name]
                field_class = UTCSplitDateTimeField if isinstance(original, forms.SplitDateTimeField) else UTCDateTimeField
                self.fields[name] = field_class(required=original.required, widget=original.widget,
                    label=f"{original.label} (UTC)",
                    help_text="Times without an offset are interpreted as UTC.", disabled=original.disabled,
                    initial=original.initial, error_messages=original.error_messages)

    def _get_validation_exclusions(self):
        exclusions = super()._get_validation_exclusions()
        exclusions.discard("owner")
        return exclusions

    def clean(self):
        cleaned = super().clean()
        if self._meta.model is Category and "name" in cleaned:
            cleaned["name"] = cleaned["name"].strip()
            validate_category_name(self.actor, cleaned["name"], resource_id=self._resource_id)
        return cleaned

    def save(self, commit=True):
        # ModelForm checks errors first and applies its cleaned values.
        obj = super().save(commit=False)
        if not commit:
            return obj
        values = {field.name: getattr(obj, field.name) for field in obj._meta.fields
                  if field.editable and not field.primary_key and field.name in self.fields}
        try:
            if self._resource_id is None:
                self.instance = create_inventory(self.actor, self._meta.model, **values)
            else:
                self.instance = update_inventory(self.actor, self._meta.model, self._resource_id, **values)
        except ValidationError as error:
            # Keep a race visible to the caller and attached to the bound form.
            self._update_errors(error)
            raise
        return self.instance


class CategoryForm(OwnedInventoryForm):
    class Meta:
        model = Category
        fields = ("name", "icon", "notes", "is_archived")


class BikeForm(OwnedInventoryForm):
    class Meta:
        model = Bike
        fields = ("name", "brand", "model", "serial_number", "acquired_on", "acquisition_anchor_at",
                  "retired_at", "notes", "purchase_amount", "purchase_currency")


class ItemForm(OwnedInventoryForm):
    class Meta:
        model = Item
        fields = (*BikeForm.Meta.fields, "category")


class LocalDateTimeField(forms.DateTimeField):
    """Keep wall time naive until the explicitly submitted IANA zone is known."""
    def to_python(self, value):
        if value in self.empty_values:
            return None
        if isinstance(value, datetime):
            parsed = value
        else:
            try:
                parsed = parse_datetime(str(value).strip())
            except ValueError:
                parsed = None
            if parsed is None:
                for date_format in self.input_formats:
                    try:
                        parsed = datetime.strptime(str(value), date_format)
                        break
                    except ValueError:
                        continue
        if parsed is None:
            raise ValidationError("Introduce una fecha y hora local.", code="invalid")
        if timezone.is_aware(parsed):
            raise ValidationError("Introduce la hora local sin desfase y elige su zona horaria aparte.", code="invalid_local_time")
        return parsed

    def prepare_value(self, value):
        # UsageBaselineForm prepares the selected zone's naive wall time.
        return value


def local_time_to_utc(value, zone_name):
    if not isinstance(value, datetime) or timezone.is_aware(value):
        raise ValidationError("Introduce la hora local sin desfase.", code="invalid_local_time")
    try:
        zone = ZoneInfo(zone_name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ValidationError("Elige una zona horaria IANA válida.", code="invalid_time_zone") from None
    candidates = set()
    try:
        for fold in (0, 1):
            instant = value.replace(tzinfo=zone, fold=fold).astimezone(datetime_timezone.utc)
            if instant.astimezone(zone).replace(tzinfo=None) == value:
                candidates.add(instant)
    except (OverflowError, ValueError):
        raise ValidationError("Esa hora local está fuera del intervalo admitido.", code="invalid_local_time") from None
    if not candidates:
        raise ValidationError("Esa hora local no existe (cambio de hora): elige otra.", code="nonexistent_local_time")
    if len(candidates) != 1:
        raise ValidationError("Esa hora local se repite (cambio de hora): elige otra.", code="ambiguous_local_time")
    return candidates.pop()


class ExactUsageDecimalField(forms.DecimalField):
    def to_python(self, value):
        parsed = super().to_python(value)
        return exact_usage_value(parsed) if parsed is not None else None


class UsageBaselineForm(OwnedInventoryForm):
    """New readings require a new key; corrections use an explicit owned instance."""
    cut_at = LocalDateTimeField(label="Instante de referencia (hora local)",
                               help_text="Una fecha sin hora es la medianoche local de la zona elegida.")
    time_zone = forms.CharField(initial="UTC", label="Zona horaria IANA", help_text="Por ejemplo UTC o Europe/Madrid.")
    value = ExactUsageDecimalField(max_digits=20, decimal_places=3,
        help_text="Metros, segundos o salidas según la métrica. Desconocido significa sin lectura.")

    class Meta:
        model = UsageBaseline
        fields = ("item", "metric", "scope", "service_event", "cut_at", "time_zone", "value", "source", "is_estimated", "notes")

    def __init__(self, *args, user, time_zone="UTC", **kwargs):
        super().__init__(*args, user=user, **kwargs)
        self.fields["item"].queryset = scoped_inventory(self.actor, Item)
        self.fields["service_event"].queryset = scoped_inventory(self.actor, ServiceEvent)
        self.initial.setdefault("time_zone", time_zone)
        if not self.is_bound and isinstance(self.initial.get("cut_at"), datetime):
            value = self.initial["cut_at"]
            if timezone.is_aware(value):
                try:
                    zone = ZoneInfo(self.initial["time_zone"])
                except (ZoneInfoNotFoundError, ValueError, TypeError):
                    raise ValidationError("Elige una zona horaria IANA válida.", code="invalid_time_zone") from None
                self.initial["cut_at"] = value.astimezone(zone).replace(tzinfo=None)

    def clean_time_zone(self):
        value = self.cleaned_data["time_zone"]
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValidationError("Elige una zona horaria IANA válida.", code="invalid_time_zone") from None
        return value

    def clean(self):
        cleaned = super().clean()
        if "cut_at" in cleaned and "time_zone" in cleaned:
            try:
                cleaned["cut_at"] = local_time_to_utc(cleaned["cut_at"], cleaned["time_zone"])
            except ValidationError as error:
                self.add_error("cut_at", error)
        return cleaned

    def save(self, commit=True):
        obj = forms.ModelForm.save(self, commit=False)
        if not commit:
            return obj
        values = {field.name: getattr(obj, field.name) for field in obj._meta.fields
                  if field.editable and not field.primary_key and field.name in self.fields}
        try:
            self.instance = record_baseline(self.actor, **values) if self._resource_id is None else update_baseline(
                self.actor, self._resource_id, **values)
        except ValidationError as error:
            self._update_errors(error)
            raise
        return self.instance
