from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .charts import line_chart
from .local_forms import localize
from .models import ServiceEvent
from .services.monthly import monthly_usage
from .services.ownership import InventoryWriteError, scoped_inventory
from .services.statistics import statistics
from .statistics_forms import StatisticsForm
from .timezones import user_time_zone

PERIODS = (("12m", "12 meses"), ("year", "Este año"), ("last", "Año pasado"), ("all", "Todo"))
# What the monthly chart sums (garage-030 phase 3): ?chart=elevation switches it to metres of climbing.
CHARTS = {"km": ("Km", "distance_m", {}), "elevation": ("Desnivel", "elevation_gain_m", {"unit": "m", "divisor": Decimal(1), "title": "Desnivel (m)"})}
LEGACY = ("bike", "category", "item", "started_from", "started_to", "time_zone")
TOP_ITEMS = 8


def period_bounds(period, zone, now):
    """[start, end) in the viewer's zone, plus the chart's last month and length.

    One computation shared by the figures and the chart, so both always add up.
    """
    local = now.astimezone(zone)
    if period == "year":
        return datetime(local.year, 1, 1, tzinfo=zone), now, (local.year, local.month), local.month
    if period == "last":
        return datetime(local.year - 1, 1, 1, tzinfo=zone), datetime(local.year, 1, 1, tzinfo=zone), (local.year - 1, 12), 12
    if period == "all":
        return None, now, (local.year, local.month), 12
    year, month = local.year, local.month - 11
    if month < 1:
        year, month = year - 1, month + 12
    return datetime(year, month, 1, tzinfo=zone), now, (local.year, local.month), 12


def _share(value, maximum):
    """0-100 width for an SVG bar (no inline styles)."""
    if value is None or not maximum:
        return "0"
    return f"{min(Decimal(value) / Decimal(maximum), Decimal(1)) * 100:.1f}"


def _spending(user, start, end):
    """Declared intervention costs in [start, end) per currency, each event once."""
    events = scoped_inventory(user, ServiceEvent).filter(performed_at__lt=end)
    if start is not None:
        events = events.filter(performed_at__gte=start)
    totals = events.aggregate(unknown=Count("id", filter=Q(amount__isnull=True)))
    rows = events.filter(amount__isnull=False).values("currency").annotate(total=Sum("amount"), count=Count("id")).order_by("currency")
    return list(rows), totals["unknown"]


@login_required
@never_cache
@require_GET
def statistics_page(request):
    zone = user_time_zone(request)
    now = timezone.now()
    custom = any(key in request.GET for key in LEGACY)
    period = "custom" if custom else request.GET.get("period", "12m")
    if period not in dict(PERIODS) and not custom:
        period = "12m"
    chart_key = request.GET.get("chart", "km")
    if chart_key not in CHARTS:
        chart_key = "km"
    report = chart = series = None
    context = {"title": "Estadísticas", "tab": "stats", "periods": PERIODS, "period": period, "user_tz": zone,
               "last_year": now.astimezone(zone).year - 1, "chart_key": chart_key,
               "charts": [(key, label) for key, (label, _, _) in CHARTS.items()],
               "chart_metric": CHARTS[chart_key][1]}
    if custom:
        # The detailed form as before: explicit zone and bounds.
        form = localize(StatisticsForm(request.GET, user=request.user), zone)
        if form.is_valid():
            try:
                report = statistics(request.user, **{key: form.cleaned_data[key] for key in ("bike", "category", "item", "started_from", "started_to")})
            except InventoryWriteError as error:
                for field, errors in error.message_dict.items():
                    form.add_error(field, errors)
            else:
                # Dates on the page follow the zone the bounds were written in.
                context["user_tz"] = ZoneInfo(form.cleaned_data["time_zone"])
                # The summary covers every ride; with a bike, category or item filter only the detailed report applies.
                context["filtered"] = any(form.cleaned_data.get(key) for key in ("bike", "category", "item"))
                context["open_end"] = form.cleaned_data.get("started_to") is None
    else:
        start, end, through, months = period_bounds(period, zone, now)
        initial = {"started_from": start.astimezone(zone).replace(tzinfo=None) if start else None,
                   "started_to": end.astimezone(zone).replace(tzinfo=None).replace(microsecond=0) if period == "last" else None,
                   "time_zone": zone.key}
        form = localize(StatisticsForm(user=request.user, initial=initial), zone)
        if start is None or start < end:
            report = statistics(request.user, started_from=start, started_to=end)
            _, metric, options = CHARTS[chart_key]
            series = monthly_usage(request.user, all_rides=True, tz=zone, at=now, months=months, through=through, metric=metric)
            chart = line_chart(series.buckets, **options)
            # Rides of these months without elevation (garage-030 phase 3 review): the chart is a minimum.
            context["chart_missing"] = sum(bucket.missing for bucket in series.buckets) if chart_key == "elevation" else 0
        # else: the very first instant of the year, nothing can have happened yet.
    if report is not None:
        bikes = sorted((row for row in report.rows if row.kind == "bike"), key=lambda row: (-(row.observed[0].value or 0), row.target.name.lower()))
        top = max([row.observed[0].value or 0 for row in bikes] + [report.no_bike[0].value or 0 if report.no_bike else 0])
        items = sorted((row for row in report.rows if row.kind == "item" and row.observed[0].value),
                       key=lambda row: (-row.observed[0].value, row.target.name.lower()))
        spending, unknown_costs = _spending(request.user, report.start, report.end)
        context.update(bikes=[{"row": row, "share": _share(row.observed[0].value, top)} for row in bikes if row.observed[2].value],
                       no_bike_share=_share(report.no_bike[0].value if report.no_bike else None, top),
                       items=items[:TOP_ITEMS], spending=spending, unknown_costs=unknown_costs)
    context.update(form=form, report=report, chart=chart, monthly=series)
    return render(request, "garage/statistics.html", context)
