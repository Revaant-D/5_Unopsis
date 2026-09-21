"""
Views for Unopsis: the same domain model (BriefItem, one ranked card on a brief) shown in the
four styles this assignment asks for.

    1. item_list_manual   function-based view, loads the template by hand + HttpResponse
    2. item_list_render   function-based view, render() shortcut
    3. ItemListBaseView   class-based view, inherits from View and queries by hand
    4. ItemListView       class-based generic view (ListView), plus ItemDetailView (DetailView)

All four list views send the SAME context to the SAME template
(templates/unopsis/briefitem_list.html), so the template does not care how the data arrived.
"""

from django.db.models import Case, IntegerField, Value, When
from django.http import HttpResponse
from django.shortcuts import render
from django.template import loader
from django.views import View
from django.views.generic import DetailView, ListView

from .models import BriefItem

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
