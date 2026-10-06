# Unopsis

INFO 490 · Part 4 · Data Modeling & Admin Kickoff

> **Historical document.** This is the README from the *data-modeling* assignment, kept because
> the naming rationale, the constraint evidence and the admin walkthrough are still the best
> record of why the schema looks the way it does. It describes the project as it stood then:
> admin-only, a single flat `settings.py`, no views. For how the project runs **today** — the
> pages, the URL map, the static files, the settings package — read the top-level
> [`README.md`](../../README.md) instead, which supersedes this file wherever the two disagree.

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
http://127.0.0.1:8000/admin/. At the time of this assignment `/` had no view and showed
Django's default welcome page; it is now the home page, and every other page is reachable
from its navigation bar. See the top-level README's **URL map**.

### Superusers

Two superuser accounts exist, `mohitg2` and `tester`; `mohitg2` owns all of the seeded demo
data. Their passwords were written out here in an earlier draft and have been removed — the
database file is committed to this repository now (see `.gitignore`), so the repo is the wrong
place to publish working credentials. Ask a team member, or make your own account with
`python manage.py createsuperuser`.

---

## Reproducing the database from scratch

`db.sqlite3` ships with data already in it — and as of Assignment 4 it is **committed to the
repository**, so deleting it is a change to a tracked file, not a local-only cleanup. Rebuild
only if you mean to replace the data everyone else is working against:

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

The entity relationship diagram workbook is **[unopsis-erd.xlsx](unopsis-erd.xlsx)**, in this
folder. (An earlier draft of this file linked `docs/er-diagram.pdf`, `.png`, `.html` and a
vendored `mermaid.min.js`; none of those were ever committed, so the links went nowhere.)

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

The layout below is the one this assignment was handed in with. It has since grown views,
templates, a stylesheet and a settings *package*; the current tree is described in the
top-level README.

```
5_Unopsis/
├── manage.py
├── db.sqlite3                  ← at project root, as required
├── README.md                   ← project README (setup, URL map, static files)
├── docs/design/
│   ├── PART4_README.md         ← this file (naming rationale, constraint evidence)
│   ├── DESIGN.md               ← model design decisions and justifications
│   └── unopsis-erd.xlsx        ← the ER diagram workbook
├── inboxtriage/                ← project package (urls, wsgi, asgi)
│   └── settings/               ← split per environment since Assignment 4
│       ├── base.py
│       ├── development.py
│       └── production.py
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
