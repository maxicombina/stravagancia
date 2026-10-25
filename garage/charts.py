"""Server-rendered SVG geometry for small charts. Pure functions, no queries."""
from dataclasses import dataclass
from decimal import Decimal
from math import ceil, floor, log10

from .presentation import number

LEFT, RIGHT, TOP, BASE = 34, 8, 20, 140


def _f(value):
    """Locale-independent SVG coordinate."""
    return f"{value:.2f}"


@dataclass(frozen=True)
class ChartPoint:
    index: int
    x: str
    y: str | None
    label: str
    tip: str
    partial: bool


@dataclass(frozen=True)
class LineChart:
    width: int
    height: int
    x_end: int
    month_y: int
    ticks: tuple
    points: tuple[ChartPoint, ...]
    solid: tuple[str, ...]
    areas: tuple[str, ...]
    dashed: tuple | None
    value_labels: tuple
    end_point: ChartPoint | None
    dots: tuple
    band: str
    summary: str
    empty: bool


def _nice_scale(maximum, max_intervals=4):
    """Smallest 1-2-2.5-5 step whose multiple covers maximum in at most max_intervals."""
    magnitude = 10 ** floor(log10(maximum / max_intervals))
    for step in (factor * magnitude for factor in (1, 2, 2.5, 5, 10, 20)):
        intervals = ceil(maximum / step)
        if intervals <= max_intervals:
            return step, max(intervals, 1)
    return 20 * magnitude, 1


def _fmt(value):
    return number(value, decimals=0 if abs(value) >= 100 else 1)


def line_chart(buckets, *, unit="km", divisor=Decimal(1000), width=320, height=170, title=None):
    """Monthly line chart: last bucket is the month in progress (dashed segment).

    Missing months break the line. Labels mark the maximum and the month in
    progress only; every value stays available in the tooltip and a table.
    `title` names the figure in the summary (default: the unit, «Km»).
    """
    values = [None if b.value is None else Decimal(b.value) / divisor for b in buckets]
    known = [v for v in values if v is not None]
    maximum = max(known, default=Decimal(0))
    band = (width - LEFT - RIGHT) / max(len(buckets), 1)
    empty = maximum <= 0
    step, intervals = _nice_scale(float(maximum)) if not empty else (1, 1)
    top = step * intervals
    plot = BASE - TOP

    def y(value):
        return BASE - float(value) / top * plot

    points = []
    for index, (bucket, value) in enumerate(zip(buckets, values)):
        x = LEFT + band * (index + 0.5)
        if value is None:
            tip = f"{bucket.name}: sin datos"
        else:
            tip = f"{bucket.name}{' (en curso)' if bucket.partial else ''}: {_fmt(value)} {unit}"
        points.append(ChartPoint(index, _f(x), None if value is None or empty else _f(y(value)), bucket.label, tip, bucket.partial))
    # (line y, label baseline y, text); the first tick is the baseline.
    ticks = () if empty else tuple((_f(y(step * k)), _f(y(step * k) + 3.7), number(Decimal(str(step * k)), decimals=2)) for k in range(intervals + 1))
    solid, areas, dots, run = [], [], [], []
    for point in points + [None]:
        closes_run = point is None or point.y is None or point.partial
        if point is not None and point.y is not None and not point.partial:
            run.append(point)
        if closes_run and run:
            if len(run) == 1 and not (point is not None and point.partial and point.y is not None):
                dots.append(run[0])  # an isolated month draws no line: mark it
            solid.append(" ".join(f"{p.x},{p.y}" for p in run))
            areas.append(f"M{run[0].x} {BASE}" + "".join(f"L{p.x} {p.y}" for p in run) + f"L{run[-1].x} {BASE}Z")
            run = []
    last = points[-1] if points else None
    dashed = None
    if last is not None and last.partial and last.y is not None and len(points) > 1 and points[-2].y is not None:
        dashed = (points[-2].x, points[-2].y, last.x, last.y)
    labels = []
    if not empty:
        peak = max((p for p in points if p.y is not None), key=lambda p: (values[p.index], -p.index))
        labels.append((peak.x, _f(float(peak.y) - 8), _fmt(values[peak.index])))
        if last is not None and last.y is not None and last.index != peak.index:
            labels.append((last.x, _f(float(last.y) - 8), _fmt(values[last.index])))
    end_point = last if last is not None and last.y is not None else None
    if empty:
        summary = "Aún no hay salidas en estos meses."
    else:
        summary = (f"{title or unit.capitalize()} por mes de {buckets[0].name} a {buckets[-1].name}. "
                   f"Máximo en {buckets[peak.index].name} con {_fmt(values[peak.index])} {unit}.")
    return LineChart(width, height, width - RIGHT, height - 13, ticks, tuple(points), tuple(solid), tuple(areas), dashed,
                     tuple(labels), end_point, tuple(dots), _f(band), summary, empty)
