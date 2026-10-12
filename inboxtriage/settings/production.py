"""
Production settings: used on the live server.

Run locally to test production mode:
    python manage.py runserver --settings=inboxtriage.settings.production
(wsgi.py and asgi.py use this module by default.)
"""

# Start from everything in base.py, then override what differs for production.
from .base import *
from inboxtriage.secrets_environment import env

# SECURITY WARNING: never run with DEBUG=True on a public site. With DEBUG=False Django shows
# a plain error page instead of leaking file paths, settings and code to visitors.
DEBUG = False

# With DEBUG=False Django refuses to serve any host that is not listed here.
# The list comes from ALLOWED_HOSTS in .env (comma-separated), so a real domain can be added
# at deployment without editing code. It defaults to localhost so production mode can be
# tried on a laptop.
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['localhost', '127.0.0.1'])

# PythonAnywhere ends HTTPS at its own proxy and passes the request on to Django over plain
# HTTP, telling it the original scheme in the X-Forwarded-Proto header. Trusting that header
# makes request.is_secure() and build_absolute_uri() say "https" -- which matters for
# /vega-lite/<chart>.json, whose data.url is built from the request: an http:// URL there
# would be blocked as mixed content when the spec is opened in the (https) Vega-Lite editor.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# ---------------------------------------------------------------------------------------
# CSRF over HTTPS behind a proxy (Assignment 5, Part 1)
# ---------------------------------------------------------------------------------------
# Log in, sign up and log out are the first POSTs this site accepts from the deployed domain,
# and Django 4+ checks more than the CSRF token on them: for an HTTPS request it also compares
# the Origin header against CSRF_TRUSTED_ORIGINS, and rejects anything unlisted with
# "Origin checking failed". The symptom is the one that looks like a broken deployment --
# every page works until you try to log in, and then the login form 403s.
#
# The list is DERIVED from ALLOWED_HOSTS rather than written out, for two reasons. The
# deployed hostname is not known while this is being built, and nothing in version control is
# allowed to carry it; and a second hard-coded copy of a domain is a second place to forget to
# change. One line in the server's .env (ALLOWED_HOSTS=...) now configures both.
#
# https:// only: the deployed site is served over TLS and PythonAnywhere terminates it at the
# proxy above, so an http:// origin arriving for one of our hostnames is not a request we want
# to accept a password on. Django requires the scheme on every entry, which is why "https://"
# is prepended rather than the host being listed bare.
#
# Wildcard ALLOWED_HOSTS entries ("*", ".example.com") are dropped: they are host patterns,
# not origins, and "https://.example.com" is not an origin any browser will ever send.
CSRF_TRUSTED_ORIGINS = [
    f"https://{host}" for host in ALLOWED_HOSTS if not host.startswith(("*", "."))
]

# ---------------------------------------------------------------------------------------
# HTTPS-only cookies (Assignment 5, Part 1)
# ---------------------------------------------------------------------------------------
# A5 is the release where the session cookie starts carrying an identity. Before it, the
# cookie held a flash message and a CSRF token; now it is the single credential that says
# "this request is that person", for the whole of its lifetime. The difference matters because
# a cookie without the Secure flag is sent on a plain-HTTP request to the same host, in
# cleartext, where anybody on the path can read it and replay it -- and replaying a session
# cookie needs no password, defeats "Continue with Google" exactly as thoroughly as it defeats
# a typed password, and leaves nothing in any log to notice.
#
# This is a production-only block because every flag in it breaks http://127.0.0.1: the
# browser would simply decline to store a Secure cookie, so logging in locally would fail with
# no error anywhere -- the form would post, the response would redirect, and the next request
# would arrive signed out.
#
# SECURE_PROXY_SSL_HEADER above is what makes these work at all behind PythonAnywhere, which
# terminates TLS at its proxy and forwards plain HTTP: without it Django would believe every
# request was insecure, refuse to set the cookies, and SECURE_SSL_REDIRECT would redirect to
# https in an endless loop. The two settings are a pair; do not keep one without the other.
#
# HTTPS_ONLY is the escape hatch for the one legitimate case where production settings run
# without TLS: trying production mode on a laptop, which README.md documents
# (`runserver --settings=inboxtriage.settings.production`). Set HTTPS_ONLY=False in .env for
# that, and leave it alone -- i.e. True -- on the server. It is a boolean, not a hostname, so
# nothing here needs to know the deployed domain.
HTTPS_ONLY = env.bool('HTTPS_ONLY', default=True)

# The session cookie is the credential. Secure keeps it off plain HTTP; HttpOnly keeps it out
# of document.cookie, so an XSS bug becomes a defacement rather than an account takeover.
# HttpOnly is already Django's default and is pinned here because a default that is load-
# bearing should be written down -- nothing in this project ever reads the session from
# JavaScript, so there is no cost to saying so.
SESSION_COOKIE_SECURE = HTTPS_ONLY
SESSION_COOKIE_HTTPONLY = True

# The CSRF cookie is not a credential, but an attacker who can read it over plain HTTP can
# forge a POST that passes the CSRF check -- which in this project means the item-update and
# item-create forms, and the log-out form.
CSRF_COOKIE_SECURE = HTTPS_ONLY

# Upgrade any request that does arrive over plain HTTP, rather than serving it. Without this
# the flags above are a quiet refusal: the browser is told the cookies are HTTPS-only and then
# left on an HTTP page where it cannot send them, which looks like a broken login rather than
# like a security setting doing its job.
SECURE_SSL_REDIRECT = HTTPS_ONLY

# SECURE_HSTS_SECONDS is deliberately NOT set, and `check --deploy` will keep saying so.
# HSTS tells every browser that has ever visited to refuse plain HTTP for this host for the
# next N seconds, and it is cached by the browser, not by us: set it with a wrong value, or on
# a hostname that later needs to serve anything over HTTP, and there is no server-side change
# that undoes it for the people who already have it. It is the right setting once the deployed
# domain is final and confirmed to serve HTTPS -- which is, on purpose, a decision for the
# person who knows the domain, not a line committed by somebody who does not.

# Same SQLite file for now; a real production database can be swapped in here later
# without touching development settings.
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}


# ---------------------------------------------------------------------------------------
# Cache busting for static files
# ---------------------------------------------------------------------------------------
# The problem: a browser is told to cache /static/css/unopsis.css for a long time (that is the
# whole point of a static file). Ship a new stylesheet at the same address and returning
# visitors keep the old one until the cache expires -- the site looks broken for exactly the
# people who use it most.
#
# The fix: change the address whenever the bytes change. ManifestStaticFilesStorage hashes the
# contents of each file during `collectstatic` and writes a copy with the hash in its name:
#
#     static/css/unopsis.css  ->  staticfiles/css/unopsis.6fd1a0e94b2c.css
#
# It records the mapping in staticfiles.json, and {% static 'css/unopsis.css' %} then renders
# the hashed name. A new release produces a new hash, which is a new URL, which no browser has
# cached, so the update is picked up immediately -- while the old URL stays cacheable forever.
# Nothing in any template changes; the tag does the lookup.
#
# This is production-only on purpose: in development the file should be re-read on every
# refresh, and the manifest would mean re-running collectstatic after every CSS edit.
#
# One wrinkle. staticfiles.json only exists after collectstatic has run, and Django's stock
# ManifestStaticFilesStorage treats a missing entry as a fatal ValueError -- raised by the
# {% static %} tag mid-render, so a fresh clone started in production mode answers HTTP 500 on
# every HTML page instead of merely looking unstyled. We therefore point at our own subclass,
# which keeps the hashing and only softens that one failure; inboxtriage/staticfiles_storage.py
# explains the trade in full. Run collectstatic anyway -- README.md lists it as a required step
# before production mode -- this just stops forgetting it from taking the site down.
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'inboxtriage.staticfiles_storage.ResilientManifestStaticFilesStorage',
    },
}
