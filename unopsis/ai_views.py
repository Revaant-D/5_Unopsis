"""
Assignment 6, Part 2: the two AI features as Django views.

    /ai/                        ai-lab           GET the AI lab; POST triages pasted text with
                                                 the LOCAL Hugging Face model (feature 1)
    /ai/briefs/<pk>/write/      ai-brief-write   POST runs the HYBRID pipeline on one of your
                                                 briefs: local model filters, Groq writes (feature 2)

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

from .ai import groq_client, guardrails, local_llm, pipeline
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
