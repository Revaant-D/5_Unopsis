# 5_Unopsis

**Team 5, INFO 490.** Unopsis collects a person's notifications from every place they arrive
(Gmail, Outlook, Slack, Discord, WhatsApp, iMessage) and turns them into one short, ranked
"brief" in which every item can be traced back to the real messages behind it.

- Django project: `inboxtriage` (settings, URLs)
- Django app: `unopsis` (models, admin, views, templates)
- Design docs, wireframes, branching strategy and weekly notes live in [`docs/`](docs/)
- The site is navigable from the home page at `/`: briefs, brief items, a search-and-insights
  page with live matplotlib and Vega-Lite charts, a reports page with CSV/JSON exports, and a
  public JSON API that also checks deadlines against a live public-holiday calendar.
- `/` is the product page for a visitor (a signed-in user goes straight to `/work/brief/`); the
  course dashboard that used to be the home page is at `/under-the-hood/`. A visitor's only way
  into the app is **Sign in** or **Create account**: the "Open the app" shortcuts appear only
  once signed in.
- **The app itself** -- the screens from the wireframes -- starts at `/work/brief/`; `/journey/`
  links every screen in order. See **The app (wireframe UI)** below.
- **AI (Assignment 6)**: message triage with a local Hugging Face model and brief writing with
  the Groq API, at `/ai/` (**AI lab** in the navigation once signed in). The workflow,
  preprocessing and guardrails are in [`README_AI.md`](README_AI.md); the 15-model benchmark is
  [`llm-test/ai_prototype.ipynb`](llm-test/ai_prototype.ipynb).

---

## Setup

Requires **Python 3.11+**.

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # Mac / Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create your local .env (it is git-ignored and never committed)
copy .env.example .env            # Windows
# cp .env.example .env            # Mac / Linux
#    then open .env and replace SECRET_KEY with a fresh value:
python -c "import secrets; print(secrets.token_urlsafe(50))"

# 4. The database is ALREADY in the repo -- `db.sqlite3` is committed on purpose (see
#    .gitignore for why), so the demo data is there the moment you clone. Just apply any
#    migrations that landed after it was last committed:
python manage.py migrate

# 5. Run it
python manage.py runserver
```

> **Why is a database file in version control?** Normally it should not be: a database is data,
> not code. Assignment 4 asks for this one specifically, so that the graded site has its demo
> content without anyone having to seed it first. `.gitignore` carries the same note, so nobody
> "tidies it up" by re-ignoring the file.

If you ever need to rebuild the data from nothing — which replaces a tracked file, so tell the
team first:

```bash
rm db.sqlite3
python manage.py migrate
python manage.py createsuperuser  # use username: mohitg2  (the demo data is owned by this user)
python manage.py seed_demo                 # seeds mohitg2 by default
python manage.py seed_demo --user somebody # or any other existing account
```

Since A5 the demo data belongs to **one account at a time**, because every queryset is scoped
to its owner. `seed_demo` gives one user their own set; signing up on the site does the same
thing automatically for the new account (`SEED_NEW_ACCOUNTS`, see **Environment variables**).

Before committing `db.sqlite3` &mdash; which this repository does on purpose &mdash; run:

```bash
python manage.py scrub_db          # report what must not be committed
python manage.py scrub_db --apply  # empty django_session
```

A Django `session_key` *is* the value of the `sessionid` cookie, so a committed session row is
a password-free login to the deployed site for anybody who can read the repository. Every
`runserver` you log into writes one. `manage.py clearsessions` is not a substitute: it removes
only sessions that have already expired, which is exactly the set that cannot be replayed.

## Running: development and production settings

Settings are split into `inboxtriage/settings/` (`base.py`, `development.py`, `production.py`).

| Mode | Command | `DEBUG` |
|---|---|---|
| **Development** (default for `manage.py`) | `python manage.py runserver` | `True` |
| **Production** | `python manage.py runserver --settings=inboxtriage.settings.production` | `False` |

Once the server is running, open **http://127.0.0.1:8000/** &mdash; the root address is the home
page, and every other page is reachable from the navigation bar. http://127.0.0.1:8000/admin/ is
the admin. All routes are listed under **URL map** below.

**Before running production mode, run `collectstatic` once.** This is a required step, not a
polish step:

```bash
python manage.py collectstatic --settings=inboxtriage.settings.production
```

Production hashes every static file's name for cache busting (see **Static files and the UI**),
and the table of hashes is written by `collectstatic`. Until it exists, `{% static %}` has
nothing to look names up in.

> With `DEBUG=False` Django's development server does not serve static files itself, so pages
> look unstyled in production mode unless you add `--insecure`. That part is expected. What is
> *not* expected is a crash, so `inboxtriage/staticfiles_storage.py` makes a missing hash table
> fall back to the plain filename instead of raising `ValueError` mid-render — without it, a
> fresh clone started in production mode returns **HTTP 500 on every HTML page**. Run
> `collectstatic` anyway; the fallback is a safety net, not the plan.

`wsgi.py` / `asgi.py` (used by real web servers) default to the production settings.

## Environment variables

Secrets are read from `.env` (see `.env.example` for every variable):

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Django's signing key. Required; the project refuses to start without it |
| `OPENAI_API_KEY` | Example third-party key (dummy value for now) |
| `ALLOWED_HOSTS` | Comma-separated hosts allowed in production. Production settings also derive `CSRF_TRUSTED_ORIGINS` from it, so adding the deployed domain here configures both |
| `GOOGLE_OAUTH_CLIENT_ID` | Google OAuth client id (A5 Part 2). Optional: without it the Google button renders disabled and username/password login is unaffected |
| `GOOGLE_OAUTH_CLIENT_SECRET` | The other half of that pair. Never commit it; it is not stored in the database either |
| `SEED_NEW_ACCOUNTS` | Default `True`. Gives each new account its own copy of the demo rows, so a fresh sign-up does not land on an empty site |
| `HTTPS_ONLY` | Default `True`, production settings only. Drives `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` and `SECURE_SSL_REDIRECT`. Set `False` only to try production mode on a laptop |

**No hostname is written into any tracked file.** The deployed domain reaches the code through
`ALLOWED_HOSTS` alone, and the Google redirect URI is built by allauth from the incoming request.
One line in the server's `.env` moves the site to a new domain.

## The app (wireframe UI)

The thirteen screens of the wireframes (`docs/wireframes/v2/`) are built as real pages that read
the same database: a four-step setup, today's work brief, a one-decision focus view, the thread
with its receipts and a copyable reply draft, a wrap-up with Undo, and the personal catch-up. They
live in their own files (`unopsis/app_views.py`, `unopsis/app_urls.py`, `unopsis/ui.py`,
`templates/unopsis/app/`, `static/css/app.css`, `static/js/app.js`), so none of the course code
above changed.

Two limits until Assignment 5: **there is no login yet** (the pages show the first work and
personal space in the database, and `/signup/` and `/login/` submit nothing), and **nothing is
ever sent anywhere** -- buttons that would act outside Unopsis are disabled, and replies are copied
to the clipboard and finished in the original app. Run it the usual way and open `/journey/`.

| URL | Route name | Screen |
|---|---|---|
| `/` | `app-landing` (and `home`) | Product page for a visitor; a signed-in user is redirected to `/work/brief/` |
| `/under-the-hood/` | `under-the-hood` | The course dashboard (`views.home`, unchanged): totals, latest briefs, the four view kinds |
| `/signup/`, `/login/` | `app-signup`, `app-login` | Create account / sign in (static until A5) |
| `/setup/world/` | `app-setup-world` | Setup 1: work, personal or both |
| `/setup/sources/` | `app-setup-sources` | Setup 2: the connected accounts |
| `/setup/scope/` | `app-setup-scope` | Setup 3: the channels and labels that are read |
| `/setup/tuning/` | `app-setup-tuning` | Setup 4: always/never rules, schedule, quiet hours |
| `/work/brief/building/` | `app-work-building` | First run: the stored generation steps, replayed |
| `/work/brief/` | `app-work-brief` | Today's brief (with the sync-error banner when a source fails) |
| `/work/brief/item/<id>/` | `app-work-focus` | One decision at a time; keys J/K move, E done, S snooze |
| `/work/needs-you/` | `app-work-needs-you` | Redirects to the first open item |
| `/work/thread/<id>/`, `/personal/thread/<id>/` | `app-thread` | Receipts in order and the reply draft |
| `/work/handled/` | `app-work-handled` | What is left, what was handled today, Undo |
| `/personal/catchup/building/` | `app-personal-building` | Personal first run |
| `/personal/catchup/` | `app-personal-catchup` | "You were gone N hours." |
| `/personal/caught-up/` | `app-personal-caught-up` | "That was everything." |
| `/app/items/<id>/action/` | `app-item-action` | POST only: handle / snooze / dismiss / reopen |
| `/journey/` | `app-journey` | Every screen in order |

## URL map

Every route has a `name=`, so templates link with `{% url 'name' %}` and models reverse their own
address in `get_absolute_url()`. Nothing in this project hard-codes a path.

| URL | Route name | View | What it is |
|---|---|---|---|
| `/` | `home` | `app_views.landing` (FBV) | The product page (see **The app**). `reverse("home")` is still `/` |
| `/under-the-hood/` | `under-the-hood` | `home` (FBV) | The course dashboard: totals, the latest briefs and the three items that need you |
| `/briefs/` | `brief-list` | `BriefListView` (ListView) | Every brief, with its item count annotated in the database |
| `/briefs/<id>/` | `brief-detail` | `BriefDetailView` (DetailView) | One brief by **primary key**, plus the POST form that creates an item |
| `/items/manual/` | `item-list-manual` | `item_list_manual` (FBV, `HttpResponse`) | The four view kinds from the previous assignment: same list, four ways |
| `/items/render/` | `item-list-render` | `item_list_render` (FBV, `render()`) | |
| `/items/cbv-base/` | `item-list-cbv-base` | `ItemListBaseView` (base `View`) | |
| `/items/cbv-generic/` | `item-list-cbv-generic` | `ItemListView` (`ListView`) | |
| `/items/<id>/` | `item-detail` | `ItemDetailView` (`DetailView`) | One item by **primary key**, its receipts, and a POST form that updates it |
| `/insights/` | `insights` | `InsightsView` (`ListView` + `post()`) | ORM search: a GET form, a POST lookup, and the aggregations |
| `/insights/lanes.png` | `chart-lanes` | `lane_chart_png` | matplotlib bar chart served as `image/png` |
| `/insights/providers.png` | `chart-providers` | `provider_chart_png` | matplotlib pie chart served as `image/png` |
| `/api/items/` | `api-items` | `api_items` (FBV) | JSON API, filtered by query parameters |
| `/api/items/cbv/` | `api-items-cbv` | `ItemsApiView` (CBV) | The same endpoint as a class-based view |
| `/api/insights/` | `api-insights` | `api_insights` (FBV) | The aggregations as JSON |
| `/api/items.txt` | `api-items-text` | `api_items_text` | Same data through `HttpResponse` (`text/plain`) |
| `/api/items.csv` | `api-items-csv` | `api_items_csv` | Same data through `HttpResponse` (`text/csv`) |
| `/api/insights/items-by-lane/` | `api-items-by-lane` | `api_items_by_lane` | Chart 1's data: a flat JSON array, one record per lane |
| `/api/insights/messages-by-hour/` | `api-messages-by-hour` | `api_messages_by_hour` | Chart 2's data: a flat JSON array, one record per hour |
| `/api/deadlines/holidays/` | `api-deadline-holidays` | `deadline_holidays` | External API: open deadlines checked against Nager.Date (`?country=US&bridge_days=1`) |
| `/vega-lite/chart1/`, `/vega-lite/chart2/` | `vega-chart-page` | `vega_chart_page` | Each Vega-Lite chart on its own page |
| `/vega-lite/chart1.json`, `/vega-lite/chart2.json` | `vega-chart-spec` | `vega_chart_spec` | The chart's Vega-Lite spec, `data.url` made absolute |
| `/vega-lite/chart1.png`, `/vega-lite/chart2.png` | `vega-chart-png` | `vega_chart_png` | The same spec rendered to PNG on the server |
| `/reports/` | `reports` | `reports` (FBV) | Grouped summaries in tables, plus the two download buttons |
| `/export/brief-items.csv` | `export-items-csv` | `export_items_csv` | Every item as a timestamped CSV download |
| `/export/brief-items.json` | `export-items-json` | `export_items_json` | The same rows, same order, as a JSON download |

**`get_absolute_url()`** is implemented on `BriefItem` and on `Brief` (`unopsis/models.py`). It
reverses the named route, so templates write `{{ item.get_absolute_url }}` instead of
`{% url 'item-detail' item.pk %}`, the admin's *View on site* button works, and `redirect(item)`
after a POST needs no `success_url`.

**End-to-end flow**, all visible on the dashboard at `/under-the-hood/`: `models.py` (the data and its own URL) →
`urls.py` (the address and its name) → `views.py` (the query and the context) → `templates/`
(the rendering and the links onward).

## Authentication and access (A5 Parts 1 and 2)

| URL | Route name | View | What it is |
|---|---|---|---|
| `/accounts/login/` | `login` | `UnopsisLoginView` | Our login page, with "Continue with Google" |
| `/accounts/signup/` | `signup` | `SignUpView` | Our sign-up page, same Google button |
| `/accounts/logout/` | `logout` | `UnopsisLogoutView` | **POST only** &mdash; Django 5 answers 405 to a GET |
| `/accounts/google/login/` | `google_login` | django-allauth | Off to Google |
| `/accounts/google/login/callback/` | `google_callback` | django-allauth | Back from Google; this is the URI registered in Google Cloud |

The three views are in `unopsis/auth_views.py`; the templates are
`templates/registration/{login,signup}.html` with the button shared in `_google_button.html`.
Log out is a small POST form in the navigation bar rather than a link, because a GET logout can
be fired by any `<img src>` on any page.

**Who can reach what**, in three tiers:

| Tier | What is in it | Logged out |
|---|---|---|
| Public by design | `/`, `/accounts/login/`, `/accounts/signup/`, and **`/api/insights/items-by-lane/`** | 200 |
| Everything else | every page and feed above that returns something a person wrote, including both POST forms | 302 → `/accounts/login/?next=…` |
| Yours only | all of the above, once signed in: every queryset is scoped to the requesting account | &mdash; |

Two details worth knowing before reading the code:

- **The mixin has to be first.** `BriefDetailView(LoginRequiredMixin, DetailView)`, never the
  other way round. Python resolves `dispatch()` left to right, so a mixin listed second never
  runs: the class looks protected, reviews as protected, and serves the page to anybody, with no
  error anywhere.
- **A protected JSON endpoint answers 302, not 401.** That is Django's standard behaviour and
  what `LOGIN_URL` is for, but it means `curl` follows the redirect and prints an HTML login page
  with status 200 &mdash; which reads at a glance as though the endpoint were still open. The
  tests assert the 302 itself (`fetch_redirect_response=False`), which is the honest check.

The navigation in `templates/base.html` is wrapped in `{% if user.is_authenticated %}`, so the
protected links are not shown before login. Hiding a link is not security &mdash; the views are
what turn a request away &mdash; but showing a logged-out stranger a brief headline is a leak
even when the page behind the link would have bounced them.

Google credentials come from `.env` (`GOOGLE_OAUTH_CLIENT_ID` / `_SECRET`) and are never stored
in the database or in any tracked file. With them absent the login and sign-up pages still render
and still work &mdash; the Google button is simply shown disabled with a note saying why. Setup,
including both redirect URIs, is in [`docs/a5/google-oauth-setup.md`](docs/a5/google-oauth-setup.md).

<a id="the-one-public-api-a5-part-3"></a>
### The one public API (A5 Part 3)

`/api/insights/items-by-lane/` is the single endpoint that needs no account. It returns a bare
JSON array of `{lane, label, total}` &mdash; counts only, backed by the real tables, with no
title, no summary, no name, no handle and no timestamp in it. That is *why* it can be published:
not because of who asks, but because of what it answers.

It is the feed behind the submitted Vega-Lite chart
([`docs/a5/vega_lite_chart.txt`](docs/a5/vega_lite_chart.txt)) and the three alternative-use
programs in [`docs/a5/alternative_uses/`](docs/a5/alternative_uses/). Its response shape is a
contract with those files: it is a bare array on purpose, and wrapping it in an object would
make the chart fail by silently rendering empty. `PublicApiSubmissionTests` reads those files on
every test run and checks their field names against what the live view actually returns.

Note that this feed reports **site-wide** counts while every other view reports only your own
rows. That is deliberate and is the reason it is safe to publish: an aggregate over everybody is
not a fact about anybody.

## Searching the data (ORM)

`/insights/` is where the queries live.

* **GET search** &mdash; `?q=`, `?lane=`, `?state=`, `?space=`, `?author=`, `?max_rank=`,
  `?due_only=`. The filters travel in the URL, so the result is a link: bookmark it, reload it,
  send it to a teammate and the same rows come back. Try
  [`/insights/?q=deadline&lane=needs_you`](http://127.0.0.1:8000/insights/?q=deadline&lane=needs_you).
* **POST lookup** &mdash; finds a person by the handle they are reached on (a mobile number, a
  personal address). Still only a read, but the *query* is the sensitive part, so it is sent in
  the request body and the URL stays `/insights/`. Nothing about it can be bookmarked, shared in
  a screen share, or read back out of a web server's access log.
* **Field lookups used**: `__icontains`, `__exact`, `__lte`, `__isnull`, `__in`, and relationship
  spanning with `__` (`brief__space__kind`, `messages__author__display_name`).
* **Aggregations**: totals with `.count()` / `.aggregate(Avg(...))`, and grouped summaries with
  `.values(...).annotate(Count(...))` &mdash; items per lane, items per space, messages per
  provider, messages per person, and items and receipts per brief.

## Static files and the UI

| | |
|---|---|
| Layout | one project-level `static/` folder (`static/css/unopsis.css`, `static/css/app.css`, `static/img/unopsis-logo.svg`, `static/js/vega-charts.js`, `static/js/app.js`) |
| Settings | `STATICFILES_DIRS` and `STATIC_ROOT` in `inboxtriage/settings/base.py` |
| Templates | `{% load static %}` at the top of `base.html`, then `{% static 'css/unopsis.css' %}` |
| Cache busting | `ManifestStaticFilesStorage`, subclassed in `inboxtriage/staticfiles_storage.py`, wired up in `inboxtriage/settings/production.py` |

The stylesheet is layered on top of Bootstrap rather than replacing it. Since the wireframe UI
landed, the whole site uses the wireframe's palette -- warm paper, black for "selected", one blue
accent -- with a serif display face (Fraunces) for the course pages' titles against a humanist sans
(Source Sans 3), the Unopsis logo in the header (served through `{% static %}`), stat tiles, and the
three lane colours (red / blue / green) used consistently on every card. The app screens add
`static/css/app.css` (loaded only by `templates/unopsis/app/shell.html`): the left rail, the
Work/Personal switch, pills, dashed asides and a layout that stacks on phone-width screens.

Cache busting: `collectstatic` hashes each file's contents and writes
`css/unopsis.33e154d07268.css` next to it, recording the mapping in `staticfiles.json`. The
`{% static %}` tag then renders the hashed name, so a new release is a new URL that no browser
has cached, while the old URL stays cacheable forever. Nothing in any template changes.

```bash
python manage.py collectstatic --settings=inboxtriage.settings.production
```

## Charts

`/insights/lanes.png` and `/insights/providers.png` are Django views that return a real PNG:
the ORM computes the counts, matplotlib (with the headless `Agg` backend) draws the figure,
`savefig()` writes it into a `BytesIO` buffer in memory, and the bytes go back as
`HttpResponse(png, content_type="image/png")`. No file is ever written to disk, and every figure
is closed so matplotlib's global figure registry does not grow one request at a time. The
insights page embeds both with a heading, a caption and descriptive `alt` text.

## Vega-Lite charts (A4 Part 1)

Two charts are built in Vega-Lite from the project's own internal API. Each spec loads its numbers
with `"data": {"url": ...}`; no data is ever written inline into a spec or a page.

| | Bar chart | Line chart |
|---|---|---|
| Spec file (submitted) | [`unopsis/vega_lite/chart1_items_by_lane.vl.json`](unopsis/vega_lite/chart1_items_by_lane.vl.json) | [`unopsis/vega_lite/chart2_messages_by_hour.vl.json`](unopsis/vega_lite/chart2_messages_by_hour.vl.json) |
| Data (`data.url`) | `/api/insights/items-by-lane/` | `/api/insights/messages-by-hour/` |
| What it shows | Brief items per lane (`GROUP BY lane`) | Messages per hour (`TruncHour(sent_at)`), quiet hours as 0 |
| Chart page | `/vega-lite/chart1/` | `/vega-lite/chart2/` |
| Spec for the editor | `/vega-lite/chart1.json` | `/vega-lite/chart2.json` |
| Server-rendered image | `/vega-lite/chart1.png` | `/vega-lite/chart2.png` |

Both charts are also embedded on `/insights/`. How the pieces fit:

- **The data feeds** return a *bare JSON array of flat records*, the shape Vega-Lite reads with
  nothing but a URL. `/api/insights/` has the same numbers, but nested inside an object.
- **The spec files** store `data.url` as a path, so they work on any host. The `.json` endpoint
  rewrites it to an absolute URL for the host that served it.
- **Cross-origin reads are allowed.** The editor runs on another site, so these responses carry
  `Access-Control-Allow-Origin: *` (`unopsis/middleware.py`). HTML pages do not get the header.

> **Assignment 5 changed who may read these, and this section used to say otherwise.**
> It claimed the chart endpoints were "public, GET-only and cookie-free, so nothing new is
> exposed", and that a spec URL could be pasted straight into the
> [Vega-Lite editor](https://vega.github.io/editor/) to load live data from the deployed site.
> Both were true when they were written and neither is true now. A5 put a login on every
> endpoint that returns anything a person wrote, and `/vega-lite/chartN.json` and
> `/api/insights/messages-by-hour/` are among them. The editor is another origin with no
> session cookie, so it now receives a 302 to the login page.
>
> What that means in practice, because the failure is silent -- Vega-Lite does not error on an
> unreachable `data.url`, it draws an empty chart:
>
> | URL | Signed out | Signed in |
> |---|---|---|
> | `/api/insights/items-by-lane/` | **200, the one public feed** | 200 |
> | `/api/insights/messages-by-hour/` | 302 to the login page | 200 |
> | `/vega-lite/chart1.json`, `/vega-lite/chart2.json` | 302 to the login page | 200 |
> | `/vega-lite/chart1/`, `/vega-lite/chart2/`, the `.png`s | 302 to the login page | 200 |
>
> So: **both charts work on the site**, signed in, exactly as before -- `/insights/`,
> `/vega-lite/chart1/` and `/vega-lite/chart2/` are unchanged for a logged-in reader. What no
> longer works is pasting a spec URL into the Vega-Lite editor and having it fetch for itself.
> The chart that can still be built in the editor is the bar chart, because its data is the one
> public feed; the spec to paste is in
> [`docs/a5/vega_lite_chart.txt`](docs/a5/vega_lite_chart.txt), which is the A5 Part 3
> deliverable and is kept honest by `PublicApiSubmissionTests`.
>
> Chart 2 is protected rather than published on purpose. An hour-by-hour record of when one
> person's messages arrive is also a record of when they sleep, when they work and when they
> were away; a count about a person is still about a person. `/api/insights/items-by-lane/` is
> three rows of `{lane, label, total}` with no title, no name and no timestamp in it, which is
> why that one, and only that one, is open.
- **Embedding.** `static/js/vega-charts.js` fetches each spec by URL and hands it to
  `vega-embed`. It changes only the width (`"container"`), so the chart fills its column.
- **The PNG endpoints** render the same spec on the server with
  [`vl-convert-python`](https://pypi.org/project/vl-convert-python/), which runs the real
  Vega-Lite compiler, so they are not look-alikes. The renderer cannot fetch a relative URL from
  inside the request, so the view passes it the rows from the same function the data URL serves.

## Forms: GET and POST

| Form | Method | Where | Why that method |
|---|---|---|---|
| Item search | GET | `/insights/` | The result is a link, and nothing is modified |
| Private lookup | POST | `/insights/` | A read whose *query* must not appear in a URL, history or log |
| Update an item | POST | `/items/<id>/` | Writes to the database |
| Add an item to a brief | POST | `/briefs/<id>/` | Creates a row |

Every POST form carries `{% csrf_token %}`; a POST without it is rejected with a 403 (there is a
test for exactly that). The write forms redirect after a successful save (Post/Redirect/Get), so
refreshing the page cannot submit the same change twice.

Three class-based views were adapted to handle input: `InsightsView` (a `ListView` with `post()`),
`ItemDetailView` and `BriefDetailView` (`DetailView`s with `post()`).

## JSON API

A small read-only API over the briefs. It serves the *ranked, public-facing read* of a brief
&mdash; titles, lanes, ranks, states, summaries, deadlines and links &mdash; and never the raw
provider payloads, the private message bodies, draft replies or credential references.

Since A5 it requires a session and returns **only the signed-in account's own rows**. The one
exception is `/api/insights/items-by-lane/`, which is open to everybody; see
[A5 Part 3](#the-one-public-api-a5-part-3) below.

| Endpoint | Style | Notes |
|---|---|---|
| `/api/items/` | function-based view | `{"count": N, "filters": {...}, "results": [...]}` |
| `/api/items/cbv/` | class-based view | Same rows, `django.views.View` |
| `/api/insights/` | function-based view | Totals and the grouped counts; `?space=work` narrows them |

Filtering is by query parameter: `?lane=`, `?state=`, `?space=`, `?brief=`, `?q=`, `?due_before=`,
`?limit=`. Unknown parameters are ignored, so a client can add one without breaking.

> **Scope &mdash; this paragraph used to say the opposite, and both halves have changed.**
> It read: *"This is a single-user demo: there is no login, so the pages, the API and the POST
> forms are all open, and every queryset covers every space."* Assignment 5 closed both.
>
> **Authentication.** Every page and every endpoint that returns something a person wrote now
> needs a session (`@login_required` / `LoginRequiredMixin`), including the two POST forms,
> which were the only unauthenticated writes this project had.
>
> **Authorization.** Every queryset now runs through an `owned_*(user)` helper in
> `unopsis/views.py`, so a signed-in account reads and writes its own briefs and nobody
> else's. This is the half that is easy to skip, because skipping it has no symptom: with a
> login and no scoping, the site looks locked, every test about the lock passes, and any
> account reads every other account's item titles, summaries, draft replies, contacts and
> message bodies. And `/accounts/signup/` is public &mdash; the assignment requires it &mdash;
> so "any account" means anybody who wants one. `TenantIsolationTests` performs that exact
> attack (sign up through the real form, then reach for another user's rows by primary key)
> and asserts on response bodies and on the database, not on status codes, because a 200 that
> renders an empty page and a 200 that renders somebody else's data look identical to a status
> check.
>
> Another user's `pk` answers **404, not 403**: 403 would confirm the row exists and belongs
> to someone, which is itself a fact about another account and enough to enumerate the table
> by walking the integers.
>
> **Why a new account is not empty.** Scoping means a brand-new account owns nothing, so it
> would sign in and land on a site with no briefs and six zeroes &mdash; correct, and
> indistinguishable from a failed deployment, which is the page a grader signing in with
> Google would meet. So each new account is given its *own* copy of the demo rows when it is
> created (`unopsis/onboarding.py`, `SEED_NEW_ACCOUNTS` in `.env`). Nothing is shared between
> accounts; `NewAccountSeedingTests` pins that two sign-ups get two separate sets.

```bash
curl -s "http://127.0.0.1:8000/api/items/?lane=needs_you&limit=2"
curl -s "http://127.0.0.1:8000/api/insights/?space=personal"

# JsonResponse vs HttpResponse: the same rows, three MIME types
curl -sI http://127.0.0.1:8000/api/items/     | grep -i content-type   # application/json
curl -sI http://127.0.0.1:8000/api/items.txt  | grep -i content-type   # text/plain
curl -sI http://127.0.0.1:8000/api/items.csv  | grep -i content-type   # text/csv
```

`JsonResponse` serializes the dict for you and sets `application/json`, so a browser or `fetch()`
treats the body as data. `HttpResponse` serializes nothing and defaults to `text/html`, which is
why the text and CSV versions have to pass `content_type` explicitly &mdash; and why the CSV one
downloads instead of rendering.

## External API: deadlines vs. public holidays (A4 Part 2)

`/api/deadlines/holidays/?country=US&bridge_days=1` checks every open deadline in the database
against [Nager.Date](https://date.nager.at), a keyless public-holiday API. The form is under
**Deadlines vs. public holidays** on `/insights/`.

Why Nager.Date: it needs no key, and it is on PythonAnywhere's allow-list. A free PythonAnywhere
account can only call sites on that list, so most other APIs would fail once deployed.

**What the view does:**

1. **Validates the query.** `country` must be a two-letter code and `bridge_days` a number from
   0 to 5. Bad input is a JSON `400`, returned before any external call is made.
2. **Calls two Nager.Date endpoints** for each year that has a deadline: *public holidays*, and
   *long weekends*. The long-weekend call passes `availableBridgeDays` as a query parameter.
   Every call goes through `requests.get(url, params=..., timeout=5)` and then
   `.raise_for_status()`.
3. **Triangulates each deadline** (`BriefItem.deadline_at`) against that calendar. For each one
   it reports:
   - the weekday, and days until (or since) the deadline;
   - whether it falls on a weekend, a public holiday, a bridge day, or inside a long weekend;
   - the nearest holiday;
   - the next working day, and how many days the deadline would slip to reach it;
   - an `at_risk` flag.
4. **Summarizes across all deadlines:**
   - how many are at risk, and what share;
   - how many fall on a holiday, a weekend, or a long weekend;
   - how many are overdue;
   - the next upcoming holiday.
5. **Stores nothing.** The calendar lives only for the length of the request; no model is written.

**Errors:**
- An unknown country (Nager.Date answers `404`) is a `400`.
- A timeout, connection failure or error status from the service is a `502` with an `error` key.

The tests (`ExternalApiTests`) mock `requests.get`, so the suite never touches the network.

## Reports and exports

`/reports/` is a read-only snapshot of the database: four grouped summaries, a totals strip and a
totals line, and the two download buttons.

| Export | URL | Content-Type | Filename |
|---|---|---|---|
| CSV | `/export/brief-items.csv` | `text/csv` | `brief_items_YYYY-MM-DD_HH-MM.csv` |
| JSON | `/export/brief-items.json` | `application/json` | `brief_items_YYYY-MM-DD_HH-MM.json` |

Both files hold the same rows in the same order. The filename carries the minute it was produced,
so today's export never silently overwrites yesterday's. The JSON one is indented and wraps the
records in metadata &mdash; `generated_at` (ISO) and `record_count` &mdash; so the file can
describe itself once it has left the site.

## Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request to `main`, on a clean Ubuntu
machine with no `.env` and no virtualenv:

1. install from `requirements.txt`
2. fail if `db.sqlite3` is **not** committed (this assignment requires it in the repo)
3. fail if `.env` **was** committed
4. `manage.py check` under development **and** production settings
5. the full test suite
6. `collectstatic` under production settings

The two hygiene gates ask git what is *tracked* rather than looking at the filesystem, because by
the time the later steps run a `.env` exists on disk. The team's branch-to-deploy process is
written up in [`docs/sdlc/README.md`](docs/sdlc/README.md).

## Tests

```bash
python manage.py test
```

45 tests: the named routes and `get_absolute_url()`, the four list views and their shared
templates, ordering, both empty states, the GET search and its relationship-spanning filters, the
aggregations, the static files, the PNG chart endpoints, all three POST forms (including a CSRF
rejection), the JSON API with its filtering and MIME types, and the reports page and both file
exports (including their behaviour against an empty database). Django builds a temporary database
for the run, so the committed `db.sqlite3` is never read or written by the tests.

## Screenshots

**The app (wireframe UI)**

| | |
|---|---|
| **Landing page** (`/`) | ![Landing page](docs/screenshots/37_landing_page.png) |
| **Under the hood** (`/under-the-hood/`) | ![Under the hood](docs/screenshots/38_under_the_hood.png) |
| **Sign up** (`/signup/`) | ![Sign up](docs/screenshots/22_app_signup.png) |
| **Sign in** (`/login/`) | ![Sign in](docs/screenshots/23_app_login.png) |
| **Setup 1-4** | ![World](docs/screenshots/24_app_setup_world.png) ![Sources](docs/screenshots/25_app_setup_sources.png) ![Scope](docs/screenshots/26_app_setup_scope.png) ![Tuning](docs/screenshots/27_app_setup_tuning.png) |
| **First run** (`/work/brief/building/`) | ![Building](docs/screenshots/28_app_work_building.png) |
| **Today's brief** (`/work/brief/`) | ![Brief](docs/screenshots/29_app_work_brief.png) |
| **Focus** (`/work/brief/item/<id>/`) | ![Focus](docs/screenshots/30_app_work_focus.png) |
| **Thread** (`/work/thread/<id>/`) | ![Thread](docs/screenshots/31_app_work_thread.png) |
| **Handled today**, with Undo | ![Handled](docs/screenshots/32_app_work_handled.png) |
| **Personal first run and catch-up** | ![Personal building](docs/screenshots/33_app_personal_building.png) ![Catch-up](docs/screenshots/34_app_personal_catchup.png) |
| **Caught up** | ![Caught up](docs/screenshots/35_app_personal_caught_up.png) |
| **The whole journey** (`/journey/`) | ![Journey](docs/screenshots/36_app_journey.png) |

**Assignment 4 and earlier**

| | |
|---|---|
| **Vega-Lite bar chart** (`/vega-lite/chart1/`) | ![Vega-Lite bar chart](docs/screenshots/18_vega_lite_chart1_bar.png) |
| **Vega-Lite line chart** (`/vega-lite/chart2/`) | ![Vega-Lite line chart](docs/screenshots/19_vega_lite_chart2_line.png) |
| **Both Vega-Lite charts + the holiday check** on `/insights/` | ![Insights Vega-Lite](docs/screenshots/20_insights_vega_lite_and_holiday_check.png) |
| **External API** (`/api/deadlines/holidays/?country=US`) | ![Holiday check](docs/screenshots/21_external_api_deadline_holidays.png) |
| **Reports & exports** (`/reports/`) | ![Reports page](docs/screenshots/17_reports_and_exports.png) |
| **Home page** (`/`) | ![Home page](docs/screenshots/07_home_page.png) |
| **Navigation** working (Briefs) | ![Briefs](docs/screenshots/08_navigation_briefs.png) |
| **Detail page** reached from a link | ![Detail page](docs/screenshots/09_detail_page_via_link.png) |
| **GET search**, filters in the URL | ![GET search](docs/screenshots/10_search_get_query_params.png) |
| **Aggregations and charts** | ![Insights](docs/screenshots/11_insights_aggregations_and_charts.png) |
| **Chart endpoint** `/insights/lanes.png` | ![Lane chart](docs/screenshots/12_chart_lanes_png_endpoint.png) |
| **Chart endpoint** `/insights/providers.png` | ![Provider chart](docs/screenshots/13_chart_providers_png_endpoint.png) |
| **JSON API**, filtered | ![JSON API](docs/screenshots/14_json_api_filtered.png) |
| **JSON API**, aggregations | ![JSON insights](docs/screenshots/15_json_api_insights.png) |
| **POST create form** on a brief | ![Brief detail](docs/screenshots/16_brief_detail_post_create_form.png) |

The home, briefs and detail screenshots also show the custom CSS, the logo and the navigation bar.

**The four view kinds** (previous assignment, re-shot with the current styling)

| | |
|---|---|
| **1. HttpResponse view** | ![HttpResponse view](docs/screenshots/01_httpresponse_view.png) |
| **2. render() view** | ![render view](docs/screenshots/02_render_view.png) |
| **3. Base class-based view** | ![Base CBV](docs/screenshots/03_base_cbv_view.png) |
| **4. Generic ListView** | ![Generic CBV](docs/screenshots/04_generic_cbv_view.png) |
| **Empty state** (`?state=snoozed`) | ![Empty state](docs/screenshots/05_empty_state.png) |
| **Detail page** | ![Detail page](docs/screenshots/06_detail_page.png) |

## Documentation

| Folder | Contents |
|---|---|
| `docs/wireframes/v1/` | Wireframes from the previous assignment |
| `docs/wireframes/v2/` | All 13 wireframe screens, the screen -> route -> data map and the design rationale |
| `docs/branching_strategy/` | How this team uses Git branches (write-up and diagram) |
| `docs/notes/notes.txt` | Weekly progress, view inventory, reminders and challenges |
| `docs/screenshots/` | Browser screenshots of every page, the charts and the JSON output |
| `docs/design/` | Data-model design decisions (`DESIGN.md`), the ER diagram as an image (`unopsis-erd.png`) and as the original workbook, and the Part 4 README |
| `static/` | The project's own stylesheet, logo and Vega-Lite embed script (see **Static files and the UI**) |
| `unopsis/vega_lite/` | The two Vega-Lite specs (see **Vega-Lite charts**) |
