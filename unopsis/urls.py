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

]
