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

    # django.contrib.sites (Assignment 5, Part 2). Not something this project wants for its
    # own sake -- there is one site -- but allauth is written to work either way and turning
    # it on is the configuration every allauth tutorial, and the project brief, describes.
    # What it actually changes: allauth looks up social applications stored in the DATABASE
    # with SocialApp.objects.on_site(request), i.e. filtered to the Site whose id is SITE_ID.
    # Our Google credentials do NOT come from the database (see SOCIALACCOUNT_PROVIDERS at
    # the bottom of this file), so that filter has nothing to do today. It matters the moment
    # somebody prefers to type the client id into /admin/ instead: then the SocialApp row has
    # to be attached to the Site row, and that Site row's domain has to be the deployed one.
    # docs/a5/google-oauth-setup.md spells that out, because a mismatch there makes the
    # Google button disappear in production with no error message anywhere.
    'django.contrib.sites',

    # Unopsis's core domain app: ingestion, contacts, threads, summaries.
    'unopsis',

    # django-allauth (Assignment 5, Part 2): "Continue with Google".
    #   allauth                  the shared machinery (adapters, rate limits, internal URLs)
    #   allauth.account          email/username accounts -- we keep our own login and signup
    #                            pages in front of it, but allauth needs this app to exist
    #   allauth.socialaccount    the SocialAccount/SocialApp/SocialToken models that link a
    #                            Google identity to a django.contrib.auth User
    #   ...providers.google      the one provider we actually use. Providers are separate
    #                            apps on purpose: installing fifty of them would publish
    #                            fifty sets of /accounts/<provider>/login/ routes.
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
]

# Which Site row is "this site". Required by django.contrib.sites; 1 is the row its own
# migration creates. The row's domain starts life as "example.com" and is only consulted for
# database-backed social applications, which this project does not use -- see the note above.
SITE_ID = 1

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    # allauth, and it is not optional: allauth.account.apps.AccountConfig.ready() raises
    # ImproperlyConfigured if this line is missing, so every management command -- including
    # `check` and `test` -- dies at startup rather than at the first login. It sits directly
    # after AuthenticationMiddleware because it works with request.user (it finishes
    # interrupted sign-up flows and makes sure a stale allauth redirect cannot be replayed),
    # and request.user does not exist until the line above has run.
    'allauth.account.middleware.AccountMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Lets other sites (the Vega-Lite editor, classmates' pages) read /api/ and /vega-lite/.
    'unopsis.middleware.PublicApiCorsMiddleware',
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


# ---------------------------------------------------------------------------------------
# Authentication (Assignment 5, Part 1)
# ---------------------------------------------------------------------------------------
# Three settings, and between them they are the whole conversation Django has with a visitor
# who is not logged in. They live in base.py rather than in development.py/production.py
# because the answer is the same on a laptop and on the deployed site -- the route NAMES are
# stable even though the host is not, which is also why every value here is a name from
# unopsis/urls.py and not a path. Change the address of the login page there and these three
# follow; hard-coded "/accounts/login/" strings would not.
#
#   LOGIN_URL            where @login_required and LoginRequiredMixin send an anonymous
#                        visitor, with ?next=<the page they asked for> appended so they land
#                        on the thing they wanted instead of the home page after logging in.
#   LOGIN_REDIRECT_URL   where LoginView goes after a successful log in when there is no
#                        ?next= to honour. Home, because it is the page that then shows the
#                        real data it hides from a stranger.
#   LOGOUT_REDIRECT_URL  where LogoutView goes afterwards. Home again -- and home must stay
#                        reachable logged out, or signing out would bounce straight back to
#                        the login page and look like the sign-out failed.
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'home'
LOGOUT_REDIRECT_URL = 'home'

# allauth reads its own name for the same idea. Setting it keeps "Sign out" from an allauth
# page (the social-signup or authentication-error pages, which we do not hand-write) landing
# somewhere different from the Log out button in the navigation bar.
ACCOUNT_LOGOUT_REDIRECT_URL = 'home'


# ---------------------------------------------------------------------------------------
# What a brand-new account is given (Assignment 5)
# ---------------------------------------------------------------------------------------
# A5 scoped every queryset in unopsis/views.py to the requesting user, which is what stops one
# signed-in account reading another's briefs. The cost of getting that right is that a new
# account owns nothing and therefore sees nothing: it signs in, the navigation fills with
# links, and every one of them leads to an empty page. The account most likely to meet that
# is the grader's, created the first time anybody clicks "Continue with Google" on the
# deployed domain.
#
# With this on, each account is given its OWN copy of the demo rows when it is created --
# their own Spaces, their own briefs, nothing shared and nothing leaked. unopsis/onboarding.py
# explains the alternatives that were rejected and why.
#
# Off (SEED_NEW_ACCOUNTS=False in .env) is the right setting the day this holds data somebody
# cares about, when handing every sign-up a pile of invented messages stops being hospitable.
SEED_NEW_ACCOUNTS = env.bool('SEED_NEW_ACCOUNTS', default=True)


# ---------------------------------------------------------------------------------------
# Who is allowed to say "this is who I am" (Assignment 5, Part 2)
# ---------------------------------------------------------------------------------------
# Django ships ONE authentication backend by default and does not write the setting down.
# The moment a second way to sign in exists, the list has to be spelled out, and leaving it
# out is the classic allauth failure: everything looks configured, Google's consent screen
# appears, the callback comes back -- and the final login() raises
# "no authentication backend" because the social account was verified by a backend Django was
# never told about. There is no earlier warning.
#
# Order is not cosmetic. django.contrib.auth.login() and the test client's force_login() both
# fall back to AUTHENTICATION_BACKENDS[0] when nobody names a backend, so ModelBackend goes
# first: username-and-password is this project's primary login, and the eighty-odd existing
# tests sign in that way.
AUTHENTICATION_BACKENDS = [
    # Username + password against the User table. Part 1's login page.
    'django.contrib.auth.backends.ModelBackend',
    # A user already verified by allauth (i.e. by Google). It does not check passwords; it
    # exists so that login() has a backend to record on the session for a social sign-in.
    'allauth.account.auth_backends.AuthenticationBackend',
]


# ---------------------------------------------------------------------------------------
# django-allauth: account behaviour
# ---------------------------------------------------------------------------------------
# Scope first, because it explains why there is so little here. This project keeps its OWN
# login and signup pages (unopsis/auth_views.py, templates/registration/) in front of
# /accounts/login/ and /accounts/signup/, so most of allauth's account machinery is never
# reached by a human. These settings govern the one path that does run through it: somebody
# arriving from Google for the first time, whose account allauth has to create.
#
# Every name below is the one allauth 65 actually wants. The older names
# (ACCOUNT_AUTHENTICATION_METHOD, ACCOUNT_USERNAME_REQUIRED, ACCOUNT_EMAIL_REQUIRED, ...) are
# what most tutorials still show, and allauth now answers each of them with a Django
# system-check Warning -- which means `manage.py check` stops being clean, under both settings
# modules, and the CI workflow that runs it goes yellow for a configuration that works.
# Verified against allauth/account/checks.py in the installed version, not from memory.

# How somebody proves who they are: by username. A set, not a string -- {"username", "email"}
# would accept either. Must intersect with the required fields below or allauth raises
# account.W001.
ACCOUNT_LOGIN_METHODS = {'username'}

# The fields allauth's own signup form would collect; '*' means required. 'password1' and
# 'password2' (never 'password' -- allauth answers that with a CRITICAL check that hard-fails
# `manage.py check`) are the two password boxes. Email is required so that a Google identity
# and a local account can be recognised as the same person later.
ACCOUNT_SIGNUP_FIELDS = ['username*', 'email*', 'password1*', 'password2*']

# No confirmation email. This is a deployment fact, not laziness: the default is 'optional',
# which sends mail through the configured EMAIL_BACKEND on every signup, and this project has
# no mail server -- on PythonAnywhere that send raises mid-POST and the signup page answers
# 500. Nothing here is protected strongly enough to be worth a mailbox the site cannot reach.
ACCOUNT_EMAIL_VERIFICATION = 'none'

# One account per email address. Required if 'email' is ever added to ACCOUNT_LOGIN_METHODS
# (allauth raises a CRITICAL check otherwise), and sensible now: it is what stops two people
# signing in with the same Google address and getting two different sets of briefs.
ACCOUNT_UNIQUE_EMAIL = True

# Where mail goes: the console (i.e. the server log), everywhere, on purpose.
#
# This project cannot send email. Django's default EMAIL_BACKEND is SMTP against localhost:25,
# which on a laptop and on PythonAnywhere alike means a ConnectionRefusedError raised in the
# middle of a POST -- an HTTP 500 on a form that otherwise worked. Part 1 avoided the problem
# by publishing no password-reset routes; Part 2's include("allauth.urls") brings allauth's
# own back (/accounts/password/reset/ and the email-management pages), and they are reachable
# by anyone who types the address even though nothing links to them.
#
# The console backend turns "crash" into "write the message to the log". That is not the same
# as working -- a password-reset link printed into a server log reaches nobody -- and it is
# not pretended to be: the honest fix is an SMTP service, which is out of scope for this
# assignment. It is chosen because a dead end is a smaller failure than a 500, and because it
# makes the flow testable: in development the reset email appears in the terminal running
# runserver, link and all.
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Do not keep Google's access/refresh tokens. False is already the default; it is written
# down because this repository COMMITS db.sqlite3, so a token stored in that table would be
# pushed to GitHub. We only need Google to tell us who somebody is, once, at sign-in; we
# never call a Google API on their behalf afterwards.
SOCIALACCOUNT_STORE_TOKENS = False


# ---------------------------------------------------------------------------------------
# django-allauth: the Google application
# ---------------------------------------------------------------------------------------
# The client id and secret identify THIS site to Google. They come from .env (and are empty
# in a fresh clone), never from a tracked file and -- deliberately -- never from the database:
# allauth can read either, and the database would be the more convenient choice if db.sqlite3
# were not committed to this repository. It is, so a SocialApp row holding the secret would be
# published to GitHub the next time anyone commits the demo data. Settings + .env keeps the
# secret in exactly one place that git never sees.
#
# Pick ONE source, not both: allauth blends the settings-backed apps and the database-backed
# ones, finds two Google applications, and raises MultipleObjectsReturned at login time.
GOOGLE_OAUTH_CLIENT_ID = env('GOOGLE_OAUTH_CLIENT_ID', default='')
GOOGLE_OAUTH_CLIENT_SECRET = env('GOOGLE_OAUTH_CLIENT_SECRET', default='')

SOCIALACCOUNT_PROVIDERS = {
    'google': {
        # What we ask Google for: the name and picture ('profile') and the verified email
        # address ('email'). Nothing else -- no Gmail, no Drive, no contacts. A narrower scope
        # is a shorter consent screen, which is also a consent screen people say yes to.
        'SCOPE': ['profile', 'email'],
        # 'online' means: do not issue a refresh token. We are not acting on the user's behalf
        # while they are away, so a long-lived credential would be a liability with no use.
        'AUTH_PARAMS': {'access_type': 'online'},
        # PKCE. The authorization code that comes back through the browser is useless to
        # anybody who intercepts it without the verifier this server kept. Google supports it;
        # there is no reason not to.
        'OAUTH_PKCE_ENABLED': True,
    },
}

# The credentials are attached ONLY when both halves are present, and this `if` is the whole
# graceful-degradation story:
#
#   * with them, allauth lists a Google application, the provider appears in
#     {% get_providers %}, and templates/registration/_google_button.html renders a working
#     "Continue with Google" button;
#   * without them, allauth lists no application at all, {% get_providers %} comes back empty
#     and the same template renders a disabled button with a one-line explanation.
#
# The alternative -- always declaring APP and letting client_id be "" -- is worse in exactly
# the places it matters: a fresh clone, and the CI machine that has no .env, would both offer
# a live-looking button that sends the grader to a Google error page. And the inverse,
# declaring nothing and letting the template call {% provider_login_url 'google' %} anyway,
# raises SocialApp.DoesNotExist mid-render, i.e. HTTP 500 on the login page itself.
if GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET:
    SOCIALACCOUNT_PROVIDERS['google']['APP'] = {
        'client_id': GOOGLE_OAUTH_CLIENT_ID,
        'secret': GOOGLE_OAUTH_CLIENT_SECRET,
        # Unused by OAuth2 providers (it is there for the ones that need a third value), but
        # allauth reads the key, so an explicit empty string beats a KeyError.
        'key': '',
    }


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
#
# Organisation: ONE project-level static/ folder rather than a static/ folder inside each app.
# This project has a single app (unopsis) and a single look, so an app-level folder would add a
# directory level without adding an owner. Files are namespaced by type inside it:
#
#     static/css/unopsis.css     the site stylesheet
#     static/img/unopsis-logo.svg the header mark
#     static/js/vega-charts.js   embeds the Vega-Lite charts from their spec URLs
#
# Templates always reference them through {% load static %} + {% static 'css/unopsis.css' %},
# never as a hard-coded "/static/css/unopsis.css", so STATIC_URL can change (to a CDN, say)
# without editing a template.

# The public URL prefix the browser asks for.
STATIC_URL = 'static/'

# Where Django LOOKS for static files in development (in addition to each app's static/).
STATICFILES_DIRS = [BASE_DIR / 'static']

# Where `python manage.py collectstatic` COPIES them for a real web server to serve.
# It is generated output, so it is git-ignored and never edited by hand.
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ---------------------------------------------------------------------------------------
# Assignment 6: AI features (see README_AI.md and unopsis/ai/)
# ---------------------------------------------------------------------------------------
# Feature 1, local: a Hugging Face model run with `transformers`. The weights are downloaded
# automatically into the Hugging Face cache the first time the AI lab is used, never into the
# repository. The default is the size-vs-quality "sweet spot" from llm-test/ai_prototype.ipynb.
AI_LOCAL_MODEL = env('AI_LOCAL_MODEL', default='Qwen/Qwen2.5-1.5B-Instruct')
# False skips the local model entirely (the rule-based triage answers instead). Set it to
# False on PythonAnywhere, whose free plan cannot install torch.
AI_LOCAL_ENABLED = env.bool('AI_LOCAL_ENABLED', default=True)
AI_LOCAL_MAX_NEW_TOKENS = env.int('AI_LOCAL_MAX_NEW_TOKENS', default=80)
# How many worked examples go into the triage prompt: 0 zero-shot, 1 one-shot, 4 few-shot,
# 8 many-shot. Few-shot won the notebook's Route A comparison.
AI_TRIAGE_SHOTS = env.int('AI_TRIAGE_SHOTS', default=4)
# The hybrid pipeline triages at most this many messages per brief (CPU time per request).
AI_PIPELINE_MAX_MESSAGES = env.int('AI_PIPELINE_MAX_MESSAGES', default=12)

# Feature 2, external: Groq's OpenAI-compatible API (free tier). Key from console.groq.com/keys.
GROQ_API_KEY = env('GROQ_API_KEY', default='')
GROQ_MODEL = env('GROQ_MODEL', default='openai/gpt-oss-20b')
GROQ_TIMEOUT_SECONDS = env.int('GROQ_TIMEOUT_SECONDS', default=20)

# Guardrail: model runs per signed-in account per minute, across both features.
AI_REQUESTS_PER_MINUTE = env.int('AI_REQUESTS_PER_MINUTE', default=10)
