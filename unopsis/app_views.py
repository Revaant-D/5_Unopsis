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

from urllib.parse import urlparse

from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import ui
from .app_forms import ItemActionForm
from .models import BriefItem, Connection, Message, Person, Provider, Space

WORK, PERSONAL = Space.Kind.WORK, Space.Kind.PERSONAL
NEEDS_YOU, MOVING, FYI = BriefItem.Lane.NEEDS_YOU, BriefItem.Lane.MOVING, BriefItem.Lane.FYI
OPEN, HANDLED = BriefItem.State.OPEN, BriefItem.State.HANDLED

# Roughly how long one decision takes, for "2 things left. About 4 minutes."
MINUTES_PER_DECISION = 2


def landing(request):
    """
    "/" -- the product page for a visitor; a signed-in user goes straight to their brief.

    Today the only way to be signed in is the Django admin login; from Assignment 5 it is every
    account, with no change here. It renders unopsis/home.html (the template the course's
    home-page tests pin at "/") in landing mode. The course dashboard that used to live at "/"
    is views.home, unchanged, at /under-the-hood/.
    """
    if request.user.is_authenticated:
        return redirect("app-work-brief")
    return render(request, "unopsis/home.html", {"landing": True})


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


def _step_ms(step):
    """A stored step's duration in ms, or 0 when it is missing or not a number."""
    value = step.get("ms", 0)
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def building(request, kind):
    """Screens 6 and 11, "Reading 14 hours for you.": the stored Brief.steps, replayed."""
    space, brief, now = _world(kind)
    steps = [
        {**step, "ms": _step_ms(step), "seconds": round(_step_ms(step) / 1000)}
        for step in (brief.steps if brief else [])
        if isinstance(step, dict)
    ]
    return _render_world(
        request, "unopsis/app/building.html", kind, "brief" if kind == WORK else "since",
        space, brief, now,
        steps=steps,
        total_seconds=round(sum(step.get("ms", 0) for step in steps) / 1000),
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


def thread(request, kind, pk):
    """
    Screen 9: one topic in full -- what happened, the receipts in order, and the reply draft
    with copy buttons. Read-only: replying happens in the original app.
    ?show=all brings back the messages marked as noise; any other value is ignored.
    """
    item = get_object_or_404(
        BriefItem.objects.select_related("brief__space", "primary_message__connection")
        .prefetch_related("messages__connection"),
        pk=pk, brief__space__kind=kind,
    )
    show_all = request.GET.get("show") == "all"
    receipts = item.messages.select_related("author", "connection").order_by("sent_at")
    hidden = receipts.filter(is_noise=True).count()
    if not show_all:
        receipts = receipts.exclude(is_noise=True)
    space, brief, now = item.brief.space, item.brief, timezone.now()
    primary = item.primary_message
    # Only ever hand the browser an http(s) link to open: permalinks come from provider data.
    safe_link = primary is not None and urlparse(primary.permalink).scheme in ("http", "https")
    return _render_world(
        request, "unopsis/app/thread.html", kind, "threads" if kind == WORK else "since",
        space, brief, now,
        item=item,
        chips=ui.source_chips(item),
        receipts=list(receipts),
        hidden=hidden,
        show_all=show_all,
        total=item.messages.count(),
        people=Person.objects.filter(messages__brief_items=item).distinct().order_by("display_name"),
        decision=ui.primary_action(item),
        secondary=ui.secondary_actions(item),
        open_url=primary.permalink if safe_link else "",
        open_label=primary.connection.get_provider_display() if primary else "",
    )


def handled(request):
    """
    Screen 10, the wrap-up: what is still open, what was closed today, and what arrived since
    the brief was written. ?done=<pk> (set by the action endpoint) shows the Undo banner;
    anything that is not the id of a handled work item is ignored rather than an error.
    """
    space, brief, now = _world(WORK)
    still = list(ui.lane_items(brief, NEEDS_YOU))
    for item in still:
        item.primary = ui.primary_action(item)
    start_of_day = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    done_today = (
        brief.items.filter(state=HANDLED, handled_at__gte=start_of_day)
        .select_related("primary_message__connection").order_by("-handled_at")
        if brief else BriefItem.objects.none()
    )
    done = request.GET.get("done", "")
    just_done = (
        BriefItem.objects.filter(pk=int(done), state=HANDLED, brief__space__kind=WORK).first()
        if done.isascii() and done.isdigit() else None   # "²".isdigit() is True; int("²") fails
    )
    since = (brief.generated_at or brief.window_end) if brief else None
    new_since = (
        Message.objects.filter(connection__space=space, sent_at__gt=since).count() if since else 0
    )
    return _render_world(
        request, "unopsis/app/handled.html", WORK, "handled", space, brief, now,
        still=still, minutes=len(still) * MINUTES_PER_DECISION, done_today=done_today,
        just_done=just_done, since=since, new_since=new_since,
    )


def personal_catchup(request):
    """Screen 12: "You were gone 6 hours." The lead reply, the rest by place, then the quiet."""
    space, brief, now = _world(PERSONAL)
    needs = list(ui.lane_items(brief, NEEDS_YOU))
    for item in needs:
        item.chips = ui.source_chips(item)
        item.primary = ui.primary_action(item)
    place_rows = ui.places(space, brief)
    return _render_world(
        request, "unopsis/app/personal_catchup.html", PERSONAL, "since", space, brief, now,
        lead=needs[0] if needs else None,
        rest=needs[1:],
        want_reply=len(needs),
        hours=ui.window_hours(brief),
        place_count=len(place_rows),
        quiet_places=[p for p in place_rows if not p["wants_you"]],
        broken=_broken(space),
    )


def caught_up(request):
    """Screen 13: the deliberate dead end -- what you did, and when the next read lands."""
    space, brief, now = _world(PERSONAL)
    done = (
        brief.items.filter(state=HANDLED).order_by("handled_at")
        if brief else BriefItem.objects.none()
    )
    return _render_world(
        request, "unopsis/app/caught_up.html", PERSONAL, "caught-up", space, brief, now,
        done=done,
        work_next=ui.next_digest(ui.current_space(WORK), now),
    )


def journey(request):
    """Every screen in the order a new user meets them -- the screen flow, clickable."""
    first = ui.lane_items(ui.latest_brief(ui.current_space(WORK)), NEEDS_YOU).first()
    screens = [
        ("Sign up", reverse("app-signup"), "The account, before any source is connected."),
        ("Setup 1 · Your world", reverse("app-setup-world"), "Work, personal, or both."),
        ("Setup 2 · Sources", reverse("app-setup-sources"), "The read-only accounts."),
        ("Setup 3 · What's read", reverse("app-setup-scope"), "Channels and labels."),
        ("Setup 4 · What matters", reverse("app-setup-tuning"), "The ranking rule."),
        ("First run", reverse("app-work-building"), "The funnel: messages → topics → things."),
        ("Today's brief", reverse("app-work-brief"), "The one page."),
        ("Focus", reverse("app-work-focus", args=[first.pk]) if first else None,
         "One decision at a time."),
        ("Thread", reverse("app-thread", args=["work", first.pk]) if first else None,
         "Receipts and the reply."),
        ("Handled today", reverse("app-work-handled"), "What is left, what is done."),
        ("Personal first run", reverse("app-personal-building"), "The same funnel, other world."),
        ("Catch-up", reverse("app-personal-catchup"), "You were gone N hours."),
        ("Caught up", reverse("app-personal-caught-up"), "The deliberate dead end."),
    ]
    return render(request, "unopsis/app/journey.html", {"screens": screens})

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
