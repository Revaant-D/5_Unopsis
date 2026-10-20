"""
The external API (AI feature 2: writing the brief) -- Groq.

Groq serves open models behind an OpenAI-compatible Chat Completions endpoint, has a free tier
that needs no card, and is among the fastest hosted inference services. The default model is
openai/gpt-oss-20b (settings.GROQ_MODEL). It is a reasoning model, so the request asks for
low reasoning effort and leaves the reasoning out of the response.

It is called with plain `requests` (already a project dependency) rather than an SDK, the same
way views.py calls Nager.Date: one function, a timeout, and two failure types.

The key lives in .env as GROQ_API_KEY and is read through settings; it is never logged, put in
a template, or committed. Create one at https://console.groq.com/keys.
"""

import time

import requests
from django.conf import settings

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqUnavailable(Exception):
    """No API key, a network failure, a non-2xx answer, or a response without content."""


def is_configured():
    return bool(getattr(settings, "GROQ_API_KEY", ""))


def chat(messages, max_tokens=600, temperature=0.3):
    """
    Send one chat to Groq and return {"text", "model", "usage", "ms"}.

    Raises GroqUnavailable for everything that can go wrong, so callers handle one exception.
    """
    if not is_configured():
        raise GroqUnavailable("GROQ_API_KEY is not set in .env.")
    model = getattr(settings, "GROQ_MODEL", "openai/gpt-oss-20b")
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if model.startswith("openai/gpt-oss"):
        payload["reasoning_effort"] = "low"
        payload["include_reasoning"] = False

    started = time.perf_counter()
    try:
        response = requests.post(
            GROQ_CHAT_URL,
            json=payload,
            headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
            timeout=getattr(settings, "GROQ_TIMEOUT_SECONDS", 20),
        )
    except requests.exceptions.RequestException as exc:
        raise GroqUnavailable(f"Could not reach Groq: {exc.__class__.__name__}") from exc

    if response.status_code == 429:
        raise GroqUnavailable("Groq rate limit reached (free tier). Try again in a minute.")
    if response.status_code >= 400:
        # The body may echo the request; only the status goes into the message.
        raise GroqUnavailable(f"Groq answered HTTP {response.status_code}.")
    try:
        data = response.json()
        text = data["choices"][0]["message"]["content"] or ""
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise GroqUnavailable("Groq returned an unexpected response.") from exc
    if not text.strip():
        raise GroqUnavailable("Groq returned an empty answer.")
    return {
        "text": text,
        "model": data.get("model", model),
        "usage": data.get("usage", {}),
        "ms": int((time.perf_counter() - started) * 1000),
    }
