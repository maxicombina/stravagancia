"""Más → Strava forms (garage-030, token mode). Spanish messages, owner-scoped choices."""
from datetime import datetime, time

from django import forms
from django.utils import timezone

from .maintenance_forms import SpanishWebMixin
from .models import Bike
from .services.ownership import scoped_inventory


class StravaImportForm(SpanishWebMixin, forms.Form):
    after = forms.DateField(label="Importar histórico desde", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
                            help_text="Fecha local. Se piden a Strava sus salidas en bici desde ese día, en páginas de 50.")

    def __init__(self, *args, zone, **kwargs):
        super().__init__(*args, **kwargs)
        self.zone = zone

    def clean_after(self):
        value = self.cleaned_data["after"]
        instant = datetime.combine(value, time.min, tzinfo=self.zone)
        if instant >= timezone.now():
            raise forms.ValidationError("Elige una fecha pasada.", code="invalid_period")
        return instant


def owner_bikes(user):
    """The owner's bikes, read once and shared by every GearLinkForm of a page (no query per form)."""
    return list(scoped_inventory(user, Bike).order_by("name", "pk"))


class GearLinkForm(SpanishWebMixin, forms.Form):
    bike = forms.ChoiceField(required=False, label="Bici de Garage")

    def __init__(self, *args, bikes, gear_name="", **kwargs):
        super().__init__(*args, **kwargs)
        self.bikes = {str(bike.pk): bike for bike in bikes}
        self.fields["bike"].choices = [("", "Sin vincular"), *((key, bike.name) for key, bike in self.bikes.items())]
        if gear_name:
            # Each select names its Strava bike: several forms share one page.
            self.fields["bike"].label = f"Bici de Garage para «{gear_name}»"

    def clean_bike(self):
        value = self.cleaned_data["bike"]
        return self.bikes.get(value) if value else None


class StravaRemoveForm(SpanishWebMixin, forms.Form):
    confirm = forms.BooleanField(label="Confirmo quitar todo lo que llegó desde Strava", required=True,
                                 error_messages={"required": "Marca la casilla para confirmar."})


class ConfirmForm(SpanishWebMixin, forms.Form):
    confirm = forms.BooleanField(label="Confirmo", required=True, error_messages={"required": "Marca la casilla para confirmar."})

    def __init__(self, *args, label=None, **kwargs):
        super().__init__(*args, **kwargs)
        if label:
            self.fields["confirm"].label = label


class MergeForm(SpanishWebMixin, forms.Form):
    ride = forms.ChoiceField(label="Unir con", widget=forms.RadioSelect)

    def __init__(self, *args, choices, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ride"].choices = choices
