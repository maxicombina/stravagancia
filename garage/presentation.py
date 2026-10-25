"""Pure presentation helpers for the mobile screens. No queries, no writes.

The domain certifies "soon" or "current" only with complete coverage. Partial
observed usage is a lower bound (see services.maintenance_due), so these helpers
show it as "al menos" and never turn an uncertain value into "Al día".
"""
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from math import pi

STATES = {
    "due": ("Vencido", "octagon"),
    "review": ("Revisar", "alert"),
    "soon": ("Próximo", "alert"),
    "progress": ("En curso", "gauge"),
    "current": ("Al día", "check-circle"),
    "nodata": ("Sin datos", "help"),
    "snoozed": ("Pospuesto", "clock"),
}
SEVERITY = ("due", "review", "soon", "snoozed", "nodata", "progress", "current")
ATTENTION = frozenset({"due", "review", "soon"})
UNITS = {"distance_m": "km", "moving_time_s": "h", "ride_count": "salidas", "calendar_days": "días", "elevation_gain_m": "m"}
NAMES = {"distance_m": "Distancia", "moving_time_s": "Tiempo en movimiento", "ride_count": "Salidas",
         "calendar_days": "Calendario", "elevation_gain_m": "Desnivel"}
# Elevation metres are marked «↑» wherever a figure stands alone, so they never read as a distance.
MARKS = {"elevation_gain_m": "↑ "}
SMALL_RING, LARGE_RING = 22, 62


def number(value, *, decimals=0, rounding=ROUND_HALF_UP):
    """Spanish grouping: 2840 -> '2.840', 92.4 -> '92,4'. Trailing ',0' is dropped."""
    if value is None:
        return "—"
    quantum = Decimal(1).scaleb(-decimals)
    rounded = Decimal(value).quantize(quantum, rounding=rounding)
    sign = "-" if rounded < 0 else ""
    integer, _, fraction = f"{abs(rounded):f}".partition(".")
    groups = []
    while len(integer) > 3:
        groups.insert(0, integer[-3:])
        integer = integer[:-3]
    groups.insert(0, integer)
    text = ".".join(groups)
    if fraction and fraction.strip("0"):
        text += "," + fraction.rstrip("0")
    return sign + text


def quantity(name, value, *, up=False, down=False):
    """Display a metric value already converted to its unit (km, h, rides, days, metres).

    up=True rounds towards larger values, for upper bounds such as "como máx."."""
    if value is None:
        return "—"
    value = Decimal(value)
    if name in {"ride_count", "calendar_days"}:
        return number(value.to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR))
    rounding = ROUND_CEILING if up else ROUND_FLOOR if down else ROUND_HALF_UP
    if name == "elevation_gain_m":
        return number(value, rounding=rounding)  # whole metres, as the forms take them
    return number(value, decimals=0 if abs(value) >= 100 else 1, rounding=rounding)


def _floor_percent(ratio):
    return int((ratio * 100).to_integral_value(rounding=ROUND_FLOOR))


def ring(ratio, radius):
    """SVG stroke-dasharray for a progress ring; never draws past a full turn."""
    circumference = Decimal(str(2 * pi * radius))
    filled = circumference * min(max(ratio or Decimal(0), Decimal(0)), Decimal(1))
    return f"{filled:.2f} {circumference:.2f}"


@dataclass(frozen=True)
class WearMetric:
    metric: object
    state: str
    ratio: Decimal | None

    @classmethod
    def build(cls, metric):
        ratio = None if metric.value is None or metric.threshold <= 0 else metric.value / metric.threshold
        if metric.status in {"due", "soon", "current"}:
            state = metric.status
        elif metric.value is None:
            state = "nodata"
        else:
            state = "review" if metric.value * 10 >= metric.threshold * 9 else "progress"
        return cls(metric, state, ratio)

    @property
    def name(self):
        return self.metric.name

    @property
    def title(self):
        return NAMES[self.name]

    @property
    def unit(self):
        return UNITS[self.name]

    @property
    def unit_text(self):
        """'km', or '↑ m' for elevation."""
        return MARKS.get(self.name, "") + self.unit

    @property
    def lower_bound(self):
        """Observed value that may still miss real rides. An estimated reading is
        not a guaranteed minimum, so it is never shown as one."""
        return self.metric.value is not None and self.metric.coverage != "complete" and not self.metric.is_estimated

    @property
    def estimated(self):
        return self.metric.is_estimated

    @property
    def missing_text(self):
        """'3 sin desnivel': elevation observed as a minimum because some rides lack it (garage-030 phase 3 review)."""
        if self.name != "elevation_gain_m" or self.metric.value is None or not self.metric.missing_values:
            return ""
        return f"{number(self.metric.missing_values)} sin desnivel"

    @property
    def unrecorded(self):
        """No ride since the reference records elevation: unknown («sin datos»), not 0."""
        return bool(getattr(self.metric, "unrecorded", False))

    @property
    def percent(self):
        return None if self.ratio is None else _floor_percent(self.ratio)

    @property
    def percent_text(self):
        if self.percent is None:
            return "?"
        if self.estimated:
            return f"≈ {self.percent} %"
        return f"{'≥ ' if self.lower_bound else ''}{self.percent} %"

    @property
    def bar(self):
        """Width for a CSS meter, capped at 100 %."""
        return "0%" if self.ratio is None else f"{min(self.ratio, Decimal(1)) * 100:.1f}%"

    @property
    def bar_width(self):
        """0-100 for an SVG meter (no inline styles)."""
        return "0" if self.ratio is None else f"{min(self.ratio, Decimal(1)) * 100:.1f}"

    @property
    def value_text(self):
        return quantity(self.name, self.metric.display_value)

    @property
    def threshold_text(self):
        return quantity(self.name, self.metric.display_threshold)

    @property
    def threshold_label(self):
        """'4.000 km', or '↑ 6.000 m' for elevation: the threshold with its unit."""
        return f"{MARKS.get(self.name, '')}{self.threshold_text} {self.unit}"

    @property
    def remaining_text(self):
        # With a lower-bound value the remaining figure is an upper bound: never understate it.
        return quantity(self.name, self.metric.display_remaining, up=self.lower_bound)

    @property
    def overrun_text(self):
        if self.metric.value is None or self.metric.value < self.metric.threshold:
            return None
        # A lower-bound overrun is a minimum: never overstate it.
        return quantity(self.name, self.metric._display(self.metric.value - self.metric.threshold), down=self.lower_bound)

    @property
    def big(self):
        """Headline figure: overrun when due, remaining otherwise."""
        if self.state == "nodata":
            return "—"
        if self.state == "due":
            return "+" + self.overrun_text
        return self.remaining_text

    @property
    def big_caption(self):
        if self.state == "nodata":
            return "sin datos"
        if self.state == "due":
            return f"{self.unit_text} de más" + (" (estimado)" if self.estimated else " como mín." if self.lower_bound else "")
        if self.estimated:
            return f"{self.unit_text} estimados"
        return f"{self.unit_text} como máx." if self.lower_bound else f"{self.unit_text} quedan"

    @property
    def word(self):
        return STATES[self.state][0]

    @property
    def icon(self):
        return STATES[self.state][1]

    @property
    def small_ring(self):
        return ring(self.ratio, SMALL_RING)

    @property
    def large_ring(self):
        return ring(self.ratio, LARGE_RING)


SINGULAR = {"salidas": "salida", "días": "día"}


@dataclass(frozen=True)
class Wear:
    due: object
    metrics: tuple[WearMetric, ...]
    headline: WearMetric | None
    snooze_metrics: tuple[WearMetric, ...] = ()

    @property
    def real_state(self):
        return self.headline.state if self.headline else "nodata"

    @property
    def snooze(self):
        return getattr(self.due, "snooze", None)

    @property
    def snoozed(self):
        """Postponed (garage-034): only an alert that needs attention, while the snooze is active."""
        return self.real_state in ATTENTION and self.snooze is not None and self.snooze.active

    @property
    def state(self):
        return "snoozed" if self.snoozed else self.real_state

    @property
    def real_word(self):
        return STATES[self.real_state][0]

    @property
    def real_icon(self):
        return STATES[self.real_state][1]

    @property
    def snooze_left(self):
        """'como máx. 150 km o 5 días': what is left of the snooze; the first to run out ends it.

        Observed km, hours and rides are a minimum, so what is left of them is at most that."""
        parts = []
        for metric in self.snooze_metrics:
            # Days are rounded up: half a day left is still «1 día», never «0 días» while it is postponed.
            text = quantity(metric.name, metric.metric.display_remaining, up=True) if metric.name == "calendar_days" else metric.remaining_text
            unit = SINGULAR.get(metric.unit, metric.unit) if text == "1" else metric.unit
            parts.append(f"{'como máx. ' if metric.lower_bound else ''}{MARKS.get(metric.name, '')}{text} {unit}")
        return " o ".join(parts)

    @property
    def snooze_verb(self):
        """«queda 1 día», «quedan 5 días o 0,5 km»."""
        return "queda" if self.snooze_left and " o " not in self.snooze_left and self.snooze_left.split(" ")[-2] == "1" else "quedan"

    @property
    def snooze_reached(self):
        """'2 días': only the amounts that ran out, exact as they were postponed."""
        from types import SimpleNamespace
        names = ("distance_m", "moving_time_s", "ride_count", "calendar_days", "elevation_gain_m")
        reached = {metric.name: metric.metric.threshold for metric in self.snooze_metrics
                   if metric.metric.value is not None and metric.metric.value >= metric.metric.threshold}
        return thresholds(SimpleNamespace(**{name: reached.get(name) for name in names}), separator=" y ")

    @property
    def word(self):
        return STATES[self.state][0]

    @property
    def icon(self):
        return STATES[self.state][1]

    @property
    def rule(self):
        return self.due.rule

    @property
    def target(self):
        return self.due.rule.item or self.due.rule.bike

    @property
    def needs_attention(self):
        return self.state in ATTENTION

    @property
    def estimated(self):
        return any(metric.estimated for metric in self.metrics)

    @property
    def elevation(self):
        """The rule's elevation metric, or None without an elevation threshold."""
        return next((metric for metric in self.metrics if metric.name == "elevation_gain_m"), None)


def _rank(metric):
    ratio = metric.ratio if metric.ratio is not None else Decimal(-1)
    return SEVERITY.index(metric.state), -ratio


def wear(due):
    metrics = tuple(WearMetric.build(metric) for metric in due.metrics)
    snooze = getattr(due, "snooze", None)
    return Wear(due, metrics, min(metrics, key=_rank, default=None),
                tuple(WearMetric.build(metric) for metric in snooze.metrics) if snooze is not None else ())


def by_severity(wears):
    def key(item):
        ratio = item.headline.ratio if item.headline and item.headline.ratio is not None else Decimal(-1)
        return SEVERITY.index(item.state), -ratio, str(item.target), str(item.rule.pk)
    return sorted(wears, key=key)


def thresholds(rule, separator=" · "):
    """'3.000 km · 100 h · 30 salidas · 365 días · 20.000 m', exact: never rounded.

    Distance is always exact in km (metres have 3 decimals). A time that has no
    exact value in hours with 6 decimals is shown in seconds. Elevation is in
    metres (the forms take whole metres; a decimal one stays exact).
    """
    parts = []
    distance, moving = rule.distance_m, rule.moving_time_s
    if distance is not None:
        parts.append(f"{number(Decimal(distance) / 1000, decimals=6)} km")
    if moving is not None:
        hours = Decimal(moving) / 3600
        exact = hours == hours.quantize(Decimal("0.000001")) and hours * 3600 == Decimal(moving)
        parts.append(f"{number(hours, decimals=6)} h" if exact else f"{number(moving, decimals=3)} s")
    for name, singular, plural in (("ride_count", "salida", "salidas"), ("calendar_days", "día", "días")):
        value = getattr(rule, name)
        if value is not None:
            parts.append(f"{number(value)} {singular if value == 1 else plural}")
    elevation = getattr(rule, "elevation_gain_m", None)
    if elevation is not None:
        parts.append(f"{number(elevation, decimals=3)} m de desnivel")
    return separator.join(parts)


def ride_speed(ride):
    """Average km/h over the moving time, or None without both figures."""
    if not ride.distance_m or not ride.moving_time_s:
        return None
    return Decimal(ride.distance_m) / Decimal(ride.moving_time_s) * 3600 / 1000


def power_figures(ride):
    """((figure, caption), …) of the ride's known power and energy (garage-030 phase 3), for its own screens only.

    «Ø» average, «máx» maximum, «NP» normalized (weighted) power, whole W and kJ.
    """
    figures = []
    for field, mark, caption in (("average_power_w", "Ø ", "W media"), ("max_power_w", "máx ", "W máxima"),
                                 ("weighted_power_w", "NP ", "W normalizada")):
        value = getattr(ride, field, None)
        if value is not None:
            figures.append((mark + number(value), caption))
    if getattr(ride, "energy_kj", None) is not None:
        figures.append((number(ride.energy_kj), "kJ"))
    return tuple(figures)
