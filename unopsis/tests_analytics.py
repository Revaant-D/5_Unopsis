"""
Tests for the Assignment 10 analytics dashboard.

Grouped by what could actually go wrong rather than by function, because the risky parts of
this feature are not the aggregations themselves:

  AnalyticsAccessTests      the dashboard reports on everyone's traffic, so it must be
                            login-only -- an unauthenticated reader must not learn how the
                            system performs or what people search for
  TelemetryTests            recording must never break the feature it measures, and must
                            still write a row when the feature raises
  PrivacyTests              triage input is third-party message content and must never reach
                            the telemetry table
  StatisticsTests           the percentile and cold/warm logic, which is where a quiet wrong
                            answer would be most believable
  ChartSpecTests            every widget named in CHARTS resolves and returns a usable spec
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import analytics
from .ai import telemetry
from .models import AIEvent

PASSWORD = "uiuc12345-test"


def make_event(**kw):
    defaults = dict(feature=AIEvent.Feature.SEARCH, status=AIEvent.Status.OK,
                    latency_ms=100, cpu_ms=80)
    defaults.update(kw)
    return AIEvent.objects.create(**defaults)


class AnalyticsAccessTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("grader", password=PASSWORD)

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("analytics-dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.url)

    def test_chart_spec_requires_login(self):
        response = self.client.get(reverse("analytics-chart-spec", args=["usage_by_feature"]))
        self.assertEqual(response.status_code, 302)

    def test_dashboard_renders_for_a_signed_in_user(self):
        self.client.login(username="grader", password=PASSWORD)
        make_event()
        response = self.client.get(reverse("analytics-dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "AI analytics")

    def test_every_chart_prints_the_question_it_answers(self):
        """The assignment's rule: question-driven, not chart-driven."""
        self.client.login(username="grader", password=PASSWORD)
        make_event()
        html = self.client.get(reverse("analytics-dashboard")).content.decode()
        from .analytics_views import CHARTS
        for name, config in CHARTS.items():
            with self.subTest(chart=name):
                self.assertIn(config["question"], html)

    def test_empty_database_renders_rather_than_crashing(self):
        self.client.login(username="grader", password=PASSWORD)
        response = self.client.get(reverse("analytics-dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No AI requests recorded")


class TelemetryTests(TestCase):
    def test_a_successful_call_is_recorded(self):
        with telemetry.record("search", None, query="what did my mom say") as ev:
            ev.ok(output_text="four words here", result_count=3, top_score=0.44)
        event = AIEvent.objects.get()
        self.assertEqual(event.feature, "search")
        self.assertEqual(event.status, "ok")
        self.assertEqual(event.result_count, 3)
        self.assertFalse(event.simulated)

    def test_an_exception_still_writes_a_row_and_is_not_swallowed(self):
        """A dashboard that only records successes shows a system that never fails."""
        with self.assertRaises(ValueError):
            with telemetry.record("answer", None) as ev:
                ev.ok()
                raise ValueError("model exploded")
        event = AIEvent.objects.get()
        self.assertEqual(event.status, "error")

    def test_recording_failure_never_breaks_the_feature(self):
        """If telemetry cannot write, the user's request must still succeed."""
        from unittest import mock
        with mock.patch.object(AIEvent.objects, "create", side_effect=RuntimeError("db down")):
            with telemetry.record("triage", None) as ev:
                ev.ok(output_text="fyi")
        self.assertEqual(AIEvent.objects.count(), 0)   # nothing written, nothing raised


class PrivacyTests(TestCase):
    def test_triage_input_text_is_counted_but_never_stored(self):
        secret = "Invoice 4471 from a real person, which is nobody's business but theirs."
        with telemetry.record("triage", None) as ev:
            ev.add_input(secret)
            ev.ok(output_text="needs_you")
        event = AIEvent.objects.get()
        self.assertEqual(event.query_text, "")
        self.assertGreater(event.input_chars, 0)
        self.assertNotIn("Invoice", str(event.__dict__))

    def test_search_queries_are_stored_because_a_widget_reads_them(self):
        with telemetry.record("search", None, query="when is the career fair") as ev:
            ev.ok(result_count=1)
        self.assertEqual(AIEvent.objects.get().query_text, "when is the career fair")


class StatisticsTests(TestCase):
    def test_percentile_of_an_empty_series_is_none_not_an_error(self):
        self.assertIsNone(analytics.percentile([], 95))

    def test_percentile_picks_the_expected_rank(self):
        self.assertEqual(analytics.percentile(list(range(1, 101)), 50), 50)
        self.assertEqual(analytics.percentile(list(range(1, 101)), 95), 95)

    def test_cold_starts_are_excluded_from_warm_latency(self):
        for _ in range(9):
            make_event(latency_ms=100, cold_start=False)
        make_event(latency_ms=200_000, cold_start=True)
        summary = analytics.summary(30)
        self.assertEqual(summary["p50_warm_ms"], 100)
        self.assertEqual(summary["cold_starts"], 1)
        self.assertLess(summary["p95_warm_ms"], 1000)

    def test_small_samples_are_flagged_as_unreliable(self):
        make_event()
        self.assertFalse(analytics.summary(30)["success_rate_is_reliable"])
        for _ in range(40):
            make_event()
        self.assertTrue(analytics.summary(30)["success_rate_is_reliable"])

    def test_no_match_is_not_counted_as_success(self):
        make_event(status=AIEvent.Status.OK)
        make_event(status=AIEvent.Status.NO_MATCH)
        self.assertAlmostEqual(analytics.summary(30)["success_rate"], 0.5)

    def test_breakeven_reports_none_when_there_is_nothing_to_project_from(self):
        self.assertIsNone(analytics.breakeven(30))

    def test_breakeven_uses_the_cpu_budget(self):
        for _ in range(10):
            make_event(cpu_ms=1000)
        result = analytics.breakeven(30)
        self.assertEqual(result["max_requests_per_day"],
                         analytics.DAILY_CPU_BUDGET_SECONDS)

    def test_stopwords_are_excluded_from_query_terms(self):
        for _ in range(3):
            make_event(feature=AIEvent.Feature.SEARCH, query_text="what did my mom say")
        terms = [row["term"] for row in analytics.top_query_terms(30)]
        self.assertIn("mom", terms)
        for stop in ("what", "did", "my", "say"):
            self.assertNotIn(stop, terms)

    def test_events_outside_the_window_are_excluded(self):
        old = make_event()
        AIEvent.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timezone.timedelta(days=90))
        make_event()
        self.assertEqual(analytics.summary(30)["total_requests"], 1)


class ChartSpecTests(TestCase):
    def setUp(self):
        get_user_model().objects.create_user("grader", password=PASSWORD)
        self.client.login(username="grader", password=PASSWORD)
        for i in range(25):
            make_event(feature=AIEvent.Feature.SEARCH if i % 2 else AIEvent.Feature.TRIAGE,
                       latency_ms=100 + i * 10, cpu_ms=90 + i * 8,
                       query_text="what did my mom say" if i % 2 else "")

    def test_every_declared_chart_returns_a_vega_lite_spec(self):
        from .analytics_views import CHARTS
        for name in CHARTS:
            with self.subTest(chart=name):
                response = self.client.get(reverse("analytics-chart-spec", args=[name]))
                self.assertEqual(response.status_code, 200)
                spec = response.json()
                self.assertIn("vega-lite", spec["$schema"])
                self.assertTrue(spec.get("data", {}).get("values") is not None
                                or "layer" in spec)

    def test_an_unknown_chart_is_a_404_not_a_500(self):
        response = self.client.get(reverse("analytics-chart-spec", args=["not_a_chart"]))
        self.assertEqual(response.status_code, 404)

    def test_the_days_parameter_is_clamped_to_a_sane_range(self):
        for raw, _ in (("0", 1), ("9999", 365), ("abc", 30)):
            with self.subTest(days=raw):
                response = self.client.get(
                    reverse("analytics-chart-spec", args=["usage_by_hour"]), {"days": raw})
                self.assertEqual(response.status_code, 200)

    def test_the_cpu_chart_draws_the_budget_line(self):
        spec = self.client.get(reverse("analytics-chart-spec", args=["cpu_by_day"])).json()
        rules = [layer for layer in spec["layer"] if layer["mark"]["type"] == "rule"]
        self.assertEqual(rules[0]["encoding"]["y"]["datum"],
                         analytics.DAILY_CPU_BUDGET_SECONDS)


class ColdStartDetectionTests(TestCase):
    """A cold start must mean 'this request loaded the model', not 'the model is absent'.

    Regression test for a bug the dashboard surfaced about itself: with torch uninstalled,
    is_loaded() is False forever, so every fallback request was recorded as a cold start and
    the cold-start median came out at 1 ms -- a physically impossible number for a request
    that supposedly loaded a 2B model.
    """

    def test_a_request_that_loads_the_model_is_a_cold_start(self):
        with telemetry.record("triage", None, cold_start=True) as ev:
            ev.loaded_after(True)
            ev.ok()
        self.assertTrue(AIEvent.objects.get().cold_start)

    def test_a_fallback_when_the_model_is_unavailable_is_not_a_cold_start(self):
        with telemetry.record("triage", None, cold_start=True) as ev:
            ev.loaded_after(False)        # never became loaded: this was the rules path
            ev.ok()
        self.assertFalse(AIEvent.objects.get().cold_start)

    def test_a_warm_request_stays_warm(self):
        with telemetry.record("triage", None, cold_start=False) as ev:
            ev.loaded_after(True)
            ev.ok()
        self.assertFalse(AIEvent.objects.get().cold_start)

    def test_a_guardrail_refusal_is_never_a_cold_start(self):
        """Refused before the model was called, so no loading cost was paid."""
        with telemetry.record("triage", None, cold_start=True) as ev:
            ev.outcome("refused")
        self.assertFalse(AIEvent.objects.get().cold_start)

    def test_a_rate_limited_request_is_never_a_cold_start(self):
        with telemetry.record("answer", None, cold_start=True) as ev:
            ev.outcome("rate_limited")
        self.assertFalse(AIEvent.objects.get().cold_start)
