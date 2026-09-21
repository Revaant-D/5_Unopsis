"""
Django Admin for Unopsis.

Registered so the whole spine can be walked in a browser: pick a Space, see its
Connections and People, open a Brief, and follow one BriefItem down to the actual
messages that justify it.

Message is deliberately search-first rather than browsable -- it is the one table
meant to be large, and paging through it is not something anyone should do.
"""

from django.contrib import admin
from django.utils import timezone

from .models import Brief, BriefItem, Connection, Message, Person, Space


class ConnectionInline(admin.TabularInline):
    model = Connection
    extra = 0
    fields = ("provider", "external_account", "status", "read_only", "last_synced_at")


class PersonInline(admin.TabularInline):
    model = Person
    extra = 0
    fields = ("display_name", "handles", "is_vip")


class BriefItemInline(admin.TabularInline):
    model = BriefItem
    extra = 0
    fields = ("lane", "rank", "title", "summary", "state", "deadline_at")
    # Summaries are generated; editing them here would desync an item from the
    # messages cited as its evidence.
    readonly_fields = ("summary",)
    ordering = ("lane", "rank")


@admin.register(Space)
class SpaceAdmin(admin.ModelAdmin):
    list_display = ("__str__", "kind", "user", "connection_count", "people_count",
                    "detail_level", "last_brief")
    list_filter = ("kind",)
    inlines = [ConnectionInline, PersonInline]
    fieldsets = (
        (None, {"fields": ("user", "kind")}),
        ("Delivery", {"fields": ("detail_level", "quiet_start", "quiet_end",
                                 "deliver_in_app", "deliver_email", "deliver_chat_dm",
                                 "digest_times")}),
        ("Surfacing rules", {"fields": ("rules",)}),
    )

    @admin.display(description="Connections")
    def connection_count(self, obj):
        return obj.connections.count()

    @admin.display(description="People")
    def people_count(self, obj):
        return obj.people.count()

    @admin.display(description="Last brief")
    def last_brief(self, obj):
        brief = obj.briefs.first()  # ordering is -window_end
        return brief.window_end if brief else "--"


@admin.register(Connection)
class ConnectionAdmin(admin.ModelAdmin):
    list_display = ("external_account", "provider", "space", "status", "scope_count",
                    "read_only", "last_synced_at")
    list_filter = ("provider", "status", "space__kind")
    search_fields = ("external_account", "display_name")
    actions = ["sync_now"]

    @admin.display(description="Included scopes")
    def scope_count(self, obj):
        return len(obj.included_scopes or [])

    @admin.action(description="Sync now")
    def sync_now(self, request, queryset):
        """Stamps last_synced_at, standing in for the real sync job."""
        n = queryset.update(last_synced_at=timezone.now(), last_error="")
        self.message_user(request, f"Marked {n} connection(s) as just synced.")


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ("display_name", "space", "is_vip", "handle_list", "message_count")
    list_filter = ("is_vip", "space__kind")
    search_fields = ("display_name",)
    list_editable = ("is_vip",)

    @admin.display(description="Handles")
    def handle_list(self, obj):
        return ", ".join(obj.handles) if obj.handles else "--"

    @admin.display(description="Messages")
    def message_count(self, obj):
        return obj.messages.count()


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    """Search-first: this table is meant to be large, so browsing it is not offered."""

    list_display = ("__str__", "author", "connection", "scope_name", "sent_at", "is_noise")
    list_filter = ("is_noise", "connection__provider", "connection")
    search_fields = ("body", "author__display_name", "external_id")
    raw_id_fields = ("connection", "author")
    readonly_fields = ("raw",)
    date_hierarchy = "sent_at"
    show_full_result_count = False


@admin.register(Brief)
class BriefAdmin(admin.ModelAdmin):
    """The useful one: the funnel from raw messages down to ranked items."""

    list_display = ("__str__", "space", "status", "trigger", "funnel", "window_end", "generated_at")
    list_filter = ("status", "trigger", "space__kind")
    inlines = [BriefItemInline]
    actions = ["regenerate"]

    @admin.display(description="messages -> topics -> items")
    def funnel(self, obj):
        return f"{obj.message_count} -> {obj.topic_count} -> {obj.items.count()}"

    @admin.action(description="Regenerate")
    def regenerate(self, request, queryset):
        """Marks briefs for rebuild; the real pipeline would pick these up."""
        n = queryset.update(status=Brief.Status.BUILDING, generated_at=None)
        self.message_user(request, f"Marked {n} brief(s) for regeneration.")


@admin.register(BriefItem)
class BriefItemAdmin(admin.ModelAdmin):
    list_display = ("__str__", "brief", "lane", "rank", "state", "cited", "deadline_at", "feedback")
    list_filter = ("lane", "state", "brief__space__kind")
    search_fields = ("title", "summary")
    # The receipts, made easy to inspect and edit in the browser.
    filter_horizontal = ("messages",)
    raw_id_fields = ("brief", "primary_message")
    fieldsets = (
        (None, {"fields": ("brief", "title", "lane", "rank", "state")}),
        ("The read", {"fields": ("summary", "why", "deadline_at")}),
        ("Receipts", {"fields": ("primary_message", "messages")}),
        ("Actions and reply", {"fields": ("actions", "draft_body", "draft_sent_at")}),
        ("Signal", {"fields": ("open_count", "feedback", "handled_at", "snoozed_until")}),
    )

    @admin.display(description="Citations")
    def cited(self, obj):
        return obj.messages.count()
