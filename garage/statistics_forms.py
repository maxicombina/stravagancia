from django import forms

from .forms import LocalDateTimeField
from .models import Bike, Category, Item
from .services.ownership import get_inventory, require_actor, scoped_inventory
from .web_forms import LOCAL_WIDGET, ZONE_HELP, clean_zone, convert_local_fields


class StatisticsForm(forms.Form):
    bike = forms.ModelChoiceField(Bike.objects.none(), required=False, label="Bici (uso observado)")
    category = forms.ModelChoiceField(Category.objects.none(), required=False, label="Categoría")
    item = forms.ModelChoiceField(Item.objects.none(), required=False, label="Objeto")
    started_from = LocalDateTimeField(required=False, widget=LOCAL_WIDGET, label="Desde (incluido)")
    started_to = LocalDateTimeField(required=False, widget=LOCAL_WIDGET, label="Hasta (excluido; vacío: ahora)")
    time_zone = forms.CharField(initial="UTC", help_text=ZONE_HELP, label="Zona IANA")

    def __init__(self, *args, user, **kwargs):
        self.actor = require_actor(user)
        super().__init__(*args, **kwargs)
        for name, model in (("bike", Bike), ("category", Category), ("item", Item)):
            self.fields[name].queryset = scoped_inventory(self.actor, model)
            # Resolve submitted UUIDs first: unowned/malformed identifiers are 404.
            if self.is_bound and self.data.get(name):
                get_inventory(self.actor, model, self.data[name])

    def clean_time_zone(self):
        return clean_zone(self.cleaned_data["time_zone"])

    def clean(self):
        cleaned = convert_local_fields(self, super().clean(), ("started_from", "started_to"))
        start, end = cleaned.get("started_from"), cleaned.get("started_to")
        if start is not None and end is not None and start >= end:
            self.add_error("started_to", "El final debe seguir al inicio.")
        return cleaned
