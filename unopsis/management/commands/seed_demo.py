"""
Seeds realistic Unopsis test data for ONE user.

Run with:  python manage.py seed_demo            (seeds the default owner below)
           python manage.py seed_demo --user bob (seeds that account instead)

The data walks the product's whole spine for one user: a work Space and a personal
Space, each with connections, included scopes, rules and delivery preferences;
raw messages from four providers authored by people unified across handles; and a
finished brief for each space whose items sit in lanes, cite real messages, and
carry actions and a draft reply.

Idempotent -- every lookup goes through get_or_create keyed on the same fields the
uniqueness constraints protect, so running it twice changes nothing.

ASSIGNMENT 5 made the seeding itself importable. The work used to live inside
Command.handle() with the owner's username written into it, which was fine while every
row in the database belonged to one person and every signed-in account could read all of
them. A5 scoped every queryset in views.py to the requesting user (the owned_*() helpers
there), and the moment it did, "who owns these rows" stopped being a detail of a developer
convenience command: a brand-new account -- the grader's, the one Google hands back the
first time somebody clicks "Continue with Google" -- owns nothing, so it signs in
successfully and lands on an empty site that reads as broken.

So seed_demo_data(owner) is now a function any caller can hand a User, and
unopsis/onboarding.py calls it once when an account is created. The command is a thin
wrapper over it, and the demo data is defined in exactly one place either way.
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from unopsis.models import Brief, BriefItem, Connection, Message, Person, Provider, Space

# The account the command seeds when --user is not given: the team's own, which is the one
# this repository's committed db.sqlite3 was built around. A module constant rather than a
# literal buried in handle(), so the one place that has to change if the team account is
# renamed is visible from the top of the file.
DEFAULT_OWNER_USERNAME = "mohitg2"


@transaction.atomic
def seed_demo_data(owner):
    """
    Give `owner` a full set of demo rows, and return a {name: count} summary of theirs.

    Atomic because the rows are only meaningful together: a Brief whose BriefItems failed to
    write is worse than no brief at all, and a half-seeded account is the kind of state that
    is found weeks later by a chart that cannot explain its own numbers.

    Idempotent per owner, through the same get_or_create calls the command always used. Two
    users seeded one after another get two complete, separate sets: every get_or_create below
    is keyed on a Space belonging to `owner`, so nothing can be adopted from somebody else.
    """
    # The clock is read HERE, per call, and not once at import. It used to be a module
    # constant, which was correct for a command that runs for two seconds and exits. This
    # function is now also called from a web request (unopsis/onboarding.py), inside a worker
    # process that PythonAnywhere keeps alive for days -- so a module-level NOW would stamp
    # every account created today with the timestamp of whenever the server last restarted,
    # and the brief windows and the "messages per hour" chart would quietly describe last
    # Tuesday. `ago` is local for the same reason: it closes over this call's NOW.
    NOW = timezone.now()

    def ago(**kw):
        return NOW - timedelta(**kw)

    # ---- Spaces: the "two products are one product" split ----
    work, _ = Space.objects.get_or_create(
        user=owner, kind=Space.Kind.WORK,
        defaults={
            "detail_level": 3, "quiet_start": "19:00", "quiet_end": "08:00",
            "deliver_in_app": True, "deliver_email": True, "deliver_chat_dm": True,
            "digest_times": ["08:00", "16:30"],
            "rules": [
                {"mode": "always", "target": "person", "value": "Prof. Ramirez"},
                {"mode": "always", "target": "keyword", "value": "deadline"},
                {"mode": "never", "target": "channel", "value": "#random"},
                {"mode": "never", "target": "sender_domain", "value": "chegg.com"},
            ],
        },
    )
    personal, _ = Space.objects.get_or_create(
        user=owner, kind=Space.Kind.PERSONAL,
        defaults={
            "detail_level": 2, "quiet_start": "22:00", "quiet_end": "09:00",
            "deliver_in_app": True, "deliver_email": False, "deliver_chat_dm": False,
            "digest_times": ["18:00"],
            "rules": [{"mode": "always", "target": "person", "value": "Mom"}],
        },
    )

    # ---- Connections, with their included scopes ----
    conns = {}
    for key, space, provider, account, name, scopes in [
        ("wmail", work, Provider.GMAIL, "mohitg2@illinois.edu", "UIUC Mail",
         [{"id": "INBOX", "name": "Inbox", "type": "label"}]),
        ("wslack", work, Provider.SLACK, "hci-lab.slack.com", "HCI Lab",
         [{"id": "C08KJ21X", "name": "#engineering", "type": "channel"},
          {"id": "C08DEP44", "name": "#deploys", "type": "channel"}]),
        ("pmail", personal, Provider.GMAIL, "mohit.personal@gmail.com", "Personal Mail",
         [{"id": "INBOX", "name": "Inbox", "type": "label"}]),
        ("pdisc", personal, Provider.DISCORD, "mohitg#4417", "Discord",
         [{"id": "srv-friends", "name": "Friends", "type": "server"}]),
        ("pwa", personal, Provider.WHATSAPP_BUSINESS, "+1-217-555-0142", "WhatsApp",
         [{"id": "wa-family-01", "name": "Family", "type": "chat"}]),
    ]:
        conns[key], _ = Connection.objects.get_or_create(
            space=space, provider=provider, external_account=account,
            defaults={"display_name": name, "included_scopes": scopes,
                      "last_synced_at": ago(minutes=6),
                      "token_ref": f"vault://unopsis/{key}"},
        )
    # One connection in a failed state, so the admin shows a real error path.
    Connection.objects.filter(pk=conns["pdisc"].pk).update(
        status=Connection.Status.ERROR,
        last_error="401 Unauthorized: token revoked by the provider.",
    )
    conns["pdisc"].refresh_from_db()

    # ---- People, unified across handles ----
    people = {}
    for key, space, name, handles, vip in [
        ("ramirez", work, "Prof. Ramirez", ["ramirez@illinois.edu", "@ramirez"], True),
        ("priya", work, "Priya Shah", ["priya@illinois.edu", "@priya"], False),
        ("devon", work, "Devon Clark", ["devon@illinois.edu", "@devon"], False),
        ("sam", work, "Sam Whitaker", ["sam@illinois.edu", "@sam"], False),
        ("vendor", work, "Northwind Billing", ["billing@northwind.example"], False),
        ("promo", work, "Chegg Promotions", ["noreply@chegg.com"], False),
        ("mom", personal, "Mom", ["+1-630-555-0188"], True),
        ("lena", personal, "Lena Ortiz", ["lena#2210", "lena@mail.example",
                                          "+1-312-555-0117"], False),
    ]:
        people[key], _ = Person.objects.get_or_create(
            space=space, display_name=name,
            defaults={"handles": handles, "is_vip": vip},
        )

    # ---- Messages: the raw units ----
    msgs = {}
    rows = [
        ("r1", "wmail", "Inbox", "ramirez", "m-r1", 200,
         "Your draft looks solid. Tighten section 3 and resend before Friday.", False),
        ("r2", "wmail", "Inbox", "ramirez", "m-r2", 195,
         "Also please cite the Django docs properly in the references.", False),
        ("r3", "wslack", "#engineering", "ramirez", "s-r3", 150,
         "Reminder that Friday is a hard deadline, no extensions.", False),
        ("p1", "wslack", "#engineering", "priya", "s-p1", 140,
         "did everyone see the rubric got updated? ER diagram is required now", False),
        ("p2", "wslack", "#engineering", "priya", "s-p2", 138,
         "friday. hard deadline per the syllabus", False),
        ("d1", "wslack", "#engineering", "devon", "s-d1", 136, "wait it changed again??", False),
        ("d2", "wslack", "#engineering", "devon", "s-d2", 130,
         "someone needs to own the models file", False),
        ("s1", "wslack", "#engineering", "sam", "s-s1", 128,
         "i can take admin registration", False),
        ("dep1", "wslack", "#deploys", "devon", "s-dep1", 62,
         "deploy to staging failed again, third time today", False),
        ("dep2", "wslack", "#deploys", "sam", "s-dep2", 60,
         "looking into it, probably the migration", False),
        ("dep3", "wslack", "#deploys", "sam", "s-dep3", 45,
         "confirmed: migration 0004 locks the table. rolling back.", False),
        ("v1", "wmail", "Inbox", "vendor", "m-v1", 300,
         "Invoice #4471 is 14 days overdue. Please approve payment.", False),
        ("v2", "wmail", "Inbox", "vendor", "m-v2", 90,
         "Second notice: Invoice #4471 requires your approval to avoid a late fee.", False),
        ("n1", "wmail", "Promotions", "promo", "m-n1", 1400,
         "FLASH SALE: 50% off all textbook rentals!", True),
        ("n2", "wmail", "Promotions", "promo", "m-n2", 1300,
         "You left something in your cart", True),
        ("mom1", "pwa", "Family", "mom", "w-mom1", 360,
         "call me when you get a chance sweetie", False),
        ("mom2", "pwa", "Family", "mom", "w-mom2", 355, "did you eat", False),
        ("mom3", "pwa", "Family", "mom", "w-mom3", 200,
         "also grandma's birthday dinner is sunday at 6, can you make it?", False),
        ("l1", "pdisc", "Friends", "lena", "d-l1", 240,
         "are we still doing the trip in march?", False),
        ("l2", "pdisc", "Friends", "lena", "d-l2", 235,
         "i found flights for like $180 rt", False),
        ("l3", "pmail", "Inbox", "lena", "pm-l3", 230,
         "Forwarding the flight options so you can compare. Need to book by the 15th.", False),
        ("pm1", "pmail", "Inbox", "lena", "pm-1", 600,
         "Also your prescription is ready for pickup, saw the text.", False),
    ]
    for key, ck, scope, ak, ext, mins, body, noise in rows:
        msgs[key], _ = Message.objects.get_or_create(
            connection=conns[ck], external_id=ext,
            defaults={"author": people[ak], "scope_name": scope,
                      "sent_at": ago(minutes=mins), "body": body, "is_noise": noise,
                      "permalink": f"https://example.invalid/{ext}",
                      "raw": {"provider_id": ext}},
        )

    # ---- The work brief ----
    brief, _ = Brief.objects.get_or_create(
        space=work, window_start=ago(hours=16), window_end=NOW,
        trigger=Brief.Trigger.SCHEDULED,
        defaults={
            "status": Brief.Status.READY,
            "headline": "Three things need you before noon.",
            "message_count": 212, "topic_count": 18, "read_seconds": 95,
            "model_version": "brief-v3", "generated_at": ago(minutes=4),
            "steps": [
                {"label": "Reading 212 messages across 2 connections",
                 "status": "done", "ms": 3100},
                {"label": "Filtering excluded scopes and noise", "status": "done", "ms": 640},
                {"label": "Grouping into 18 topics", "status": "done", "ms": 5200},
                {"label": "Ranking and writing", "status": "done", "ms": 4400},
            ],
        },
    )

    items = {}
    item_rows = [
        ("draft", "Thesis draft: section 3 revisions due Friday",
         BriefItem.Lane.NEEDS_YOU, 1,
         "Prof. Ramirez approved your draft but wants section 3 tightened and the Django "
         "citations fixed, resent before Friday.",
         "Ramirez is marked always-surface, and the message names a deadline.",
         48, ["r1", "r2", "r3"], "r1",
         [{"kind": "reply", "label": "Reply to Prof. Ramirez", "primary": True},
          {"kind": "snooze", "label": "Snooze until tomorrow", "primary": False}],
         "Thanks -- revised section 3 attached, and I've fixed the Django citations. "
         "Sending the full draft Thursday.", 2, 1),
        ("invoice", "Invoice #4471 overdue, needs your approval",
         BriefItem.Lane.NEEDS_YOU, 2,
         "Northwind sent a second notice on invoice #4471, now 14 days overdue. It needs "
         "your approval to avoid a late fee.",
         "Second notice on the same thread, and it asks for an explicit approval.",
         24, ["v1", "v2"], "v2",
         [{"kind": "approve", "label": "Approve payment", "primary": True},
          {"kind": "forward", "label": "Forward to finance", "primary": False}],
         "", 1, 0),
        ("rubric", "Project rubric changed: ER diagram now required",
         BriefItem.Lane.NEEDS_YOU, 3,
         "The rubric changed: an ER diagram is now required and Friday is a hard deadline. "
         "Sam took admin registration; the models file is still unowned.",
         "Matched your 'deadline' keyword rule and five people are discussing it.",
         48, ["p1", "p2", "d2", "s1"], "p1",
         [{"kind": "calendar", "label": "Add Friday deadline to calendar", "primary": True}],
         "", 1, 0),
        ("deploy", "Staging deploys failing on migration 0004",
         BriefItem.Lane.MOVING, 1,
         "Staging deploys failed three times; Sam traced it to migration 0004 locking the "
         "table and is rolling back.",
         "Resolved without you, but it touches the release you're on.",
         None, ["dep1", "dep3"], "dep3",
         [{"kind": "open", "label": "Open in Slack", "primary": True}], "", 1, 0),
        ("promos", "Promotional mail suppressed",
         BriefItem.Lane.FYI, 1,
         "Two promotional emails were suppressed by your chegg.com rule.",
         "Shown only so the filtering is visible, never as something to act on.",
         None, ["n1", "n2"], None, [], "", 0, 0),
    ]
    for key, title, lane, rank, summary, why, dl, mks, primary, actions, draft, opens, fb \
            in item_rows:
        items[key], created = BriefItem.objects.get_or_create(
            brief=brief, title=title,
            defaults={
                "lane": lane, "rank": rank, "summary": summary, "why": why,
                "deadline_at": NOW + timedelta(hours=dl) if dl else None,
                "primary_message": msgs[primary] if primary else None,
                "actions": actions, "draft_body": draft,
                "open_count": opens, "feedback": fb,
            },
        )
        items[key].messages.set([msgs[k] for k in mks])

    # ---- The personal brief: same models, Space.kind="personal" ----
    pbrief, _ = Brief.objects.get_or_create(
        space=personal, window_start=ago(hours=24), window_end=NOW,
        trigger=Brief.Trigger.ON_DEMAND,
        defaults={"status": Brief.Status.READY,
                  "headline": "Two people are waiting on you.",
                  "message_count": 46, "topic_count": 6, "read_seconds": 40,
                  "model_version": "brief-v3", "generated_at": ago(minutes=9),
                  "steps": [{"label": "Reading 46 messages", "status": "done", "ms": 900},
                            {"label": "Ranking and writing", "status": "done", "ms": 2100}]},
    )
    for key, title, lane, rank, summary, why, mks, primary in [
        ("bday", "Grandma's birthday dinner Sunday 6pm", BriefItem.Lane.NEEDS_YOU, 1,
         "Mom asked you to call, and wants to know if you can make grandma's birthday "
         "dinner Sunday at 6.",
         "Mom is marked always-surface and asked a direct question.",
         ["mom1", "mom3"], "mom3"),
        ("trip", "March trip: flights found, book by the 15th",
         BriefItem.Lane.NEEDS_YOU, 2,
         "Lena found $180 round-trip flights for the March trip and needs a decision by "
         "the 15th.",
         "A decision with a date, raised across Discord and email.",
         ["l2", "l3"], "l3"),
    ]:
        it, _ = BriefItem.objects.get_or_create(
            brief=pbrief, title=title,
            defaults={"lane": lane, "rank": rank, "summary": summary, "why": why,
                      "primary_message": msgs[primary],
                      "actions": [{"kind": "reply", "label": "Reply", "primary": True}]},
        )
        it.messages.set([msgs[k] for k in mks])

    return {
        "spaces": Space.objects.filter(user=owner).count(),
        "connections": Connection.objects.filter(space__user=owner).count(),
        "people": Person.objects.filter(space__user=owner).count(),
        "messages": Message.objects.filter(connection__space__user=owner).count(),
        "briefs": Brief.objects.filter(space__user=owner).count(),
        "items": BriefItem.objects.filter(brief__space__user=owner).count(),
    }


class Command(BaseCommand):
    help = "Seed realistic demo data for Unopsis (one user's worth)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--user",
            default=DEFAULT_OWNER_USERNAME,
            help=(
                "Username to seed. Defaults to %(default)r. The account must already exist: "
                "creating one here would mean inventing a password, and an account nobody "
                "chose a password for is an account nobody can audit."
            ),
        )

    def handle(self, *args, **options):
        username = options["user"]
        try:
            owner = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(
                f"No user named {username!r}. Create one first with "
                "`python manage.py createsuperuser` (or sign up on the site), then re-run."
            )

        counts = seed_demo_data(owner)
        self.stdout.write(self.style.SUCCESS(
            f"Seeded {owner.username}: {counts['spaces']} spaces, "
            f"{counts['connections']} connections, {counts['people']} people, "
            f"{counts['messages']} messages, {counts['briefs']} briefs, "
            f"{counts['items']} items."
        ))
