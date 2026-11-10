"""
Moves one account's demo data forward in time, so the newest brief ended this morning.

Run with:  python manage.py refresh_demo --user tester
           python manage.py refresh_demo --user tester --at "2026-11-10 08:00"

WHY THIS EXISTS (D-1). seed_demo stamps everything relative to the moment it runs. A database
seeded a month ago therefore says "4 weeks ago" on every card and shows deadlines that passed
weeks ago, which makes a live demo look abandoned. Re-seeding is no fix: seed_demo is
idempotent, so it leaves existing rows alone.

WHAT IT DOES. It finds the account's newest brief, works out how far its window_end is from
the anchor (08:00 today, or now if it is earlier than that), and shifts every timestamp the
account owns by that same amount. Because everything moves together, every gap between two
rows stays the same: "you were gone 14 hours", "3 new messages since the brief", the
messages-per-hour chart. Deadlines are then rounded to 5 PM on their (shifted) day, so they
read "Fri 5:00 PM" rather than "Fri 3:47 AM". An item whose title names a weekday ("revisions
due Friday") gets the next such day instead, so the chip and the title can never disagree.

It also applies the demo persona (B-7): connections still carrying the old real
identifiers are renamed to Alex Rivera's .example addresses. That is what lets an existing
database pick up the persona WITHOUT re-running seed_demo, which keys its briefs on the
moment it runs and so, on a later day, adds a second set of briefs beside the old ones.

Running it twice in the same morning is a no-op: the second run computes a shift of zero.
Only the named account's rows are touched; every query is filtered by owner.
"""

import re
from datetime import datetime, time, timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F, Max
from django.utils import timezone

from unopsis.management.commands.seed_demo import rename_legacy_accounts
from unopsis.models import Brief, BriefItem, Connection, Message, Person, Space

ANCHOR_TIME = time(8, 0)      # "this morning": when the newest brief should have ended
DEADLINE_TIME = time(17, 0)   # deadlines are rounded to 5 PM on their day
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
WEEKDAY_IN_TITLE = re.compile(r"\b(" + "|".join(WEEKDAYS) + r")\b", re.IGNORECASE)


def deadline_day(title, shifted_day, anchor_day):
    """
    The day a deadline should fall on: the weekday the title names, if it names one (the
    first such day on or after the anchor), otherwise the shifted day unchanged.
    """
    named = WEEKDAY_IN_TITLE.search(title or "")
    if not named:
        return shifted_day
    wanted = WEEKDAYS.index(named.group(1).lower())
    return anchor_day + timedelta(days=(wanted - anchor_day.weekday()) % 7)


def default_anchor(now=None):
    """08:00 today in the site's time zone, or `now` itself if it is not 08:00 yet."""
    now = timezone.localtime(now or timezone.now())
    morning = now.replace(hour=ANCHOR_TIME.hour, minute=ANCHOR_TIME.minute, second=0, microsecond=0)
    return morning if now >= morning else now.replace(second=0, microsecond=0)


def describe(delta):
    """timedelta(-1, 67197) prints as "-1 day, 18:39:57"; say "back 5h 20m" instead."""
    direction = "back" if delta < timedelta(0) else "forward"
    minutes = int(abs(delta).total_seconds() // 60)
    days, minutes = divmod(minutes, 24 * 60)
    hours, minutes = divmod(minutes, 60)
    parts = [f"{days}d"] * bool(days) + [f"{hours}h"] * bool(hours) + [f"{minutes}m"]
    return f"{direction} {' '.join(parts)}" if delta else "not at all (already current)"


def _shift(queryset, delta, *fields):
    """Add `delta` to each named nullable DateTimeField in one UPDATE per field."""
    for field in fields:
        queryset.filter(**{f"{field}__isnull": False}).update(**{field: F(field) + delta})


@transaction.atomic
def refresh_demo_data(owner, anchor=None):
    """
    Shift every timestamp `owner` has so their newest brief ends at `anchor`.

    Returns the timedelta applied, or None when the account has no briefs (nothing to anchor
    to, so nothing is moved).
    """
    anchor = anchor or default_anchor()
    rename_legacy_accounts(owner)
    newest = Brief.objects.filter(space__user=owner).aggregate(end=Max("window_end"))["end"]
    if newest is None:
        return None
    delta = anchor - newest

    if delta:
        _shift(Message.objects.filter(connection__space__user=owner), delta, "sent_at")
        _shift(Brief.objects.filter(space__user=owner), delta,
               "window_start", "window_end", "generated_at")
        _shift(BriefItem.objects.filter(brief__space__user=owner), delta,
               "deadline_at", "handled_at", "snoozed_until", "draft_sent_at")
        _shift(Connection.objects.filter(space__user=owner), delta, "last_synced_at")
        _shift(Person.objects.filter(space__user=owner), delta, "first_seen_at")
        _shift(Space.objects.filter(user=owner), delta, "created_at")

    # Round deadlines to 5 PM on their own day, in the site's time zone. Done even when the
    # shift is zero, so a fresh seed gets tidy deadlines too.
    tz = timezone.get_current_timezone()
    anchor_day = timezone.localtime(anchor, tz).date()
    items = BriefItem.objects.filter(brief__space__user=owner, deadline_at__isnull=False)
    for item in items:
        day = deadline_day(item.title, timezone.localtime(item.deadline_at, tz).date(), anchor_day)
        rounded = timezone.make_aware(datetime.combine(day, DEADLINE_TIME), tz)
        if rounded != item.deadline_at:
            item.deadline_at = rounded
            item.save(update_fields=["deadline_at"])

    # A sync time in the future would read "synced in 3 hours"; cap it at the anchor.
    Connection.objects.filter(space__user=owner, last_synced_at__gt=anchor).update(
        last_synced_at=anchor - timedelta(minutes=6)
    )
    return delta


class Command(BaseCommand):
    help = "Shift one account's demo data so its newest brief ended this morning."

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True, help="Username whose rows to move.")
        parser.add_argument(
            "--at",
            help='Where the newest brief should end, e.g. "2026-11-10 08:00" (site time zone). '
                 "Defaults to 08:00 today, or now if it is earlier than that.",
        )

    def handle(self, *args, **options):
        try:
            owner = User.objects.get(username=options["user"])
        except User.DoesNotExist:
            raise CommandError(f"No account named {options['user']!r}.")

        anchor = None
        if options["at"]:
            try:
                parsed = datetime.fromisoformat(options["at"])
            except ValueError:
                raise CommandError(f"--at must look like 2026-11-10 08:00, not {options['at']!r}.")
            anchor = parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)

        delta = refresh_demo_data(owner, anchor)
        if delta is None:
            self.stdout.write(f"{owner.username} has no briefs; run seed_demo first. Nothing moved.")
            return
        newest = Brief.objects.filter(space__user=owner).aggregate(end=Max("window_end"))["end"]
        self.stdout.write(self.style.SUCCESS(
            f"Moved {owner.username}'s demo data {describe(delta)}. "
            f"Newest brief now ends {timezone.localtime(newest):%a %d %b %H:%M}."
        ))
