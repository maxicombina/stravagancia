"""Template helpers for the mobile shell: platform, active tab, icons, Spanish numbers and dates."""
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal

from django import template
from django.utils.html import format_html

from garage.assets import asset_url
from garage.icons import ICON_LABELS, category_icon_key, item_icon_key
from garage.presentation import number, power_figures as ride_power_figures, quantity, thresholds as rule_thresholds
from garage.services.lifecycle import RETIRES_TEXT
from garage.sports import sport_label as modality_label
from garage.timezones import DEFAULT_ZONE, user_time_zone

register = template.Library()

TABS = (
    ("rides", ("usage-ride", "ride-review", "history")),
    ("workshop", ("maintenance", "service-")),
    ("stats", ("statistics",)),
    ("more", ("more", "category-", "usage-profile", "export")),
)
WEEKDAYS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")
MONTHS = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")


def tab_for(url_name):
    for tab, prefixes in TABS:
        if any((url_name or "").startswith(prefix) for prefix in prefixes):
            return tab
    return "garage"


@register.simple_tag
def asset(path):
    return asset_url(path)


@register.simple_tag(takes_context=True)
def current_tab(context):
    if context.get("tab"):
        return context["tab"]
    match = getattr(context.get("request"), "resolver_match", None)
    return tab_for(match.url_name if match else "")


@register.simple_tag(takes_context=True)
def client_os(context):
    request = context.get("request")
    agent = request.META.get("HTTP_USER_AGENT", "") if request is not None else ""
    return "android" if "Android" in agent else "ios"


# ImportRun.State keeps its English choice labels (changing them would need a migration).
RUN_STATES = {"pending": "Pendiente", "running": "En curso", "paused": "En pausa", "completed": "Completado",
              "failed": "Con error", "cancelled": "Cancelado"}


@register.filter
def run_state(run):
    """Spanish label of an import job state."""
    return RUN_STATES.get(getattr(run, "state", run), "Desconocido")


@register.filter
def sport_label(key):
    """Spanish label of a cycling modality key (garage/sports.py); other keys as stored."""
    return modality_label(key)


@register.filter
def item_icon(item):
    """Sprite key of an item: its category's icon, else deduced from the names (garage/icons.py)."""
    return item_icon_key(item)


@register.filter
def category_icon(category):
    """Sprite key of a category: its own icon, else what its name suggests, else a tag (garage-041)."""
    return category_icon_key(category)


@register.filter
def icon_label(key):
    """Spanish name of an icon key; empty for unknown keys."""
    return ICON_LABELS.get(key, "")


@register.filter
def thresholds(rule):
    return rule_thresholds(rule)


@register.filter
def thresholds_or(rule):
    """'3.000 km o 365 días': whichever comes first."""
    return rule_thresholds(rule, separator=" o ")


@register.filter
def rule_name(rule):
    """«Vida útil» for a component's useful-life rule (garage-033), else its intervention type."""
    from garage.services.lifespan import is_life
    return "Vida útil" if is_life(rule) else rule.service_type.name


@register.filter
def is_life(rule):
    from garage.services.lifespan import is_life as life
    return life(rule)


@register.filter
def nodata_reason(due):
    from garage.services.workshop import nodata_reason as reason
    return reason(due)


@register.filter
def num(value, decimals=0):
    return number(value, decimals=int(decimals))


@register.filter
def money(value):
    """Two fixed decimals: 32.9 -> '32,90'."""
    if value is None:
        return "—"
    text = number(value, decimals=2)
    whole, _, cents = text.partition(",")
    return f"{whole},{(cents + '00')[:2]}"


@register.filter
def km(meters):
    """Meters to a km figure: 92400 -> '92,4', 2840000 -> '2.840'."""
    return "—" if meters is None else quantity("distance_m", Decimal(meters) / Decimal(1000))


@register.filter
def duration(seconds):
    """Seconds to '3 h 41' (or '41 min' under an hour)."""
    if seconds is None:
        return "—"
    minutes = int(seconds) // 60
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02d}" if hours else f"{minutes} min"


@register.filter
def hours(seconds):
    return "—" if seconds is None else quantity("moving_time_s", Decimal(seconds) / Decimal(3600))


@register.filter
def metric_m(metres):
    """Whole metres with Spanish grouping (garage-030 phase 3): 1234.4 -> '1.234 m'. Templates write the «↑»."""
    return "—" if metres is None else f"{quantity('elevation_gain_m', Decimal(metres))} m"


@register.filter
def power_figures(ride):
    """Known power and energy of one ride as (figure, caption) pairs: only for its own screens."""
    return ride_power_figures(ride)


def _local(context, value):
    zone = context.get("user_tz")
    if zone is None:
        request = context.get("request")
        zone = user_time_zone(request) if request is not None else DEFAULT_ZONE
    try:
        return value.astimezone(zone)
    except OverflowError:
        # Year 9999 seen from a zone ahead of UTC would leave the calendar: show it in UTC.
        return value.astimezone(dt_timezone.utc)


@register.simple_tag(takes_context=True)
def local_date(context, value, style="short"):
    """'11 oct 2026'; style 'weekday' adds 'sáb'. Empty for unknown instants. Plain dates stay as they are."""
    if value is None or value == "":
        return ""
    local = _local(context, value) if isinstance(value, datetime) else value
    text = f"{local.day} {MONTHS[local.month - 1]} {local.year}"
    if isinstance(local, datetime) and local.tzinfo is dt_timezone.utc:
        text += " (UTC)"  # overflow fallback
    return f"{WEEKDAYS[local.weekday()]} {text}" if style == "weekday" else text


@register.simple_tag(takes_context=True)
def life_text(context, lifecycle):
    """An item's state line (garage-042): «Disponible», «En Gravel desde el 3 mar 2026»… Dates in the viewer's zone.

    A retirement still to come is added at the end: «Disponible · se retira el 21 oct 2026».
    """
    if lifecycle is None:
        return ""
    text = lifecycle.text if lifecycle.since is None else f"{lifecycle.text} {local_date(context, lifecycle.since)}"
    if lifecycle.retires is not None:
        text += f" · {RETIRES_TEXT} {local_date(context, lifecycle.retires)}"
    return text


@register.simple_tag(takes_context=True)
def local_time(context, value):
    if value is None:
        return ""
    local = _local(context, value)
    return f"{local.hour}:{local.minute:02d}"


def _datetime_text(local):
    text = f"{local.day} {MONTHS[local.month - 1]} {local.year}, {local.hour}:{local.minute:02d}"
    if local.second or local.microsecond:
        text += f":{local.second:02d}" + (f",{local.microsecond:06d}" if local.microsecond else "")
    if local.tzinfo is dt_timezone.utc:  # only the overflow fallback: viewer zones are ZoneInfo
        text += " (UTC)"
    other = local.replace(fold=1 - local.fold)
    if other.utcoffset() != local.utcoffset():
        offset = local.strftime("%z")
        text += f" (UTC{offset[:3]}:{offset[3:]})"
    return text


def datetime_text(value, zone):
    """Plain '17 oct 2026, 10:30' in `zone`, for option labels built outside templates."""
    return "" if value is None else _datetime_text(_local({"user_tz": zone}, value))


@register.simple_tag(takes_context=True)
def local_datetime(context, value):
    """'17 oct 2026, 10:30' in the viewer's zone inside <time datetime="…Z"> with the exact instant.

    Seconds (and microseconds) appear only when present; in the repeated hour at
    the end of summer time the offset is named so the text stays unambiguous.
    """
    if value is None or value == "":
        return ""
    exact = value.astimezone(dt_timezone.utc).isoformat().replace("+00:00", "Z")
    return format_html('<time datetime="{}">{}</time>', exact, _datetime_text(_local(context, value)))


@register.simple_tag(takes_context=True)
def local_bound(context, value):
    """A period bound: the date when it is a local midnight, else the exact local date and time."""
    if value is None:
        return ""
    if not isinstance(value, datetime):
        return local_date(context, value)
    local = _local(context, value)
    if (local.hour, local.minute, local.second, local.microsecond) == (0, 0, 0, 0):
        return local_date(context, value)
    return local_datetime(context, value)


def _span_parts(span):
    parts = []
    for metric in span.metrics:
        if metric.value is None:
            continue
        mark = "≈ " if metric.estimated else "" if metric.complete else "≥ "
        value = metric.display_value
        if metric.name == "distance_m":
            parts.append(f"{mark}{quantity('distance_m', value, down=not metric.complete)} km")
        elif metric.name == "moving_time_s":
            parts.append(f"{mark}{quantity('moving_time_s', value, down=not metric.complete)} h")
        elif metric.name == "elevation_gain_m":
            parts.append(f"↑ {mark}{quantity('elevation_gain_m', value, down=not metric.complete)} m")
        else:
            count = int(value)
            parts.append(f"{mark}{number(count)} {'salida' if count == 1 else 'salidas'}")
    days = int(span.days)
    return parts, f"{number(days)} {'día' if days == 1 else 'días'}"


@register.filter
def span_text(span):
    """'≥ 3.240 km · ≥ 120 h · ≥ 45 salidas · ↑ ≥ 21.000 m · 210 días' (garage-036, garage-030 phase 3).

    Observed km, hours, rides and elevation are a minimum (≥) unless a reading fixes them;
    an estimated reading is «≈»; unknown figures are left out; days are exact.
    """
    if span is None:
        return ""
    parts, days = _span_parts(span)
    return " · ".join([*parts, days]) if parts else f"{days} · uso desconocido"


@register.filter
def span_short(span):
    """'≥ 3.240 km' or, without known km, '210 días': for one-line lists."""
    if span is None:
        return ""
    parts, days = _span_parts(span)
    return next((part for part in parts if part.endswith(" km")), days)


@register.filter
def whole_days(days):
    """Whole days elapsed, never rounded up: '1 día', '210 días'."""
    count = int(days)
    return f"{number(count)} {'día' if count == 1 else 'días'}"


@register.filter
def metric_km(metric):
    """'≥ 99,9', '≈ 1.000' or '1.000' km of a statistics metric; a minimum is rounded down."""
    if metric is None or metric.value is None:
        return "—"
    mark = "≈ " if metric.estimated else "" if metric.complete else "≥ "
    return mark + quantity("distance_m", metric.display_value, down=not metric.complete)
