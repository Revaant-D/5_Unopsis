"""
Settings shared by every environment (development and production).

Anything that differs between environments (DEBUG, ALLOWED_HOSTS, DATABASES) lives in
development.py or production.py, which start with `from .base import *`.
"""

from pathlib import Path

# The `.env` reader (see inboxtriage/secrets_environment.py). Secrets never appear in code.
from inboxtriage.secrets_environment import env

# SECURITY: the signing key comes from .env, never from source control.
# The project refuses to start if SECRET_KEY is missing.
SECRET_KEY = env('SECRET_KEY')

# Example third-party API key. A dummy value is fine until something actually calls the API.
OPENAI_API_KEY = env('OPENAI_API_KEY', default='')

# Build paths inside the project like this: BASE_DIR / 'subdir'.
# This file now lives at <project>/inboxtriage/settings/base.py, one folder deeper than the
# old settings.py, so we need one more .parent to climb back up to the folder with manage.py.
BASE_DIR = Path(__file__).resolve().parent.parent.parent


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Unopsis's core domain app: ingestion, contacts, threads, summaries.
    'unopsis',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'inboxtriage.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        # Project-level templates/ folder (templates/base.html, templates/unopsis/...).
        # Without this Django only looks inside each app and raises TemplateDoesNotExist.
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'inboxtriage.wsgi.application'


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = 'static/'

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
