"""
Views for Unopsis.

Part A -- the four view kinds (previous assignment). The same domain model (BriefItem, one
ranked card on a brief) shown four ways:

    1. item_list_manual   function-based view, loads the template by hand + HttpResponse
    2. item_list_render   function-based view, render() shortcut
    3. ItemListBaseView   class-based view, inherits from View and queries by hand
    4. ItemListView       class-based generic view (ListView), plus ItemDetailView (DetailView)

All four list views send the SAME context to the SAME template
(templates/unopsis/briefitem_list.html), so the template does not care how the data arrived.

Part B -- this assignment:

    home              (/)                     the home page, so the root URL is not a 404
    BriefListView     (/briefs/)              list of briefs, each linking to its detail page
    BriefDetailView   (/briefs/<pk>/)         detail by primary key, and a POST form that
                                              CREATES an item on that brief
    InsightsView      (/insights/)            ORM search: a GET form (shareable) and a POST
                                              form (deliberately not shareable), plus the
                                              aggregations

ItemDetailView also gained a post() so one item's state and draft reply can be changed.
"""

from django.contrib import messages as flash
from django.db.models import Avg, Case, Count, IntegerField, Q, TextField, Value, When
from django.db.models.functions import Cast
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.template import loader
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView

from .forms import BriefItemCreateForm, ItemSearchForm, ItemUpdateForm, PrivateLookupForm
from .models import Brief, BriefItem, Connection, Message, Person, Provider, Space

LIST_TEMPLATE = "unopsis/briefitem_list.html"

# BriefItem.lane is text, so ordering by it alphabetically would put "fyi" first and
# "needs_you" last. The product wants Needs-you first, so we rank the lanes explicitly here.
LANE_PRIORITY = Case(
    When(lane=BriefItem.Lane.NEEDS_YOU, then=Value(0)),
    When(lane=BriefItem.Lane.MOVING, then=Value(1)),
    default=Value(2),
    output_field=IntegerField(),
)


def filtered_items(request):
    """
    The one query every list view shares.

    Returns BriefItems with the work brief first, then Needs-you -> Moving -> FYI, then by the
    stored rank. Optional filters come from the query string: ?state=snoozed or ?lane=fyi.
    A filter that matches nothing is how we reach the empty state on the page.
    """
    items = (
        BriefItem.objects.select_related("brief__space")
        .annotate(lane_priority=LANE_PRIORITY)
        .order_by("-brief__space__kind", "lane_priority", "rank")
    )
    state = request.GET.get("state")
    lane = request.GET.get("lane")
    if state:
        items = items.filter(state=state)
    if lane:
        items = items.filter(lane=lane)
    return items


def active_filters(request):
    """The filters currently applied, so the template can explain an empty list."""
    filters = {}
    for name in ("state", "lane"):
        if request.GET.get(name):
            filters[name] = request.GET[name]
    return filters


def list_context(request, view_label):
    """The context dictionary shared by views 1, 2 and 3 (view 4 builds the same keys itself)."""
    return {
        "items": filtered_items(request),
        "filters": active_filters(request),
        "view_label": view_label,
    }


# --------------------------------------------------------------------------------------
# 1. Function-based view, manual: load the template yourself, render it, wrap in HttpResponse
# --------------------------------------------------------------------------------------
def item_list_manual(request):
    """
    Shows every stage of what Django normally hides:
      1. loader.get_template() finds the HTML file,
      2. template.render() fills it with the context,
      3. HttpResponse wraps the finished HTML for the browser.
    """
    template = loader.get_template(LIST_TEMPLATE)
    context = list_context(request, "Function-based view: HttpResponse (manual)")
    output = template.render(context, request)
    return HttpResponse(output)


# --------------------------------------------------------------------------------------
# 2. Function-based view, shortcut: render() does the three steps above in one call
# --------------------------------------------------------------------------------------
def item_list_render(request):
    """Same page as view 1 with render(request, template, context): load + fill + wrap."""
    context = list_context(request, "Function-based view: render() shortcut")
    return render(request, LIST_TEMPLATE, context)


# --------------------------------------------------------------------------------------
# 3. Class-based view, base: inherit from View and write get() yourself
# --------------------------------------------------------------------------------------
class ItemListBaseView(View):
    """
    The base View knows nothing about our model, so we query it ourselves inside get().
    (`model = BriefItem` would do nothing here. That is what the generic view adds.)
    """

    def get(self, request):
        context = list_context(request, "Class-based view: base View")
        return render(request, LIST_TEMPLATE, context)


# --------------------------------------------------------------------------------------
# 4. Class-based view, generic: ListView / DetailView do the querying and template lookup
# --------------------------------------------------------------------------------------
class ItemListView(ListView):
    """
    model = BriefItem is enough for ListView to fetch rows and to find its template by
    convention: <app>/<model>_list.html  ->  unopsis/briefitem_list.html.
    We only override get_queryset (to reuse the Needs-you-first ordering and the filters) and
    name the context variable `items` so it matches the shared template.
    """

    model = BriefItem
    context_object_name = "items"

    def get_queryset(self):
        return filtered_items(self.request)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filters"] = active_filters(self.request)
        context["view_label"] = "Class-based view: generic ListView"
        return context


class ItemDetailView(DetailView):
    """
    One card in full, including its "receipts" (the messages it was built from).
    Default template by convention: unopsis/briefitem_detail.html, with the object as `item`.
    """

    model = BriefItem
    context_object_name = "item"

    def get_queryset(self):
        return BriefItem.objects.select_related(
            "brief__space", "primary_message"
        ).prefetch_related("messages__author", "messages__connection")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # The bound form is put in the context on a failed POST (see post()); on a GET we
        # build it fresh from the row so the fields show what is currently stored.
        context.setdefault("form", ItemUpdateForm(instance=self.object))
        return context

    # ---- the CBV handling input: GET renders, POST writes -----------------------------
    def post(self, request, *args, **kwargs):
        """
        A DetailView is GET-only out of the box; adding post() is all it takes to make the
        same class handle input.

        This is the modifying half of the GET/POST split: it changes a row, so it must be
        POST (never a link), it must carry {% csrf_token %}, and it finishes with a redirect
        rather than a rendered page -- the Post/Redirect/Get pattern -- so that refreshing the
        result cannot submit the same change a second time.
        """
        self.object = self.get_object()
        form = ItemUpdateForm(request.POST, instance=self.object)
        if form.is_valid():
            item = form.save(commit=False)
            # Stamp the clock fields the form does not expose.
            if item.state == BriefItem.State.HANDLED and not item.handled_at:
                item.handled_at = timezone.now()
            if item.state != BriefItem.State.HANDLED:
                item.handled_at = None
            item.save()
            flash.success(request, f"Saved \u201c{item.title}\u201d as {item.get_state_display()}.")
            # get_absolute_url() again: the model knows where it lives, so the redirect
            # does not have to name a route.
            return redirect(item.get_absolute_url())
        context = self.get_context_data(object=self.object, form=form)
        return self.render_to_response(context)


# ======================================================================================
# PART B -- SECTION 1: the home page and the brief pages (URL linking and navigation)
# ======================================================================================
def home(request):
    """
    The home page, wired to "" in unopsis/urls.py so the root address is a real page instead
    of Django's "page not found" list.

    It is also the shortest end-to-end demonstration of the flow the assignment asks for:

        models.py    Brief / BriefItem / Message define the data and get_absolute_url()
        urls.py      path("", views.home, name="home") gives that view an address and a name
        views.py     this function queries the models and builds a context dict
        templates/   unopsis/home.html renders the context and links onward with {% url %}
                     and {{ item.get_absolute_url }}
    """
    briefs = (
        Brief.objects.select_related("space", "space__user")
        .annotate(item_count=Count("items", distinct=True))
        .order_by("-window_end")
    )
    context = {
        "briefs": briefs[:4],
        # Needs-you items only, best rank first: the three things the product exists to say.
        "urgent_items": (
            BriefItem.objects.filter(lane=BriefItem.Lane.NEEDS_YOU)
            .exclude(state=BriefItem.State.DISMISSED)
            .select_related("brief__space")
            .order_by("rank")[:3]
        ),
        # A LIST of (label, number) pairs rather than a dict: in a template, {{ totals.items }}
        # would look up the dict KEY "items" before it ever reached dict.items().
        "totals": [
            ("Spaces", Space.objects.count()),
            ("Connections", Connection.objects.count()),
            ("People", Person.objects.count()),
            ("Messages", Message.objects.count()),
            ("Briefs", Brief.objects.count()),
            ("Brief items", BriefItem.objects.count()),
        ],
    }
    return render(request, "unopsis/home.html", context)


class BriefListView(ListView):
    """
    Every brief, newest first, with the number of items on it computed in the database rather
    than by calling .items.count() once per row in the template.
    """

    model = Brief
    context_object_name = "briefs"
    template_name = "unopsis/brief_list.html"

    def get_queryset(self):
        return (
            Brief.objects.select_related("space", "space__user")
            .annotate(
                item_count=Count("items", distinct=True),
                needs_you_count=Count(
                    "items", filter=Q(items__lane=BriefItem.Lane.NEEDS_YOU), distinct=True
                ),
            )
            .order_by("-window_end")
        )


class BriefDetailView(DetailView):
    """
    One brief by primary key: /briefs/<int:pk>/.

    The pk in the URL is the whole point of the section -- DetailView reads it from the URL
    kwargs, fetches that row (404 if it does not exist), and the template links back out with
    {{ brief.get_absolute_url }} and {{ item.get_absolute_url }}.

    It also carries the CREATE form (Section 5): GET renders it empty, POST validates and
    saves a new BriefItem attached to this brief.
    """

    model = Brief
    context_object_name = "brief"
    template_name = "unopsis/brief_detail.html"

    def get_queryset(self):
        return Brief.objects.select_related("space", "space__user").prefetch_related("items")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault("create_form", BriefItemCreateForm(brief=self.object))
        context["items"] = (
            self.object.items.annotate(lane_priority=LANE_PRIORITY)
            .annotate(receipt_count=Count("messages"))
            .order_by("lane_priority", "rank")
        )
        return context

    def post(self, request, *args, **kwargs):
        """POST creates an item on this brief. The brief comes from the URL, not the form."""
        self.object = self.get_object()
        form = BriefItemCreateForm(request.POST, brief=self.object)
        if form.is_valid():
            item = form.save()
            flash.success(request, f"Added \u201c{item.title}\u201d to this brief.")
            return redirect(self.object.get_absolute_url())
        flash.error(request, "That item could not be added -- see the errors below.")
        return self.render_to_response(self.get_context_data(create_form=form))


# ======================================================================================
# PART B -- SECTION 2 + 5: ORM queries, the GET form, the POST form, and aggregations
# ======================================================================================
def search_items(cleaned):
    """
    Turn the cleaned GET form into one queryset, one Django field lookup at a time.

    Lookups used here, which is the list the assignment asks to see:

        __icontains   case-insensitive substring          title / summary / person name
        __exact       equality (the default lookup)       lane, state
        __lte         less than or equal                  rank
        __isnull      NULL or not                         deadline_at
        __in          membership in a list                lanes shown on the chart
        field__field  spanning a relationship with __     brief__space__kind,
                                                          messages__author__display_name

    Everything is chained onto ONE queryset, so Django sends a single SQL query with an AND
    of the conditions; nothing is evaluated until the template iterates it.
    """
    items = (
        BriefItem.objects.select_related("brief__space")
        .annotate(lane_priority=LANE_PRIORITY)
        .order_by("-brief__space__kind", "lane_priority", "rank")
    )

    q = cleaned.get("q")
    if q:
        # Q objects let one search box cover three columns with OR.
        items = items.filter(
            Q(title__icontains=q) | Q(summary__icontains=q) | Q(why__icontains=q)
        )
    if cleaned.get("lane"):
        items = items.filter(lane__exact=cleaned["lane"])
    if cleaned.get("state"):
        items = items.filter(state__exact=cleaned["state"])
    if cleaned.get("space"):
        # Relationship spanning: BriefItem -> Brief -> Space, two hops with __.
        items = items.filter(brief__space__kind__exact=cleaned["space"])
    if cleaned.get("author"):
        # Spanning a many-to-many and then a foreign key: item -> messages -> author.
        # .distinct() because a join across a to-many relation repeats the item once per
        # matching message.
        items = items.filter(
            messages__author__display_name__icontains=cleaned["author"]
        ).distinct()
    if cleaned.get("max_rank"):
        items = items.filter(rank__lte=cleaned["max_rank"])
    if cleaned.get("due_only"):
        items = items.filter(deadline_at__isnull=False)
    return items


# Human-readable names for the stored codes ("needs_you" -> "Needs you"). Templates cannot
# index a dict by a variable, so the labels are attached to each aggregation row below.
LANE_LABELS = dict(BriefItem.Lane.choices)
STATE_LABELS = dict(BriefItem.State.choices)
SPACE_LABELS = dict(Space.Kind.choices)
PROVIDER_LABELS = dict(Provider.choices)


def label_rows(rows, key, labels):
    """Attach a display label to each GROUP BY row, so the template can just print it."""
    for row in rows:
        row["label"] = labels.get(row[key], row[key] or "Unknown")
    return rows


def aggregate_summaries():
    """
    The aggregation half of Section 2.

    * a TOTAL with .count() / .aggregate(), which collapses a queryset to one number, and
    * GROUPED summaries with .values(...).annotate(Count(...)), which is Django's GROUP BY:
      values() names the grouping columns, annotate() is the aggregate per group.
    """
    return {
        # --- totals ---
        "total_items": BriefItem.objects.count(),
        "total_messages": Message.objects.count(),
        "total_noise": Message.objects.filter(is_noise=True).count(),
        "total_briefs": Brief.objects.count(),
        "avg_items_per_brief": (
            Brief.objects.annotate(n=Count("items")).aggregate(avg=Avg("n"))["avg"] or 0
        ),
        # --- grouped: items per lane (GROUP BY lane) ---
        "by_lane": label_rows(
            list(
                BriefItem.objects.values("lane")
                .annotate(total=Count("id"))
                .order_by("-total")
            ),
            "lane", LANE_LABELS,
        ),
        # --- grouped: items per space kind, spanning two relationships ---
        "by_space": label_rows(
            list(
                BriefItem.objects.values("brief__space__kind")
                .annotate(total=Count("id"))
                .order_by("-total")
            ),
            "brief__space__kind", SPACE_LABELS,
        ),
        # --- grouped: messages per provider, spanning Message -> Connection ---
        "by_provider": label_rows(
            list(
                Message.objects.values("connection__provider")
                .annotate(total=Count("id"))
                .order_by("-total")
            ),
            "connection__provider", PROVIDER_LABELS,
        ),
        # --- grouped: who sends the most, and how much of it is cited in a brief ---
        "by_person": label_rows(
            list(
                Person.objects.values("display_name", "space__kind")
                .annotate(
                    sent=Count("messages", distinct=True),
                    cited=Count("messages__brief_items", distinct=True),
                )
                .filter(sent__gt=0)
                .order_by("-sent")[:6]
            ),
            "space__kind", SPACE_LABELS,
        ),
        # --- grouped: each brief with its item count and its receipt count ---
        "by_brief": list(
            Brief.objects.select_related("space")
            .annotate(
                item_count=Count("items", distinct=True),
                receipt_count=Count("items__messages", distinct=True),
            )
            .order_by("-window_end")
        ),
    }


class InsightsView(ListView):
    """
    The page that carries Sections 2 and 5 at once: a list, a GET search, a POST lookup and
    the aggregation summaries.

    Adapted CBV: ListView normally answers GET only. get_queryset() reads request.GET, and
    post() below handles request.POST on the same URL -- one class, two methods, two very
    different jobs.
    """

    model = BriefItem
    context_object_name = "items"
    template_name = "unopsis/insights.html"

    def get_queryset(self):
        """
        GET: the search that IS the link.

        The form is bound to request.GET, so /insights/?q=deadline&lane=needs_you can be
        bookmarked, shared, or reloaded and returns the same rows every time. Nothing here
        writes, so there is no harm in the browser re-issuing it.
        """
        self.search_form = ItemSearchForm(self.request.GET or None)
        if self.request.GET and self.search_form.is_valid():
            return search_items(self.search_form.cleaned_data)
        return search_items({})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["search_form"] = self.search_form
        context.setdefault("lookup_form", PrivateLookupForm())
        context.setdefault("lookup_results", None)
        context.setdefault("lookup_ran", False)
        context["summaries"] = aggregate_summaries()
        context["lane_labels"] = LANE_LABELS
        context["state_labels"] = STATE_LABELS
        context["space_labels"] = SPACE_LABELS
        context["provider_labels"] = PROVIDER_LABELS
        # Which GET parameters are actually in play, for the "showing N of M" line and the
        # {% empty %} explanation.
        context["active_filters"] = {
            key: value for key, value in self.request.GET.items() if value
        }
        return context

    def post(self, request, *args, **kwargs):
        """
        POST: the search that must NOT be a link.

        Looking somebody up by the handle they are reached on -- a mobile number, a personal
        address -- is still only a read, so it is not POST for safety of the database. It is
        POST so the query stays out of the URL: out of the address bar during a screen share,
        out of browser history, out of bookmarks, out of the server's access log, and out of
        any link a teammate could be sent. GET would turn "everything Mom sent me" into a
        shareable address, which is the opposite of what this product promises.

        The response is rendered, not redirected, precisely because there is no address that
        could carry the result.
        """
        form = PrivateLookupForm(request.POST)
        results = None
        if form.is_valid():
            handle = form.cleaned_data["handle"].strip()
            # Person.handles is a JSONField (a list). Cast it to text so a plain icontains
            # works on SQLite as well as on Postgres.
            people = (
                Person.objects.annotate(handles_text=Cast("handles", TextField()))
                .filter(Q(handles_text__icontains=handle)
                        | Q(display_name__icontains=handle))
                .select_related("space")
                .annotate(message_count=Count("messages", distinct=True))
            )
            results = {
                "handle": handle,
                "people": list(people),
                # Items whose receipts cite a message written by one of those people.
                "items": list(
                    BriefItem.objects.filter(messages__author__in=people)
                    .select_related("brief__space")
                    .distinct()
                    .order_by("lane", "rank")
                ),
                "messages": list(
                    Message.objects.filter(author__in=people)
                    .select_related("author", "connection")
                    .order_by("-sent_at")[:10]
                ),
            }
        self.object_list = self.get_queryset()
        context = self.get_context_data(
            lookup_form=form, lookup_results=results, lookup_ran=True
        )
        return self.render_to_response(context)
