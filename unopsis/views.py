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
    BriefDetailView   (/briefs/<pk>/)         one brief by primary key
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
"""

from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.http import HttpResponse
from django.shortcuts import render
from django.template import loader
from django.views import View
from django.views.generic import DetailView, ListView

from .models import Brief, BriefItem, Connection, Message, Person, Space

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

    """

    model = Brief
    context_object_name = "brief"
    template_name = "unopsis/brief_detail.html"

    def get_queryset(self):
        return Brief.objects.select_related("space", "space__user").prefetch_related("items")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["items"] = (
            self.object.items.annotate(lane_priority=LANE_PRIORITY)
            .annotate(receipt_count=Count("messages"))
            .order_by("lane_priority", "rank")
        )
        return context
