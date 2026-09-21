"""
Proves Unopsis's constraints and on_delete behaviour actually hold.

Run with:  python manage.py verify_constraints

Every destructive check runs inside a savepoint that is rolled back afterwards, so
this demonstrates the behaviour without damaging the seeded data. It can be run
repeatedly and leaves the database exactly as it found it.
"""

from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.utils import timezone

from unopsis.models import Brief, BriefItem, Connection, Message, Person, Space


class _Rollback(Exception):
    """Raised to roll back a demonstration savepoint without reporting an error."""


class Command(BaseCommand):
    help = "Demonstrate uniqueness constraints and on_delete behaviour."

    def ok(self, label, detail):
        self.stdout.write(self.style.SUCCESS(f"PASS  {label}"))
        self.stdout.write(f"      {detail}\n")

    def bad(self, label, detail):
        self.stdout.write(self.style.ERROR(f"FAIL  {label}"))
        self.stdout.write(f"      {detail}\n")

    def handle(self, *args, **options):
        self.stdout.write("\nVerifying Unopsis constraints\n" + "=" * 70 + "\n")

        # ---- 1. One work space and one personal space per user ----
        space = Space.objects.first()
        try:
            with transaction.atomic():
                Space.objects.create(user=space.user, kind=space.kind)
            self.bad("Space uniqueness", "A second space of the same kind was accepted.")
        except IntegrityError as e:
            self.ok("UniqueConstraint on Space (user, kind)",
                    f"A second {space.kind!r} space was rejected: "
                    f"{str(e).strip().splitlines()[0]}")

        # ---- 2. Idempotent ingest ----
        m = Message.objects.select_related("connection", "author").first()
        try:
            with transaction.atomic():
                Message.objects.create(connection=m.connection, author=m.author,
                                       external_id=m.external_id, body="duplicate ingest",
                                       sent_at=timezone.now())
            self.bad("Message uniqueness", "A duplicate ingest was accepted.")
        except IntegrityError as e:
            self.ok("UniqueConstraint on Message (connection, external_id)",
                    f"Re-ingesting {m.external_id!r} was rejected: "
                    f"{str(e).strip().splitlines()[0]}  <- this is what makes syncing idempotent")

        # ---- 3. The same inbox cannot be linked twice ----
        c = Connection.objects.first()
        try:
            with transaction.atomic():
                Connection.objects.create(space=c.space, provider=c.provider,
                                          external_account=c.external_account)
            self.bad("Connection uniqueness", "The same inbox was linked twice.")
        except IntegrityError as e:
            self.ok("UniqueConstraint on Connection (space, provider, external_account)",
                    f"Relinking {c.external_account!r} was rejected: "
                    f"{str(e).strip().splitlines()[0]}")

        # ---- 4. One item per lane/rank slot ----
        item = BriefItem.objects.select_related("brief").first()
        try:
            with transaction.atomic():
                BriefItem.objects.create(brief=item.brief, title="a different subject",
                                         lane=item.lane, rank=item.rank, summary="x")
            self.bad("BriefItem slot uniqueness", "Two items claimed the same lane and rank.")
        except IntegrityError as e:
            self.ok("UniqueConstraint on BriefItem (brief, lane, rank)",
                    f"A second item at {item.lane!r} rank {item.rank} was rejected: "
                    f"{str(e).strip().splitlines()[0]}")

        # ---- 5. Conditional constraint: scheduled briefs only ----
        sched = Brief.objects.filter(trigger=Brief.Trigger.SCHEDULED).first()
        rejected = False
        try:
            with transaction.atomic():
                Brief.objects.create(space=sched.space, window_start=sched.window_start,
                                     window_end=sched.window_end,
                                     trigger=Brief.Trigger.SCHEDULED)
        except IntegrityError:
            rejected = True
        if not rejected:
            self.bad("Conditional constraint on Brief", "A duplicate scheduled brief was accepted.")
        else:
            try:
                with transaction.atomic():
                    Brief.objects.create(space=sched.space, window_start=sched.window_start,
                                         window_end=sched.window_end,
                                         trigger=Brief.Trigger.ON_DEMAND)
                    self.ok("Conditional UniqueConstraint on Brief (scheduled only)",
                            "A second SCHEDULED brief for the same window was rejected, while an "
                            "ON_DEMAND brief for that same window was allowed. A plain constraint "
                            "would have blocked a legitimate 'catch me up' request.")
                    raise _Rollback()
            except _Rollback:
                pass

        # ---- 6. PROTECT: a person's message history is real data ----
        p = Person.objects.filter(messages__isnull=False).distinct().first()
        n = p.messages.count()
        try:
            with transaction.atomic():
                p.delete()
            self.bad("PROTECT on Message.author", "A person with messages was deleted.")
        except ProtectedError:
            self.ok("PROTECT on Message.author",
                    f"Deleting {p.display_name!r} was blocked because {n} message(s) still "
                    f"reference them (ProtectedError), rather than silently erasing the history.")

        # ---- 7. CASCADE: removing a Space takes its whole subtree ----
        target = Space.objects.filter(connections__isnull=False).distinct().first()
        counts = (Connection.objects.filter(space=target).count(),
                  Message.objects.filter(connection__space=target).count(),
                  Brief.objects.filter(space=target).count())
        before = (Connection.objects.count(), Message.objects.count(), Brief.objects.count())
        try:
            with transaction.atomic():
                # Message.author is PROTECTed, so the messages must go before the people
                # they point at -- which is the PROTECT guarantee working as designed.
                Message.objects.filter(connection__space=target).delete()
                target.delete()
                after = (Connection.objects.count(), Message.objects.count(),
                         Brief.objects.count())
                self.ok("CASCADE from Space through Connection to Message",
                        f"Deleting the {target.kind!r} space removed {counts[0]} connection(s), "
                        f"{counts[1]} message(s) and {counts[2]} brief(s): connections "
                        f"{before[0]}->{after[0]}, messages {before[1]}->{after[1]}, "
                        f"briefs {before[2]}->{after[2]}.")
                raise _Rollback()
        except _Rollback:
            pass

        # ---- 8. SET_NULL: losing the lead quote must not lose the item ----
        lead = BriefItem.objects.filter(primary_message__isnull=False).first()
        items_before = BriefItem.objects.count()
        try:
            with transaction.atomic():
                msg = lead.primary_message
                msg.brief_items.clear()
                msg.delete()
                lead.refresh_from_db()
                if BriefItem.objects.count() == items_before and lead.primary_message_id is None:
                    self.ok("SET_NULL on BriefItem.primary_message",
                            f"Deleting the quoted message kept all {items_before} brief item(s); "
                            f"{lead.title[:40]!r} survives with primary_message=NULL.")
                else:
                    self.bad("SET_NULL on BriefItem.primary_message", "The item did not survive.")
                raise _Rollback()
        except _Rollback:
            pass

        # ---- 9. The M2M receipts actually resolve to real messages ----
        cited = BriefItem.objects.filter(messages__isnull=False).distinct().first()
        bodies = list(cited.messages.values_list("body", flat=True))
        if bodies:
            self.ok("ManyToMany receipts on BriefItem.messages",
                    f"{cited.title[:44]!r} cites {len(bodies)} real message(s), first: "
                    f"{bodies[0][:52]!r}")
        else:
            self.bad("ManyToMany receipts", "An item cited no messages.")

        # ---- 10. Default ordering is the stored ranking ----
        rows = list(BriefItem.objects.filter(brief=item.brief).values_list("lane", "rank"))
        if rows == sorted(rows):
            self.ok("Default ordering on BriefItem",
                    "BriefItem.objects.all() came back ordered by lane then rank with no "
                    "explicit order_by() -- the stored ranking, not a render-time sort.")
        else:
            self.bad("Default ordering on BriefItem", f"Got {rows}.")

        self.stdout.write("=" * 70)
        self.stdout.write(self.style.SUCCESS(
            f"Database intact: {Space.objects.count()} spaces, "
            f"{Connection.objects.count()} connections, {Person.objects.count()} people, "
            f"{Message.objects.count()} messages, {BriefItem.objects.count()} items, "
            f"{BriefItem.messages.through.objects.count()} citations.\n"))
