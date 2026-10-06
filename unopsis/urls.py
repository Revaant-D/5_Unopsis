"""
URL routes for the unopsis app.

Every route has a name= so templates link to it with {% url 'name' %} and models can reverse
it in get_absolute_url(). The address can then change here without touching a single template.

    /                        home                  the home page (Section 1)
    /briefs/                 brief-list
    /briefs/<pk>/            brief-detail          detail by primary key + POST create form
    /items/manual/           item-list-manual      the four view kinds from the last assignment
    /items/render/           item-list-render
    /items/cbv-base/         item-list-cbv-base
    /items/cbv-generic/      item-list-cbv-generic
    /items/<pk>/             item-detail           detail by primary key; BriefItem.get_absolute_url()
    /insights/               insights              GET search + POST lookup + aggregations
    /insights/lanes.png      chart-lanes           matplotlib bar chart, served as image/png
    /insights/providers.png  chart-providers       matplotlib pie chart, served as image/png
    /api/items/              api-items             JSON, function-based view
    /api/items/cbv/          api-items-cbv         JSON, class-based view
    /api/insights/           api-insights          JSON aggregations
    /api/insights/items-by-lane/    api-items-by-lane     chart 1's feed: a flat JSON array
    /api/insights/messages-by-hour/ api-messages-by-hour  chart 2's feed: a flat JSON array
    /api/items.txt           api-items-text        the same data via HttpResponse (text/plain)
    /api/items.csv           api-items-csv         the same data via HttpResponse (text/csv)
    /reports/                reports               grouped summaries + the two download buttons
    /export/brief-items.csv  export-items-csv      every BriefItem, downloadable CSV
    /export/brief-items.json export-items-json     every BriefItem, downloadable pretty JSON
    /api/deadlines/holidays/ api-deadline-holidays external API: Nager.Date public holidays
                                                    and long weekends, triangulated against
                                                    BriefItem.deadline_at
    /vega-lite/<chart>/      vega-chart-page       one Vega-Lite chart on its own page
    /vega-lite/<chart>.json  vega-chart-spec       that chart's spec, data.url made absolute
    /vega-lite/<chart>.png   vega-chart-png        that chart rendered to PNG on the server
                             (<chart> is chart1 or chart2; anything else is a 404)

Ordering note: /items/<int:pk>/ is last among the /items/ routes on purpose. Django matches
top to bottom, and <int:pk> cannot swallow "manual" or "render" because those are not integers,
but keeping the literal paths above the variable one is the habit that stops the bug the day
the converter becomes <slug:...>.
"""

from django.urls import path

from . import views

urlpatterns = [
    # ---- Section 1: home and the brief pages ----
    path("", views.home, name="home"),
    path("briefs/", views.BriefListView.as_view(), name="brief-list"),
    path("briefs/<int:pk>/", views.BriefDetailView.as_view(), name="brief-detail"),

    # ---- the four view kinds (previous assignment, unchanged) ----
    # 1. Function-based view, HttpResponse (manual)
    path("items/manual/", views.item_list_manual, name="item-list-manual"),
    # 2. Function-based view, render() shortcut
    path("items/render/", views.item_list_render, name="item-list-render"),
    # 3. Class-based view, base View
    path("items/cbv-base/", views.ItemListBaseView.as_view(), name="item-list-cbv-base"),
    # 4. Class-based views, generic (list + detail)
    path("items/cbv-generic/", views.ItemListView.as_view(), name="item-list-cbv-generic"),
    path("items/<int:pk>/", views.ItemDetailView.as_view(), name="item-detail"),

    # ---- Sections 2 + 5: ORM search (GET), private lookup (POST), aggregations ----
    path("insights/", views.InsightsView.as_view(), name="insights"),

    # ---- Section 4: charts served straight off a URL, like /sections/enrollment.png ----
    path("insights/lanes.png", views.lane_chart_png, name="chart-lanes"),
    path("insights/providers.png", views.provider_chart_png, name="chart-providers"),

    # ---- Section 6: the JSON API ----
    path("api/items/", views.api_items, name="api-items"),
    path("api/items/cbv/", views.ItemsApiView.as_view(), name="api-items-cbv"),
    path("api/insights/", views.api_insights, name="api-insights"),
    # Chart-ready feeds for Vega-Lite: bare arrays of flat records, nothing to unwrap.
    path("api/insights/items-by-lane/", views.api_items_by_lane, name="api-items-by-lane"),
    path("api/insights/messages-by-hour/", views.api_messages_by_hour,
         name="api-messages-by-hour"),
    # Same data, different Content-Type, to show what JsonResponse is actually doing.
    path("api/items.txt", views.api_items_text, name="api-items-text"),
    path("api/items.csv", views.api_items_csv, name="api-items-csv"),

    # ---- Assignment 4, Part 3: the reports page and the two file exports ----
    # The exports live under /export/ rather than /api/ on purpose: /api/ answers machines
    # and returns a filtered feed, /export/ answers a person clicking a button and returns a
    # whole, timestamped snapshot that lands in their Downloads folder. The .csv and .json
    # endings are part of the address so the link looks like the file it produces.
    path("reports/", views.reports, name="reports"),
    path("export/brief-items.csv", views.export_items_csv, name="export-items-csv"),
    path("export/brief-items.json", views.export_items_json, name="export-items-json"),

    # ---- external API integration: a public holiday calendar, called live, never stored ----
    path("api/deadlines/holidays/", views.deadline_holidays, name="api-deadline-holidays"),

    # ---- Assignment 4, Part 1: every Vega-Lite chart as a page, a spec and an image ----
    # <str:chart> stops at "/" but not at ".", so "chart1.json" binds chart="chart1".
    path("vega-lite/<str:chart>/", views.vega_chart_page, name="vega-chart-page"),
    path("vega-lite/<str:chart>.json", views.vega_chart_spec, name="vega-chart-spec"),
    path("vega-lite/<str:chart>.png", views.vega_chart_png, name="vega-chart-png"),
]
