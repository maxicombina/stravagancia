"""Phone-friendly local time for the existing forms (garage-032).

The forms keep their explicit `time_zone` field and exact parsing. This module
only preselects the viewer's zone, shows initial instants in that zone and
offers the native date-time picker whenever the value fits it.
"""
import re
from datetime import datetime, timezone as datetime_timezone

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .forms import LocalDateTimeField, local_time_to_utc

PICKER = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?")


class LocalDateTimeInput(forms.DateTimeInput):
    """`datetime-local` when the value has no fraction of a second; exact text otherwise.

    The native picker cannot hold microseconds, so such values keep a text input
    with the full format instead of being truncated on the next save.
    """
    supports_microseconds = True

    def __init__(self, attrs=None):
        super().__init__({"placeholder": "2026-01-01T10:30", **(attrs or {})}, format="%Y-%m-%dT%H:%M:%S.%f")

    def format_value(self, value):
        if isinstance(value, datetime):
            if value.microsecond:
                return value.strftime("%Y-%m-%dT%H:%M:%S.%f")
            return value.strftime("%Y-%m-%dT%H:%M:%S" if value.second else "%Y-%m-%dT%H:%M")
        return super().format_value(value)

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        widget = context["widget"]
        text = widget["value"] or ""
        match = PICKER.fullmatch(text)
        if not text or match:
            widget["type"] = "datetime-local"
            widget["attrs"].pop("placeholder", None)
            if match and match.group(1):
                widget["attrs"]["step"] = "1"
        return context


def _shown_in_utc(form, name):
    value = form.initial.get(name, form.fields[name].initial)
    return None if value in (None, "") else value


def localize(form, zone):
    """Preselect `zone` and show initial local times in it; bound forms are untouched.

    Forms render unbound instants as naive UTC wall time with zone "UTC". Only
    then are they converted, so an explicit non-UTC initial zone keeps its values.
    """
    if form is None or "time_zone" not in form.fields:
        return form
    names = [name for name, field in form.fields.items() if isinstance(field, LocalDateTimeField)]
    for name in names:
        widget = LocalDateTimeInput()
        widget.is_required = form.fields[name].required
        form.fields[name].widget = widget
    if form.is_bound or (_shown_in_utc(form, "time_zone") or "UTC") != "UTC":
        return form
    converted = {}
    for name in names:
        value = _shown_in_utc(form, name)
        if value is None:
            continue
        if not isinstance(value, datetime):
            return form  # text or callable initial: its zone is unknown, keep UTC
        aware = value if timezone.is_aware(value) else value.replace(tzinfo=datetime_timezone.utc)
        try:
            wall = aware.astimezone(zone).replace(tzinfo=None)
            if local_time_to_utc(wall, zone.key) != aware:
                return form
        except (ValidationError, OverflowError, ValueError):
            # A repeated hour (end of summer time) or an extreme year cannot round-trip: keep UTC.
            return form
        converted[name] = wall
    form.initial.update(converted)
    form.initial["time_zone"] = zone.key
    return form
