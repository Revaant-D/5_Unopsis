"""
Assignment 6, Part 2: the two AI features as Django views.

    /ai/                        ai-lab           GET the AI lab; POST triages pasted text with
                                                 the LOCAL Hugging Face model (feature 1)
    /ai/briefs/<pk>/write/      ai-brief-write   POST runs the HYBRID pipeline on one of your
                                                 briefs: local model filters, Groq writes (feature 2)
    /ai/search/                 ai-search        Assignment 9: GET ?q= searches your messages by
                                                 meaning (sentence-transformers); &ask=1 also
                                                 answers from the results with the local model
    /search/                    app-search       the same search inside the product (app shell):
                                                 results open the thread that cites them, the
                                                 answer's [n] citations jump to the results

Both are login-only, and the brief route goes through owned_briefs(), so nobody can spend the
team's API quota on -- or read -- another account's messages. Each account is also limited to
settings.AI_REQUESTS_PER_MINUTE model runs per minute: generation is the most expensive thing
this site does, and the external API is billed (or rate-limited) per call.
"""

import re
import time

from django import forms
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST

from . import ui
from .ai import ask, groq_client, guardrails, local_llm, pipeline, semantic_search
from .ai import warmup  # noqa: F401  (connects the login receiver that pre-builds the search index)
from .models import BriefItem
from .views import owned_briefs


class TriageForm(forms.Form):
    text = forms.CharField(
        label="A message to triage",
        min_length=3,
        max_length=guardrails.MAX_INPUT_CHARS,
        strip=True,
        widget=forms.Textarea(attrs={
            "rows": 4, "class": "form-control",
            "placeholder": "e.g. Invoice #4471 is 14 days overdue. Please approve payment.",
        }),
    )


def _over_limit(user):
    """True if `user` has used up this minute's AI runs. Counts the current run."""
    limit = getattr(settings, "AI_REQUESTS_PER_MINUTE", 10)
    key = f"ai-rate:{user.pk}:{int(time.time() // 60)}"
    cache.add(key, 0, timeout=120)
    try:
        count = cache.incr(key)
    except ValueError:  # the key expired between add and incr
        cache.set(key, 1, timeout=120)
        count = 1
    return count > limit


def _status():
    return {
        "local_model": local_llm.model_name(),
        "local_enabled": getattr(settings, "AI_LOCAL_ENABLED", True),
        "local_loaded": local_llm.is_loaded(),
        "groq_configured": groq_client.is_configured(),
        "groq_model": getattr(settings, "GROQ_MODEL", ""),
        "shots": getattr(settings, "AI_TRIAGE_SHOTS", 0),
        "max_messages": getattr(settings, "AI_PIPELINE_MAX_MESSAGES", 6),
        "embed_model": semantic_search.model_name(),
        "embed_loaded": semantic_search.is_loaded(),
        "search_enabled": getattr(settings, "AI_SEARCH_ENABLED", True),
        "top_k": getattr(settings, "AI_SEARCH_TOP_K", 5),
        "min_score": getattr(settings, "AI_SEARCH_MIN_SCORE", 0.25),
    }


@login_required
def ai_lab(request):
    """Feature 1: triage one message with the local model, plus the list of briefs to write."""
    form = TriageForm(request.POST or None)
    result, refused, status_code = None, [], 200
    if request.method == "POST":
        if _over_limit(request.user):
            form.add_error(None, "Too many AI requests this minute. Wait a moment and try again.")
            status_code = 429
        elif form.is_valid():
            cleaned = guardrails.clean_message_text(form.cleaned_data["text"])
            refused = guardrails.find_injection(cleaned)
            if refused:
                status_code = 400
            else:
                result = local_llm.triage(cleaned)
                result["cleaned"] = cleaned
        else:
            status_code = 400
    context = {
        "form": form,
        "result": result,
        "refused": refused,
        "status": _status(),
        "briefs": owned_briefs(request.user).select_related("space").order_by("-window_end")[:10],
    }
    return render(request, "unopsis/ai_lab.html", context, status=status_code)


@login_required
@require_POST
def ai_brief_write(request, pk):
    """Feature 2: the hybrid pipeline for one of the user's own briefs."""
    brief = get_object_or_404(owned_briefs(request.user).select_related("space"), pk=pk)
    if _over_limit(request.user):
        return render(request, "unopsis/ai_brief.html",
                      {"brief": brief, "limited": True, "status": _status()}, status=429)
    outcome = pipeline.run_hybrid_brief(brief)
    return render(request, "unopsis/ai_brief.html",
                  {"brief": brief, "outcome": outcome, "status": _status()})


class SearchForm(forms.Form):
    q = forms.CharField(
        label="Search your messages", required=False, strip=True,
        max_length=semantic_search.MAX_QUERY_CHARS,
        widget=forms.TextInput(attrs={
            "class": "form-control", "autofocus": True,
            "placeholder": "e.g. what did my mom say?  /  is the staging deploy fixed?",
        }),
    )
    ask = forms.BooleanField(
        label="Also answer with the local model (slow on a laptop CPU)", required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )


@login_required
def ai_search(request):
    """
    Assignment 9: semantic search over the signed-in user's own messages, plus an optional
    grounded answer from the local model (RAG). GET, so a search is a shareable URL and the
    back button works; only the opt-in answer counts against the per-minute AI limit.
    """
    form = SearchForm(request.GET or None)
    context = {"form": form, "status": _status()}
    found, status_code = _search_and_answer(request, form)
    context.update(found)
    return render(request, "unopsis/ai_search.html", context, status=status_code)


def _search_and_answer(request, form):
    """
    The search + optional answer step shared by /ai/search/ and /search/. Returns
    ({"outcome", "answer", "error"}, http_status). Only the opt-in answer counts against the
    per-minute AI limit; the search itself is cheap.
    """
    found = {"outcome": None, "answer": None, "error": ""}
    params = {k: v for k, v in request.GET.items() if k in form.fields}
    if not params:
        return found, 200                       # first visit: just the form
    if not form.is_valid():
        return found, 400
    if not form.cleaned_data["q"]:
        found["error"] = "Type a few words to search for."
        return found, 400
    try:
        outcome = semantic_search.search(request.user, form.cleaned_data["q"])
    except semantic_search.InvalidQuery as exc:
        found["error"] = str(exc)
        return found, 400
    found["outcome"] = outcome
    if form.cleaned_data["ask"]:
        if _over_limit(request.user):
            found["answer"] = {"status": "limited", "note":
                               "Too many AI requests this minute. Wait a moment and try again."}
            return found, 429
        found["answer"] = ask.answer_question(outcome["cleaned"], outcome["results"])
    return found, 200


# ---------------------------------------------------------------------- /search/ (the product)

EXAMPLE_QUERIES = ["what did my mom say?", "is the staging deploy fixed?", "when is grandma's dinner?"]

# Plain-language versions of ask.answer_question()'s statuses, for the product page.
ANSWER_NOTES = {
    "no_context": "Nothing in your messages matched, so there was nothing to answer from.",
    "refused": "That question looks like an attempt to give the assistant instructions, so it wasn't answered.",
    "unavailable": "The answer assistant isn't available on this computer right now. The matching messages are below.",
    "failed": "The assistant couldn't write an answer this time. The matching messages are below.",
    "timeout": "The assistant took too long and was stopped. The matching messages are below.",
    "limited": "Too many answers this minute. Wait a moment and try again.",
    "uncited": "This answer doesn't point to a specific message, so check it against the results below.",
    "not_found": "Your messages don't say. The closest matches are below.",
}

_CITATION = re.compile(r"\[(\d{1,2})\]")


def _linked_answer(text, result_count):
    """Escape the answer, then turn each [n] that points at a shown result into a jump link."""
    def link(match):
        n = int(match.group(1))
        if 1 <= n <= result_count:
            return f'<a class="cite" href="#r{n}" aria-label="Source {n}">[{n}]</a>'
        return match.group(0)
    return mark_safe(_CITATION.sub(link, escape(text)))


def _attach_threads(rows):
    """
    For each result, the brief item that cites its message (newest brief first), so the page can
    link to that thread. One query for all results, not one per result.
    """
    ids = [row["id"] for row in rows]
    if not ids:
        return rows
    first_item = {}
    items = (BriefItem.objects.filter(messages__id__in=ids)
             .select_related("brief__space")
             .prefetch_related("messages")
             .order_by("-brief__window_end", "rank"))
    for item in items:
        for message in item.messages.all():
            first_item.setdefault(message.pk, item)
    for row in rows:
        item = first_item.get(row["id"])
        row["item"] = item
        row["thread_url"] = None
        if item is not None:
            url = reverse("app-thread", args=[item.brief.space.kind, item.pk])
            # The thread hides noise messages unless asked; show them if that's what was found.
            row["thread_url"] = url + ("?show=all" if row.get("noise") else "")
        row["world"] = row["message"].connection.space.get_kind_display()
        row["strength"] = _strength(row.get("score"))
    return rows


def _strength(score):
    """A word for the similarity score: users read "39%" as a bad match, which it isn't."""
    if score is None:
        return ""
    if score >= 0.5:
        return "Strong match"
    if score >= 0.35:
        return "Good match"
    return "Possible match"


@login_required
def app_search(request):
    """
    /search/: semantic search inside the product. Same engine and guardrails as /ai/search/,
    presented in the app shell with the left rail: each result links to the thread that cites
    it, and the answer's [n] citations jump to the matching result.
    """
    world = request.GET.get("world")
    kind = world if world in ("work", "personal") else "work"
    space = ui.current_space(kind, request.user)
    brief = ui.latest_brief(space)
    form = SearchForm(request.GET or None)
    found, status_code = _search_and_answer(request, form)

    outcome, answer = found["outcome"], found["answer"]
    if outcome:
        _attach_threads(outcome["results"])
    if answer is not None:
        answer = {**answer, "plain_note": ANSWER_NOTES.get(answer.get("status"), "")}
        if answer.get("answer"):
            shown = len(outcome["results"]) if outcome else 0
            answer["html"] = _linked_answer(answer["answer"], shown)

    context = {
        "active": "search",
        "brief": brief,
        **ui.sidebar_context(kind, space, brief, timezone.now()),
        "form": form,
        "q": form.cleaned_data.get("q", "") if form.is_bound and form.is_valid() else request.GET.get("q", ""),
        "outcome": outcome,
        "answer": answer,
        "error": found["error"],
        "examples": EXAMPLE_QUERIES,
        "status": _status(),
    }
    return render(request, "unopsis/app/search.html", context, status=status_code)
