"""
The hybrid pipeline: the local model filters and labels, the external API writes.

    1. gather     the brief's window of messages from its Space (at most AI_PIPELINE_MAX_MESSAGES)
    2. prefilter  drop messages ingest already marked is_noise           (free, no model)
    3. screen     clean every body; hold back anything that looks like
                  prompt injection for a human, never forward it          (free, no model)
    4. triage     local Hugging Face model: lane + 15-word summary       (local CPU/GPU, $0)
                  noise is dropped here
    5. write      Groq turns the short, triaged list into the brief      (external API, paid
                  prose                                                   per token)
    6. validate   the JSON answer is checked; a template writer stands in
                  if Groq is unavailable or its answer does not validate

Why this order saves money: the external API never sees raw message bodies, promotions or
duplicates -- only one short line per message that survived triage. On the demo data the
prompt sent to Groq is a few hundred tokens instead of the full text of every message, and
the cheap local model does the per-message work that scales with inbox size.

Privacy follows from the same order: bodies are cleaned (e-mail addresses, phone numbers and
links replaced) before any model sees them, and only the local model sees them at all.
"""

import time

from django.conf import settings

from ..models import BriefItem, Message
from . import groq_client, guardrails, local_llm, prompts

LANE_ORDER = {"needs_you": 0, "moving": 1, "fyi": 2, "noise": 3}


def _step(steps, label, started, status="done", detail=""):
    steps.append({
        "label": label, "status": status, "detail": detail,
        "ms": int((time.perf_counter() - started) * 1000),
    })


def template_brief(rows):
    """The deterministic writer used when Groq cannot be: correct, plain, never invented."""
    needs = [r for r in rows if r["lane"] == "needs_you"]
    moving = [r for r in rows if r["lane"] == "moving"]
    fyi = [r for r in rows if r["lane"] == "fyi"]
    if not needs:
        headline = "Nothing needs you right now."
    elif len(needs) == 1:
        headline = "One thing needs you."
    else:
        headline = f"{len(needs)} things need you."
    parts = []
    for r in needs:
        due = f" (deadline: {r['deadline']})" if r.get("deadline") else ""
        parts.append(f"{r['who']}: {r['summary']}{due}")
    if moving:
        parts.append("Moving without you: " + "; ".join(f"{r['who']} -- {r['summary']}" for r in moving))
    if fyi:
        parts.append(f"Also, {len(fyi)} FYI message{'s' if len(fyi) != 1 else ''}, nothing to do.")
    return {"headline": headline, "body": " ".join(parts) or "No messages in this window."}


def window_messages(brief):
    """The messages in the brief's Space and time window, newest first, capped."""
    limit = getattr(settings, "AI_PIPELINE_MAX_MESSAGES", 6)
    return list(
        Message.objects.filter(
            connection__space=brief.space,
            sent_at__gte=brief.window_start,
            sent_at__lte=brief.window_end,
        )
        .select_related("author", "connection")
        .order_by("-sent_at")[:limit]
    )


def run_hybrid_brief(brief):
    """
    Run the pipeline for one Brief (already checked to belong to the requesting user).
    Returns a dict the template renders; never raises for model or network problems.
    """
    steps, rows, held = [], [], []
    total = time.perf_counter()

    t = time.perf_counter()
    messages = window_messages(brief)
    _step(steps, f"Gathered {len(messages)} messages from the window", t)

    t = time.perf_counter()
    kept = [m for m in messages if not m.is_noise]
    _step(steps, f"Prefilter dropped {len(messages) - len(kept)} already-flagged noise", t)

    t = time.perf_counter()
    screened = []
    for m in kept:
        cleaned = guardrails.clean_message_text(m.body)
        reasons = guardrails.find_injection(cleaned)
        if reasons:
            held.append({"who": m.author.display_name, "reasons": reasons, "text": cleaned})
        else:
            screened.append((m, cleaned))
    _step(steps, f"Screened for prompt injection: {len(held)} held for review", t)

    t = time.perf_counter()
    sources = {"local": 0, "rules": 0}
    dropped_noise = 0
    for m, cleaned in screened:
        result = local_llm.triage(cleaned)
        sources[result["source"]] += 1
        if result["lane"] == "noise":
            dropped_noise += 1
            continue
        rows.append({
            "lane": result["lane"], "summary": result["summary"], "deadline": result["deadline"],
            "who": m.author.display_name,
            "where": f"{m.connection.get_provider_display()}"
                     + (f" {m.scope_name}" if m.scope_name else ""),
            "source": result["source"],
        })
    rows.sort(key=lambda r: LANE_ORDER[r["lane"]])
    triage_label = (
        f"Local model ({local_llm.model_name()}) triaged {sources['local']}"
        + (f", rules triaged {sources['rules']}" if sources["rules"] else "")
        + f"; {dropped_noise} more dropped as noise"
    )
    _step(steps, triage_label, t, status="done" if sources["local"] else "fallback")

    t = time.perf_counter()
    writer, note, usage = "groq", "", {}
    draft = None
    if rows:
        try:
            reply = groq_client.chat(prompts.build_brief_messages(rows, brief.space.get_kind_display()))
            usage = reply["usage"]
            draft = guardrails.validate_brief(guardrails.parse_json_object(reply["text"]))
            if draft is None:
                note = "Groq's answer was not valid brief JSON, so the template writer was used."
        except groq_client.GroqUnavailable as exc:
            note = str(exc)
    else:
        note = "Nothing survived triage, so there was nothing to send to the API."
    if draft is None:
        draft, writer = template_brief(rows), "template"
    _step(steps, "Brief written by " + ("Groq" if writer == "groq" else "the template writer"),
          t, status="done" if writer == "groq" else "fallback", detail=note)

    return {
        "draft": draft,
        "rows": rows,
        "held": held,
        "steps": steps,
        "writer": writer,
        "writer_note": note,
        "usage": usage,
        "groq_model": getattr(settings, "GROQ_MODEL", ""),
        "local_model": local_llm.model_name(),
        "total_ms": int((time.perf_counter() - total) * 1000),
        "lanes": dict(BriefItem.Lane.choices) | {"noise": "Noise"},
    }
