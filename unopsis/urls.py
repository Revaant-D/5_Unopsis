"""
URL routes for the unopsis app. Every route has a name= so templates can link to it with
{% url 'name' %} and the address can change later without touching any HTML.
"""

from django.urls import path

from . import views

urlpatterns = [
    # 1. Function-based view, HttpResponse (manual)
    path("items/manual/", views.item_list_manual, name="item-list-manual"),
    # 2. Function-based view, render() shortcut
    path("items/render/", views.item_list_render, name="item-list-render"),
    # 3. Class-based view, base View
    path("items/cbv-base/", views.ItemListBaseView.as_view(), name="item-list-cbv-base"),
    # 4. Class-based views, generic (list + detail)
    path("items/cbv-generic/", views.ItemListView.as_view(), name="item-list-cbv-generic"),
    path("items/<int:pk>/", views.ItemDetailView.as_view(), name="item-detail"),
]
