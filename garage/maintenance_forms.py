"""Actor-bound maintenance forms with explicit local-time interpretation."""
import re
from datetime import datetime
from decimal import Decimal, localcontext
from functools import cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import DecimalValidator, MaxLengthValidator, ProhibitNullCharactersValidator

from .choices import TARGET_FIELDS
from .forms import LocalDateTimeField, OwnedInventoryForm, local_time_to_utc
from .models import THRESHOLD_FIELDS, Bike, Item, MaintenanceRule, ServiceEvent, ServiceType
from .ordering import by_name
from .services.lifespan import is_life_type
from .services.maintenance import save_maintenance
from .services.ownership import scoped_inventory
from .validators import MAX_USAGE_VALUE, exact_usage_value

LOCAL_WIDGET = forms.DateTimeInput(format="%Y-%m-%dT%H:%M:%S.%f", attrs={"placeholder": "2026-01-01T10:30:00.123456"})
LOCAL_WIDGET.supports_microseconds = True


# Model messages are English; the private pages speak Spanish (same codes and fields).
SPANISH = {
    "Configure at least one independent threshold.": "Indica al menos un umbral: distancia, tiempo, salidas, días o desnivel.",
    "Enter a strictly positive threshold.": "Debe ser mayor que cero.",
    "Choose exactly one item or bike.": "Elige un objeto o una bici, no ambos.",
    "Choose one of your own resources.": "Elige uno de tus propios elementos.",
    "Enter both an amount and its currency, or neither.": "Indica importe y moneda, o ninguno de los dos.",
    "Correct or remove service readings before changing the event reference.":
        "Corrige o elimina antes las lecturas de esta intervención para cambiar su objeto, tipo o fecha.",
    "A photographed intervention cannot change its target.": "Una intervención con fotos no puede cambiar de objeto o bici.",
    "Constraint “garage_rule_item_type_unique” is violated.": "Ya hay una regla de ese tipo para este objeto: edítala.",
    "Constraint “garage_rule_bike_type_unique” is violated.": "Ya hay una regla de ese tipo para esta bici: edítala.",
    "Constraint “garage_servicetype_owner_name_unique” is violated.": "Ya tienes un tipo con ese nombre.",
    "Enter an instant with an explicit time zone.": "Indica la fecha y hora con su zona horaria.",
    "Enter an uppercase ISO 4217 currency code.": "Usa un código de moneda ISO 4217, por ejemplo EUR.",
    # Inventory, mounts and readings (garage-047 F07).
    "This item is already installed during this period.": "Este objeto ya está montado en ese período.",
    "This position is occupied during this period.": "Esa posición ya está ocupada en ese período.",
    "These installations form a cycle during a common period.": "Esos montajes forman un ciclo en un período común.",
    "Choose exactly one destination.": "Elige exactamente una bici o un objeto de destino.",
    "An item cannot contain itself.": "Un objeto no puede ir montado dentro de sí mismo.",
    "The end must be later than the start.": "El final debe ser posterior al inicio.",
    "The installation must finish by this resource's retirement.": "El montaje debe terminar antes de que se retire.",
    "The installation overlaps recorded inactivity.": "El montaje coincide con un período en el que estaba retirado.",
    "Choose an instant strictly inside the outgoing installation.":
        "El cambio tiene que caer dentro del montaje actual: después de su inicio y, si tiene final, antes de él.",
    "Use a lowercase ASCII position key.": "Usa minúsculas, números y guion bajo, por ejemplo rear_wheel.",
    "This installation is already closed; edit it explicitly to correct history.":
        "Ese montaje ya está cerrado: corrígelo con «Editar período».",
    "Enter a nonempty name.": "Escribe un nombre.",
    "You already have a category with this name.": "Ya tienes una categoría con ese nombre.",
    "Enter both a purchase amount and its currency, or neither.": "Indica precio y moneda, o ninguno de los dos.",
    "Choose one of your own categories.": "Elige una de tus categorías.",
    "Choose one of your own items.": "Elige uno de tus objetos.",
    "Correct acquisition readings before removing their anchor.":
        "Hay lecturas «Desde mi adquisición»: corrígelas antes de quitar este inicio.",
    "The acquisition anchor cannot follow an existing acquisition reading.":
        "El inicio del uso desde adquisición no puede ser posterior a una lectura «Desde mi adquisición» ya registrada.",
    "Declare the reading's source.": "Indica la procedencia de la lectura.",
    "The reading cannot precede acquisition.": "La lectura no puede ser anterior a la adquisición.",
    "Confirm the acquisition instant before recording this scope.": "Confirma antes el inicio de la adquisición para este ámbito.",
    "Constraint “garage_baseline_unique_reading” is violated.": "Ya hay una lectura de esa métrica y ámbito en ese instante: corrígela.",
    "Constraint “garage_baseline_service_unique” is violated.": "Ya hay una lectura de esa métrica y ámbito en ese instante: corrígela.",
    "Correct the existing reading at this cut instead of creating another.":
        "Ya hay una lectura de esa métrica y ámbito en ese instante: corrígela.",
    "Only service readings require an intervention.":
        "La intervención va con el ámbito «Desde una intervención concreta», y sólo con él.",
    "Choose an intervention on this own item.": "Elige una intervención de este mismo objeto.",
    "The reading cannot precede the intervention.": "La lectura no puede ser anterior a la intervención.",
    "The number of rides must be an integer.": "Las salidas son un número entero.",
    "The value must be exactly representable with three decimal places.": "El valor exacto admite como máximo 3 decimales.",
    "Enter a finite nonnegative value within the supported range.": "Escribe un valor positivo o cero, dentro del máximo admitido.",
    # ModelChoiceField.to_python raises it itself, before run_validators could use FIELD_MESSAGES.
    "Null characters are not allowed.": "No se admiten caracteres nulos.",
    # Usage profiles and manual rides (garage-047 D25).
    "Use an explicit historical operation for past dates.":
        "Esa fecha ya ha pasado: para fechas pasadas, elige «Aplicar explícitamente al histórico».",
    "Split strictly inside this profile version's interval.":
        "La nueva versión tiene que empezar dentro de la vigencia de esta: después de su inicio y, si tiene final, antes de él.",
    "Profile versions in the same series cannot overlap.": "Las versiones de un mismo perfil no pueden solaparse.",
    "A correction cannot remove the only known start.": "Ninguna fuente aporta el inicio: sin la corrección, quedaría desconocido.",
    # A forged choice that is not even a key: the model's UUIDField refuses it before ModelChoiceField and
    # ModelMultipleChoiceField look it up, with the value in the text (garage-047 B2b-R1-02). Found by its template.
    "“%(value)s” is not a valid UUID.": "Elige una opción válida.",
}
FIELD_MESSAGES = {"required": "Este campo es obligatorio.", "invalid_choice": "Elige una opción válida.",
                  "min_value": "Debe ser como mínimo %(limit_value)s.", "max_value": "Debe ser como máximo %(limit_value)s.",
                  "max_length": "Como máximo %(limit_value)d caracteres.",
                  # Validators' codes: Field.run_validators shows these instead and keeps their parameters.
                  "max_decimal_places": "Como máximo %(max)s decimales.", "max_digits": "Como máximo %(max)s cifras.",
                  "max_whole_digits": "Como máximo %(max)s cifras antes de la coma.",
                  "null_characters_not_allowed": "No se admiten caracteres nulos."}
# DecimalField subclasses IntegerField: the most specific type goes first. DateTimeField is no DateField.
INVALID = ((forms.DecimalField, "Introduce un número."), (forms.IntegerField, "Introduce un número entero."),
           (forms.DateTimeField, "Introduce una fecha y hora válidas."), (forms.DateField, "Introduce una fecha válida."),
           (forms.FileField, "No llegó ningún archivo: vuelve a elegirlo."))
# A file's own limit is on its name, with other parameters than a text's (garage-047 D25).
FILE_MESSAGES = {"empty": "El archivo está vacío.",
                 "max_length": "El nombre del archivo admite como máximo %(max)d caracteres."}


def _spanish_one(error):
    message = str(error.message % error.params if error.params else error.message)
    if message in SPANISH:
        return ValidationError(SPANISH[message], code=error.code)
    template = str(error.message)  # a message that carries the value typed is only known by its template
    if error.params and template in SPANISH:
        return ValidationError(SPANISH[template], code=error.code, params=error.params)
    return error


def error_key(error):
    """The code and the text of one error once translated: two errors with the same key say the same thing."""
    spanish = _spanish_one(error)
    return spanish.code, str(spanish.message % spanish.params if spanish.params else spanish.message)


def _spanish(error):
    if isinstance(error, ValidationError):
        if hasattr(error, "error_dict"):
            return ValidationError({key: [_spanish_one(item) for item in items] for key, items in error.error_dict.items()})
        return ValidationError([_spanish_one(item) for item in error.error_list])
    if isinstance(error, str):
        return SPANISH.get(error, error)
    if isinstance(error, dict):
        return {key: _spanish(value) for key, value in error.items()}
    if isinstance(error, list):
        return [_spanish(item) for item in error]
    return error


def _default_message(field, code):
    for cls in type(field).__mro__:
        message = vars(cls).get("default_error_messages", {}).get(code)
        if message is not None:
            return message
    return None


def spanish_fields(form):
    """Spanish built-in messages for the fields present now (LANGUAGE_CODE stays en-us for the old app).

    Messages a field already customizes are kept.
    """
    for field in form.fields.values():
        wanted = dict(FIELD_MESSAGES)
        for kind, message in INVALID:
            if isinstance(field, kind):
                wanted["invalid"] = message
                break
        if isinstance(field, forms.FileField):
            wanted.update(FILE_MESSAGES)
        for code, message in wanted.items():
            current = field.error_messages.get(code)
            if current is None or current == _default_message(field, code):
                field.error_messages[code] = message


class SpanishWebMixin:
    """Phone pages: Spanish built-in and model messages. The admin forms keep their own."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        spanish_fields(self)

    def add_error(self, field, error):
        super().add_error(field, _spanish(error))


class DecimalTextInput(forms.TextInput):
    """Shows decimals with a comma, as the person types them."""

    def format_value(self, value):
        if isinstance(value, Decimal):
            return format(value, "f").replace(".", ",")
        return super().format_value(value)


SPANISH_GROUPED = re.compile(r"[+-]?[1-9]\d{0,2}(\.\d{3})+,\d*")
COMMA_DECIMAL = re.compile(r"[+-]?\d*,\d*")
DOT_GROUPS = re.compile(r"[+-]?[1-9]\d{0,2}(\.\d{3})+")  # "0.500" is a decimal: a thousands group never starts with 0


class DecimalInput(forms.DecimalField):
    """Text with a decimal keypad: '3,5', '2.700,5' and '2700.5' are read; '3.000' is ambiguous and rejected.

    A number input could silently drop a decimal comma, and a dot that groups
    thousands must never become a decimal point.
    """
    widget = DecimalTextInput

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.widget.attrs.update({"inputmode": "decimal", "autocomplete": "off"})

    def widget_attrs(self, widget):
        return {}  # no number-input min/step attributes on a text field

    def to_python(self, value):
        if isinstance(value, str):
            value = value.strip().replace(" ", "").replace("\u00a0", "").replace("\u202f", "")
            if "," in value:
                if not (SPANISH_GROUPED.fullmatch(value) or COMMA_DECIMAL.fullmatch(value)):
                    raise ValidationError(self.error_messages["invalid"], code="invalid")
                value = value.replace(".", "").replace(",", ".")
            elif DOT_GROUPS.fullmatch(value):
                raise ValidationError("¿Miles o decimales? Usa coma decimal (3,5) o escribe el número sin puntos (3000).", code="ambiguous")
        return super().to_python(value)


SPACES = (" ", "\u00a0", "\u202f")  # space, no-break space and narrow no-break space (fr/es thousands)


class WholeNumberInput(forms.IntegerField):
    """Whole numbers as typed in Spanish: '20.000' and '20 000' are 20000; '1.5', '2,5' and '1.000,0' are rejected.

    Django's IntegerField drops a trailing '.0*' before int(), so '1.000' would
    silently become 1 (garage-030 phase 3 review). No decimals are ever allowed
    here, so a dot grouping thousands is unambiguous; any other dot or comma is
    an error. A text input with a numeric keypad: a number input could reinterpret
    the dot before the server sees it.
    """
    widget = forms.TextInput

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.widget.attrs.update({"inputmode": "numeric", "autocomplete": "off"})

    def to_python(self, value):
        if isinstance(value, str):
            for space in SPACES:
                value = value.replace(space, "")
            value = value.strip()
            if DOT_GROUPS.fullmatch(value):
                value = value.replace(".", "")
            elif "." in value or "," in value:
                raise ValidationError(self.error_messages["invalid"], code="invalid")
        return super().to_python(value)


ELEVATION_HELP = "Metros enteros de subida acumulada. Cuentan las salidas que lo registran."
ELEVATION_MESSAGES = {"invalid": "Introduce metros enteros, sin decimales (1500 o 1.500).", "min_value": "Debe ser al menos 1 m.",
                      "max_value": "Valor fuera del intervalo admitido."}


def elevation_field(label="Desnivel (m)", help_text=ELEVATION_HELP):
    """Whole metres of climbing (garage-030 phase 3), stored as an exact Decimal by the form's clean()."""
    return WholeNumberInput(required=False, min_value=1, max_value=int(MAX_USAGE_VALUE), label=label, help_text=help_text,
                            error_messages=dict(ELEVATION_MESSAGES))


def whole_metres(value):
    return None if value is None else Decimal(value)


class UpperCodeField(forms.CharField):
    def to_python(self, value):
        value = super().to_python(value)
        return value.upper() if value else value


class MaintenanceForm(OwnedInventoryForm):
    time_zone = forms.CharField(initial="UTC", label="Zona horaria IANA", help_text="Por ejemplo Europe/Madrid. Las horas se interpretan en esta zona.")

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, user=user, **kwargs)
        for field, model in (("item", Item), ("bike", Bike), ("service_type", ServiceType)):
            if field in self.fields:
                self.fields[field].queryset = by_name(scoped_inventory(self.actor, model))
                self.fields[field].empty_label = "Elige un tipo" if field == "service_type" else "—"
        for field in ("performed_at", "anchor_at"):
            if field in self.fields:
                original = self.fields[field]
                self.fields[field] = LocalDateTimeField(required=original.required, widget=LOCAL_WIDGET,
                    label={"performed_at": "Fecha y hora", "anchor_at": "Contar desde (opcional)"}[field],
                    help_text="" if field == "performed_at" else "Sin intervención previa, la regla cuenta desde aquí. Vacío: referencia desconocida.")
                if not self.is_bound and isinstance(self.initial.get(field), datetime):
                    self.initial[field] = self.initial[field].astimezone(ZoneInfo("UTC")).replace(tzinfo=None)

    def clean(self):
        cleaned = super().clean()
        zone = cleaned.get("time_zone")
        if zone:
            try:
                ZoneInfo(zone)
            except (ValueError, KeyError, ZoneInfoNotFoundError):
                self.add_error("time_zone", "Elige una zona horaria IANA válida.")
            else:
                for field in ("performed_at", "anchor_at"):
                    if cleaned.get(field) is not None:
                        try:
                            cleaned[field] = local_time_to_utc(cleaned[field], zone)
                        except ValidationError as error:
                            self.add_error(field, error)
        return cleaned

    def save(self, commit=True):
        obj = forms.ModelForm.save(self, commit=False)
        if not commit:
            return obj
        written = set(self.fields) | set(getattr(self, "converted_fields", ()))
        values = {f.name: getattr(obj, f.name) for f in obj._meta.fields if f.editable and not f.primary_key and f.name in written}
        self.instance = save_maintenance(self.actor, self._meta.model, self._resource_id, **values)
        return self.instance


class ServiceTypeForm(MaintenanceForm):
    time_zone = None

    class Meta:
        model = ServiceType
        fields = ("name", "notes")


class ServiceTypeWebForm(SpanishWebMixin, ServiceTypeForm):
    class Meta(ServiceTypeForm.Meta):
        labels = {"name": "Nombre", "notes": "Notas"}  # here, not in ServiceTypeForm: the admin keeps its own

    def clean_name(self):
        name = self.cleaned_data["name"]
        from .services.lifespan import LIFE_TYPE
        current = (self.instance.name or "") if self.instance.pk else ""
        renamed = current.strip().lower() == LIFE_TYPE.lower() and name.strip().lower() != LIFE_TYPE.lower()
        if renamed and MaintenanceRule.objects.filter(owner=self.actor, service_type=self.instance, item__isnull=False).exists():
            raise ValidationError(f"«{LIFE_TYPE}» guarda la vida útil de tus componentes: no se puede renombrar mientras alguno la tenga.",
                                  code="life_type")
        return name


TARGET_LABELS = {"item": "Objeto", "bike": "Bici", "service_type": "Tipo", "notes": "Notas"}


class ServiceEventForm(MaintenanceForm):
    class Meta:
        model = ServiceEvent
        fields = ("item", "bike", "service_type", "performed_at", "time_zone", "notes", "amount", "currency")
        labels = {**TARGET_LABELS, "amount": "Importe (opcional)", "currency": "Moneda"}
        help_texts = {"item": "Un objeto o una bici, no ambos.", "currency": "Código ISO, por ejemplo EUR."}


class ServiceEventWebForm(SpanishWebMixin, ServiceEventForm):
    """Phone page: decimal comma, field order and a preselected currency (garage-032)."""

    class Meta(ServiceEventForm.Meta):
        field_classes = TARGET_FIELDS  # options that tell equal names apart (garage-047 F02); the admin keeps its own

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        currency = self.fields["currency"]
        self.fields["currency"] = UpperCodeField(required=False, max_length=3, label=currency.label, help_text=currency.help_text,
            validators=[v for v in currency.validators if not isinstance(v, (MaxLengthValidator, ProhibitNullCharactersValidator))],
            empty_value=None, error_messages=currency.error_messages)
        # No placeholder: a grey «EUR» looked like a value already typed (garage-047 F13). The help gives the example.
        self.fields["currency"].widget.attrs.update({"autocapitalize": "characters"})
        # Lets changed_data tell a preselected currency from one the person chose, also on POST.
        self.fields["currency"].show_hidden_initial = True
        amount = self.fields["amount"]
        self.fields["amount"] = DecimalInput(required=False, max_digits=amount.max_digits, decimal_places=amount.decimal_places,
            label=amount.label, help_text=amount.help_text,
            validators=[v for v in amount.validators if not isinstance(v, DecimalValidator)],
            error_messages={**FIELD_MESSAGES, "invalid": "Introduce un importe, por ejemplo 32,90.", "max_decimal_places": "Como máximo 2 decimales.",
                            "max_digits": "Importe fuera del intervalo admitido.", "max_whole_digits": "Importe fuera del intervalo admitido.",
                            "min_value": "El importe no puede ser negativo."})
        self.order_fields(("item", "bike", "service_type", "performed_at", "amount", "currency", "notes"))

    def clean(self):
        cleaned = super().clean()
        # A currency preselected by the page, left untouched, means nothing without an amount.
        if cleaned.get("amount") is None and cleaned.get("currency") and "currency" not in self.changed_data:
            cleaned["currency"] = None
        return cleaned


# Stored exactly in metres and seconds (3 decimals); shown in km and hours when exact.
UNITS = (("distance_m", "distance_km", Decimal(1000), "Distancia (km)", "Como máximo 6 decimales (milímetros)."),
         ("moving_time_s", "moving_time_h", Decimal(3600), "Tiempo en movimiento (horas)",
          "Ese tiempo no se puede guardar exacto (milisegundos): usa menos decimales."))


LIFE_NOTE = "(en un objeto, es su vida útil)"
LIFE_OPTION = f"Sustitución {LIFE_NOTE}"


def rule_type_labels(kinds):
    """How each «Tipo» option of a rule reads (garage-047 F06): a rule of an item of the «Sustitución» type is its useful life.

    Its option says so. Two types can both count as that one: a database that lowercases only ASCII keeps «SUSTITUCIÓN»
    apart from «Sustitución». Then each option keeps its own name in front, so no two read the same. `kinds` (the field's
    queryset) is read only when such an option is shown.
    """
    @cache
    def several():
        return sum(is_life_type(name) for name in kinds.values_list("name", flat=True)) > 1

    def label(kind):
        if not is_life_type(kind.name):
            return str(kind)
        return f"{kind.name.strip()} {LIFE_NOTE}" if several() else LIFE_OPTION
    return label


def _plain(value):
    """Decimal without exponent or trailing zeros: 3000.000 -> 3000, 0.500 -> 0.5."""
    return Decimal(format(value.normalize(), "f"))


def _shown(stored, scale):
    """stored / scale when it is exact with at most 6 decimals, else None."""
    with localcontext() as context:
        context.prec = 60
        shown = stored / scale
        return _plain(shown) if shown == shown.quantize(Decimal("0.000001")) and shown * scale == stored else None


class MaintenanceRuleForm(MaintenanceForm):
    class Meta:
        model = MaintenanceRule
        fields = ("item", "bike", "service_type", "distance_m", "moving_time_s", "ride_count", "calendar_days", "elevation_gain_m",
                  "anchor_at", "time_zone", "notes")
        labels = {**TARGET_LABELS, "distance_m": "Distancia (metros)", "moving_time_s": "Tiempo en movimiento (segundos)",
                  "ride_count": "Salidas", "calendar_days": "Calendario (días)", "elevation_gain_m": "Desnivel (metros)"}
        help_texts = {"item": "Un objeto o una bici, no ambos.", "ride_count": "Número de salidas.",
                      "calendar_days": "Días de 24 horas, aunque no se use.", "elevation_gain_m": "Subida acumulada desde la referencia."}



class MaintenanceRuleWebForm(SpanishWebMixin, MaintenanceRuleForm):
    """Phone page: km and hours when exact, stored as exact metres and seconds (garage-032)."""

    class Meta(MaintenanceRuleForm.Meta):
        # '1.000' salidas or días is a thousand, never 1 (Django's IntegerField would drop '.000').
        # Options that tell equal names apart (garage-047 F02); the admin keeps its own.
        field_classes = {"ride_count": WholeNumberInput, "calendar_days": WholeNumberInput, **TARGET_FIELDS}
        # «Salidas» says it already; on the phone «Número de salidas.» only made its row taller (garage-047 F20). The admin keeps it.
        help_texts = {name: text for name, text in MaintenanceRuleForm.Meta.help_texts.items() if name != "ride_count"}

    # Thresholds two by two, so «Contar desde» comes up the page (garage-047 F20). The km and hours names: a value kept in
    # metres or seconds has another field, and then each of the pair goes on its own line.
    field_rows = (("distance_km", "moving_time_h"), ("ride_count", "calendar_days"))

    # A threshold the form rejected reached the rule empty, so «at least one» would be false: one was typed (garage-047 F07).
    FOLLOWS = {**MaintenanceRuleForm.FOLLOWS, **{name: "Configure at least one independent threshold."
                                                 for name in (*THRESHOLD_FIELDS, *(friendly for _, friendly, *_ in UNITS))}}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        service_type = self.fields["service_type"]
        service_type.label_from_instance = rule_type_labels(service_type.queryset)  # only the text: the value sent is the same
        self.converted_fields = set()
        fields = {}
        for name, field in self.fields.items():
            unit = next((unit for unit in UNITS if unit[0] == name), None)
            if unit is None:
                fields[name] = field
                continue
            exact, friendly, scale, label, _ = unit
            stored = self.initial.get(exact)
            if self.is_bound:
                # Posting the exact field (metres, seconds) stays supported.
                keep_exact = exact in self.data and friendly not in self.data
                shown = None
            else:
                shown = _shown(Decimal(stored), scale) if stored is not None else None
                keep_exact = stored is not None and shown is None
            if keep_exact:
                fields[name] = field
                continue
            fields[friendly] = DecimalInput(required=False, label=label, min_value=Decimal(0), max_digits=24, decimal_places=6,
                error_messages={"invalid": "Introduce un número.", "min_value": "Debe ser mayor que cero.",
                                "max_digits": "Valor fuera del intervalo admitido.", "max_whole_digits": "Valor fuera del intervalo admitido.",
                                "max_decimal_places": "Como máximo 6 decimales."})
            if shown is not None:
                self.initial[friendly] = shown
            self.converted_fields.add(exact)
        stored = getattr(self.instance, "elevation_gain_m", None)
        if "elevation_gain_m" in fields:
            if stored is None or stored == stored.to_integral_value():
                # Whole metres on the phone.
                fields["elevation_gain_m"] = elevation_field()
                if stored is not None and not self.is_bound:
                    self.initial["elevation_gain_m"] = int(stored)
            else:
                # A decimal value set in the admin keeps its exact field, read the Spanish way: «1.234,5» is 1234.5
                # and «2.000» is refused as ambiguous (a plain DecimalField would read it as 2 m).
                exact = fields["elevation_gain_m"]
                fields["elevation_gain_m"] = DecimalInput(required=False, label=exact.label, help_text=exact.help_text,
                    max_digits=exact.max_digits, decimal_places=exact.decimal_places,
                    validators=[v for v in exact.validators if not isinstance(v, DecimalValidator)],
                    error_messages={**FIELD_MESSAGES, "invalid": "Introduce un número.", "min_value": "Debe ser mayor que cero.",
                                    "max_digits": "Valor fuera del intervalo admitido.", "max_whole_digits": "Valor fuera del intervalo admitido.",
                                    "max_decimal_places": "Como máximo 3 decimales."})
                if not self.is_bound:
                    self.initial["elevation_gain_m"] = _plain(stored)
        self.fields = fields

    def add_error(self, field, error):
        """Errors the model reports on metres/seconds belong to the km/hours field shown."""
        names = {exact: friendly for exact, friendly, *_ in UNITS if exact in getattr(self, "converted_fields", ())}
        if names:
            if field is None and isinstance(error, ValidationError) and hasattr(error, "error_dict"):
                merged = {}
                for key, value in error.error_dict.items():
                    merged.setdefault(names.get(key, key), []).extend(value)
                error = ValidationError(merged)
            elif isinstance(error, dict):
                error = {names.get(key, key): value for key, value in error.items()}
            field = names.get(field, field)
        super().add_error(field, error)

    def clean_elevation_gain_m(self):
        value = self.cleaned_data.get("elevation_gain_m")
        return whole_metres(value) if isinstance(value, int) else value

    def clean(self):
        cleaned = super().clean()
        for exact, friendly, scale, _, precision in UNITS:
            if friendly not in self.fields or friendly in self.errors:
                continue
            value = cleaned.get(friendly)
            if value is None:
                cleaned[exact] = None
                continue
            try:
                with localcontext() as context:
                    context.prec = 60  # 24 digits × 4 digits: always exact
                    product = value * scale
                cleaned[exact] = exact_usage_value(product)
            except ValidationError as error:
                self.add_error(friendly, precision if error.code == "invalid_precision" else "Valor fuera del intervalo admitido.")
        return cleaned
