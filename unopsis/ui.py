"""
Queries and small calculations behind the wireframe UI (the /work/, /personal/ and /setup/
pages in app_views.py).

Nothing in here renders a template or reads a request. That keeps the one assumption that
changes in Assignment 5 -- "whose space is this?" -- in exactly one function, current_space(),
which today takes the first space of a kind and will read request.user once login exists.
"""

from datetime import datetime, timedelta

from django.db.models import Count, IntegerField, Q, Value
from django.utils import timezone

from .models import Brief, BriefItem, Connection, Message, Provider, Space

# What the item-action endpoint accepts. "reopen" is the Undo on the wrap-up screen.
ACTIONS = ("handle", "snooze", "dismiss", "reopen")

# Snoozing when no digest is left today pushes an item this far into the future.
SNOOZE_FALLBACK = timedelta(hours=3)


def current_space(kind):
    """The space the UI is showing. No login until A5, so: the first space of that kind."""
    return Space.objects.filter(kind=kind).order_by("pk").first()


def latest_brief(space):
    """The newest ready brief in a space, or None (no space, or nothing generated yet)."""
    if space is None:
        return None
    return space.briefs.filter(status=Brief.Status.READY).order_by("-window_end").first()


def lane_items(brief, lane, states=(BriefItem.State.OPEN,)):
    """
    One lane of a brief in rank order, with everything a card shows prefetched.

    Asking for open items also returns snoozed items whose snoozed_until has passed: that is
    what "Snooze to 4:30 PM" promises, and without it a snoozed item would never come back.
    """
    if brief is None:
        return BriefItem.objects.none()
    wanted = Q(state__in=states)
    if BriefItem.State.OPEN in states:
        wanted |= Q(state=BriefItem.State.SNOOZED, snoozed_until__lte=timezone.now())
    return (
        brief.items.filter(wanted, lane=lane)
        .select_related("primary_message__connection")
        .prefetch_related("messages__connection", "messages__author")
        .order_by("rank")
    )


def window_hours(brief):
    """How many hours a brief covers, as a whole number ("Covers 14 hours")."""
    if brief is None:
        return 0
    return max(round((brief.window_end - brief.window_start).total_seconds() / 3600), 0)


def quiet_message_count(brief):
    """
    "208 messages needed nothing from you": what the brief read minus what its Needs-you items
    cite. Never below zero -- message_count is stored when the brief is built, so cited rows
    added afterwards can outnumber it.
    """
    if brief is None:
        return 0
    cited = (
        Message.objects.filter(
            brief_items__brief=brief, brief_items__lane=BriefItem.Lane.NEEDS_YOU
        )
        .distinct()
        .count()
    )
    return max(brief.message_count - cited, 0)


def daily_reading_load(brief):
    """About how many messages a day arrive, scaled from the latest brief's window."""
    hours = window_hours(brief)
    if not hours:
        return 0
    return round(brief.message_count * 24 / hours)


def source_chips(item):
    """
    Where an item's receipts came from, busiest first: [{"label": "Slack #acme", "count": 2}].

    Channels that start with # keep their name; mailboxes and chats show the provider alone.
    Reads item.messages.all(), so prefetch messages__connection before calling it in a loop.
    """
    counts = {}
    for message in item.messages.all():
        label = message.connection.get_provider_display()
        if message.scope_name.startswith("#"):
            label = f"{label} {message.scope_name}"
        counts[label] = counts.get(label, 0) + 1
    return [
        {"label": label, "count": count}
        for label, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    ]


def connection_label(connection):
    """The sidebar line for a connection: "Gmail · Inbox + Clients" or "Slack · 3 channels"."""
    names = [
        scope["name"]
        for scope in connection.included_scopes or []
        if isinstance(scope, dict) and scope.get("name")
    ]
    if not names:
        scope_text = "everything"
    elif len(names) <= 2:
        scope_text = " + ".join(names)
    else:
        scope_text = f"{len(names)} channels"
    return f"{connection.get_provider_display()} · {scope_text}"


def parse_time(value):
    """"16:30" -> time(16, 30); anything unparseable -> None."""
    try:
        return datetime.strptime(value, "%H:%M").time()
    except (TypeError, ValueError):
        return None


def next_digest(space, now):
    """
    The next scheduled brief after `now` as a time of day, or None when there is no schedule.
    After the last slot of the day it wraps to tomorrow's first. Bad entries are skipped.
    """
    if space is None:
        return None
    times = sorted(t for t in (parse_time(v) for v in space.digest_times or []) if t)
    if not times:
        return None
    current = timezone.localtime(now).time()
    return next((t for t in times if t > current), times[0])


def snooze_until(space, now):
    """When a snoozed item comes back: the next digest later today, else SNOOZE_FALLBACK."""
    local_now = timezone.localtime(now)
    slot = next_digest(space, now)
    if slot is not None and slot > local_now.time():
        return local_now.replace(hour=slot.hour, minute=slot.minute, second=0, microsecond=0)
    return now + SNOOZE_FALLBACK


def primary_action(item):
    """The action flagged primary in item.actions, or None."""
    return next(
        (a for a in item.actions or [] if isinstance(a, dict) and a.get("primary")), None
    )


def secondary_actions(item):
    """Every other offered action. Rendered disabled: nothing is sent on the user's behalf."""
    return [a for a in item.actions or [] if isinstance(a, dict) and not a.get("primary")]


def apply_action(item, action, now):
    """
    Change an item's state the way one wireframe button does, and save it.

        handle   -> handled, stamped with handled_at
        snooze   -> snoozed until the next digest (see snooze_until)
        dismiss  -> dismissed, feedback -1 ("Not important" is a ranking signal)
        reopen   -> open again; the Undo on the wrap-up screen

    Only state fields are written -- never draft_body -- which is why this exists instead of
    reusing ItemUpdateForm, whose POST would blank a draft it was not sent.
    """
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}")
    item.handled_at = None
    item.snoozed_until = None
    if action == "handle":
        item.state = BriefItem.State.HANDLED
        item.handled_at = now
    elif action == "snooze":
        item.state = BriefItem.State.SNOOZED
        item.snoozed_until = snooze_until(item.brief.space, now)
    elif action == "dismiss":
        item.state = BriefItem.State.DISMISSED
        item.feedback = -1
    else:
        item.state = BriefItem.State.OPEN
    item.save(update_fields=["state", "handled_at", "snoozed_until", "feedback"])


def places(space, brief):
    """
    The personal sidebar's "Your places -- ranked by what wants you": every channel or chat the
    space's messages arrived in, with how many open Needs-you items on `brief` cite it.
    """
    if space is None:
        return []
    rows = Message.objects.filter(connection__space=space).values(
        "connection__provider", "scope_name"
    )
    if brief is None:
        rows = rows.annotate(
            messages=Count("id"), wants_you=Value(0, output_field=IntegerField())
        )
    else:
        rows = rows.annotate(
            messages=Count("id", distinct=True),
            wants_you=Count(
                "brief_items",
                filter=Q(
                    brief_items__brief=brief,
                    brief_items__lane=BriefItem.Lane.NEEDS_YOU,
                    brief_items__state=BriefItem.State.OPEN,
                ),
                distinct=True,
            ),
        )
    labels = dict(Provider.choices)
    return [
        {
            "name": row["scope_name"] or labels.get(row["connection__provider"], ""),
            "provider": labels.get(row["connection__provider"], ""),
            "messages": row["messages"],
            "wants_you": row["wants_you"],
        }
        for row in rows.order_by("-wants_you", "-messages", "scope_name")
    ]


def sidebar_context(kind, space, brief, now):
    """Everything the left rail of a /work/ or /personal/ page shows."""
    needs_you = lane_items(brief, BriefItem.Lane.NEEDS_YOU)
    connections = list(space.connections.all()) if space else []
    return {
        "world": kind,
        "space": space,
        "today": timezone.localtime(now),
        "needs_you_count": needs_you.count(),
        "first_needs_you": needs_you.first(),
        "connections": [
            {
                "connection": connection,
                "label": connection_label(connection),
                "broken": connection.status == Connection.Status.ERROR,
            }
            for connection in connections
        ],
        "next_digest": next_digest(space, now),
        "places": places(space, brief) if kind == Space.Kind.PERSONAL else [],
    }
