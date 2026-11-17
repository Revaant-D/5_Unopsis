"""
Recording side of the analytics dashboard: one AIEvent per AI request.

Used as a context manager so the measurement cannot be forgotten on an error path -- the row
is written in `finally`, which means a request that raises is still counted. A dashboard that
only records successes would show a system that never fails, which is precisely the opposite
of what it is for.

    with telemetry.record("search", user, query="who messaged me") as ev:
        rows = semantic_search.search(user, q)
        ev.ok(result_count=len(rows), top_score=rows[0]["score"] if rows else None)

Recording must never break the feature it measures. Every write is wrapped: if telemetry
fails, the user's request still succeeds and the failure is logged, because losing a metric
is a much smaller problem than losing the answer the user asked for.
"""

import logging
import time

logger = logging.getLogger(__name__)

# Rough token estimate. The local pipeline returns no usage counts, so the dashboard labels
# every token figure "est." rather than implying a precision we do not have.
CHARS_PER_TOKEN = 4


def estimate_tokens(text):
    return max(0, len(text or "")) // CHARS_PER_TOKEN


class _Recorder:
    def __init__(self, feature, user, query="", model_name="", cold_start=False):
        self.feature = feature
        self.user = user if getattr(user, "is_authenticated", False) else None
        self.query = (query or "")[:160]
        self.model_name = model_name or ""
        self.cold_start = cold_start
        self.status = "ok"
        self.input_chars = len(query or "")
        self.input_tokens = estimate_tokens(query)
        self.output_tokens = 0
        self.result_count = 0
        self.top_score = None
        self._t0 = None
        self._c0 = None

    # --- outcome setters, called by the view once it knows what happened ---------------
    def ok(self, output_text="", result_count=0, top_score=None):
        self.status = "ok"
        self.output_tokens = estimate_tokens(output_text)
        self.result_count = result_count
        self.top_score = top_score
        return self

    # Outcomes reached WITHOUT invoking the model. A request refused by the guardrails or
    # turned away by the rate limiter never touched the model, so it cannot have paid a
    # model-loading cost no matter what is_loaded() said beforehand.
    NO_MODEL_CALL = {"refused", "rate_limited"}

    def outcome(self, status, **kw):
        self.status = status
        if status in self.NO_MODEL_CALL:
            self.cold_start = False
        for k, v in kw.items():
            setattr(self, k, v)
        return self

    def loaded_after(self, is_loaded_now):
        """Confirm a cold start actually happened.

        `cold_start` is provisionally True when the model was not in memory before the call.
        That is not sufficient: if the model is unavailable entirely (no torch installed, or
        generation disabled) it is never loaded, so every request would look like a cold
        start while actually being a 1 ms fallback to the rule-based path. A cold start is
        only real if the model was absent BEFORE and present AFTER.
        """
        self.cold_start = bool(self.cold_start and is_loaded_now)
        return self

    def add_input(self, text):
        """Count input the view did not pass to the constructor (e.g. triage body).

        The TEXT is counted but never stored -- see the AIEvent docstring on why triage
        content stays out of the telemetry table.
        """
        self.input_chars += len(text or "")
        self.input_tokens += estimate_tokens(text)
        return self


class record:
    def __init__(self, feature, user, query="", model_name="", cold_start=False):
        self.rec = _Recorder(feature, user, query, model_name, cold_start)

    def __enter__(self):
        self.rec._t0 = time.perf_counter()
        self.rec._c0 = time.process_time()
        return self.rec

    def __exit__(self, exc_type, exc, tb):
        r = self.rec
        latency_ms = int((time.perf_counter() - r._t0) * 1000)
        cpu_ms = int((time.process_time() - r._c0) * 1000)
        if exc_type is not None and r.status == "ok":
            r.status = "error"
        try:
            from ..models import AIEvent
            AIEvent.objects.create(
                user=r.user, feature=r.feature, status=r.status, model_name=r.model_name,
                latency_ms=latency_ms, cpu_ms=cpu_ms, cold_start=r.cold_start,
                input_chars=r.input_chars, input_tokens_est=r.input_tokens,
                output_tokens_est=r.output_tokens,
                query_text=r.query if r.feature == "search" else "",
                result_count=r.result_count, top_score=r.top_score, simulated=False,
            )
        except Exception:                                    # never break the feature
            logger.exception("AIEvent could not be written for feature=%s", r.feature)
        return False                                         # never swallow the real error
