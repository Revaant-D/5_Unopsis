"""
The wireframe UI: the pages a person using Unopsis actually sees (docs/wireframes/v2).

The course pages in views.py -- the four view kinds, insights, reports, Vega-Lite and the APIs --
are untouched. Everything here is new and lives under /signup/, /login/, /setup/, /work/,
/personal/, /app/ and /journey/. Every page reads real rows; nothing is copied from the mockups.

Two deliberate limits until Assignment 5:
  * there is no login, so ui.current_space() picks the first space of a kind;
  * nothing is ever sent anywhere. Buttons that would act outside Unopsis (Connect, Forward,
    Reconnect) are rendered disabled; "Copy & open" copies to the clipboard and opens the
    original message, which is the read-only promise the wireframe makes.
"""

from django.shortcuts import render

from . import ui
from .models import Connection, Provider, Space

WORK, PERSONAL = Space.Kind.WORK, Space.Kind.PERSONAL


def coming_soon(request, task="a later task", **kwargs):
    """Temporary target for routes whose screen is not built yet. Task 11 proves none remain."""
    return render(request, "unopsis/app/coming_soon.html", {"task": task})


def signup(request):
    """Screen 1, "Create account" page. Static until A5: the page submits nothing."""
    return render(request, "unopsis/app/auth.html", {"mode": "signup"})


def login_page(request):
    """Screen 1, "Sign in" page. Named login_page so it never shadows django.contrib.auth.login."""
    return render(request, "unopsis/app/auth.html", {"mode": "login"})


# ---- Setup (screens 2-5): read-only display of what is stored; "Continue" only navigates ----
SETUP_STEPS = [
    (1, "Your world", "Work, personal or both — decides sources and ranking", "app-setup-world"),
    (2, "Sources", "The accounts to read. Nothing to summarize without them", "app-setup-sources"),
    (3, "What's read", "Channels and labels — scoping the input keeps the output short", "app-setup-scope"),
    (4, "What matters", "The ranking rule: who and what is always urgent for you", "app-setup-tuning"),
]

# In the wireframe, not (yet) Provider choices -- shown only in the "Request a source" tile.
REQUESTABLE_SOURCES = ["Teams", "Telegram", "Linear", "Notion"]


def _setup(request, template, step, **extra):
    context = {
        "steps": SETUP_STEPS,
        "step": step,
        "work": ui.current_space(WORK),
        "personal": ui.current_space(PERSONAL),
    }
    context.update(extra)
    return render(request, template, context)


def setup_world(request):
    """Screen 2: work, personal or both. Each card lists the providers already linked there."""
    return _setup(request, "unopsis/app/setup_world.html", 1)


def setup_sources(request):
    """Screen 3: one tile per provider. Work's connection wins when both worlds link one."""
    by_provider = {
        connection.provider: connection
        for connection in Connection.objects.select_related("space").order_by("space__kind", "pk")
    }   # personal sorts before work, so a work connection overwrites a personal one
    tiles = [
        {"provider": value, "label": label, "connection": by_provider.get(value)}
        for value, label in Provider.choices
    ]
    connected = sum(
        1 for tile in tiles
        if tile["connection"] and tile["connection"].status == Connection.Status.CONNECTED
    )
    return _setup(request, "unopsis/app/setup_sources.html", 2,
                  tiles=tiles, connected=connected, requestable=REQUESTABLE_SOURCES)


def setup_scope(request):
    """Screen 4: the included channels and labels per work connection, and the daily load."""
    work = ui.current_space(WORK)
    return _setup(request, "unopsis/app/setup_scope.html", 3,
                  connections=list(work.connections.all()) if work else [],
                  reading_load=ui.daily_reading_load(ui.latest_brief(work)))


def setup_tuning(request):
    """Screen 5: always/never rules, detail level, schedule, quiet hours, delivery."""
    work = ui.current_space(WORK)
    rules = [r for r in (work.rules if work else []) if isinstance(r, dict)]
    times = (ui.parse_time(v) for v in (work.digest_times if work else []))
    return _setup(request, "unopsis/app/setup_tuning.html", 4,
                  always=[r for r in rules if r.get("mode") == "always"],
                  never=[r for r in rules if r.get("mode") == "never"],
                  digest_times=[t for t in times if t])
