"""
Assignment 10: the analytics dashboard.

    /analytics/                  analytics-dashboard   the page
    /analytics/<chart>.json      analytics-chart-spec  one Vega-Lite spec, data embedded

The split mirrors the existing /vega-lite/ routes: the page is HTML, each chart is a spec the
browser fetches and renders. Rendering client-side is not a style preference here -- this
deployment has a 100 CPU-second daily budget, and server-side chart rendering would spend that
budget drawing pictures of how the budget is being spent.

Every chart on this page exists because a question needed answering. The mapping is written
into CHARTS below so it cannot drift from the write-up, and the page prints each question
above its own chart.
"""

import json

from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import render

from . import analytics

# question -> widget, kept next to the code that builds the widget.
CHARTS = {
    "latency_by_feature": {
        "question": "P1. How does latency vary across the three AI features?",
        "title": "Warm latency by feature (mean and p95)",
        "builder": analytics.latency_by_feature,
    },
    "latency_over_time": {
        "question": "P1/P3. Is response time getting better or worse over time?",
        "title": "Daily p50 and p95 latency",
        "builder": analytics.latency_over_time,
    },
    "latency_histogram": {
        "question": "P3. How consistent is response time?",
        "title": "Distribution of warm latency",
        "builder": analytics.latency_histogram,
    },
    "usage_by_feature": {
        "question": "U1. Which AI feature is actually used?",
        "title": "Requests by feature",
        "builder": analytics.usage_by_feature,
    },
    "usage_by_hour": {
        "question": "U1. When during the day is the AI used?",
        "title": "Requests by hour of day",
        "builder": analytics.usage_by_hour,
    },
    "top_terms": {
        "question": "U2. What are users actually asking for?",
        "title": "Most common search terms",
        "builder": analytics.top_query_terms,
    },
    "outcomes": {
        "question": "U3. How often does a request NOT produce an answer, and why?",
        "title": "Outcome by feature",
        "builder": analytics.outcomes_by_feature,
    },
    "cpu_by_day": {
        "question": "C1. How close is daily CPU use to the free-tier budget?",
        "title": "CPU-seconds per day vs the 100 s/day budget",
        "builder": analytics.cpu_by_day,
    },
}

_AXIS = {"labelFontSize": 11, "titleFontSize": 12}
_BASE = {"$schema": "https://vega.github.io/schema/vega-lite/v5.json",
         "width": "container", "height": 240, "config": {"axis": _AXIS}}


def _spec(name, days):
    rows = CHARTS[name]["builder"](days=days)
    title = CHARTS[name]["title"]

    if name == "latency_by_feature":
        values = [{"feature": r["feature"], "measure": m, "ms": r[k]}
                  for r in rows for m, k in (("mean", "mean_ms"), ("p95", "p95_ms"))]
        return {**_BASE, "title": title, "data": {"values": values},
                "mark": {"type": "bar", "tooltip": True},
                "encoding": {
                    "x": {"field": "feature", "type": "nominal", "title": None},
                    "xOffset": {"field": "measure"},
                    "y": {"field": "ms", "type": "quantitative", "title": "milliseconds"},
                    "color": {"field": "measure", "title": "statistic"}}}

    if name == "latency_over_time":
        values = [{"date": r["date"], "measure": m, "ms": r[k]}
                  for r in rows for m, k in (("p50", "p50_ms"), ("p95", "p95_ms"))]
        return {**_BASE, "title": title, "data": {"values": values},
                "mark": {"type": "line", "point": True, "tooltip": True},
                "encoding": {
                    "x": {"field": "date", "type": "temporal", "title": None},
                    "y": {"field": "ms", "type": "quantitative", "title": "milliseconds"},
                    "color": {"field": "measure", "title": "percentile"}}}

    if name == "latency_histogram":
        return {**_BASE, "title": title, "data": {"values": rows},
                "mark": {"type": "bar", "tooltip": True},
                "encoding": {
                    "x": {"field": "bucket_start_ms", "type": "quantitative",
                          "bin": {"binned": True, "step": 1},
                          "title": "latency (ms)"},
                    "x2": {"field": "bucket_end_ms"},
                    "y": {"field": "count", "type": "quantitative", "title": "requests"}}}

    if name in ("usage_by_feature", "top_terms"):
        field = "feature" if name == "usage_by_feature" else "term"
        return {**_BASE, "title": title, "data": {"values": rows},
                "mark": {"type": "bar", "tooltip": True},
                "encoding": {
                    "y": {"field": field, "type": "nominal", "sort": "-x", "title": None},
                    "x": {"field": "n", "type": "quantitative", "title": "requests"}}}

    if name == "usage_by_hour":
        return {**_BASE, "title": title, "data": {"values": rows},
                "mark": {"type": "bar", "tooltip": True},
                "encoding": {
                    "x": {"field": "hour", "type": "ordinal", "title": "hour of day (local)"},
                    "y": {"field": "n", "type": "quantitative", "title": "requests"}}}

    if name == "outcomes":
        return {**_BASE, "title": title, "data": {"values": rows},
                "mark": {"type": "bar", "tooltip": True},
                "encoding": {
                    "x": {"field": "feature", "type": "nominal", "title": None},
                    "y": {"field": "n", "type": "quantitative", "stack": "normalize",
                          "title": "share of requests"},
                    "color": {"field": "status", "title": "outcome"}}}

    if name == "cpu_by_day":
        # The budget is drawn as a rule on the same axis: a bar chart of CPU seconds means
        # nothing without the ceiling it is approaching.
        return {**_BASE, "title": title, "data": {"values": rows},
                "layer": [
                    {"mark": {"type": "bar", "tooltip": True},
                     "encoding": {
                         "x": {"field": "date", "type": "temporal", "title": None},
                         "y": {"field": "cpu_seconds", "type": "quantitative",
                               "title": "CPU seconds"}}},
                    {"mark": {"type": "rule", "strokeDash": [6, 4], "color": "firebrick"},
                     "encoding": {"y": {"datum": analytics.DAILY_CPU_BUDGET_SECONDS}}},
                ]}

    raise Http404(name)


def _days(request):
    try:
        d = int(request.GET.get("days", 30))
    except (TypeError, ValueError):
        d = 30
    return max(1, min(d, 365))


@login_required
def chart_spec(request, chart):
    if chart not in CHARTS:
        raise Http404(chart)
    return JsonResponse(_spec(chart, _days(request)))


@login_required
def dashboard(request):
    """The page. Login-only: it reports on everybody's traffic, not the viewer's own."""
    days = _days(request)
    context = {
        "days": days,
        "summary": analytics.summary(days),
        "cost_table": analytics.cost_table(days),
        "breakeven": analytics.breakeven(days),
        "cold_vs_warm": analytics.cold_vs_warm(days),
        "charts": [{"name": n, **{k: v for k, v in c.items() if k != "builder"}}
                   for n, c in CHARTS.items()],
        "api_in_rate": analytics.API_USD_PER_1M_INPUT,
        "api_out_rate": analytics.API_USD_PER_1M_OUTPUT,
    }
    return render(request, "unopsis/analytics_dashboard.html", context)
