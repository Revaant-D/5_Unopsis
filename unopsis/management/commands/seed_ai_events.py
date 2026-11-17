"""
Seed simulated AIEvent rows so the analytics dashboard has a shape to show.

The assignment allows simulated data. What it does not allow is passing simulated data off as
measured, so every row written here is marked `simulated=True`, the dashboard reports what
share of the window is simulated, and real traffic recorded by telemetry.py is never touched
or overwritten.

The generator is not uniform noise. It reproduces the behaviour the three features actually
show, because a dashboard tested only against flat random data will look fine and then fall
over on the first real distribution it meets:

  * **Right-skewed latency.** Generation is slow and variable; embedding search is fast and
    tight. Both are drawn from lognormal-ish distributions, not uniform ones.
  * **Cold starts.** One or two per day, two orders of magnitude slower than a warm request.
    These are what make the mean a liar and the percentiles necessary.
  * **A daily rhythm.** Usage peaks in the evening, which is when students read their mail.
  * **Real failure modes.** Searches that match nothing above the 0.25 threshold, triage
    inputs refused by the injection guardrail, and the occasional rate-limited burst.
"""

import random
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from unopsis.models import AIEvent

QUERIES = [
    "what did my mom say", "when is grandma's birthday dinner", "is the staging deploy fixed",
    "did anyone reply about the invoice", "what time is the career fair",
    "who messaged me about rent", "any updates on the group project",
    "did my package ship", "what did the professor say about the deadline",
    "meeting notes from monday", "is the gym open on sunday", "who needs a reply today",
    "what did sam send", "anything urgent from work", "did i miss anything important",
]

# (feature, share, warm latency centre ms, spread, cpu fraction of wall time)
PROFILES = [
    ("search", 0.52, 140, 0.45, 0.85),
    ("triage", 0.26, 6800, 0.35, 0.95),
    ("answer", 0.18, 7400, 0.40, 0.95),
    ("brief", 0.04, 2600, 0.50, 0.30),   # Groq does the writing, so little local CPU
]


class Command(BaseCommand):
    help = "Create simulated AIEvent rows for the analytics dashboard."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=30)
        parser.add_argument("--per-day", type=int, default=26)
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--clear", action="store_true",
                            help="Delete existing SIMULATED rows first. Never touches real ones.")

    def handle(self, *args, **opts):
        rng = random.Random(opts["seed"])
        if opts["clear"]:
            deleted, _ = AIEvent.objects.filter(simulated=True).delete()
            self.stdout.write(f"removed {deleted} simulated row(s); real rows untouched")

        users = list(get_user_model().objects.all()[:5])
        now = timezone.now()
        feats = [p[0] for p in PROFILES]
        weights = [p[1] for p in PROFILES]
        by_name = {p[0]: p for p in PROFILES}
        rows, cold_days = [], 0

        for day in range(opts["days"]):
            day_start = (now - timedelta(days=day)).replace(hour=0, minute=0, second=0,
                                                            microsecond=0)
            n = max(0, int(rng.gauss(opts["per_day"], opts["per_day"] * 0.35)))
            # One cold start on most days: the server restarts, the next request pays for it.
            cold_index = rng.randrange(n) if n and rng.random() < 0.8 else -1
            if cold_index >= 0:
                cold_days += 1

            for i in range(n):
                feature = rng.choices(feats, weights)[0]
                _, _, centre, spread, cpu_frac = by_name[feature]
                # Evening-weighted hour of day.
                hour = min(23, max(6, int(rng.triangular(7, 23, 20))))
                when = day_start + timedelta(hours=hour, minutes=rng.randrange(60),
                                             seconds=rng.randrange(60))
                cold = (i == cold_index) and feature in ("triage", "answer")
                if cold:
                    latency = int(rng.uniform(95_000, 225_000))
                else:
                    latency = max(12, int(rng.lognormvariate(0, spread) * centre))

                status, result_count, top_score, query = AIEvent.Status.OK, 0, None, ""
                if feature == "search":
                    query = rng.choice(QUERIES)
                    if rng.random() < 0.14:          # nothing cleared the 0.25 threshold
                        status, result_count, top_score = AIEvent.Status.NO_MATCH, 0, \
                            round(rng.uniform(0.05, 0.24), 3)
                    else:
                        result_count = rng.randint(1, 5)
                        top_score = round(rng.uniform(0.26, 0.82), 3)
                elif feature == "triage" and rng.random() < 0.07:
                    status = AIEvent.Status.REFUSED   # injection guardrail fired
                    latency = int(rng.uniform(3, 20))  # refused before the model is called
                if rng.random() < 0.02:
                    status = AIEvent.Status.RATE_LIMITED
                    latency = int(rng.uniform(2, 12))

                in_tok = rng.randint(12, 90) if feature != "brief" else rng.randint(300, 900)
                out_tok = 0 if status != AIEvent.Status.OK else (
                    rng.randint(20, 70) if feature in ("triage", "answer")
                    else rng.randint(80, 240) if feature == "brief" else 0)

                rows.append(AIEvent(
                    user=rng.choice(users) if users else None,
                    feature=feature, status=status,
                    model_name="ibm-granite/granite-3.3-2b-instruct" if feature != "search"
                    else "sentence-transformers/all-MiniLM-L6-v2",
                    latency_ms=latency,
                    cpu_ms=int(latency * cpu_frac * rng.uniform(0.85, 1.0)),
                    cold_start=cold,
                    input_chars=in_tok * 4, input_tokens_est=in_tok, output_tokens_est=out_tok,
                    query_text=query, result_count=result_count, top_score=top_score,
                    simulated=True,
                ))
                rows[-1]._when = when

        created = AIEvent.objects.bulk_create(rows)
        # auto_now_add ignores any value passed in, so the timestamps are corrected after
        # insert. Without this every simulated row lands "now" and all the time-series
        # widgets collapse into a single bar, which is exactly how this was first written.
        for obj in created:
            AIEvent.objects.filter(pk=obj.pk).update(created_at=obj._when)

        self.stdout.write(self.style.SUCCESS(
            f"created {len(created)} simulated AI events over {opts['days']} days "
            f"({cold_days} with a cold start)"))
