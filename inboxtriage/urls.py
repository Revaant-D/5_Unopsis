"""
URL configuration for inboxtriage project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('unopsis.urls')),   # all unopsis routes live in unopsis/urls.py

    # ---- Assignment 5, Part 2: django-allauth ----------------------------------------
    # Mounted at /accounts/, which is also where our own three authentication routes live
    # (unopsis/urls.py: login, signup, logout). That overlap is intentional and the ORDER is
    # what makes it safe: Django tries these patterns top to bottom, unopsis.urls is tried
    # first, so /accounts/login/ and /accounts/signup/ keep rendering OUR pages and only the
    # addresses unopsis.urls does not claim fall through to allauth. In particular:
    #
    #     /accounts/google/login/            name=google_login     -> off to Google
    #     /accounts/google/login/callback/   name=google_callback  -> back from Google
    #
    # The callback is the address that has to be registered, character for character, in the
    # Google Cloud console -- see docs/a5/google-oauth-setup.md. It is a relative path, so
    # nothing here knows or needs the deployed hostname: allauth builds the absolute URL from
    # the incoming request, and production.py's SECURE_PROXY_SSL_HEADER is what makes that
    # come out as https:// behind PythonAnywhere's proxy. Google rejects an http:// redirect
    # URI on a public domain, so that one line in production.py is load-bearing here too.
    #
    # Two more names arrive with this include and are reached only by allauth itself:
    # /accounts/3rdparty/ (socialaccount_connections) and the social signup / authentication
    # error pages, which wear the site's chrome thanks to templates/allauth/layouts/base.html.
    #
    # It is included AFTER unopsis.urls rather than before for one more reason: allauth also
    # publishes password-reset and email-management routes at this prefix. Any that unopsis
    # does not shadow stay reachable, which is harmless, but none of them may be allowed to
    # take over the two pages this assignment asks us to write ourselves.
    path('accounts/', include('allauth.urls')),
]
