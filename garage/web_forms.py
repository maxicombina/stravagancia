"""Private HTML forms composed from the actor-bound domain forms."""
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .forms import BikeForm, CategoryForm, ItemForm, LocalDateTimeField, UsageBaselineForm, local_time_to_utc
from .icons import ICON_CHOICES, ICON_KEYS
from .models import Bike, Item, UsageBaseline
from .services.baselines import record_baseline
from .services.categories import suggest_icon
from .services.installations import create_installation, update_installation
from .services.ownership import require_actor, scoped_inventory
from .validators import exact_usage_value

ZONE_HELP = "Zona IANA, por ejemplo UTC o Europe/Madrid. Horas locales: AAAA-MM-DDTHH:MM:SS (fracciones opcionales). Las horas ambiguas o inexistentes deben corregirse."
LOCAL_WIDGET = forms.DateTimeInput(attrs={"placeholder": "2026-01-01T10:30:00.123456"}, format="%Y-%m-%dT%H:%M:%S.%f")
LOCAL_WIDGET.supports_microseconds = True
LABELS = {"name": "Nombre", "brand": "Marca", "model": "Modelo", "serial_number": "Número de serie",
          "acquired_on": "Fecha de compra", "acquisition_anchor_at": "Inicio del uso desde adquisición",
          "notes": "Notas", "purchase_amount": "Precio de compra", "purchase_currency": "Moneda (ISO 4217)",
          "category": "Categoría", "is_archived": "Archivada", "icon": "Icono", "time_zone": "Zona horaria IANA",
          "bike": "Bici de destino", "parent_item": "Objeto de destino", "slot": "Posición exclusiva",
          "started_at": "Inicio", "ended_at": "Final (vacío: sigue montado)", "at": "Instante del cambio",
          "incoming_item": "Objeto entrante", "metric": "Métrica", "scope": "Ámbito de la lectura",
          "cut_at": "Instante de referencia", "value": "Valor (metros, segundos o salidas)",
          "source": "Procedencia declarada", "is_estimated": "Lectura estimada"}
SCOPES = [("lifetime", "Toda la vida"), ("acquisition", "Desde mi adquisición"), ("service", "Desde una intervención concreta")]
METRICS = [("distance_m", "Distancia (metros)"), ("moving_time_s", "Movimiento (segundos)"), ("ride_count", "Salidas")]
SOURCE_CHOICES = [("manual", "Lectura manual propia"), ("manual_garmin_reading", "Lectura manual de Garmin")]


def decorate(form):
    for name, field in form.fields.items():
        field.label = LABELS.get(name, field.label)
        if isinstance(field.widget, forms.DateInput) and not isinstance(field.widget, forms.DateTimeInput):
            field.widget = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


def clean_zone(value):
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ValidationError("Elige una zona horaria IANA válida.", code="invalid_time_zone") from None
    return value


def convert_local_fields(form, cleaned, names):
    zone = cleaned.get("time_zone")
    if zone:
        for name in names:
            value = cleaned.get(name)
            if value is not None:
                try:
                    cleaned[name] = local_time_to_utc(value, zone)
                except ValidationError as error:
                    form.add_error(name, error)
    return cleaned


class InventoryWebMixin:
    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, user=user, **kwargs)
        # Retirement is an explicit action, not an accidental empty edit field.
        self.fields.pop("retired_at", None)
        if "acquisition_anchor_at" in self.fields:
            self.fields["acquisition_anchor_at"] = LocalDateTimeField(required=False,
                widget=LOCAL_WIDGET, label=LABELS["acquisition_anchor_at"],
                help_text="Opcional e independiente de la compra. No se deduce automáticamente de su fecha.")
            self.fields["time_zone"] = forms.CharField(initial="UTC", help_text=ZONE_HELP)
            value = self.initial.get("acquisition_anchor_at")
            if isinstance(value, datetime) and timezone.is_aware(value):
                self.initial["acquisition_anchor_at"] = value.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        decorate(self)

    def clean_time_zone(self):
        return clean_zone(self.cleaned_data["time_zone"])

    def clean(self):
        return convert_local_fields(self, super().clean(), ("acquisition_anchor_at",))


class IconGrid(forms.RadioSelect):
    """Radio buttons drawn as a grid of icons by _icon_grid.html (widget_type 'icongrid'); no JavaScript.

    `suggested` is the glyph drawn in the «Según el nombre» tile: what the name deduces right now.
    """
    suggested = ""

    def value_omitted_from_data(self, data, files, name):
        # A radio group with nothing checked posts nothing. That means «Según el nombre» (''),
        # never «keep the stored key», which may be one the list no longer offers.
        return False


BY_NAME_HELP = ("Lo heredan sus objetos. «Según el nombre» no fija ninguno: cada objeto toma el que sugiere su nombre "
                "y, si no, el del nombre de la categoría.")
ICON_ERROR = "Elige uno de los iconos de la lista."


class CategoryWebForm(InventoryWebMixin, CategoryForm):
    icon = forms.ChoiceField(required=False, widget=IconGrid, label="Icono",
        choices=[("", "Según el nombre"), *((key, label) for key, label, _ in ICON_CHOICES)], help_text=BY_NAME_HELP,
        # invalid_icon: Category.clean() rejecting a key (ModelForm maps model error codes to these).
        error_messages={"invalid_choice": ICON_ERROR, "invalid_icon": ICON_ERROR})

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Not instance.pk: OwnedResource.id has a uuid4 default, so a new category has one too.
        self.editing = self._resource_id is not None
        if self.editing and self.instance.icon not in ICON_KEYS:
            # '' or a key the list no longer offers: «Según el nombre» is checked, so a plain edit
            # posts a valid choice. '' is kept as '' (deduced each time), never frozen to a suggestion.
            self.initial["icon"] = ""
        if self.is_bound:
            name = self.data.get(self.add_prefix("name")) or ""
        else:
            name = self.instance.name if self.editing else ""
        self.fields["icon"].widget.suggested = suggest_icon(name)


class BikeWebForm(InventoryWebMixin, BikeForm):
    pass


class ItemWebForm(InventoryWebMixin, ItemForm):
    pass


class UsedItemWebForm(ItemWebForm):
    """Optional independent readings; the outer transaction includes the item."""
    reading_definitions = (("distance", "distance_m", Decimal("1000"), "Kilómetros previos conocidos"),
                           ("time", "moving_time_s", Decimal("3600"), "Horas de movimiento previas conocidas"),
                           ("rides", "ride_count", Decimal("1"), "Salidas previas conocidas"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for key, metric, scale, label in self.reading_definitions:
            self.fields[f"previous_{key}"] = forms.DecimalField(required=False, max_digits=20, decimal_places=6,
                label=label, help_text="Vacío significa desconocido; cero indica una lectura conocida de cero.")
            self.fields[f"previous_{key}_cut"] = LocalDateTimeField(required=False, widget=LOCAL_WIDGET,
                label=f"Referencia de {label.lower()}")
            self.fields[f"previous_{key}_scope"] = forms.ChoiceField(choices=[choice for choice in SCOPES if choice[0] != "service"], required=False,
                initial="lifetime", label="Qué uso cubre esta lectura")
        self.fields["reading_source"] = forms.ChoiceField(choices=SOURCE_CHOICES, initial="manual", required=False,
                                                         label="Procedencia de las lecturas")
        self.fields["reading_estimated"] = forms.BooleanField(required=False, label="Estas lecturas son estimadas")

    def clean(self):
        cleaned = super().clean()
        convert_local_fields(self, cleaned, [f"previous_{key}_cut" for key, *_ in self.reading_definitions])
        for key, metric, scale, label in self.reading_definitions:
            field, cut, scope = f"previous_{key}", f"previous_{key}_cut", f"previous_{key}_scope"
            value = cleaned.get(field)
            if value is None:
                if cleaned.get(cut) is not None:
                    self.add_error(field, "Introduce una lectura o deja también su referencia vacía.")
                continue
            try:
                cleaned[field] = exact_usage_value(value * scale, metric=metric)
            except ValidationError as error:
                self.add_error(field, error)
            if cleaned.get(cut) is None and cut not in self.errors:
                self.add_error(cut, "Indica el instante de referencia de esta métrica.")
            if not cleaned.get(scope):
                self.add_error(scope, "Elige qué uso cubre esta lectura.")
            if not cleaned.get("reading_source"):
                self.add_error("reading_source", "Declara la procedencia de la lectura.")
            if cleaned.get(scope) == "acquisition":
                anchor = cleaned.get("acquisition_anchor_at")
                if anchor is None:
                    self.add_error(scope, "Confirma el inicio de adquisición para este ámbito.")
                elif cleaned.get(cut) is not None and cleaned[cut] < anchor:
                    self.add_error(cut, "La referencia no puede ser anterior a la adquisición.")
        return cleaned

    def save_with_readings(self):
        with transaction.atomic():
            item = self.save()
            for key, metric, scale, label in self.reading_definitions:
                value = self.cleaned_data.get(f"previous_{key}")
                if value is not None:
                    record_baseline(self.actor, item=item, metric=metric,
                        scope=self.cleaned_data[f"previous_{key}_scope"],
                        cut_at=self.cleaned_data[f"previous_{key}_cut"], value=value,
                        source=self.cleaned_data["reading_source"], is_estimated=self.cleaned_data["reading_estimated"])
            return item


class TemporalActionForm(forms.Form):
    time_zone = forms.CharField(initial="UTC", label=LABELS["time_zone"], help_text=ZONE_HELP)
    at = LocalDateTimeField(widget=LOCAL_WIDGET, label=LABELS["at"])

    def __init__(self, *args, user, **kwargs):
        self.actor = require_actor(user)
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial.setdefault("at", timezone.now().astimezone(ZoneInfo("UTC")).replace(tzinfo=None, microsecond=0))
        decorate(self)

    def clean_time_zone(self):
        return clean_zone(self.cleaned_data["time_zone"])

    def clean(self):
        return convert_local_fields(self, super().clean(), ("at",))


class InstallationWebForm(TemporalActionForm):
    # No editable item/owner/UUID: the item is fixed by the owned URL.
    at = None
    started_at = LocalDateTimeField(widget=LOCAL_WIDGET)
    ended_at = LocalDateTimeField(required=False, widget=LOCAL_WIDGET)
    bike = forms.ModelChoiceField(queryset=Bike.objects.none(), required=False)
    parent_item = forms.ModelChoiceField(queryset=Item.objects.none(), required=False)
    slot = forms.CharField(max_length=80, required=False, help_text="Ejemplos: main_saddle, front_wheel, rear_wheel. Vacío: sin exclusividad.")
    notes = forms.CharField(widget=forms.Textarea, required=False)

    def __init__(self, *args, user, item, installation=None, **kwargs):
        self.item, self.installation = item, installation
        super().__init__(*args, user=user, **kwargs)
        self.fields["bike"].queryset = scoped_inventory(self.actor, Bike)
        self.fields["parent_item"].queryset = scoped_inventory(self.actor, Item).exclude(pk=item.pk)
        if installation is not None and not self.is_bound:
            for field in ("bike", "parent_item", "slot", "notes"):
                self.initial[field] = getattr(installation, field)
            for field in ("started_at", "ended_at"):
                value = getattr(installation, field)
                self.initial[field] = value.astimezone(ZoneInfo("UTC")).replace(tzinfo=None) if value else None
        elif not self.is_bound:
            self.initial.setdefault("started_at", timezone.now().astimezone(ZoneInfo("UTC")).replace(tzinfo=None, microsecond=0))

    def clean(self):
        cleaned = super().clean()
        convert_local_fields(self, cleaned, ("started_at", "ended_at"))
        if bool(cleaned.get("bike")) == bool(cleaned.get("parent_item")):
            self.add_error(None, "Elige exactamente una bici o un objeto de destino.")
        if cleaned.get("started_at") and cleaned.get("ended_at") and cleaned["ended_at"] <= cleaned["started_at"]:
            self.add_error("ended_at", "El final debe ser posterior al inicio.")
        return cleaned

    def save(self):
        values = {key: self.cleaned_data.get(key) for key in ("bike", "parent_item", "slot", "started_at", "ended_at", "notes")}
        if self.installation is None:
            return create_installation(self.actor, item=self.item, **values)
        return update_installation(self.actor, self.installation.pk, **values)


class ReplacementWebForm(TemporalActionForm):
    incoming_item = forms.ModelChoiceField(queryset=Item.objects.none())
    inherit_lifespan = forms.BooleanField(required=False, initial=True, label="La pieza nueva hereda la vida útil",
        help_text="Los mismos umbrales (km, horas, desnivel, tiempo y salidas), contados desde el reemplazo. No cambia una vida útil que ya tenga.")

    retire_outgoing = forms.BooleanField(required=False, initial=False, label="Retirar lo que sale",
        help_text="Deja de avisar y de aparecer como disponible, en el mismo instante. Se puede reactivar. "
                  "Sin marcar queda disponible (por ejemplo, ruedas de invierno).")

    def __init__(self, *args, user, installation, **kwargs):
        super().__init__(*args, user=user, **kwargs)
        self.fields["incoming_item"].queryset = scoped_inventory(self.actor, Item).exclude(pk=installation.item_id)
        self.fields["retire_outgoing"].label = f"Retirar lo que sale ({installation.item.name})"
        if installation.item.retired_at is not None:
            self.fields.pop("retire_outgoing")  # its retirement is already scheduled
        else:
            from .services.retirement import direct_parts
            inside = direct_parts(self.actor, installation.item)
            if inside:
                self.fields["retire_outgoing"].help_text += (" Sus piezas (" + ", ".join(obj.name for obj in inside) +
                                                             ") se desmontan y quedan disponibles; lo que llevan dentro sigue en ellas.")
        from .services.lifespan import lifespan_rule
        if lifespan_rule(self.actor, installation.item_id) is None:
            self.fields.pop("inherit_lifespan")  # nothing to inherit


class RetireWebForm(TemporalActionForm):
    """Retire a bike or item; optionally what is mounted in it too (garage-038)."""
    with_parts = forms.BooleanField(required=False, initial=False)
    shown_parts = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, user, inside=(), **kwargs):
        super().__init__(*args, user=user, **kwargs)
        if inside:
            names = ", ".join(obj.name for obj in inside)
            self.fields["with_parts"].label = f"Retirar también lo que lleva montado ({len(inside)})"
            self.fields["with_parts"].help_text = (f"Ahora: {names}. Sin marcar, lo montado directamente se desmonta y queda "
                                                   "disponible; lo que va dentro de otra pieza sigue en ella. Reactivar después "
                                                   "no reactiva ni vuelve a montar nada.")
            self.initial["shown_parts"] = ",".join(str(obj.pk) for obj in inside)
        else:
            self.fields.pop("with_parts")
            self.fields.pop("shown_parts")

    def clean_shown_parts(self):
        from uuid import UUID
        try:
            # Empty or unreadable: nothing to compare (a client that never showed the list).
            return [UUID(value) for value in self.cleaned_data["shown_parts"].split(",") if value] or None
        except ValueError:
            return None


class TransferWebForm(TemporalActionForm):
    bike = forms.ModelChoiceField(queryset=Bike.objects.none(), required=False)
    parent_item = forms.ModelChoiceField(queryset=Item.objects.none(), required=False)
    slot = forms.CharField(max_length=80, required=False, help_text="Vacío: posición no exclusiva en el nuevo destino.")

    def __init__(self, *args, user, installation, **kwargs):
        super().__init__(*args, user=user, **kwargs)
        self.fields["bike"].queryset = scoped_inventory(self.actor, Bike)
        self.fields["parent_item"].queryset = scoped_inventory(self.actor, Item).exclude(pk=installation.item_id)

    def clean(self):
        cleaned = super().clean()
        if bool(cleaned.get("bike")) == bool(cleaned.get("parent_item")):
            self.add_error(None, "Elige exactamente un destino.")
        return cleaned


class BaselineWebForm(UsageBaselineForm):
    def __init__(self, *args, user, item, **kwargs):
        self.fixed_item = item
        super().__init__(*args, user=user, **kwargs)
        self.fields["item"].disabled = True
        self.initial["item"] = item
        self.fields["scope"].choices = SCOPES
        self.fields["service_event"].queryset = self.fields["service_event"].queryset.filter(item=item)
        self.fields["metric"].choices = METRICS
        self.fields["cut_at"].widget = LOCAL_WIDGET
        decorate(self)
        self.fields["time_zone"].help_text = ZONE_HELP
