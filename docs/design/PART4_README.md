# Unopsis

INFO 490 · Part 4 · Data Modeling & Admin Kickoff

Unopsis collects a person's notifications from every place they arrive (Gmail, Outlook,
Slack, Discord, WhatsApp, iMessage) and turns them into one short brief: a handful of ranked
items, each traceable back to the actual messages behind it.

The spine of both the product and the schema is one chain:

```
Space (work | personal) -> Connection -> Message -> Brief -> BriefItem
                                                      each item cites its Messages
```

---

## Why these names

**Project: `inboxtriage`.** The project folder names the overall system: software whose job
is to triage an inbox. *Triage* is the practice of sorting by urgency when more is arriving
than anyone can attend to, which is exactly the situation a person with five notification
sources is in. It describes the system's purpose rather than its plumbing.

**App: `unopsis`.** The app holds the core domain: ingesting messages, resolving who sent
them, ranking them, and writing the brief. The name comes from Latin *unus*, "one", and
Greek *ópsis*, "view" — a single view of everything. That is precisely what this app is
responsible for producing, and it is the one capability the whole product is built around.

The app is deliberately *not* named `messages`, because `django.contrib.messages` is a
built-in Django app and an app of that name would shadow it and break the admin. Naming
collisions with Django's own namespace are a real hazard, and avoiding one was a design
decision, not an accident.

Later features that are not part of the data model (the web UI, the sync workers) would
become their own apps alongside `unopsis`, which is why the project name and the app name
are not the same word.

---

## Setup

Requires Python 3.11+ and Django 5.2 or newer. Verified on Django 5.2.17 and 6.1.1 —
`manage.py check`, the migration, and all ten constraint checks behave identically on both.

```bash
pip install "django>=5.2"
cd inboxtriage
python manage.py migrate
python manage.py runserver
```

The development server runs at http://127.0.0.1:8000/ and the admin at
http://127.0.0.1:8000/admin/. Note that `/` has no view — this project is admin-only for
Part 4, so the root URL shows Django's default welcome page rather than a 404.

### Superusers

The assignment specifies two different sets of credentials in two different sections, so
**both accounts exist** and either will work:

| Username | Password |
|---|---|
| `mohitg2` | `uiuc12345` |
| `tester` | `uiuc12345` |

`mohitg2` owns all of the seeded demo data.

---

## Reproducing the database from scratch

`db.sqlite3` ships with data already in it, but the whole thing rebuilds with:

```bash
rm db.sqlite3
python manage.py migrate
python manage.py createsuperuser        # username mohitg2, password uiuc12345
python manage.py seed_demo              # realistic test data
python manage.py verify_constraints     # proves the constraints hold
```

---

## The six models

| Model | Represents | Seeded |
|---|---|---|
| `Space` | A user's world: work or personal. Carries delivery preferences and surfacing rules | 2 |
| `Connection` | One linked provider account, with the channels/labels that count | 5 |
| `Person` | Someone, unified across every handle they reach you on | 8 |
| `Message` | The raw unit — primary, highest-volume table | 22 |
| `Brief` | One generated read of a time window | 2 |
| `BriefItem` | One ranked thing in a lane, citing the messages behind it | 7 |

Plus **17 citations** in the `BriefItem.messages` join table.

**Counts:** 8 ForeignKeys · 1 ManyToManyField · 7 UniqueConstraints (all multi-field, one
conditional) · `Meta.ordering` on all six · a docstring in every model class.

**`on_delete` spread:** 6 CASCADE, 1 PROTECT (`Message.author`), 1 SET_NULL
(`BriefItem.primary_message`) — each justified in [DESIGN.md](DESIGN.md), which also
explains why eleven further concepts are fields rather than tables.

The entity relationship diagram is **[docs/er-diagram.pdf](docs/er-diagram.pdf)** (also
`.png`, generated from `docs/er-diagram.html`).

---

## Verifying the constraints

`verify_constraints` proves each constraint and `on_delete` rule actually holds. Every
destructive check runs inside a savepoint that is rolled back, so it can be run repeatedly
and leaves the database untouched.

```
$ python manage.py verify_constraints
```

```
======================================================================
PASS  UniqueConstraint on Space (user, kind)
      A second 'personal' space was rejected: UNIQUE constraint failed: unopsis_space.user_id, unopsis_space.kind
PASS  UniqueConstraint on Message (connection, external_id)
      Re-ingesting 's-dep3' was rejected: UNIQUE constraint failed: unopsis_message.connection_id, unopsis_message.external_id  <- this is what makes syncing idempotent
PASS  UniqueConstraint on Connection (space, provider, external_account)
      Relinking 'mohitg#4417' was rejected: UNIQUE constraint failed: unopsis_connection.space_id, unopsis_connection.provider, unopsis_connection.external_account
PASS  UniqueConstraint on BriefItem (brief, lane, rank)
      A second item at 'fyi' rank 1 was rejected: UNIQUE constraint failed: unopsis_briefitem.brief_id, unopsis_briefitem.lane, unopsis_briefitem.rank
PASS  Conditional UniqueConstraint on Brief (scheduled only)
      A second SCHEDULED brief for the same window was rejected, while an ON_DEMAND brief for that same window was allowed. A plain constraint would have blocked a legitimate 'catch me up' request.
PASS  PROTECT on Message.author
      Deleting 'Mom' was blocked because 3 message(s) still reference them (ProtectedError), rather than silently erasing the history.
PASS  CASCADE from Space through Connection to Message
      Deleting the 'personal' space removed 3 connection(s), 7 message(s) and 1 brief(s): connections 5->2, messages 22->15, briefs 2->1.
PASS  SET_NULL on BriefItem.primary_message
      Deleting the quoted message kept all 7 brief item(s); 'Staging deploys failing on migration 000' survives with primary_message=NULL.
PASS  ManyToMany receipts on BriefItem.messages
      'Promotional mail suppressed' cites 2 real message(s), first: 'You left something in your cart'
PASS  Default ordering on BriefItem
      BriefItem.objects.all() came back ordered by lane then rank with no explicit order_by() -- the stored ranking, not a render-time sort.
======================================================================
Database intact: 2 spaces, 5 connections, 8 people, 22 messages, 7 items, 17 citations.
```

---

## What to look at in Django Admin

Log in at `/admin/` as `mohitg2` and open:

- **Briefs → the work brief.** The list shows the funnel `212 -> 18 -> 5` (messages, topics,
  items). Inside, the `BriefItem` inline shows three lanes in stored rank order — the
  ranking is data, not a sort.
- **Brief items → any item.** The **Receipts** section is `filter_horizontal` over
  `messages`: click through to the real messages behind the summary. **Actions and reply**
  holds the offered verbs and the draft.
- **Spaces.** One row for work, one for personal, each with its delivery fields, digest
  times and surfacing rules, plus `Connection` and `Person` inlines.
- **Connections.** One is deliberately in `error` state with a revoked-token message, so the
  failure path is visible. The "Sync now" action stamps `last_synced_at`.
- **People.** `handles` shows the same person's Slack, email and phone identities collapsed
  into one row — Lena Ortiz has three.
- **Messages.** Search-first by design: this is the table meant to be large, and browsing it
  is not something the product ever asks anyone to do.

---

## Project layout

```
inboxtriage/
├── manage.py
├── db.sqlite3                  ← at project root, as required
├── README.md                   ← this file (naming rationale, setup)
├── DESIGN.md                   ← model design decisions and justifications
├── docs/
│   ├── er-diagram.pdf          ← ER diagram (single page)
│   ├── er-diagram.png
│   ├── er-diagram.html         ← source; renders offline
│   └── mermaid.min.js          ← vendored so the diagram needs no network
├── inboxtriage/                ← project package (settings, urls, wsgi, asgi)
│   └── settings.py
└── unopsis/                    ← the app
    ├── models.py               ← the six models, each with a docstring
    ├── admin.py                ← all six registered, with inlines and actions
    ├── migrations/0001_initial.py
    └── management/commands/
        ├── seed_demo.py        ← realistic test data
        └── verify_constraints.py
```

---

## References used

- Django model field reference — https://docs.djangoproject.com/en/5.2/ref/models/fields/
- `UniqueConstraint`, including conditional constraints —
  https://docs.djangoproject.com/en/5.2/ref/models/constraints/
- `on_delete` options —
  https://docs.djangoproject.com/en/5.2/ref/models/fields/#django.db.models.ForeignKey.on_delete
- Django Admin options (`inlines`, `filter_horizontal`, `raw_id_fields`, `actions`,
  `fieldsets`) — https://docs.djangoproject.com/en/5.2/ref/contrib/admin/
- Diagram rendered with Mermaid 11.4.1 —
  https://mermaid.js.org/syntax/entityRelationshipDiagram.html
