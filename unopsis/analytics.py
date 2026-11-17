"""
Aggregations behind /analytics/ -- the numbers, separated from the view that renders them.

Everything here is a pure function over AIEvent rows, which keeps the view thin and lets the
tests assert on arithmetic rather than on HTML.

Three deliberate choices about the statistics, because the shape of this data punishes the
obvious approach:

1. **Percentiles, not means, for latency.** AI latency here is strongly right-skewed: a cold
   start loads Granite into memory and costs minutes, while a warm triage costs seconds. A
   mean over that mixture describes no request that ever happened. p50 says what a typical
   user waits; p95 says what an unlucky one waits; the gap between them is the honest measure
   of consistency.
2. **Cold and warm are reported separately, never blended.** They are two different
   populations produced by two different code paths, and the only reason they share a table
   is that both are "a request".
3. **Small-n is labelled rather than hidden.** A success rate over 4 requests is not a
   success rate, and the dashboard says so instead of printing a confident percentage.
"""

import math
import re
from collections import Counter
from datetime import timedelta

from django.db.models import Avg, Count, Sum
from django.utils import timezone

from .models import AIEvent

# PythonAnywhere's free tier allows 100 CPU-seconds per day for the whole account. That is the
# binding cost constraint on this deployment -- not dollars -- because exhausting it throttles
# the site for everyone. The dashboard tracks usage against this budget.
DAILY_CPU_BUDGET_SECONDS = 100

# Hosted-API comparison rates, in USD per 1M tokens. These are ASSUMPTIONS used to answer
# "what would this traffic cost if we had not self-hosted", and are labelled as such wherever
# they are shown. They are NOT measured, because nothing here is billed.
API_USD_PER_1M_INPUT = 0.10
API_USD_PER_1M_OUTPUT = 0.40

# Inputs this short are the user telling the search box nothing useful; they are excluded from
# the "what are people asking" terms so the chart is not dominated by stopwords.
STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "what", "when", "where", "who", "why", "how",
    "did", "do", "does", "my", "me", "i", "to", "of", "in", "on", "for", "and", "or", "it",
    "that", "this", "with", "about", "from", "any", "all", "say", "said", "get", "got",
}


def percentile(values, p):
    """Nearest-rank percentile: the smallest value at or above p% of the series.

    Returns None for an empty series rather than raising, because several widgets ask for a
    p95 of a feature that may have had no traffic in the window.

    The rank is ceil(p/100 * n), 1-based. Written out rather than reached for from a library
    so the definition is visible: an earlier version used round() and returned the 96th value
    of 1..100 for p95, which is the kind of error that never looks wrong on a dashboard.
    """
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    rank = math.ceil((p / 100) * len(vals))
    return vals[max(0, min(len(vals) - 1, rank - 1))]


def _window(days):
    return timezone.now() - timedelta(days=days)


def base_queryset(days=30):
    return AIEvent.objects.filter(created_at__gte=_window(days))


# --------------------------------------------------------------- summary cards
def summary(days=30):
    """The headline numbers. Answers P3, U3 and C1 at a glance."""
    qs = base_queryset(days)
    rows = list(qs.values_list("latency_ms", "status", "cold_start", "cpu_ms",
                              "input_tokens_est", "output_tokens_est"))
    total = len(rows)
    warm = [r[0] for r in rows if not r[2]]
    ok = sum(1 for r in rows if r[1] == AIEvent.Status.OK)

    today_cpu_ms = (AIEvent.objects
                    .filter(created_at__gte=timezone.now().replace(hour=0, minute=0, second=0,
                                                                   microsecond=0))
                    .aggregate(s=Sum("cpu_ms"))["s"] or 0)
    in_tok = sum(r[4] for r in rows)
    out_tok = sum(r[5] for r in rows)

    return {
        "total_requests": total,
        "p50_warm_ms": percentile(warm, 50),
        "p95_warm_ms": percentile(warm, 95),
        "cold_starts": sum(1 for r in rows if r[2]),
        "success_rate": (ok / total) if total else None,
        "success_rate_is_reliable": total >= 30,
        "cpu_seconds_today": round(today_cpu_ms / 1000, 1),
        "cpu_budget_seconds": DAILY_CPU_BUDGET_SECONDS,
        "cpu_budget_pct": round(today_cpu_ms / 10 / DAILY_CPU_BUDGET_SECONDS, 1),
        "tokens_est": in_tok + out_tok,
        "api_cost_equiv_usd": round(in_tok / 1e6 * API_USD_PER_1M_INPUT
                                    + out_tok / 1e6 * API_USD_PER_1M_OUTPUT, 4),
        "days": days,
        # A PERCENTAGE, 0-100, because the template prints it next to a % sign. It was
        # briefly a 0-1 fraction, which rendered a 100%-simulated window as "1%".
        "simulated_pct": round(qs.filter(simulated=True).count() / total * 100) if total else 0,
    }


# --------------------------------------------------------------- P1 / P3
def latency_by_feature(days=30):
    """Mean and p95 per feature, warm requests only. Answers P1 and feeds C2."""
    out = []
    for value, label in AIEvent.Feature.choices:
        lat = list(base_queryset(days).filter(feature=value, cold_start=False)
                   .values_list("latency_ms", flat=True))
        if not lat:
            continue
        out.append({"feature": label, "n": len(lat),
                    "mean_ms": round(sum(lat) / len(lat)),
                    "p50_ms": percentile(lat, 50), "p95_ms": percentile(lat, 95)})
    return out


def latency_over_time(days=30):
    """p50 and p95 per day. Answers P1's 'how does it vary' and shows trend."""
    buckets = {}
    for created, lat, cold in base_queryset(days).filter(cold_start=False).values_list(
            "created_at", "latency_ms", "cold_start"):
        buckets.setdefault(timezone.localtime(created).date().isoformat(), []).append(lat)
    return [{"date": d, "n": len(v), "p50_ms": percentile(v, 50), "p95_ms": percentile(v, 95)}
            for d, v in sorted(buckets.items())]


def cold_vs_warm(days=30):
    """The cold-start penalty, as its own comparison. Answers P2."""
    out = []
    for cold, label in ((True, "Cold start"), (False, "Warm")):
        lat = list(base_queryset(days).filter(cold_start=cold).values_list("latency_ms", flat=True))
        if lat:
            out.append({"kind": label, "n": len(lat), "mean_ms": round(sum(lat) / len(lat)),
                        "p50_ms": percentile(lat, 50), "max_ms": max(lat)})
    return out


def latency_histogram(days=30, buckets=12):
    """Distribution of warm latency. Answers P3 -- consistency is a shape, not a number."""
    lat = sorted(base_queryset(days).filter(cold_start=False)
                 .values_list("latency_ms", flat=True))
    if not lat:
        return []
    lo, hi = lat[0], max(lat[-1], lat[0] + 1)
    width = max(1, (hi - lo) // buckets)
    counter = Counter(min(buckets - 1, (v - lo) // width) for v in lat)
    return [{"bucket_start_ms": lo + i * width, "bucket_end_ms": lo + (i + 1) * width,
             "count": counter.get(i, 0)} for i in range(buckets)]


# --------------------------------------------------------------- U1 / U2 / U3
def usage_by_feature(days=30):
    """Which feature gets used. Answers U1."""
    counts = (base_queryset(days).values("feature")
              .annotate(n=Count("id")).order_by("-n"))
    labels = dict(AIEvent.Feature.choices)
    return [{"feature": labels.get(r["feature"], r["feature"]), "n": r["n"]} for r in counts]


def usage_by_hour(days=30):
    """Requests by hour of local day. Answers U1's 'how frequently / when'."""
    counter = Counter(timezone.localtime(c).hour
                      for c in base_queryset(days).values_list("created_at", flat=True))
    return [{"hour": h, "n": counter.get(h, 0)} for h in range(24)]


def top_query_terms(days=30, limit=12):
    """What people actually search for. Answers U2.

    Search queries only: triage input is third-party message content and is never stored.
    """
    counter = Counter()
    for q in base_queryset(days).filter(feature=AIEvent.Feature.SEARCH).exclude(
            query_text="").values_list("query_text", flat=True):
        for w in re.findall(r"[a-z']+", q.lower()):
            if len(w) > 2 and w not in STOPWORDS:
                counter[w] += 1
    return [{"term": t, "n": n} for t, n in counter.most_common(limit)]


def outcomes_by_feature(days=30):
    """Status breakdown. Answers U3 -- how often users do NOT get an answer, and why."""
    labels = dict(AIEvent.Feature.choices)
    status_labels = dict(AIEvent.Status.choices)
    rows = (base_queryset(days).values("feature", "status")
            .annotate(n=Count("id")).order_by("feature"))
    return [{"feature": labels.get(r["feature"], r["feature"]),
             "status": status_labels.get(r["status"], r["status"]), "n": r["n"]} for r in rows]


# --------------------------------------------------------------- C1 / C2 / C3
def cpu_by_day(days=14):
    """CPU-seconds per day against the free-tier budget. Answers C1."""
    buckets = {}
    for created, cpu in base_queryset(days).values_list("created_at", "cpu_ms"):
        d = timezone.localtime(created).date().isoformat()
        buckets[d] = buckets.get(d, 0) + (cpu or 0)
    return [{"date": d, "cpu_seconds": round(ms / 1000, 2),
             "budget_seconds": DAILY_CPU_BUDGET_SECONDS}
            for d, ms in sorted(buckets.items())]


def cost_table(days=30):
    """Per-feature cost. Answers C2 and C3.

    `api_cost_equiv_usd` is what this traffic WOULD have cost on a hosted API at the rates at
    the top of this module. It is a comparison, not a bill: these models run locally and the
    only real resource consumed is CPU time.
    """
    labels = dict(AIEvent.Feature.choices)
    rows = (base_queryset(days).values("feature")
            .annotate(n=Count("id"), cpu=Sum("cpu_ms"), mean_cpu=Avg("cpu_ms"),
                      tin=Sum("input_tokens_est"), tout=Sum("output_tokens_est"))
            .order_by("-cpu"))
    out = []
    for r in rows:
        tin, tout = r["tin"] or 0, r["tout"] or 0
        out.append({
            "feature": labels.get(r["feature"], r["feature"]),
            "requests": r["n"],
            "mean_cpu_ms": round(r["mean_cpu"] or 0),
            "total_cpu_seconds": round((r["cpu"] or 0) / 1000, 1),
            "tokens_est": tin + tout,
            "api_cost_equiv_usd": round(tin / 1e6 * API_USD_PER_1M_INPUT
                                        + tout / 1e6 * API_USD_PER_1M_OUTPUT, 4),
            "cpu_share_of_daily_budget_pct": round(
                (r["cpu"] or 0) / 1000 / max(1, days) / DAILY_CPU_BUDGET_SECONDS * 100, 1),
        })
    return out


def breakeven(days=30):
    """At what traffic does the free CPU budget run out? Answers C3's 'when does it stop working'.

    A linear projection on purpose, with its assumption stated: mean CPU per request is taken
    from the window and held constant. It ignores caching and concurrency, so it is an upper
    bound on headroom, not a forecast.
    """
    qs = base_queryset(days)
    n = qs.count()
    if not n:
        return None
    mean_cpu_ms = (qs.aggregate(a=Avg("cpu_ms"))["a"] or 0)
    if mean_cpu_ms <= 0:
        return None
    per_day = n / max(1, days)
    return {
        "mean_cpu_ms": round(mean_cpu_ms),
        "requests_per_day_now": round(per_day, 1),
        "max_requests_per_day": int(DAILY_CPU_BUDGET_SECONDS * 1000 / mean_cpu_ms),
        "headroom_x": round((DAILY_CPU_BUDGET_SECONDS * 1000 / mean_cpu_ms) / per_day, 1)
        if per_day else None,
    }
