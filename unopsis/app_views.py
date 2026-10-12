"""
The wireframe UI: the pages a person using Unopsis actually sees (docs/wireframes/v2).

The course pages in views.py -- the four view kinds, insights, reports, Vega-Lite and the APIs --
are untouched. Everything here is new and lives under /signup/, /login/, /setup/, /work/,
/personal/, /app/ and /journey/. Every page reads real rows; nothing is copied from the mockups.

Two deliberate limits until Assignment 5:
  * there is no login, so ui.current_space() picks the first space of a kind;
  * nothing is ever sent anywhere. Buttons that would act outside Unopsis (Connect, Forward,
    Reconnect) are rendered disabled; "Copy & open" copies to the clipboard and opens the
    original message, which is the read-only promise the wireframe makes.
"""

from django.shortcuts import render


def coming_soon(request, task="a later task", **kwargs):
    """Temporary target for routes whose screen is not built yet. Task 11 proves none remain."""
    return render(request, "unopsis/app/coming_soon.html", {"task": task})


def signup(request):
    """Screen 1, "Create account" page. Static until A5: the page submits nothing."""
    return render(request, "unopsis/app/auth.html", {"mode": "signup"})


def login_page(request):
    """Screen 1, "Sign in" page. Named login_page so it never shadows django.contrib.auth.login."""
    return render(request, "unopsis/app/auth.html", {"mode": "login"})
