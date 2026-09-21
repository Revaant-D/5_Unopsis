# Data model design decisions

INFO 490 · Part 4 · Unopsis

---

## The spine

The whole schema is one chain, and every model earns its place by sitting on it:

```
Space (work | personal)
  -> Connection          a linked provider account
    -> Message           the raw unit, never shown in bulk
      -> Brief           one generated read of a time window
        -> BriefItem     one ranked thing, citing the messages behind it
```

`Person` hangs off `Space` and is pointed at by `Message.author`: it is the model that lets
a brief say "Priya" rather than naming two strangers who happen to be the same person on
Slack and on Gmail.

Reading the chain backwards explains the product: a user is shown a small number of ranked
items, each traceable back to the actual messages that produced it, all scoped to one side
of their life.

### Screen to model

| Screen | Where it lives |
|---|---|
| 1 — pick a world | `Space` |
| 2 — connect accounts | `Connection` |
| 3 — choose channels | `Connection.included_scopes` |
| 4 — tune it | `Space.rules` + the delivery fields + `Space.digest_times` |
| 5 — generating | `Brief.steps` |
| 6 / 9 / 10 — the brief | `Brief`, `BriefItem.lane`, `BriefItem.state` |
| 7 — one item | `BriefItem` + `BriefItem.primary_message` |
| 8 — receipts and reply | `BriefItem.messages` + `BriefItem.draft_body` |
| 11 / 12 — personal | the same models with `Space.kind = "personal"` |

---

## Why six tables and not seventeen

An earlier draft of this schema had a table per concept: `Scope`, `Rule`, `Preference`,
`DigestSchedule`, `Topic`, `Citation`, `SuggestedAction`, `Draft`, `BriefStep`,
`Interaction`, `SyncRun`. Each was defensible on its own. Together they were a schema that
described the screens rather than the data.

The test applied to each was: **is this ever queried across rows, or constrained?** If not,
a table buys nothing over a column.

| Folded into a field | Why a table was not needed |
|---|---|
| `Preference` → fields on `Space` | Exactly one per space, read as a block. A OneToOne to a row you always create is over-modelling. |
| `Rule` → `Space.rules` (JSON) | Read as a set when a brief is built; never filtered or joined. |
| `DigestSchedule` → `Space.digest_times` (JSON) | A list of times, read by the scheduler. |
| `Scope` → `Connection.included_scopes` (JSON) | Excluded scopes are simply absent from the list. |
| `BriefStep` → `Brief.steps` (JSON) | Written once, read once by the waiting screen, never queried. |
| `SuggestedAction` → `BriefItem.actions` (JSON) | Rendered as buttons; nothing asks "which items offer approve?" |
| `Draft` → `BriefItem.draft_body` | One draft per item is enough. |
| `Interaction` → `open_count` + `feedback` on `BriefItem` | Aggregates are what ranking consumes; the event log is only needed once training is real. |
| `SyncRun` → `Connection.last_error` + `last_synced_at` | Latest state surfaces a broken integration. Full history would matter only for trend analysis. |
| `Citation` → the `BriefItem.messages` M2M | The join table *is* the citation. The only thing lost is explicit ordering. |
| `Topic` → `BriefItem.title` + the M2M | Topics were never reused across briefs in practice, so the indirection cost a join and bought nothing. |

**What this genuinely gives up**, stated plainly: citation ordering, topics as objects
reusable across briefs, multiple drafts per item, multiple schedules per space, per-run sync
history, and queryable rules. Each is an additive migration away — a new table with a
foreign key, no change to existing rows — which is the test of whether a simplification was
a trap or a choice.

---

## Relationships and `on_delete`

Eight foreign keys and one many-to-many. Every deletion behaviour was chosen deliberately.

| Relationship | `on_delete` | Justification |
|---|---|---|
| `Space.user` | CASCADE | A space has no meaning without an owner. |
| `Connection.space` | CASCADE | An account is linked *into* a space and cannot outlive it. |
| `Person.space` | CASCADE | A person is one space's private view of someone. |
| `Message.connection` | CASCADE | A message with no source cannot be attributed, re-fetched, or displayed. |
| `Brief.space` | CASCADE | A brief is a read *of* a space. |
| `BriefItem.brief` | CASCADE | An item outside a brief has no window, no lane, and no meaning. |
| `Message.author` | **PROTECT** | The one place where a routine deletion would destroy real data. Deleting a Person would otherwise erase every message they ever sent. Django raises `ProtectedError` and forces the caller to deal with the history deliberately. |
| `BriefItem.primary_message` | **SET_NULL** | The lead quote is a presentation choice. Losing the quoted message must not delete the item or its other citations. |
| `BriefItem.messages` | **ManyToMany** | An item rests on many messages, and one message can support items in several briefs. Neither side owns the other, which is exactly what a join table is for. |

Defaulting everything to CASCADE is the common failure, and it is the one that quietly loses
data. The `PROTECT` above exists specifically so that removing a contact cannot silently
take a year of message history with it.

**One consequence worth naming:** because `Message.author` is `PROTECT` and `Person.space`
is `CASCADE`, deleting a whole `Space` fails until its messages are removed first. That is
deliberate — deleting a world should be an explicit, staged operation rather than something
a single click does silently. `manage.py verify_constraints` demonstrates the staged delete.

---

## Uniqueness constraints

Seven, all multi-field, one of them conditional.

### `Space` — `(user, kind)`

A user has exactly one work space and one personal space. Screen 1 is a choice between two
things, not a list that can grow.

### `Connection` — `(space, provider, external_account)`

The same inbox cannot be linked twice into the same space. Scoped to the space rather than
the user, so one address could legitimately appear in both work and personal.

### `Person` — `(space, display_name)`

One row per person per space, so repeated syncs cannot create a second "Prof. Ramirez".

### `Message` — `(connection, external_id)`

**The most important constraint in the schema.** Every ingested message carries the
provider's own identifier and the database refuses a second copy.

This is what makes syncing idempotent: a sync job can run a thousand times, crash halfway
through, and re-run from the beginning without producing a duplicate row. The correctness
guarantee lives in the database, where it holds regardless of which code path writes.

`Message` also carries an index on `(connection, sent_at)`, because every ingest and every
brief query filters that way.

### `BriefItem` — `(brief, lane, rank)` and `(brief, title)`

The first says one item per slot: two items claiming the same lane and rank would leave the
reading order undefined, which defeats storing it at all. The second says one item per
subject per brief — otherwise the same thing gets said twice in two lanes.

### `Brief` — a **conditional** constraint

```python
UniqueConstraint(
    fields=["space", "window_start", "window_end"],
    condition=Q(trigger="scheduled"),
    name="uniq_scheduled_brief_per_window",
)
```

The 8am brief must not be generated twice. But a user tapping "catch me up" twice in an hour
is a legitimate request, so on-demand briefs are deliberately exempt. An unconditional
constraint would have blocked a real user action; a partial index protects exactly the rows
that need protecting.

`verify_constraints` demonstrates both halves: the duplicate scheduled brief is rejected,
and an on-demand brief for that same window is accepted.

---

## Default ordering

Each `Meta.ordering` reflects how that table is actually read, so no caller has to remember
to sort:

| Model | Ordering | Why |
|---|---|---|
| `BriefItem` | `["lane", "rank"]` | Exactly the reading order of screens 6, 9 and 10 — the stored ranking, surfaced by default. |
| `Message` | `["-sent_at"]` | Newest first, the only order raw messages make sense in. |
| `Brief` | `["-window_end"]` | The most recent read at the top. |
| `Person` | `["-is_vip", "display_name"]` | VIPs first, then alphabetical — how a contact list should read. |
| `Connection` | `["space", "provider", "external_account"]` | Grouped by world then service; stable and predictable. |
| `Space` | `["user", "kind"]` | Work before personal, deterministically. |

---

## The two commitments that carry the product

Everything above is bookkeeping. Two decisions are the actual argument.

### 1. `BriefItem.lane` and `rank` are columns, not a render-time sort

The ranking is decided once, when the brief is generated, and written down. Three things
follow that would not be true of a sort applied at display time:

- **A brief is stable.** Opened at 8am and again at noon, it says the same thing in the same
  order. A brief that silently reshuffles between readings is not something a person can
  build a morning routine around.
- **A brief is auditable.** When a ranking looks wrong a week later, the decision is on disk
  and can be examined. A render-time sort leaves nothing behind to inspect.
- **A brief is a record.** `message_count` and `topic_count` live on `Brief` for the same
  reason: the claim "212 messages became 18 topics" has to survive the messages being
  archived.

`Meta.ordering = ["lane", "rank"]` means the stored ranking *is* the default queryset order.
No view has to remember to sort, and none can accidentally sort differently.

### 2. `BriefItem.messages` makes every sentence checkable

A summary a user cannot verify is one they take on faith, and the first time one is wrong
they stop trusting all of them. The M2M links each item to the real messages behind it,
which is what turns screen 8 from a claim into evidence.

---

## Security note

`Connection.token_ref` is an opaque pointer into a secrets store, not a credential. No token
material is written to this table. Storing OAuth tokens beside application rows means every
database dump, backup and read replica becomes credential material; keeping a reference
instead confines that blast radius to one system. `read_only` defaults to `True` for the
same reason — the narrower grant is the one worth asking a user for.

---

## Scalability

1. **Database-enforced idempotency.** The `(connection, external_id)` constraint means
   ingestion volume can grow without ingestion *correctness* becoming a code problem.
2. **Precomputed briefs.** `Brief.headline`, `BriefItem.summary`, `lane` and `rank` are all
   stored. Reads outnumber writes heavily in an inbox, and generation is the expensive half.
3. **Provider-agnostic core.** Nothing below `Connection` knows what a "Slack" is. Adding a
   seventh provider is a new choice value, not a migration.
4. **`Message` is written to be large.** It is indexed on the access path, excluded from bulk
   browsing in the admin, and never rendered directly to users — the product's entire job is
   to avoid showing it.

### Deliberately deferred

**Full-text search over `Message.body`** — genuinely needed at scale, but an indexing concern
rather than a modelling one, and SQLite's FTS5 would not survive a move to Postgres unchanged.

**Promoting the folded-in JSON fields back to tables** — each becomes worthwhile at a
specific, nameable moment: `rules` when a user wants to see which rule fired on which item,
`Interaction` when ranking is actually trained rather than heuristic, `SyncRun` when
per-connection reliability needs a trend rather than a latest value.
