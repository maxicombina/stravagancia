"""Mount a part inside a component from the component's screen (garage-035)."""
import re

from django import forms

from .models import Item
from .services.parts import part_candidates
from .web_forms import TemporalActionForm


class PartChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.name} · {obj.category.name}"


class PartWebForm(TemporalActionForm):
    item = PartChoice(queryset=Item.objects.none(), label="Pieza", empty_label="Elige una pieza",
                      error_messages={"required": "Elige una pieza.", "invalid_choice": "Elige una opción válida."},
                      help_text="Material propio sin montar ahora. Una pieza ya montada se mueve desde su ficha.")
    slot = forms.CharField(max_length=80, required=False, label="Posición exclusiva (opcional)",
                           help_text="Por ejemplo brake_disc: dos piezas no pueden ocupar a la vez la misma posición. Vacío: sin exclusividad.")
    notes = forms.CharField(required=False, max_length=500, label="Notas (opcional)")

    def __init__(self, *args, user, parent, **kwargs):
        super().__init__(*args, user=user, **kwargs)
        if not self.is_bound:  # to the minute, like the other phone forms
            self.initial["at"] = self.initial["at"].replace(second=0)
        self.fields["item"].queryset = part_candidates(self.actor, parent)
        # decorate() in the parent gives generic labels; these are the part's own.
        self.fields["at"].label = "Montada desde"
        self.fields["slot"].label = "Posición exclusiva (opcional)"
        self.fields["notes"].label = "Notas (opcional)"
        self.order_fields(("item", "at", "slot", "notes", "time_zone"))

    def clean_slot(self):
        slot = self.cleaned_data["slot"].strip().lower()
        if slot and not re.fullmatch(r"[a-z0-9_]+", slot):
            raise forms.ValidationError("Usa minúsculas, números y guion bajo, por ejemplo brake_disc.")
        return slot or None
