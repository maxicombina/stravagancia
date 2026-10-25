"""Phone form to postpone a rule's alert (garage-034). Exact values, decimal comma.

Every snooze has a maximum in days: observed km, hours and rides are only a
minimum, so without it an alert could stay hidden for good if rides stop being
recorded.
"""
from decimal import ROUND_CEILING, Decimal, localcontext

from django import forms
from django.core.exceptions import ValidationError

from .maintenance_forms import FIELD_MESSAGES, DecimalInput, WholeNumberInput, elevation_field, spanish_fields, whole_metres
from .validators import exact_usage_value

DECIMAL_MESSAGES = {**FIELD_MESSAGES, "invalid": "Introduce un número.", "min_value": "Debe ser mayor que cero.",
                    "max_decimal_places": "Como máximo 6 decimales.", "max_digits": "Valor fuera del intervalo admitido.",
                    "max_whole_digits": "Valor fuera del intervalo admitido."}
WHOLE_MESSAGES = {"invalid": "Introduce un número entero.", "min_value": "Debe ser al menos 1.",
                  "max_value": "Valor fuera del intervalo admitido."}
DEFAULT_DAYS = 30
MAX_DAYS = 36500


def _ceil(value, quantum):
    with localcontext() as context:
        context.prec = 60
        return Decimal(value).quantize(quantum, rounding=ROUND_CEILING)


def presets(rule):
    """{key: (label, amounts)}: one-tap snoozes. 1 mes = 30 días, as in the useful life.

    «10 % de la regla» takes a tenth of each threshold, rounded up (whole rides,
    days and metres of elevation, at least 1); without a days threshold it keeps
    the 30-day maximum.
    """
    options = {"week": ("1 semana", {"calendar_days": 7}), "fortnight": ("2 semanas", {"calendar_days": 14}),
               "month": ("1 mes", {"calendar_days": 30})}
    tenth = {}
    if rule.distance_m is not None:
        tenth["distance_m"] = _ceil(Decimal(rule.distance_m) / 10, Decimal("0.001"))
    if rule.moving_time_s is not None:
        tenth["moving_time_s"] = _ceil(Decimal(rule.moving_time_s) / 10, Decimal("0.001"))
    if rule.ride_count is not None:
        tenth["ride_count"] = max(1, int(_ceil(Decimal(rule.ride_count) / 10, Decimal(1))))  # whole rides, at least one
    tenth["calendar_days"] = min(MAX_DAYS, max(1, int(_ceil(Decimal(rule.calendar_days) / 10, Decimal(1))))) if rule.calendar_days is not None else DEFAULT_DAYS
    if getattr(rule, "elevation_gain_m", None) is not None:
        tenth["elevation_gain_m"] = max(Decimal(1), _ceil(Decimal(rule.elevation_gain_m) / 10, Decimal(1)))  # whole metres, as the form
    options["tenth"] = ("10 % de la regla", tenth)
    return options


class SnoozeForm(forms.Form):
    distance_km = DecimalInput(required=False, label="Kilómetros", min_value=Decimal(0), max_digits=24, decimal_places=6,
                               error_messages=DECIMAL_MESSAGES)
    moving_time_h = DecimalInput(required=False, label="Horas en movimiento", min_value=Decimal(0), max_digits=24, decimal_places=6,
                                 error_messages=DECIMAL_MESSAGES)
    ride_count = WholeNumberInput(required=False, min_value=1, max_value=2147483647, label="Salidas")
    calendar_days = WholeNumberInput(min_value=1, max_value=MAX_DAYS, initial=DEFAULT_DAYS, label="Días, como máximo")
    elevation_gain_m = elevation_field(help_text="Metros enteros de subida. Una salida sin desnivel registrado deja el aviso visible.")
    notes = forms.CharField(required=False, max_length=200, label="Nota (opcional)", help_text="Por ejemplo: después del viaje.")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        spanish_fields(self)
        for name in ("distance_km", "moving_time_h"):
            self.fields[name].error_messages["min_value"] = "Debe ser mayor que cero."
        for name in ("ride_count", "calendar_days"):
            self.fields[name].error_messages.update(WHOLE_MESSAGES)
            self.fields[name].widget.attrs.update({"inputmode": "numeric"})
        self.fields["calendar_days"].error_messages.update({"max_value": "Como máximo 36.500 días (100 años).",
                                                            "required": "Indica también un máximo de días."})

    def clean(self):
        cleaned = super().clean()
        amounts = {}
        for friendly, exact, scale in (("distance_km", "distance_m", Decimal(1000)), ("moving_time_h", "moving_time_s", Decimal(3600))):
            value = cleaned.get(friendly)
            if value is None:
                amounts[exact] = None
                continue
            with localcontext() as context:
                context.prec = 60
                product = value * scale
            try:
                amounts[exact] = exact_usage_value(product)
            except ValidationError as error:
                self.add_error(friendly, "Ese valor no se puede guardar exacto: usa menos decimales." if error.code == "invalid_precision"
                               else "Valor fuera del intervalo admitido.")
                continue
            if amounts[exact] == 0:
                self.add_error(friendly, "Debe ser mayor que cero; déjalo vacío si no se usa.")
        amounts["ride_count"] = cleaned.get("ride_count")
        amounts["calendar_days"] = cleaned.get("calendar_days")
        amounts["elevation_gain_m"] = whole_metres(cleaned.get("elevation_gain_m"))
        self.amounts = amounts
        return cleaned
