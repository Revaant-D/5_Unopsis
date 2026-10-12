"""
Routes for the wireframe UI (app_views.py), included from inboxtriage/urls.py beside
unopsis/urls.py. Every name starts with "app-" so it can never collide with a course route.

    /signup/  /login/                          app-signup, app-login     static until A5
    /setup/world|sources|scope|tuning/         app-setup-*               the four setup steps
    /work/brief/building/                      app-work-building         first-run screen
    /work/brief/                               app-work-brief            today's brief
    /work/brief/item/<pk>/                     app-work-focus            one decision at a time
    /work/needs-you/                           app-work-needs-you        -> first open item
    /work/handled/                             app-work-handled          the wrap-up
    /<work|personal>/thread/<pk>/              app-thread                receipts + reply draft
    /personal/catchup/building/                app-personal-building
    /personal/catchup/                         app-personal-catchup
    /personal/caught-up/                       app-personal-caught-up
    /app/items/<pk>/action/                    app-item-action           POST only
    /journey/                                  app-journey               every screen in order
"""

from django.urls import path, register_converter

from . import app_views


class WorldConverter:
    """Matches only "work" or "personal", so /elsewhere/thread/1/ is a 404 before any view runs."""

    regex = "work|personal"

    def to_python(self, value):
        return value

    def to_url(self, value):
        return value


register_converter(WorldConverter, "world")

soon = app_views.coming_soon

urlpatterns = [
    path("signup/", app_views.signup, name="app-signup"),
    path("login/", app_views.login_page, name="app-login"),
    path("setup/world/", app_views.setup_world, name="app-setup-world"),
    path("setup/sources/", app_views.setup_sources, name="app-setup-sources"),
    path("setup/scope/", app_views.setup_scope, name="app-setup-scope"),
    path("setup/tuning/", app_views.setup_tuning, name="app-setup-tuning"),
    path("work/brief/building/", app_views.building, {"kind": "work"}, name="app-work-building"),
    path("work/brief/", app_views.work_brief, name="app-work-brief"),
    path("work/brief/item/<int:pk>/", app_views.focus, name="app-work-focus"),
    path("work/needs-you/", app_views.needs_you, name="app-work-needs-you"),
    path("work/handled/", app_views.handled, name="app-work-handled"),
    path("<world:kind>/thread/<int:pk>/", app_views.thread, name="app-thread"),
    path("personal/catchup/building/", app_views.building, {"kind": "personal"},
         name="app-personal-building"),
    path("personal/catchup/", soon, {"task": "Task 9"}, name="app-personal-catchup"),
    path("personal/caught-up/", soon, {"task": "Task 9"}, name="app-personal-caught-up"),
    path("app/items/<int:pk>/action/", app_views.item_action, name="app-item-action"),
    path("journey/", soon, {"task": "Task 10"}, name="app-journey"),
]
