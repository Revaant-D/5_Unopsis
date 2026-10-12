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

from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import ui
from .app_forms import ItemActionForm
from .models import BriefItem, Connection, Provider, Space

WORK, PERSONAL = Space.Kind.WORK, Space.Kind.PERSONAL
NEEDS_YOU, MOVING, FYI = BriefItem.Lane.NEEDS_YOU, BriefItem.Lane.MOVING, BriefItem.Lane.FYI
OPEN, HANDLED = BriefItem.State.OPEN, BriefItem.State.HANDLED


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


# ---- Work and personal pages: shared plumbing ---------------------------------------------
def _world(kind):
    """(space, brief, now) for one side of the product."""
    space = ui.current_space(kind)
    return space, ui.latest_brief(space), timezone.now()


def _render_world(request, template, kind, active, space, brief, now, **extra):
    """Render a /work/ or /personal/ page with its sidebar context."""
    context = {"active": active, "brief": brief, **ui.sidebar_context(kind, space, brief, now)}
    context.update(extra)
    return render(request, template, context)


def _broken(space):
    """The space's connections whose last sync failed -- each gets the error banner."""
    return list(space.connections.filter(status=Connection.Status.ERROR)) if space else []


def building(request, kind):
    """Screens 6 and 11, "Reading 14 hours for you.": the stored Brief.steps, replayed."""
    space, brief, now = _world(kind)
    steps = [
        {**step, "seconds": round(step.get("ms", 0) / 1000)}
        for step in (brief.steps if brief else [])
        if isinstance(step, dict)
    ]
    return _render_world(
        request, "unopsis/app/building.html", kind, "brief" if kind == WORK else "since",
        space, brief, now,
        steps=steps,
        hours=ui.window_hours(brief),
        needs_count=ui.lane_items(brief, NEEDS_YOU).count(),
        moving_count=ui.lane_items(brief, MOVING).count(),
    )


def work_brief(request):
    """Screen 7, today's brief: Needs-you in rank order, then Moving, then what was folded away."""
    space, brief, now = _world(WORK)
    needs = list(ui.lane_items(brief, NEEDS_YOU))
    for item in needs:
        item.chips = ui.source_chips(item)
    return _render_world(
        request, "unopsis/app/work_brief.html", WORK, "brief", space, brief, now,
        needs=needs,
        moving=ui.lane_items(brief, MOVING, states=(OPEN, HANDLED)),
        fyi=ui.lane_items(brief, FYI, states=(OPEN, HANDLED)),
        hours=ui.window_hours(brief),
        source_count=space.connections.count() if space else 0,
        quiet_count=ui.quiet_message_count(brief),
        broken=_broken(space),
        snooze_to=ui.snooze_until(space, now),
    )


def focus(request, pk):
    """Screen 8: one Needs-you item on screen, with its place in the queue and J/K/E/S."""
    item = get_object_or_404(
        BriefItem.objects.select_related("brief__space", "primary_message")
        .prefetch_related("messages__connection"),
        pk=pk, brief__space__kind=WORK,
    )
    space, brief, now = item.brief.space, item.brief, timezone.now()
    queue = list(ui.lane_items(brief, NEEDS_YOU).values_list("pk", flat=True))
    index = queue.index(item.pk) if item.pk in queue else None
    return _render_world(
        request, "unopsis/app/focus.html", WORK, "needs-you", space, brief, now,
        item=item,
        chips=ui.source_chips(item),
        queue=queue,
        position=index + 1 if index is not None else None,
        previous_pk=queue[index - 1] if index else None,
        next_pk=queue[index + 1] if index is not None and index + 1 < len(queue) else None,
        secondary=ui.secondary_actions(item),
        since=min((m.sent_at for m in item.messages.all()), default=None),
        snooze_to=ui.snooze_until(space, now),
    )


def needs_you(request):
    """Sidebar "Needs you · N": the first open item, or the brief once none are left."""
    _space, brief, _now = _world(WORK)
    first = ui.lane_items(brief, NEEDS_YOU).first()
    if first is None:
        return redirect("app-work-brief")
    return redirect("app-work-focus", pk=first.pk)

# ---- The POST endpoint behind every state-changing button ----------------------------------
@require_POST
def item_action(request, pk):
    """
    Every state-changing button on the wireframe pages posts here: handle, snooze, dismiss,
    reopen. POST and a CSRF token because it writes; a redirect afterwards (Post/Redirect/Get)
    so a refresh cannot press the button twice.
    """
    item = get_object_or_404(BriefItem.objects.select_related("brief__space"), pk=pk)
    form = ItemActionForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest("Unknown action or destination.")
    action = form.cleaned_data["action"]
    ui.apply_action(item, action, timezone.now())
    return redirect(_landing(item, action, form.cleaned_data["return_to"] or "brief"))


def _landing(item, action, return_to):
    """The page a button lands on. Personal items have no focus or wrap-up page of their own."""
    if item.brief.space.kind == PERSONAL and return_to not in ("catchup", "caught-up"):
        return reverse("app-personal-catchup")
    if return_to == "next":
        following = ui.lane_items(item.brief, NEEDS_YOU).filter(rank__gt=item.rank).first()
        if following is not None:
            return reverse("app-work-focus", args=[following.pk])
        return reverse("app-work-handled")
    if return_to == "handled":
        url = reverse("app-work-handled")
        return f"{url}?done={item.pk}" if action == "handle" else url
    return reverse({
        "brief": "app-work-brief",
        "catchup": "app-personal-catchup",
        "caught-up": "app-personal-caught-up",
    }[return_to])
