"""
Seeds realistic Unopsis test data.

Run with:  python manage.py seed_demo

The data walks the product's whole spine for one user: a work Space and a personal
Space, each with connections, included scopes, rules and delivery preferences;
raw messages from four providers authored by people unified across handles; and a
finished brief for each space whose items sit in lanes, cite real messages, and
carry actions and a draft reply.

Idempotent -- every lookup goes through get_or_create keyed on the same fields the
uniqueness constraints protect, so running it twice changes nothing.
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from unopsis.models import Brief, BriefItem, Connection, Message, Person, Provider, Space

NOW = timezone.now()


def ago(**kw):
    return NOW - timedelta(**kw)


class Command(BaseCommand):
    help = "Seed realistic demo data for Unopsis."

    @transaction.atomic
    def handle(self, *args, **options):
        owner = User.objects.get(username="mohitg2")

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

        self.stdout.write(self.style.SUCCESS(
            f"Seeded: {Space.objects.count()} spaces, {Connection.objects.count()} connections, "
            f"{Person.objects.count()} people, {Message.objects.count()} messages, "
            f"{Brief.objects.count()} briefs, {BriefItem.objects.count()} items, "
            f"{BriefItem.messages.through.objects.count()} citations."
        ))
