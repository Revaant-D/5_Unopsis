"""
Assignment 6, Part 2: the two AI features as Django views.

    /ai/                        ai-lab           GET the AI lab; POST triages pasted text with
                                                 the LOCAL Hugging Face model (feature 1)
    /ai/briefs/<pk>/write/      ai-brief-write   POST runs the HYBRID pipeline on one of your
                                                 briefs: local model filters, Groq writes (feature 2)
    /ai/search/                 ai-search        Assignment 9: GET ?q= searches your messages by
                                                 meaning (sentence-transformers); &ask=1 also
                                                 answers from the results with the local model

Both are login-only, and the brief route goes through owned_briefs(), so nobody can spend the
team's API quota on -- or read -- another account's messages. Each account is also limited to
settings.AI_REQUESTS_PER_MINUTE model runs per minute: generation is the most expensive thing
this site does, and the external API is billed (or rate-limited) per call.
"""

import time

from django import forms
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from .ai import ask, groq_client, guardrails, local_llm, pipeline, semantic_search
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
    context = {"form": form, "status": _status(), "outcome": None, "answer": None, "error": ""}
    status_code = 200
    if request.GET and form.is_valid() and form.cleaned_data["q"]:
        try:
            outcome = semantic_search.search(request.user, form.cleaned_data["q"])
        except semantic_search.InvalidQuery as exc:
            context["error"], status_code = str(exc), 400
        else:
            context["outcome"] = outcome
            if form.cleaned_data["ask"]:
                if _over_limit(request.user):
                    context["answer"] = {"status": "limited", "note":
                                         "Too many AI requests this minute. Wait a moment and try again."}
                    status_code = 429
                else:
                    context["answer"] = ask.answer_question(outcome["cleaned"], outcome["results"])
    elif request.GET and form.is_valid():
        context["error"], status_code = "Type a few words to search for.", 400
    elif request.GET:
        status_code = 400
    return render(request, "unopsis/ai_search.html", context, status=status_code)
