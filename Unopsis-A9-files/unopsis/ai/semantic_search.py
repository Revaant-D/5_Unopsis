"""
Assignment 9: semantic search over the user's own messages ("search by meaning").

    query ──clean──▶ embed (sentence-transformers) ──cosine──▶ top-k messages ──▶ page
                                                    ▲
    the user's messages ──clean + add context──▶ embed once, cached per user ──┘

Why this feature: a brief tells you what needs you today; search answers "what did Lena say
about the flights?" a week later. Keyword search misses that (the message says "$180 rt", not
"flight price"); an embedding model matches on meaning.

The model is settings.AI_EMBED_MODEL (default sentence-transformers/all-MiniLM-L6-v2: 384
dimensions, 22M parameters, ~90 MB, a few milliseconds per message on a laptop CPU). Like the
triage model it is loaded lazily and downloaded into the Hugging Face cache on first use, never
into the repository.

Two choices the A9 evaluation tested (docs/a9/evaluation_results.md, "before vs after"):

* CONTEXT. Each message is embedded as "From Mom (WhatsApp, Family): did you eat" rather than
  the bare body, so "what did my mom say" can match a message that never mentions mom.
  settings.AI_SEARCH_INCLUDE_CONTEXT.
* THRESHOLD. Results below settings.AI_SEARCH_MIN_SCORE cosine similarity are dropped, so an
  unrelated query ("pizza recipe") returns "nothing found" instead of five random messages.

Index: one numpy matrix per (user, model, context setting), held in memory and rebuilt when
the user's message count or newest id changes. Fine for the prototype's hundreds of messages;
README_AI.md describes moving it to a vector store (pgvector) at scale.

Guardrails: empty/too-short/too-long queries are rejected before any model runs; if
sentence-transformers is missing or the model cannot load, search falls back to keyword
matching and says so on the page instead of failing.
"""

import re
import threading
import time

from django.conf import settings

from . import guardrails

MIN_QUERY_CHARS = 2
MAX_QUERY_CHARS = 300


class SearchUnavailable(Exception):
    """sentence-transformers is not installed, search is switched off, or the model failed to load."""


class InvalidQuery(ValueError):
    """The query is empty, too short or too long."""


_lock = threading.Lock()
_model = {}   # {"name": str, "model": SentenceTransformer}
_index = {}   # {(user_id, model, include_context): {"signature", "ids", "vectors", "ms"}}


def model_name():
    return getattr(settings, "AI_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")


def is_loaded():
    return bool(_model)


def _load():
    if not getattr(settings, "AI_SEARCH_ENABLED", True):
        raise SearchUnavailable("Semantic search is switched off (AI_SEARCH_ENABLED=False).")
    if _model:
        return _model["model"]
    with _lock:
        if _model:
            return _model["model"]
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise SearchUnavailable(
                "sentence-transformers is not installed (pip install -r requirements.txt)."
            ) from exc
        try:
            model = SentenceTransformer(model_name())
        except Exception as exc:  # network down on first download, wrong name...
            raise SearchUnavailable(f"Could not load {model_name()}: {exc}") from exc
        _model.update(name=model_name(), model=model)
        return model


def encode(texts):
    """Unit-length embeddings (numpy float32, one row per text), so a dot product is cosine."""
    import numpy as np

    model = _load()
    vectors = model.encode(list(texts), batch_size=32, normalize_embeddings=True,
                           convert_to_numpy=True, show_progress_bar=False)
    return np.asarray(vectors, dtype="float32")


def clean_query(query):
    """The cleaned query, or InvalidQuery with a message the page can show."""
    cleaned = guardrails.clean_message_text(query or "", max_chars=MAX_QUERY_CHARS + 50)
    if len(cleaned) < MIN_QUERY_CHARS:
        raise InvalidQuery("Type a few words to search for.")
    if len((query or "").strip()) > MAX_QUERY_CHARS:
        raise InvalidQuery(f"Keep the search under {MAX_QUERY_CHARS} characters.")
    return cleaned


def document_text(message, include_context=None):
    """What gets embedded for one message: cleaned body, optionally prefixed with who/where."""
    if include_context is None:
        include_context = getattr(settings, "AI_SEARCH_INCLUDE_CONTEXT", True)
    body = guardrails.clean_message_text(message.body)
    if not include_context:
        return body
    where = message.connection.get_provider_display()
    if message.scope_name:
        where += f", {message.scope_name}"
    return f"From {message.author.display_name} ({where}): {body}"


def _messages(user):
    from ..views import owned_messages

    limit = getattr(settings, "AI_SEARCH_MAX_MESSAGES", 2000)
    return list(owned_messages(user).select_related("author", "connection")
                .order_by("-sent_at")[:limit])


def build_index(user, include_context=None):
    """The (cached) index for `user`: {"ids", "vectors", "messages", "ms", "rebuilt"}."""
    if include_context is None:
        include_context = getattr(settings, "AI_SEARCH_INCLUDE_CONTEXT", True)
    messages = _messages(user)
    signature = (len(messages), max((m.pk for m in messages), default=0))
    key = (user.pk, model_name(), include_context)
    cached = _index.get(key)
    by_id = {m.pk: m for m in messages}
    if cached and cached["signature"] == signature:
        return {**cached, "messages": by_id, "rebuilt": False}
    started = time.perf_counter()
    vectors = encode([document_text(m, include_context) for m in messages]) if messages else None
    entry = {"signature": signature, "ids": [m.pk for m in messages], "vectors": vectors,
             "ms": int((time.perf_counter() - started) * 1000)}
    _index[key] = entry
    return {**entry, "messages": by_id, "rebuilt": True}


def _row(message, score):
    where = message.connection.get_provider_display()
    if message.scope_name:
        where += f" · {message.scope_name}"
    return {"message": message, "id": message.pk, "external_id": message.external_id,
            "score": None if score is None else round(float(score), 3),
            "who": message.author.display_name, "where": where,
            "text": guardrails.clean_message_text(message.body), "noise": message.is_noise}


_WORD = re.compile(r"[a-z0-9$#]+")
_STOP = {"the", "a", "an", "is", "are", "was", "what", "who", "about", "any", "anything", "did",
         "do", "does", "i", "me", "my", "to", "of", "for", "in", "on", "and", "or", "with", "say",
         "said", "when", "where", "why", "how", "it", "that", "this", "from", "have", "has"}


def keyword_search(user, cleaned, k):
    """The fallback when no embedding model is available: count shared words."""
    terms = {w for w in _WORD.findall(cleaned.lower()) if w not in _STOP}
    scored = []
    for m in _messages(user):
        text = f"{m.author.display_name} {m.scope_name} {m.body}".lower()
        hits = sum(1 for t in terms if t in text)
        if hits:
            scored.append((hits, m))
    scored.sort(key=lambda pair: (-pair[0], -pair[1].sent_at.timestamp()))
    return [_row(m, None) for _, m in scored[:k]]


def search(user, query, k=None, min_score=None, include_context=None):
    """
    Search `user`'s messages. Raises InvalidQuery for a bad query; never raises for model
    problems. Returns {"query", "cleaned", "mode": "semantic"|"keyword", "results",
    "dropped" (below threshold), "ms", "index_ms", "note", "model", "k", "min_score"}.
    """
    k = k or getattr(settings, "AI_SEARCH_TOP_K", 5)
    if min_score is None:
        min_score = getattr(settings, "AI_SEARCH_MIN_SCORE", 0.25)
    cleaned = clean_query(query)
    started = time.perf_counter()
    out = {"query": query, "cleaned": cleaned, "k": k, "min_score": min_score,
           "model": model_name(), "dropped": 0, "index_ms": 0, "note": ""}
    try:
        index = build_index(user, include_context)
        out["index_ms"] = index["ms"] if index["rebuilt"] else 0
        if index["vectors"] is None:
            out.update(mode="semantic", results=[], note="You have no messages to search yet.")
        else:
            import numpy as np

            q = encode([cleaned])[0]
            scores = index["vectors"] @ q
            order = np.argsort(-scores)[:k]
            results = [(index["ids"][i], scores[i]) for i in order]
            kept = [(pk, s) for pk, s in results if s >= min_score]
            out["dropped"] = len(results) - len(kept)
            out.update(mode="semantic",
                       results=[_row(index["messages"][pk], s) for pk, s in kept])
    except SearchUnavailable as exc:
        out.update(mode="keyword", results=keyword_search(user, cleaned, k),
                   note=f"{exc} Showing keyword matches instead.")
    out["ms"] = int((time.perf_counter() - started) * 1000)
    return out
