"""
Assignment 9: answer a question about your messages, grounded in what search retrieved (RAG).

    question ─▶ semantic_search.search() ─▶ top AI_ANSWER_CONTEXT messages
             ─▶ prompts.build_answer_messages() ─▶ local model (local_llm.generate)
             ─▶ validate: non-empty, citations point at real messages ─▶ answer + sources

It reuses the A6/A7 local generation model, so no external API is involved. On a laptop CPU an
answer takes about as long as one triage (tens of seconds), which is why it is opt-in on the
search page ("Also answer with the local model"), while the search itself is instant.

Guardrails, in order:
  * no retrieved messages        -> no model call; "nothing to answer from"
  * prompt-injection question    -> refused, no model call
  * model missing / error        -> the retrieved messages are still shown, with the reason
  * time limit                   -> generate(max_seconds=...) stops a slow CPU, and an answer
                                    that ran into the limit is reported ("timeout"), not shown
  * empty output                 -> reported as a failure, not shown as an answer
  * "couldn't find" + a cited fact -> the cited fact is shown, with a note (seen in A8);
                                    with no valid citation the not-found answer stands
  * citations [n] outside 1..N   -> dropped; an answer with no valid citation is flagged
"""

import re
import time

from django.conf import settings

from . import guardrails, local_llm, prompts

_CITE = re.compile(r"\[(\d{1,2})\]")
# The not-found sentence, matched loosely: any case, curly or straight apostrophe, optional period.
_NOT_FOUND = re.compile(
    re.escape(prompts.NOT_FOUND_ANSWER.rstrip(".")).replace("'", "['’]") + r"\.?", re.IGNORECASE)
MAX_ANSWER_CHARS = 500


def answer_question(question, rows):
    """
    Returns {"status", "answer", "cited", "note", "raw", "ms", "model"} where status is one of
    ok | uncited | not_found | no_context | refused | unavailable | failed | timeout.
    """
    out = {"answer": "", "cited": [], "note": "", "raw": "", "ms": 0, "model": local_llm.model_name()}
    if not rows:
        return {**out, "status": "no_context",
                "note": "Search found no matching messages, so there is nothing to answer from."}
    reasons = guardrails.find_injection(question)
    if reasons:
        return {**out, "status": "refused",
                "note": "Not sent to the model: the question looks like a prompt-injection attempt ("
                        + "; ".join(reasons) + ")."}

    context = rows[:getattr(settings, "AI_ANSWER_CONTEXT", 3)]
    limit = getattr(settings, "AI_LOCAL_MAX_SECONDS", 90)
    started = time.perf_counter()
    try:
        raw = local_llm.generate(prompts.build_answer_messages(question, context),
                                 max_new_tokens=100, max_seconds=limit)
    except local_llm.LocalModelUnavailable as exc:
        return {**out, "status": "unavailable", "note": str(exc),
                "ms": int((time.perf_counter() - started) * 1000)}
    except Exception as exc:  # never a 500 for a model problem
        return {**out, "status": "failed", "note": f"Local model error: {exc}",
                "ms": int((time.perf_counter() - started) * 1000)}
    ms = int((time.perf_counter() - started) * 1000)
    answer = " ".join((raw or "").split())

    if not answer:
        return {**out, "status": "failed", "raw": raw, "ms": ms,
                "note": "The model returned an empty answer (it may have hit the time limit)."}
    if ms >= limit * 1000:
        # transformers' max_time stops mid-sentence and returns what it has. A half-finished
        # answer can read as a confident one, so it is reported, not shown.
        return {**out, "status": "timeout", "raw": raw, "ms": ms,
                "note": f"The local model hit the {limit} s time limit, so its unfinished answer "
                        "is not shown. The search results below are still correct."}
    hedge = ""
    if _NOT_FOUND.search(answer):
        # The model said the not-found sentence. Usually that IS the whole answer. But A8 caught
        # Granite writing "NOT IN CONTEXT. ... a fourteen day refund ..." -- the abstention
        # phrase followed by the correct, sourced fact. So: if what remains cites a retrieved
        # message, show it (with a note); otherwise the not-found answer stands. An uncited
        # remainder is not shown, because nothing on the page could back it up.
        rest = " ".join(_NOT_FOUND.sub(" ", answer).split())
        if not any(1 <= int(n) <= len(context) for n in _CITE.findall(rest)):
            return {**out, "status": "not_found", "answer": prompts.NOT_FOUND_ANSWER, "raw": raw, "ms": ms}
        answer = rest.lstrip(" .,;:-") or rest
        hedge = ("The model also said it couldn't find this, then answered from the cited "
                 "message. Check the answer against it below.")

    numbers = [int(n) for n in _CITE.findall(answer)]
    valid = sorted({n for n in numbers if 1 <= n <= len(context)})
    # Remove citations that point at nothing, so the page never links a message that wasn't used.
    answer = _CITE.sub(lambda m: m.group(0) if 1 <= int(m.group(1)) <= len(context) else "", answer)
    if len(answer) > MAX_ANSWER_CHARS:
        answer = answer[:MAX_ANSWER_CHARS].rsplit(" ", 1)[0] + "..."
    cited = [{"n": n, **context[n - 1]} for n in valid]
    status, note = "ok", hedge
    if not valid:
        status = "uncited"
        note = "The answer cites none of the retrieved messages, so check it against them below."
    return {**out, "status": status, "answer": answer.strip(), "cited": cited, "note": note,
            "raw": raw, "ms": ms}
