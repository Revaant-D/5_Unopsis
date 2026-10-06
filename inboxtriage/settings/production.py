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
