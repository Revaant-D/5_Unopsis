"""
Data model for Unopsis.

The spine of the product, and of this schema, is one chain:

    Space (work | personal)
      -> Connection (a linked provider account)
        -> Message (the raw unit, never shown in bulk)
          -> Brief (one generated read of a time window)
            -> BriefItem (one ranked thing, citing the messages behind it)

Six models carry that chain. Several concerns that could each have been their own
table are deliberately folded into fields instead, and the docstrings say where:
delivery preferences and digest times live on Space, sync health on Connection,
and generation steps, suggested actions and the reply draft on Brief/BriefItem.
Each of those is write-once display data that is never queried across rows, which
is what makes a column the honest choice rather than a table.

Two design commitments carry the product's promise, and both are stored data
rather than render-time logic:

1. `BriefItem.lane` and `BriefItem.rank` are columns. The ranking is decided when
   the brief is generated and then persisted, so the same brief reads the same way
   every time it is opened and can be audited afterwards.
2. `BriefItem.messages` links every item to the real messages behind it, so no
   sentence in a brief is unverifiable.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q


class Provider(models.TextChoices):
    """The message sources Unopsis can connect to."""

    GMAIL = "gmail", "Gmail"
    OUTLOOK = "outlook", "Outlook"
    SLACK = "slack", "Slack"
    DISCORD = "discord", "Discord"
    WHATSAPP_BUSINESS = "whatsapp_business", "WhatsApp Business"
    IMESSAGE = "imessage", "iMessage"


class Space(models.Model):
    """
    Represents one of a user's separate worlds: their work life or their personal
    life, each with its own connections, people, and briefs.

    This is the model that makes "two products" into one product. Rather than a
    separate work app and personal app, a Space carries a `kind` and everything
    below it is scoped to a Space, so the personal experience is the same code
    reading rows where kind="personal". It exists to keep a user's work Slack from
    ever leaking into their personal brief.

    Delivery preferences, quiet hours, digest times and surfacing rules are fields
    here rather than separate tables: there is exactly one set per space, they are
    read as a block when a brief is built, and nothing ever queries across them.
    """

    class Kind(models.TextChoices):
        WORK = "work", "Work"
        PERSONAL = "personal", "Personal"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="spaces"
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)

    # --- how this space wants its briefs (was a separate Preference table) ---
    detail_level = models.IntegerField(
        default=3, help_text="1 = a single line per item, 5 = a full recap."
    )
    quiet_start = models.TimeField(null=True, blank=True)
    quiet_end = models.TimeField(null=True, blank=True)
    deliver_in_app = models.BooleanField(default=True)
    deliver_email = models.BooleanField(default=True)
    deliver_chat_dm = models.BooleanField(default=False)
    digest_times = models.JSONField(
        default=list, blank=True,
        help_text='When to build, e.g. ["08:00", "16:30"]. Weekday-only by convention.',
    )
    rules = models.JSONField(
        default=list, blank=True,
        help_text=(
            'Always/never surface instructions, e.g. '
            '[{"mode":"always","target":"person","value":"Prof. Ramirez"}].'
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["user", "kind"]
        constraints = [
            # A user has exactly one work space and one personal space. Screen 1 is
            # a choice between two things, not a list that can grow.
            models.UniqueConstraint(fields=["user", "kind"], name="uniq_space_per_user_kind")
        ]

    def __str__(self):
        return f"{self.user.username} / {self.get_kind_display()}"


class Connection(models.Model):
    """
    Represents one linked provider account inside a Space, such as a work Gmail
    mailbox or a particular Slack workspace.

    Everything ingested reaches back to exactly one Connection, which is what lets
    the rest of the system stay provider-agnostic: adding a seventh provider is a
    new choice value, not a schema change. `read_only` defaults to True because
    Unopsis reads far more than it writes, and the narrower grant is the one worth
    asking a user for.

    Sync health lives here as `last_synced_at` / `last_error` rather than in a
    separate run-history table. That trades the ability to say "this has failed
    every run since Tuesday" for one fewer table -- an acceptable loss while a
    single latest-state is enough to surface a broken integration.
    """

    class Status(models.TextChoices):
        CONNECTED = "connected", "Connected"
        ERROR = "error", "Error"
        REVOKED = "revoked", "Revoked"

    space = models.ForeignKey(Space, on_delete=models.CASCADE, related_name="connections")
    provider = models.CharField(max_length=32, choices=Provider.choices)
    external_account = models.CharField(
        max_length=254,
        help_text="Identifier at the provider, e.g. an address, workspace, or handle.",
    )
    display_name = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.CONNECTED)
    read_only = models.BooleanField(default=True)
    token_ref = models.CharField(
        max_length=200, blank=True,
        help_text=(
            "Opaque pointer to credentials held in a secrets store. No token "
            "material is ever written to this table."
        ),
    )
    included_scopes = models.JSONField(
        default=list, blank=True,
        help_text=(
            'Which channels/labels/chats count, e.g. '
            '[{"id":"C08KJ21X","name":"#engineering","type":"channel"}]. '
            "Excluded scopes are simply absent."
        ),
    )
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ["space", "provider", "external_account"]
        constraints = [
            # The same inbox cannot be linked twice into the same space. Scoped to
            # the space rather than the user, so one address could legitimately
            # appear in both work and personal.
            models.UniqueConstraint(
                fields=["space", "provider", "external_account"],
                name="uniq_connection_per_space_provider_account",
            )
        ]

    def __str__(self):
        return f"{self.get_provider_display()}: {self.external_account}"


class Person(models.Model):
    """
    Represents someone who appears in a Space's messages, unified across every
    provider they reach the user on.

    `handles` is a list precisely because the same person arrives as an email
    address on Gmail and an @name on Slack; collapsing those into one Person is
    what lets a brief say "Priya" instead of naming two strangers. Scoped to a
    Space because a VIP at work is not automatically a VIP at home.
    """

    space = models.ForeignKey(Space, on_delete=models.CASCADE, related_name="people")
    display_name = models.CharField(max_length=120)
    handles = models.JSONField(
        default=list, blank=True,
        help_text='Provider identities, e.g. ["priya@work.com", "@priya"].',
    )
    is_vip = models.BooleanField(default=False)
    first_seen_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_vip", "display_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["space", "display_name"], name="uniq_person_per_space_name"
            )
        ]

    def __str__(self):
        return f"{self.display_name}{' (VIP)' if self.is_vip else ''}"


class Message(models.Model):
    """
    Represents one raw message pulled from a provider. This is the highest-volume
    table in the system and the one the user is deliberately never shown in bulk.

    Messages exist to be grouped, summarized, and cited -- not read. `raw` keeps
    the provider's original payload so a summary can be regenerated later without
    re-fetching, and `is_noise` marks what the pipeline judged not worth surfacing.
    """

    connection = models.ForeignKey(Connection, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(
        Person,
        # PROTECT: a person's message history is real data. Deleting a Person must
        # not silently erase every message they ever sent; Django raises
        # ProtectedError and forces the caller to deal with the messages first.
        on_delete=models.PROTECT,
        related_name="messages",
    )
    external_id = models.CharField(max_length=200, help_text="The provider's own message id.")
    scope_name = models.CharField(
        max_length=200, blank=True,
        help_text="Channel/label the message arrived in, denormalized from the provider.",
    )
    sent_at = models.DateTimeField()
    body = models.TextField()
    permalink = models.URLField(blank=True)
    is_noise = models.BooleanField(default=False)
    raw = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-sent_at"]
        constraints = [
            # The idempotency guarantee: a sync can run repeatedly, crash halfway,
            # and re-run from the start without duplicating a single row.
            models.UniqueConstraint(
                fields=["connection", "external_id"], name="uniq_message_per_connection"
            )
        ]
        indexes = [
            # Every ingest and every brief query filters this way.
            models.Index(fields=["connection", "sent_at"], name="idx_message_conn_sent"),
        ]

    def __str__(self):
        preview = self.body[:40] + ("..." if len(self.body) > 40 else "")
        return f"{self.author.display_name}: {preview}"


class Brief(models.Model):
    """
    Represents one generated read of a Space over a time window -- the artifact the
    whole product exists to produce.

    Briefs are stored rather than rendered on demand because generating one is
    expensive and because a brief is a record of what the user was told at a
    particular moment. `message_count` and `topic_count` live on the row so the
    "212 messages became 18 topics" claim survives even after the underlying
    messages are archived.

    `steps` records the generation stages the waiting screen shows. It is a field
    rather than a table because those rows are written once, read once, and never
    queried across briefs.
    """

    class Trigger(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        ON_DEMAND = "on_demand", "On demand"

    class Status(models.TextChoices):
        BUILDING = "building", "Building"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    space = models.ForeignKey(Space, on_delete=models.CASCADE, related_name="briefs")
    window_start = models.DateTimeField()
    window_end = models.DateTimeField()
    trigger = models.CharField(max_length=16, choices=Trigger.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.BUILDING)
    headline = models.CharField(
        max_length=200, blank=True,
        help_text='The one line at the top, e.g. "Three things need you before noon."',
    )
    message_count = models.PositiveIntegerField(default=0)
    topic_count = models.PositiveIntegerField(default=0)
    read_seconds = models.PositiveIntegerField(default=0, help_text="Estimated time to read.")
    steps = models.JSONField(
        default=list, blank=True,
        help_text=(
            'Generation progress for the waiting screen, e.g. '
            '[{"label":"Reading 212 messages","status":"done","ms":3100}].'
        ),
    )
    model_version = models.CharField(max_length=80, blank=True)
    generated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-window_end"]
        constraints = [
            # Scheduled briefs are unique per window: the 8am brief must not be
            # generated twice. On-demand briefs are deliberately exempt, because a
            # user asking "catch me up" twice in an hour is a legitimate request.
            models.UniqueConstraint(
                fields=["space", "window_start", "window_end"],
                condition=Q(trigger="scheduled"),
                name="uniq_scheduled_brief_per_window",
            )
        ]

    def __str__(self):
        return f"{self.space} brief to {self.window_end:%b %d %H:%M}"


class BriefItem(models.Model):
    """
    Represents one thing on a brief: a subject, placed in a lane, at a rank, with a
    summary, the messages that justify it, and a state the user can change.

    `lane` and `rank` are stored, not computed at render time. That is the whole
    argument of the product: the system commits to an ordering, so the brief a user
    opens at noon says the same thing it said at 8am, and a ranking that looks
    wrong later can be examined rather than guessed at.

    `messages` is the receipts. Every sentence in `summary` should be supported by
    something in that set, which is what makes the brief checkable instead of
    merely plausible. `primary_message` is the one quoted on the detail screen.
    """

    class Lane(models.TextChoices):
        NEEDS_YOU = "needs_you", "Needs you"
        MOVING = "moving", "Moving without you"
        FYI = "fyi", "FYI"

    class State(models.TextChoices):
        OPEN = "open", "Open"
        HANDLED = "handled", "Handled"
        SNOOZED = "snoozed", "Snoozed"
        DISMISSED = "dismissed", "Dismissed"

    brief = models.ForeignKey(Brief, on_delete=models.CASCADE, related_name="items")
    title = models.CharField(max_length=200, help_text="The subject this item is about.")
    messages = models.ManyToManyField(
        Message, related_name="brief_items", blank=True,
        help_text="The receipts: every message this item's summary rests on.",
    )
    primary_message = models.ForeignKey(
        Message,
        # SET_NULL: the lead quote is a presentation choice. Losing the quoted
        # message must not delete the item or its other citations.
        on_delete=models.SET_NULL,
        null=True, blank=True, related_name="lead_for_items",
    )
    lane = models.CharField(max_length=16, choices=Lane.choices)
    rank = models.PositiveIntegerField()
    summary = models.TextField()
    why = models.TextField(blank=True, help_text="Why this surfaced -- shown on demand.")
    deadline_at = models.DateTimeField(null=True, blank=True)
    state = models.CharField(max_length=16, choices=State.choices, default=State.OPEN)
    handled_at = models.DateTimeField(null=True, blank=True)
    snoozed_until = models.DateTimeField(null=True, blank=True)

    # --- what you can do about it, and what you started writing ---
    actions = models.JSONField(
        default=list, blank=True,
        help_text=(
            'Offered actions, e.g. '
            '[{"kind":"reply","label":"Reply to Prof. Ramirez","primary":true}].'
        ),
    )
    draft_body = models.TextField(blank=True, help_text="A reply composed but not yet sent.")
    draft_sent_at = models.DateTimeField(null=True, blank=True)

    # --- the learning signal, kept as counters rather than an event table ---
    open_count = models.PositiveIntegerField(default=0)
    feedback = models.SmallIntegerField(
        default=0, help_text="-1 thumbs down, 0 none, +1 thumbs up."
    )

    class Meta:
        # Lane order then rank: exactly the reading order of screens 6, 9 and 10.
        ordering = ["lane", "rank"]
        constraints = [
            # One item per slot. Two items claiming the same lane and rank would
            # leave the reading order undefined, which defeats storing it at all.
            models.UniqueConstraint(fields=["brief", "lane", "rank"], name="uniq_slot_per_brief"),
            # And one item per subject per brief: the same thing said twice.
            models.UniqueConstraint(fields=["brief", "title"], name="uniq_title_per_brief"),
        ]

    def __str__(self):
        return f"[{self.get_lane_display()} #{self.rank}] {self.title}"
