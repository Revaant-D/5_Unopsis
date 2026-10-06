"""
Development settings: used on a developer's own machine.

Run with the default:   python manage.py runserver
(manage.py points at this module unless told otherwise.)
"""

# Start from everything in base.py, then override what differs for development.
from .base import *

# SECURITY WARNING: DEBUG=True shows detailed error pages (file paths, settings, code).
# That is helpful on your laptop and dangerous on a public server, so it is True ONLY here.
DEBUG = True

ALLOWED_HOSTS = ['localhost', '127.0.0.1']

# Local SQLite file in the project root. Unusually, this file IS committed to the repository
# (Assignment 4 asks for it, and .gitignore says why), so a fresh clone already has the demo
# data and needs no `migrate` + `seed_demo` before the pages show anything.
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}
