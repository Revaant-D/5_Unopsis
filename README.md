# 5_Unopsis

**Team 5, INFO 490.** Unopsis collects a person's notifications from every place they arrive
(Gmail, Outlook, Slack, Discord, WhatsApp, iMessage) and turns them into one short, ranked
"brief" in which every item can be traced back to the real messages behind it.

- Django project: `inboxtriage` (settings, URLs)
- Django app: `unopsis` (models, admin, views, templates)
- Design docs, wireframes, branching strategy and weekly notes live in [`docs/`](docs/)
- The site is navigable from the home page at `/`: briefs, brief items, a search-and-insights
  page with live matplotlib charts, and a public JSON API.

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
python manage.py seed_demo
```

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
| `ALLOWED_HOSTS` | Comma-separated hosts allowed in production |

## URL map

Every route has a `name=`, so templates link with `{% url 'name' %}` and models reverse their own
address in `get_absolute_url()`. Nothing in this project hard-codes a path.

| URL | Route name | View | What it is |
|---|---|---|---|
| `/` | `home` | `home` (FBV) | Home page. Totals, the latest briefs and the three items that need you |
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
| `/reports/` | `reports` | `reports` (FBV) | Grouped summaries in tables, plus the two download buttons |
| `/export/brief-items.csv` | `export-items-csv` | `export_items_csv` | Every item as a timestamped CSV download |
| `/export/brief-items.json` | `export-items-json` | `export_items_json` | The same rows, same order, as a JSON download |

**`get_absolute_url()`** is implemented on `BriefItem` and on `Brief` (`unopsis/models.py`). It
reverses the named route, so templates write `{{ item.get_absolute_url }}` instead of
`{% url 'item-detail' item.pk %}`, the admin's *View on site* button works, and `redirect(item)`
after a POST needs no `success_url`.

**End-to-end flow**, all visible on the home page: `models.py` (the data and its own URL) →
`urls.py` (the address and its name) → `views.py` (the query and the context) → `templates/`
(the rendering and the links onward).

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
| Layout | one project-level `static/` folder (`static/css/unopsis.css`, `static/img/unopsis-logo.svg`) |
| Settings | `STATICFILES_DIRS` and `STATIC_ROOT` in `inboxtriage/settings/base.py` |
| Templates | `{% load static %}` at the top of `base.html`, then `{% static 'css/unopsis.css' %}` |
| Cache busting | `ManifestStaticFilesStorage`, subclassed in `inboxtriage/staticfiles_storage.py`, wired up in `inboxtriage/settings/production.py` |

The stylesheet is layered on top of Bootstrap rather than replacing it: a warm paper background,
a serif display face (Fraunces) against a humanist sans (Source Sans 3), a slate/amber header
with the Unopsis logo, stat tiles, and the three lane colours (red / blue / green) used
consistently on every card in the product.

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

A small public read-only API over the briefs. It serves the *ranked, public-facing read* of a
brief &mdash; titles, lanes, ranks, states, summaries, deadlines and links &mdash; and never the
raw provider payloads, the private message bodies, draft replies or credential references.

| Endpoint | Style | Notes |
|---|---|---|
| `/api/items/` | function-based view | `{"count": N, "filters": {...}, "results": [...]}` |
| `/api/items/cbv/` | class-based view | Same rows, `django.views.View` |
| `/api/insights/` | function-based view | Totals and the grouped counts; `?space=work` narrows them |

Filtering is by query parameter: `?lane=`, `?state=`, `?space=`, `?brief=`, `?q=`, `?due_before=`,
`?limit=`. Unknown parameters are ignored, so a client can add one without breaking.

> **Scope.** This is a single-user demo: there is no login, so the pages, the API and the POST
> forms are all open, and every queryset covers every space. Section 15 of
> [`docs/notes/notes.txt`](docs/notes/notes.txt) records what scoping to the signed-in user would
> take.

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

**This assignment**

| | |
|---|---|
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
| `docs/branching_strategy/` | How this team uses Git branches (write-up and diagram) |
| `docs/notes/notes.txt` | Weekly progress, view inventory, reminders and challenges |
| `docs/screenshots/` | Browser screenshots of every page, the charts and the JSON output |
| `docs/design/` | Data-model design decisions (`DESIGN.md`), the ER diagram workbook, and the Part 4 README |
| `static/` | The project's own stylesheet and logo (see **Static files and the UI**) |
