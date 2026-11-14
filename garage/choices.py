"""Object and bike selectors that tell equal names apart (garage-047 F02, D10).

An item option reads «{name} · {category} · {where it is now}»: «en {bike}», «sobre {item}», «en uso»,
«disponible», «sin estrenar» or «retirado», from `lifecycle.item_lifecycles` (the whole list at once, in a fixed
number of reads). A bike option reads «{name}», or «{name} · retirada». The list keeps the order of its queryset (the
database's Spanish order, `ordering.by_name`) and a stable sort only moves the retired ones to the end.

Options that would read the same on screen get a date (`_as_seen`: also names that differ only in spaces, Unicode
form or invisible characters), in the viewer's zone (set by `local_forms.localize`): «desde el …» when mounted,
«retirado el …» when retired, else «comprado el …» or, with no purchase date, «alta del …». If they still read the
same, the later ones get «(2)», «(3)»… in the order of the list. Only the text changes: the value sent is the same.
"""
import unicodedata
from collections import Counter

from django import forms
from django.forms.models import ModelChoiceIterator, ModelChoiceIteratorValue
from django.utils import timezone

from .services.lifecycle import MOUNTED, RETIRED, item_lifecycles
from .templatetags.garage_ui import local_date
from .timezones import DEFAULT_ZONE


def _as_seen(text):
    """`text` as the eye tells it from another: the browser shows a run of spaces as one, a letter written whole (NFC)
    like the same letter plus its accent (NFD), and a zero-width or other format character as nothing."""
    visible = "".join(char for char in text if unicodedata.category(char) != "Cf")
    return " ".join(unicodedata.normalize("NFC", visible).split())


class _AllAtOnce(ModelChoiceIterator):
    """Labels for the whole list together: whether an option needs a date depends on the others."""

    def __iter__(self):
        if self.field.empty_label is not None:
            yield ("", self.field.empty_label)  # before any read, as Django does: a peek at the first option costs none
        for obj, label in self.field.labelled(self.queryset, at=timezone.now()):
            yield ModelChoiceIteratorValue(self.field.prepare_value(obj), obj), label


class DistinctChoiceField(forms.ModelChoiceField):
    iterator = _AllAtOnce
    zone = None  # the viewer's zone, from localize(); else the default one

    def date(self, value):
        return local_date({"user_tz": self.zone or DEFAULT_ZONE}, value)

    def rows(self, objects, at):
        """[(obj, retired, label, dated label)] in the queryset's order."""
        raise NotImplementedError

    def labelled(self, queryset, *, at):
        rows = sorted(self.rows(list(queryset), at), key=lambda row: row[1])  # stable: retired last, the rest kept
        repeated = {seen for seen, count in Counter(_as_seen(label) for _, _, label, _ in rows).items() if count > 1}
        taken = set()
        for obj, _, label, dated in rows:
            text = dated if _as_seen(label) in repeated else label
            shown, number = text, 1
            while _as_seen(shown) in taken:
                number += 1
                shown = f"{text} ({number})"
            taken.add(_as_seen(shown))
            yield obj, shown


class ItemChoiceField(DistinctChoiceField):
    """«Cadena 11v · Cadenas · en Carretera»."""

    def labelled(self, queryset, *, at):
        return super().labelled(queryset.select_related("category"), at=at)

    def rows(self, items, at):
        # One owner per list: the queryset is already scoped to it (scoped_inventory).
        lives = item_lifecycles(items[0].owner_id, items, at=at) if items else {}
        rows = []
        for item in items:
            life = lives[item.pk]
            if life.state == MOUNTED:
                place = f"sobre {life.parent}" if life.parent else f"en {life.bike}"
            else:
                place = life.word.lower()  # «retirado», «en uso», «disponible», «sin estrenar»: the lifecycle's words
            label = f"{item.name} · {item.category.name} · {place}"
            if life.state == RETIRED:
                dated = f"{label} el {self.date(life.since)}"
            elif life.state == MOUNTED:
                dated = f"{label} desde el {self.date(life.since)}"
            elif item.acquired_on is not None:
                dated = f"{label} · comprado el {self.date(item.acquired_on)}"
            else:
                dated = f"{label} · alta del {self.date(item.created_at)}"
            rows.append((item, life.state == RETIRED, label, dated))
        return rows


class BikeChoiceField(DistinctChoiceField):
    """«Gravel», or «Gravel · retirada»."""

    def rows(self, bikes, at):
        rows = []
        for bike in bikes:
            retired = bike.retired_at is not None and bike.retired_at <= at
            if retired:
                label, dated = f"{bike.name} · retirada", f"{bike.name} · retirada el {self.date(bike.retired_at)}"
            elif bike.acquired_on is not None:
                label, dated = bike.name, f"{bike.name} · comprada el {self.date(bike.acquired_on)}"
            else:
                label, dated = bike.name, f"{bike.name} · alta del {self.date(bike.created_at)}"
            rows.append((bike, retired, label, dated))
        return rows


# For the ModelForms whose `item` and `bike` come from the model (Meta.field_classes).
TARGET_FIELDS = {"item": ItemChoiceField, "bike": BikeChoiceField}
