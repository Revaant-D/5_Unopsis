"""
F-7: no cold start for search. Build the user's search index in the background as they sign in.

The first search used to pay for everything at once (load the embedding model, then embed every
message), about 55 s on a laptop. The index lives in this web process's memory
(semantic_search._index), so it has to be built *inside the server process*. A management
command run beforehand would warm a different process. So: when a user signs in, a daemon thread
loads the embedding model and embeds that user's messages while they read their brief. By the
time they open Search, it answers in milliseconds.

Only the small embedding model (~90 MB) is warmed. The Granite answer model (~5 GB) is not:
loading it on every sign-in would cost seconds of CPU and gigabytes of RAM for a feature most
visits never use, so the first *answer* stays slow and the page says so.

Rules:
  * It must never break or slow down sign-in: everything runs in the thread, in try/except.
  * It's skipped when the index is already warm, or search is switched off.
  * It's skipped while Django's test runner is active, so the ~100 tests that sign in don't
    download models in the background. Tests that want it set AI_WARM_ON_LOGIN=True explicitly.

Connected by importing this module in ai_views.py (no apps.py change needed).
"""

import logging
import threading

from django.conf import settings
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from . import semantic_search

log = logging.getLogger(__name__)


def _under_test_runner():
    # Django's setup_test_environment() adds mail.outbox; it doesn't exist in a running server.
    from django.core import mail

    return hasattr(mail, "outbox")


def enabled():
    explicit = getattr(settings, "AI_WARM_ON_LOGIN", None)
    if explicit is not None:
        return bool(explicit)
    return not _under_test_runner()


def is_warm(user):
    """True if the model is loaded and this user's index is already cached."""
    include_context = getattr(settings, "AI_SEARCH_INCLUDE_CONTEXT", True)
    key = (user.pk, semantic_search.model_name(), include_context)
    return semantic_search.is_loaded() and key in semantic_search._index


def warm_user(user_id):
    """Load the embedding model and build one user's index. Safe to call from any thread."""
    from django.contrib.auth import get_user_model
    from django.db import connection

    try:
        user = get_user_model().objects.get(pk=user_id)
        index = semantic_search.build_index(user)
        log.info("Search warm-up for user %s: %d messages, %d ms", user_id, len(index["ids"]), index["ms"])
    except semantic_search.SearchUnavailable as exc:
        log.info("Search warm-up skipped: %s", exc)       # the page falls back to keyword search
    except Exception:
        log.exception("Search warm-up failed for user %s", user_id)
    finally:
        connection.close()   # this thread opened its own database connection


def start(user):
    """Start warming `user` in a daemon thread. Returns the thread, or None if nothing to do."""
    if not enabled() or not getattr(settings, "AI_SEARCH_ENABLED", True) or is_warm(user):
        return None
    thread = threading.Thread(target=warm_user, args=(user.pk,), name="search-warmup", daemon=True)
    thread.start()
    return thread


@receiver(user_logged_in, dispatch_uid="unopsis.ai.warmup.on_login")
def on_login(sender, request, user, **kwargs):
    try:
        start(user)
    except Exception:   # never let warm-up get in the way of signing in
        log.exception("Could not start the search warm-up")
