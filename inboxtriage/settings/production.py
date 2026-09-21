"""
Production settings: used on the live server.

Run locally to test production mode:
    python manage.py runserver --settings=inboxtriage.settings.production
(wsgi.py and asgi.py use this module by default.)
"""

# Start from everything in base.py, then override what differs for production.
from .base import *

# SECURITY WARNING: never run with DEBUG=True on a public site. With DEBUG=False Django shows
# a plain error page instead of leaking file paths, settings and code to visitors.
DEBUG = False

# With DEBUG=False Django refuses to serve any host that is not listed here.
# Replace these with the real domain(s) when deploying.
ALLOWED_HOSTS = ['localhost', '127.0.0.1']

# Same SQLite file for now; a real production database can be swapped in here later
# without touching development settings.
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}
