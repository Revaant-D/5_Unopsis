# Assignment 5, Part 3 — public API, Vega-Lite, and three alternative uses

Everything in this folder is the submission for Part 3. Nothing in it contains a deployed
hostname, an OAuth client id or a secret: the host is a placeholder the reader substitutes, or
it comes from the `UNOPSIS_API` environment variable at run time.

| File | What it is |
| --- | --- |
| [`vega_lite_chart.txt`](vega_lite_chart.txt) | **3.2 / 3.3** — the Vega-Lite spec to paste into the editor. Two blocks: a production one with a `joys3.pythonanywhere.com` placeholder, and a localhost one that runs as-is. |
| [`api_access_check.txt`](api_access_check.txt) | **3.1** — a real curl transcript: the public endpoint answering 200 with clean JSON, and seventeen other routes answering 302 to the login page. |
| [`alternative_uses/`](alternative_uses/) | **3.4** — three standalone programs, their real stdout, and a README explaining each one. |
| [`screenshots/`](screenshots/) | The capture checklist for **all** of A5 — sixteen shots, each tied to the requirement it evidences. The images themselves are the last deployment step; none of them can be produced from a checkout. |
| [`google-oauth-setup.md`](google-oauth-setup.md) | **Part 2** — creating the Google Cloud client and registering both redirect URIs. |

## The one public endpoint

```
GET /api/insights/items-by-lane/      →  200, application/json, Access-Control-Allow-Origin: *

[{"lane": "needs_you", "label": "Needs you",          "total": 5},
 {"lane": "moving",    "label": "Moving without you", "total": 1},
 {"lane": "fyi",       "label": "FYI",                "total": 1}]
```

It is public because of **what it answers**, not because it was convenient. The whole response
is aggregate counts plus labels that come from `BriefItem.Lane.choices` in code — no title, no
summary, no message body, no person, no handle, no timestamp. The counts are a `GROUP BY lane`
over the real `BriefItem` table (`unopsis/views.py`, `items_by_lane_rows()`), so a reader
learns how many items sit in each lane and nothing at all about any of them.

Everything else requires a session, **including the two endpoints that look equally harmless**:
`/api/insights/` (a day-by-day activity timeline and the list of connected providers) and
`/api/insights/messages-by-hour/` (an hour-by-hour record of when one person's messages arrive,
which also says when they sleep). Counts about a person are still about a person. "Exactly one
public API" is only true because those two are shut.

## What the tests enforce, so this folder cannot quietly go stale

`unopsis/tests.py` → `PublicApiSubmissionTests` reads the files in this folder and checks them
against the live view on every `manage.py test` run:

- the feed is a **bare array** of exactly `{lane, label, total}` and contains no HTML;
- the count moves when a row is added, so the feed is database-backed and not a constant;
- every `field` in the submitted Vega-Lite spec is a real key of that feed — **this is the
  important one**, because a field name that does not exist raises nothing in Vega-Lite, it
  draws an empty chart with no error anywhere to explain it;
- the spec uses `data.url` and never an inline `values` array, and the production block carries
  a placeholder host rather than a real one;
- all three alternative-use programs compile, read `UNOPSIS_API` with a localhost default, and
  contain no hostname.

`AuthenticationTests.test_exactly_one_api_endpoint_is_public` counts the open doors rather than
trusting that nobody added one.

## A5 also changed who sees which rows, which this folder depends on

Part 1 did two things, and only the first is the headline. The first is authentication: a
login on every page and feed that returns something a person wrote. The second is
authorization: every queryset in `unopsis/views.py` now runs through an `owned_*(user)` helper,
so a signed-in account reads and writes its own briefs and nobody else's.

The second one matters here because `/accounts/signup/` is public — Part 1 requires it to be.
With a login and no scoping, the boundary stops a stranger for exactly one HTTP request: the
one where they create an account. After that they read every other account's item titles,
summaries, draft replies, contacts and message bodies, and nothing anywhere looks wrong.
`TenantIsolationTests` in `unopsis/tests.py` performs that attack and asserts it fails.

Two consequences worth knowing while reading this folder:

- **The public feed is the one thing that is still site-wide.** `items_by_lane_rows()` is not
  scoped, deliberately. Its counts are an aggregate over everybody, which is precisely why they
  can be published — and it means the totals in the public JSON will not generally match the
  totals on a signed-in `/insights/` page. That is not a bug in either one.
- **A new account is not empty.** Scoping means a freshly created account owns no rows, so it
  would sign in and land on a site showing six zeroes — correct, and indistinguishable from a
  failed deployment. That is the page a grader signing in with Google would otherwise meet, so
  each new account is given its own copy of the demo rows on creation
  (`unopsis/onboarding.py`; `SEED_NEW_ACCOUNTS=False` in `.env` turns it off). Nothing is
  shared between accounts.

## Deploying this

One line, in the server's `.env`:

```
ALLOWED_HOSTS=localhost,127.0.0.1,<your-username>.pythonanywhere.com
```

That single value also drives `CSRF_TRUSTED_ORIGINS` in production settings. After that, the
substitutions in this folder are: the placeholder in `vega_lite_chart.txt`, and
`export UNOPSIS_API=https://<your-username>.pythonanywhere.com` before running the scripts.
