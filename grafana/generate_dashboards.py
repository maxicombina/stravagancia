#!/usr/bin/env python3
"""Generate the Strava Grafana dashboards (weekly / monthly / selectable bucket).

This is the source of truth for the bucketed dashboards that replicate the
Metabase "My Activities Dashboard". Run it to (re)write the JSON files that
Grafana provisions from grafana/dashboards/:

    python grafana/generate_dashboards.py

Three dashboards are produced, all reading from the `strava-postgres`
datasource (Neon) and all grouped by start_date_local truncated to a bucket:

    strava_weekly.json   uid=strava-weekly    bucket = week
    strava_monthly.json  uid=strava-monthly   bucket = month
    strava_bucket.json   uid=strava-bucket    bucket = $bucket (dropdown)

Each dashboard mirrors Metabase: a "Totales" section (per-bucket sums/maxes),
a "Promedios por salida" section (per-ride averages), a "Derivados (por hora)"
section, and a missing-activities table at the bottom.
"""

import json
import os

DS = {"type": "grafana-postgresql-datasource", "uid": "strava-postgres"}
TABLE = "strava_integration_activity"
RIDE_FILTER = "activity_type = 'Ride'"

# (title, aggregation expression over the table, grafana unit, fixed color, viz)
# NOTE: Distance/Activities AND Calories are NOT here — they are rendered as
# combo panels (combo_distance_panel, combo_calories_panel) injected as the
# leads of the Totales section (bars + regression trend [+ activities line /
# goal line]), mirroring Metabase's combo cards with trend & goal lines.
TOTALS = [
    ("Elevation gain (m)",  "SUM(total_elevation_gain)",     "lengthm",     "green",  "barchart"),
    ("Moving time (h)",     "SUM(moving_time) / 3600.0",     "h",           "blue",   "barchart"),
    ("Max speed (km/h)",    "MAX(max_speed) * 3.6",          "velocitykmh", "purple", "timeseries"),
    ("Max heart rate (bpm)","MAX(max_heartrate)",            "short",       "red",    "timeseries"),
]

AVERAGES = [
    ("Avg km per ride",        "AVG(distance) / 1000.0",     "lengthkm",    "blue",   "barchart"),
    ("Avg calories per ride",  "AVG(calories)",              "kcal",        "orange", "barchart"),
    ("Avg moving time (h)",    "AVG(moving_time) / 3600.0",  "h",           "blue",   "barchart"),
    ("Avg elevation gain (m)", "AVG(total_elevation_gain)",  "lengthm",     "green",  "timeseries"),
    ("Avg speed (km/h)",       "AVG(average_speed) * 3.6",   "velocitykmh", "green",  "timeseries"),
    ("Avg heart rate (bpm)",   "AVG(average_heartrate)",     "short",       "red",    "timeseries"),
]

DERIVED = [
    ("Calories per hour",       "AVG(CASE WHEN moving_time = 0 THEN NULL ELSE calories / (moving_time / 3600.0) END)",             "short", "orange", "timeseries"),
    ("Max calories per hour",   "MAX(CASE WHEN moving_time = 0 THEN NULL ELSE calories / (moving_time / 3600.0) END)",             "short", "orange", "timeseries"),
    ("Elevation gain per hour", "AVG(CASE WHEN moving_time = 0 THEN NULL ELSE total_elevation_gain / (moving_time / 3600.0) END)", "short", "green",  "timeseries"),
    ("Elevation per distance",  "AVG(CASE WHEN distance = 0 THEN NULL ELSE total_elevation_gain / distance END)",                  "short", "green",  "timeseries"),
]


def agg_sql(agg, bucket, viz):
    # Barcharts use a short formatted string label as the x-axis category, so
    # the full timestamp doesn't get rendered raw (and overlap). Timeseries
    # panels need a real time-typed field for their auto-formatted time axis.
    if viz == "barchart":
        if bucket == "$bucket":
            label = (
                "to_char(date_trunc('$bucket', start_date_local), "
                "CASE WHEN '$bucket' = 'week' THEN 'YYYY-MM-DD' ELSE 'YYYY-MM' END)"
            )
        else:
            fmt = "YYYY-MM-DD" if bucket == "week" else "YYYY-MM"
            label = f"to_char(date_trunc('{bucket}', start_date_local), '{fmt}')"
        select_time = f"{label} AS period"
    else:
        select_time = f"date_trunc('{bucket}', start_date_local) AS time"
    return (
        f"SELECT {select_time}, {agg} AS value\n"
        f"FROM {TABLE}\n"
        f"WHERE $__timeFilter(start_date_local) AND {RIDE_FILTER}\n"
        f"GROUP BY 1\nORDER BY 1"
    )


def thresholds():
    return {"mode": "absolute", "steps": [{"color": "green", "value": None}]}


def combo_distance_panel(pid, bucket, x, y):
    """Metabase-style combo: green km bars (left axis) + pink activities line
    (right axis). This is the one panel that uses the timeseries viz (the only
    way to overlay a line on bars), so its x labels render horizontal."""
    # Goal line: the user's minimum per bucket — 65 km/week, 260 km/month
    # (their chosen monthly target). The combo is shared across buckets, so a
    # CASE covers the selectable-bucket dashboard. Rendered as a flat dotted line.
    if bucket == "week":
        goal_expr, goal_label = "65", "Goal (65 km/wk)"
    elif bucket == "month":
        goal_expr, goal_label = "260", "Goal (260 km/mo)"
    else:  # "$bucket" — value switches with the dropdown, so keep the label generic
        goal_expr, goal_label = "CASE WHEN '$bucket' = 'week' THEN 65 ELSE 260 END", "Goal (min)"

    # Linear-regression trend of km over the bucket index, computed in SQL
    # (regr_slope/regr_intercept), added as a 3rd "Trend (km)" series rendered
    # as a dashed line on the left (km) axis — Metabase's trend-line equivalent.
    sql = (
        f"WITH w AS (\n"
        f"  SELECT date_trunc('{bucket}', start_date_local) AS time,\n"
        f"         SUM(distance) / 1000.0 AS km,\n"
        f"         COUNT(*) AS activities\n"
        f"  FROM {TABLE}\n"
        f"  WHERE $__timeFilter(start_date_local) AND {RIDE_FILTER}\n"
        f"  GROUP BY 1\n"
        f"),\n"
        f"n AS (\n"
        f"  SELECT time, km, activities,\n"
        f"         ROW_NUMBER() OVER (ORDER BY time) - 1 AS rn\n"
        f"  FROM w\n"
        f"),\n"
        f"r AS (\n"
        f"  SELECT regr_slope(km, rn) AS slope, regr_intercept(km, rn) AS intercept FROM n\n"
        f")\n"
        f"SELECT n.time,\n"
        f"       n.km AS \"Distance (km)\",\n"
        f"       n.activities AS \"Activities\",\n"
        f"       r.intercept + r.slope * n.rn AS \"Trend (km)\",\n"
        f"       {goal_expr} AS \"{goal_label}\"\n"
        f"FROM n CROSS JOIN r\n"
        f"ORDER BY n.time"
    )
    return {
        "datasource": DS,
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "fixed", "fixedColor": "green"},
                "custom": {
                    "axisBorderShow": False,
                    "axisCenteredZero": False,
                    "axisColorMode": "text",
                    "axisLabel": "km",
                    "axisPlacement": "left",
                    "drawStyle": "bars",
                    "fillOpacity": 80,
                    "gradientMode": "none",
                    "hideFrom": {"legend": False, "tooltip": False, "viz": False},
                    "lineWidth": 1,
                    "scaleDistribution": {"type": "linear"},
                    "showPoints": "never",
                    "stacking": {"group": "A", "mode": "none"},
                    "thresholdsStyle": {"mode": "off"},
                },
                "mappings": [],
                "thresholds": thresholds(),
                "unit": "lengthkm",
            },
            "overrides": [
                {
                    "matcher": {"id": "byName", "options": "Activities"},
                    "properties": [
                        {"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}},
                        {"id": "unit", "value": "short"},
                        {"id": "custom.drawStyle", "value": "line"},
                        {"id": "custom.lineWidth", "value": 2},
                        {"id": "custom.lineInterpolation", "value": "linear"},
                        {"id": "custom.fillOpacity", "value": 0},
                        {"id": "custom.showPoints", "value": "always"},
                        {"id": "custom.pointSize", "value": 6},
                        {"id": "custom.axisPlacement", "value": "right"},
                        {"id": "custom.axisLabel", "value": "Activities"},
                    ],
                },
                {
                    "matcher": {"id": "byName", "options": "Trend (km)"},
                    "properties": [
                        {"id": "color", "value": {"mode": "fixed", "fixedColor": "light-yellow"}},
                        {"id": "custom.drawStyle", "value": "line"},
                        {"id": "custom.lineWidth", "value": 2},
                        {"id": "custom.lineInterpolation", "value": "linear"},
                        {"id": "custom.fillOpacity", "value": 0},
                        {"id": "custom.showPoints", "value": "never"},
                        {"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [10, 10]}},
                        {"id": "custom.axisPlacement", "value": "left"},
                    ],
                },
                {
                    "matcher": {"id": "byName", "options": goal_label},
                    "properties": [
                        {"id": "color", "value": {"mode": "fixed", "fixedColor": "white"}},
                        {"id": "custom.drawStyle", "value": "line"},
                        {"id": "custom.lineWidth", "value": 2},
                        {"id": "custom.lineInterpolation", "value": "linear"},
                        {"id": "custom.fillOpacity", "value": 0},
                        {"id": "custom.showPoints", "value": "never"},
                        {"id": "custom.lineStyle", "value": {"fill": "dot", "dash": [2, 10]}},
                        {"id": "custom.axisPlacement", "value": "left"},
                    ],
                },
            ],
        },
        "gridPos": {"h": 8, "w": 12, "x": x, "y": y},
        "id": pid,
        "options": {
            "legend": {"calcs": [], "displayMode": "list", "placement": "bottom", "showLegend": True},
            "tooltip": {"mode": "multi", "sort": "none"},
        },
        "title": "Distance (km) + Activities",
        "type": "timeseries",
        "targets": [{
            "datasource": DS,
            "editorMode": "code",
            "format": "table",
            "rawQuery": True,
            "rawSql": sql,
            "refId": "A",
        }],
    }


def combo_calories_panel(pid, bucket, x, y):
    """Calories combo (mirrors the Distance combo): orange kcal bars + dashed
    light-yellow linear-regression trend line + dotted white baseline. The
    baseline is the user's weekly minimum (2500 kcal/wk); scaled for month."""
    if bucket == "week":
        goal_expr, goal_label = "2500", "Baseline (2500 kcal/wk)"
    elif bucket == "month":
        goal_expr, goal_label = "10000", "Baseline (10000 kcal/mo)"
    else:  # "$bucket"
        goal_expr, goal_label = "CASE WHEN '$bucket' = 'week' THEN 2500 ELSE 10000 END", "Baseline"

    sql = (
        f"WITH w AS (\n"
        f"  SELECT date_trunc('{bucket}', start_date_local) AS time,\n"
        f"         SUM(calories) AS kcal\n"
        f"  FROM {TABLE}\n"
        f"  WHERE $__timeFilter(start_date_local) AND {RIDE_FILTER}\n"
        f"  GROUP BY 1\n"
        f"),\n"
        f"n AS (\n"
        f"  SELECT time, kcal, ROW_NUMBER() OVER (ORDER BY time) - 1 AS rn FROM w\n"
        f"),\n"
        f"r AS (\n"
        f"  SELECT regr_slope(kcal, rn) AS slope, regr_intercept(kcal, rn) AS intercept FROM n\n"
        f")\n"
        f"SELECT n.time,\n"
        f"       n.kcal AS \"Calories\",\n"
        f"       r.intercept + r.slope * n.rn AS \"Trend (kcal)\",\n"
        f"       {goal_expr} AS \"{goal_label}\"\n"
        f"FROM n CROSS JOIN r\n"
        f"ORDER BY n.time"
    )
    return {
        "datasource": DS,
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "fixed", "fixedColor": "orange"},
                "custom": {
                    "axisBorderShow": False,
                    "axisCenteredZero": False,
                    "axisColorMode": "text",
                    "axisLabel": "kcal",
                    "axisPlacement": "left",
                    "drawStyle": "bars",
                    "fillOpacity": 80,
                    "gradientMode": "none",
                    "hideFrom": {"legend": False, "tooltip": False, "viz": False},
                    "lineWidth": 1,
                    "scaleDistribution": {"type": "linear"},
                    "showPoints": "never",
                    "stacking": {"group": "A", "mode": "none"},
                    "thresholdsStyle": {"mode": "off"},
                },
                "mappings": [],
                "thresholds": thresholds(),
                "unit": "kcal",
            },
            "overrides": [
                {
                    "matcher": {"id": "byName", "options": "Trend (kcal)"},
                    "properties": [
                        {"id": "color", "value": {"mode": "fixed", "fixedColor": "light-yellow"}},
                        {"id": "custom.drawStyle", "value": "line"},
                        {"id": "custom.lineWidth", "value": 2},
                        {"id": "custom.lineInterpolation", "value": "linear"},
                        {"id": "custom.fillOpacity", "value": 0},
                        {"id": "custom.showPoints", "value": "never"},
                        {"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [10, 10]}},
                        {"id": "custom.axisPlacement", "value": "left"},
                    ],
                },
                {
                    "matcher": {"id": "byName", "options": goal_label},
                    "properties": [
                        {"id": "color", "value": {"mode": "fixed", "fixedColor": "white"}},
                        {"id": "custom.drawStyle", "value": "line"},
                        {"id": "custom.lineWidth", "value": 2},
                        {"id": "custom.lineInterpolation", "value": "linear"},
                        {"id": "custom.fillOpacity", "value": 0},
                        {"id": "custom.showPoints", "value": "never"},
                        {"id": "custom.lineStyle", "value": {"fill": "dot", "dash": [2, 10]}},
                        {"id": "custom.axisPlacement", "value": "left"},
                    ],
                },
            ],
        },
        "gridPos": {"h": 8, "w": 12, "x": x, "y": y},
        "id": pid,
        "options": {
            "legend": {"calcs": [], "displayMode": "list", "placement": "bottom", "showLegend": True},
            "tooltip": {"mode": "multi", "sort": "none"},
        },
        "title": "Calories + Trend",
        "type": "timeseries",
        "targets": [{
            "datasource": DS,
            "editorMode": "code",
            "format": "table",
            "rawQuery": True,
            "rawSql": sql,
            "refId": "A",
        }],
    }


def metric_panel(pid, title, agg, unit, color, viz, bucket, x, y):
    field_defaults = {
        "color": {"mode": "fixed", "fixedColor": color},
        "custom": {
            "axisBorderShow": False,
            "axisCenteredZero": False,
            "axisColorMode": "text",
            "axisLabel": "",
            "axisPlacement": "auto",
            "fillOpacity": 80 if viz == "barchart" else 10,
            "gradientMode": "none",
            "hideFrom": {"legend": False, "tooltip": False, "viz": False},
            "lineWidth": 1 if viz == "barchart" else 2,
            "scaleDistribution": {"type": "linear"},
            "thresholdsStyle": {"mode": "off"},
        },
        "mappings": [],
        "thresholds": thresholds(),
        "unit": unit,
    }
    if viz == "timeseries":
        field_defaults["custom"].update({
            "drawStyle": "line",
            "lineInterpolation": "smooth",
            "pointSize": 5,
            "showPoints": "auto",
            "spanNulls": True,
            "stacking": {"group": "A", "mode": "none"},
        })
        options = {
            "legend": {"calcs": [], "displayMode": "list", "placement": "bottom", "showLegend": False},
            "tooltip": {"mode": "single", "sort": "none"},
        }
    else:
        options = {
            "barRadius": 0,
            "barWidth": 0.9,
            "fullHighlight": False,
            "groupWidth": 0.7,
            "legend": {"calcs": [], "displayMode": "list", "placement": "bottom", "showLegend": False},
            "orientation": "auto",
            "showValue": "auto",
            "stacking": "none",
            "tooltip": {"mode": "single", "sort": "none"},
            "xTickLabelRotation": -45,
            "xTickLabelSpacing": 0,
        }
    return {
        "datasource": DS,
        "fieldConfig": {"defaults": field_defaults, "overrides": []},
        "gridPos": {"h": 8, "w": 12, "x": x, "y": y},
        "id": pid,
        "options": options,
        "title": title,
        "type": viz,
        "targets": [{
            "datasource": DS,
            "editorMode": "code",
            "format": "table",
            "rawQuery": True,
            "rawSql": agg_sql(agg, bucket, viz),
            "refId": "A",
        }],
    }


def text_panel(pid, text, y):
    return {
        "id": pid,
        "type": "text",
        "gridPos": {"h": 2, "w": 24, "x": 0, "y": y},
        "options": {"mode": "markdown", "content": f"### {text}"},
        "transparent": True,
    }


def missing_table_panel(pid, y):
    sql = (
        "SELECT start_date_local AS \"Fecha\", strava_id AS \"Strava ID\", "
        "loaded AS \"Cargada\"\n"
        "FROM strava_integration_missingactivity\n"
        "ORDER BY start_date_local DESC"
    )
    return {
        "datasource": DS,
        "fieldConfig": {"defaults": {"custom": {"filterable": True}}, "overrides": []},
        "gridPos": {"h": 9, "w": 24, "x": 0, "y": y},
        "id": pid,
        "options": {"showHeader": True, "cellHeight": "sm"},
        "title": "Missing activities",
        "type": "table",
        "targets": [{
            "datasource": DS,
            "editorMode": "code",
            "format": "table",
            "rawQuery": True,
            "rawSql": sql,
            "refId": "A",
        }],
    }


def build_dashboard(uid, title, bucket, default_from, templating=None):
    panels = []
    pid = 1
    y = 0

    def add_section(header, metrics, leads=None):
        nonlocal pid, y
        panels.append(text_panel(pid, header, y))
        pid += 1
        y += 2
        # `leads` are prebuilt combo panels (timeseries) placed first; the rest
        # are plain barcharts. Only barcharts let Grafana rotate the x-axis tick
        # labels, so they stay tilted/consistent (matching Metabase). The `viz`
        # column in the metric tables documents Metabase's original choice.
        items = [("lead", b) for b in (leads or [])] + [("metric", m) for m in metrics]
        for i, (kind, item) in enumerate(items):
            x = 0 if i % 2 == 0 else 12
            if kind == "lead":
                panels.append(item(pid, x, y))
            else:
                mtitle, agg, unit, color, viz = item
                panels.append(metric_panel(pid, mtitle, agg, unit, color, "barchart", bucket, x, y))
            pid += 1
            if i % 2 == 1:
                y += 8
        if len(items) % 2 == 1:
            y += 8

    add_section("Totales", TOTALS, leads=[
        lambda p, x, y: combo_distance_panel(p, bucket, x, y),
        lambda p, x, y: combo_calories_panel(p, bucket, x, y),
    ])
    add_section("Promedios por salida", AVERAGES)
    add_section("Derivados (por hora)", DERIVED)

    panels.append(missing_table_panel(pid, y))

    return {
        "annotations": {"list": [{
            "builtIn": 1,
            "datasource": {"type": "grafana", "uid": "-- Grafana --"},
            "enable": True, "hide": True,
            "iconColor": "rgba(0, 211, 255, 1)",
            "name": "Annotations & Alerts", "type": "dashboard",
        }]},
        "editable": True,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 0,
        "links": [],
        "panels": panels,
        "refresh": "",
        "schemaVersion": 39,
        "tags": ["strava"],
        "templating": {"list": templating or []},
        "time": {"from": default_from, "to": "now"},
        "timepicker": {"quick_ranges": [
            {"display": "Last 28 days", "from": "now-28d", "to": "now"},
            {"display": "Last 90 days", "from": "now-90d", "to": "now"},
            {"display": "Last 6 months", "from": "now-6M", "to": "now"},
            {"display": "Last 1 year", "from": "now-1y", "to": "now"},
            {"display": "Last 2 years", "from": "now-2y", "to": "now"},
            {"display": "Last 5 years", "from": "now-5y", "to": "now"},
            {"display": "This year so far", "from": "now/y", "to": "now"},
        ]},
        "timezone": "browser",
        "title": title,
        "uid": uid,
        "weekStart": "",
    }


BUCKET_VAR = [{
    "name": "bucket",
    "label": "Bucket",
    "type": "custom",
    "query": "week,month",
    "current": {"selected": True, "text": "month", "value": "month"},
    "options": [
        {"selected": False, "text": "week", "value": "week"},
        {"selected": True, "text": "month", "value": "month"},
    ],
    "includeAll": False,
    "multi": False,
}]


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, "dashboards")
    dashboards = [
        ("strava_weekly.json",  build_dashboard("strava-weekly",  "Strava — Weekly",  "week",  "now-3M")),
        ("strava_monthly.json", build_dashboard("strava-monthly", "Strava — Monthly", "month", "now-2y")),
        ("strava_bucket.json",  build_dashboard("strava-bucket",  "Strava — Custom bucket", "$bucket", "now-1y", BUCKET_VAR)),
    ]
    for fname, dash in dashboards:
        path = os.path.join(out, fname)
        with open(path, "w") as f:
            json.dump(dash, f, indent=2)
            f.write("\n")
        print(f"wrote {path} ({len(dash['panels'])} panels)")


if __name__ == "__main__":
    main()
