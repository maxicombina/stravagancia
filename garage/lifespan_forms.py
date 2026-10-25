"""Phone form for a component's useful life (garage-033). Exact values, local time."""
from decimal import Decimal, localcontext

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .forms import LocalDateTimeField
from .maintenance_forms import FIELD_MESSAGES, DecimalInput, WholeNumberInput, _shown, elevation_field, spanish_fields, whole_metres
from .validators import exact_usage_value
from .web_forms import clean_zone, convert_local_fields

UNITS = (("days", "días", 1), ("months", "meses", 30), ("years", "años", 365))
FACTORS = {key: factor for key, _, factor in UNITS}
# Orientative starting points by part, keyed like the item icons.
SUGGESTIONS = {
    "chain": ({"distance_km": "3000"}, "una cadena", "unos 3.000 km"),
    "cassette": ({"distance_km": "10000"}, "un casete", "unos 10.000 km"),
    "tire": ({"distance_km": "4000"}, "una cubierta", "unos 4.000 km"),
    "brake": ({"distance_km": "1500"}, "unas pastillas", "unos 1.500 km"),
    "wheel": ({"distance_km": "20000"}, "una rueda", "unos 20.000 km"),
    "shoe": ({"distance_km": "10000"}, "unas zapatillas", "unos 10.000 km"),
    "helmet": ({"time_value": "5", "time_unit": "years"}, "un casco", "5 años"),
}
# garage-041 review: before the icon list a rim was drawn as a wheel, and it keeps the wheel's figure
# (same text). Discs, chainrings, cleats and tubes used to borrow the figure of pads, a cassette, shoes
# or a tyre; that text named another part, so they get none until there is one of their own.
SUGGESTIONS["rim"] = SUGGESTIONS["wheel"]


def split_days(days):
    """365 -> (1, 'years'); 60 -> (2, 'months'); 45 -> (45, 'days')."""
    if days % 365 == 0:
        return days // 365, "years"
    if days % 30 == 0:
        return days // 30, "months"
    return days, "days"


class LifespanForm(forms.Form):
    distance_km = DecimalInput(required=False, label="Kilómetros", min_value=Decimal(0), max_digits=24, decimal_places=6,
                               error_messages={**FIELD_MESSAGES, "invalid": "Introduce un número.", "min_value": "Debe ser mayor que cero.",
                                               "max_decimal_places": "Como máximo 6 decimales.", "max_digits": "Valor fuera del intervalo admitido.",
                                               "max_whole_digits": "Valor fuera del intervalo admitido."})
    moving_time_h = DecimalInput(required=False, label="Horas en movimiento", min_value=Decimal(0), max_digits=24, decimal_places=6,
                                 error_messages={**FIELD_MESSAGES, "invalid": "Introduce un número.", "min_value": "Debe ser mayor que cero.",
                                                 "max_decimal_places": "Como máximo 6 decimales.", "max_digits": "Valor fuera del intervalo admitido.",
                                                 "max_whole_digits": "Valor fuera del intervalo admitido."})
    elevation_gain_m = elevation_field(help_text="Metros enteros de subida acumulada desde que cuenta.")
    time_value = WholeNumberInput(required=False, min_value=1, max_value=36500, label="Tiempo")
    time_unit = forms.ChoiceField(choices=[(key, label) for key, label, _ in UNITS], initial="years", label="Unidad")
    start = LocalDateTimeField(required=True, label="Cuenta desde",
                               help_text="Cuándo empezó a usarse. Si registras una sustitución, cuenta desde la última registrada.")
    time_zone = forms.CharField(initial="UTC", label="Zona horaria IANA", help_text="Por ejemplo Europe/Madrid.")

    def __init__(self, *args, rule=None, start=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.locked = {}
        if not self.is_bound:
            self.initial.setdefault("start", start)
            if rule is not None:
                self.initial["start"] = rule.anchor_at or start
                if rule.distance_m is not None:
                    self.initial["distance_km"] = _shown(rule.distance_m, Decimal(1000))
                if rule.moving_time_s is not None:
                    self.initial["moving_time_h"] = _shown(rule.moving_time_s, Decimal(3600))
                if rule.calendar_days is not None:
                    self.initial["time_value"], self.initial["time_unit"] = split_days(rule.calendar_days)
                if rule.elevation_gain_m is not None and rule.elevation_gain_m == rule.elevation_gain_m.to_integral_value():
                    self.initial["elevation_gain_m"] = int(rule.elevation_gain_m)
        if rule is not None and rule.moving_time_s is not None and _shown(rule.moving_time_s, Decimal(3600)) is None:
            # Not exact in hours: kept as it is and edited in seconds from the rules page.
            self.locked["moving_time_s"] = rule.moving_time_s
            self.fields.pop("moving_time_h")
        if rule is not None and rule.elevation_gain_m is not None and rule.elevation_gain_m != rule.elevation_gain_m.to_integral_value():
            # Not whole metres (set in the admin): kept as it is and edited from the rules page.
            self.locked["elevation_gain_m"] = rule.elevation_gain_m
            self.fields.pop("elevation_gain_m")
        # Unbound initial instants are aware: show them as UTC wall time, as the other forms do.
        if not self.is_bound and getattr(self.initial.get("start"), "tzinfo", None) is not None:
            from datetime import timezone as dt_timezone
            self.initial["start"] = self.initial["start"].astimezone(dt_timezone.utc).replace(tzinfo=None)
        spanish_fields(self)
        for name in ("distance_km", "moving_time_h"):
            if name in self.fields:
                self.fields[name].error_messages["min_value"] = "Debe ser mayor que cero."
        self.fields["time_value"].error_messages.update({"invalid": "Introduce un número entero.", "min_value": "Debe ser al menos 1.",
                                                         "max_value": "Como máximo 36.500 días (100 años)."})
        self.fields["time_value"].widget.attrs.update({"inputmode": "numeric"})

    def clean_time_zone(self):
        return clean_zone(self.cleaned_data["time_zone"])

    def clean(self):
        cleaned = convert_local_fields(self, super().clean(), ("start",))
        values = {}
        for friendly, exact, scale in (("distance_km", "distance_m", Decimal(1000)), ("moving_time_h", "moving_time_s", Decimal(3600))):
            if friendly not in self.fields:
                values[exact] = self.locked.get(exact)
                continue
            value = cleaned.get(friendly)
            if value is None:
                values[exact] = None
                continue
            with localcontext() as context:
                context.prec = 60
                product = value * scale
            try:
                values[exact] = exact_usage_value(product)
            except ValidationError as error:
                self.add_error(friendly, "Ese valor no se puede guardar exacto: usa menos decimales." if error.code == "invalid_precision"
                               else "Valor fuera del intervalo admitido.")
                continue
            if values[exact] == 0:
                self.add_error(friendly, "Debe ser mayor que cero; déjalo vacío si no se usa.")
        start = cleaned.get("start")
        # Only a start already converted with a valid zone can be compared (an invalid zone has its own error).
        if start is not None and timezone.is_aware(start) and start > timezone.now():
            self.add_error("start", "No puede ser una fecha futura: la vida útil empieza cuando la pieza se usa.")
        values["elevation_gain_m"] = whole_metres(cleaned.get("elevation_gain_m")) if "elevation_gain_m" in self.fields \
            else self.locked.get("elevation_gain_m")
        amount, unit = cleaned.get("time_value"), cleaned.get("time_unit") or "days"
        values["calendar_days"] = None if amount is None else amount * FACTORS[unit]
        if values["calendar_days"] is not None and values["calendar_days"] > 36500:
            self.add_error("time_value", "Como máximo 36.500 días (100 años).")
        self.lifespan = values
        return cleaned
