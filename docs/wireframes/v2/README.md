# Wireframes, version 2

The thirteen screens of `Wireframe.docx` (the Part 3 submission of Assignment 1), exported one
image per screen, in the order a new user meets them. Version 1 (`../v1/`) kept four of these
screens plus the sync-error state; version 2 is the full flow the app is built from.

**AI / tool disclosure.** The wireframes were made with assistance of Claude Design
(Anthropic). They are low fidelity on purpose: a sketch font and grey boxes say "layout and
flow", not "final visuals".

---

## Screen flow

```
01 sign up ──> 02 your world ──> 03 sources ──> 04 what's read ──> 05 what matters
                                                                         │
                       ┌─────────────────────────────────────────────────┘
                       v
              06 work: first run ──> 07 today's brief ──> 08 focus (1 of N) ──> 09 thread
                                          │    ^                 │                  │
                                          │    └──── back ───────┘                  │
                                          v                                         v
                                     10 handled today <───────── handled ───────────┘

              11 personal: first run ──> 12 catch-up ──> 13 caught up (deliberate dead end)

   The Work | Personal switch in the sidebar moves between 07 and 12 at any time.
```

## Screen → route → data

| # | Screen | File | Route (name) | Data it reads |
|---|---|---|---|---|
| 1 | Sign up / Sign in | `01-signup.png` | `/signup/`, `/login/` (`app-signup`, `app-login`) | none — static until Assignment 5 |
| 2 | Setup 1 · Your world | `02-setup-world.png` | `/setup/world/` (`app-setup-world`) | both `Space` rows and their connections |
| 3 | Setup 2 · Sources | `03-setup-sources.png` | `/setup/sources/` (`app-setup-sources`) | `Provider` choices × `Connection` |
| 4 | Setup 3 · What's read | `04-setup-scope.png` | `/setup/scope/` (`app-setup-scope`) | `Connection.included_scopes`, reading load from the latest brief |
| 5 | Setup 4 · What matters | `05-setup-tuning.png` | `/setup/tuning/` (`app-setup-tuning`) | `Space.rules`, `detail_level`, `digest_times`, `quiet_*`, `deliver_*` |
| 6 | Work first run | `06-work-building.png` | `/work/brief/building/` (`app-work-building`) | `Brief.steps`, `message_count`, `topic_count` |
| 7 | Today's brief | `07-work-brief.png` | `/work/brief/` (`app-work-brief`) | latest ready work `Brief`, its lanes |
| 8 | Focus | `08-work-focus.png` | `/work/brief/item/<pk>/` (`app-work-focus`) | one `BriefItem`, its place in the queue |
| 9 | Thread | `09-work-thread.png` | `/work/thread/<pk>/` (`app-thread`) | `BriefItem.messages`, `draft_body`, `actions` |
| 10 | Handled today | `10-work-handled.png` | `/work/handled/` (`app-work-handled`) | open vs handled-today items, messages since the brief |
| 11 | Personal first run | `11-personal-building.png` | `/personal/catchup/building/` (`app-personal-building`) | personal `Brief.steps` |
| 12 | Catch-up | `12-personal-catchup.png` | `/personal/catchup/` (`app-personal-catchup`) | personal brief, places (`Message.scope_name`) |
| 13 | Caught up | `13-personal-caught-up.png` | `/personal/caught-up/` (`app-personal-caught-up`) | personal items handled |
| — | Sync error | `../v1/error_state.png` | banner on 7 and 12 | `Connection.status = error`, `last_error`, `last_synced_at` |

Where the course assignments and these screens disagree, the assignment wins (for example,
Assignment 5 asks for separate login and signup pages with username/password and Google, so
screen 1 is built as two pages without the Microsoft button). The full list of differences is
in the implementation plan, `Assignements/2026-10-12-wireframe-ui-plan.md`, section 1.

---

## Design rationale

**One decision per screen (Hick's law).** The time to choose grows with the number of choices
on offer, so the focus view (8) shows exactly one item with one primary action, and the setup
flow (2–5) splits configuration into four pages of one question each instead of one long
settings form.

**Grouping by proximity and common region (Gestalt).** The sidebar is three visually separate
groups — the views of the brief, the sources being digested, and tuning — divided by a rule
and spacing, so a user reads "where am I / what is read / how it is ranked" without labels
having to say it. Each brief item keeps its title, prose, source chips and buttons inside one
block, so the chips are read as belonging to that item.

**One big, predictable target (Fitts's law).** Every screen has a single blue primary button,
larger than its neighbours, and in setup it always sits bottom-right where the eye ends a page.
Secondary actions are outlined and smaller, so the cost of hitting the wrong one is low.

**Show the funnel to earn trust (cognitive load theory).** The first-run screens (6, 11) show
"212 messages → 18 topics → 3 things" before the brief appears. The user never has to hold
212 messages in mind, and seeing the reduction is what makes the short answer believable.
The brief itself (7) caps the Needs-you list at a handful of items and folds everything else
into one line ("184 messages needed nothing from you"), with "Show anyway" for the doubtful.

**Visibility of system status and user control (Nielsen).** The sidebar footer always says
when the next brief arrives and when quiet hours start. A source that fails to sync gets a red
banner and a red sidebar row instead of silently producing a thinner brief (error state). Every
state change can be undone (10), and snoozing names the time the item comes back.

**Read-only as an affordance (Norman).** The product never sends anything. Buttons that would
act outside it (connect, forward, reconnect) are drawn disabled rather than hidden, so the user
can see the boundary; replies are copied to the clipboard and finished in the original app.

**Consistency and two worlds.** Work and personal use the same page structure, the same
sidebar position and the same controls; only the ranking and the vocabulary change ("brief"
vs "catch-up"). The black Work | Personal switch is always in the same place, and the two are
never merged into one summary.

**Deliberate dead end.** The last personal screen (13) ends with "That was everything" and
nothing more to scroll, the opposite of an infinite feed — the product's goal is that the user
leaves.
