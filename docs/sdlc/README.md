# How we ship: the team SDLC

This is the companion to [`docs/branching_strategy/`](../branching_strategy/branching_strategy.md).
That document answers *where does my work live*. This one answers *what has to be true before it
reaches `main`, and how it gets from `main` onto the live site*.

## The idea in one paragraph

Work moves in one direction and never skips a step: a branch, small commits, an automatic check
that the branch still runs, a teammate's eyes on the diff, a merge commit onto `main`, and then a
deploy that is nothing more than pulling that same `main` onto the server. Each step exists to
catch a specific kind of mistake, and each one is cheaper than the step after it. A typo caught by
the test suite costs a minute; the same typo caught by a visitor to the deployed site costs an
evening.

## The seven steps

| # | Step | Who/what does it | What it catches |
|---|---|---|---|
| 1 | **Branch** | you | two people editing `main` at once |
| 2 | **Commit** | you | a change you cannot explain or undo |
| 3 | **CI gate** | GitHub Actions | "it works on my laptop" |
| 4 | **Review** | another teammate | things only a second reader sees |
| 5 | **Merge `--no-ff`** | you, after 3 and 4 are green | a history you cannot read later |
| 6 | **Push** | you | nothing -- it just publishes |
| 7 | **Deploy** | one person, by hand, on PythonAnywhere | a server running last week's code |

### 1-2. Branch and commit

Exactly as in the branching strategy: `feature/<topic>` for code, `docs/<topic>` for writing, one
task per branch, small commits with messages that say what changed and why. Nothing new here.

One thing that *is* new, and it is the easiest way to break this repository: **never let
`git add -u` be the only thing you stage with.** `-u` stages only files git already tracks, so a
change that is half edits to tracked files and half brand-new files commits as its tracked half
alone -- which is not a smaller version of the change, it is a broken one. Three of the files added for Assignment 4
are load-bearing for files that were already tracked:

| New file | Tracked file that would break without it |
|---|---|
| `db.sqlite3` | `README.md`, `.gitignore` and the CI gate all say it is committed |
| `inboxtriage/staticfiles_storage.py` | `inboxtriage/settings/production.py` names it in `STORAGES` |
| `templates/unopsis/reports.html` | `unopsis/urls.py`, `unopsis/views.py`, `unopsis/tests.py` |

The middle row is the nastiest, because `manage.py check` does **not** catch it -- Django builds the
storage backend lazily, so the check passes and `collectstatic` is where it explodes. So stage the
Assignment 4 work as one atomic set:

```bash
git add db.sqlite3 \
        inboxtriage/staticfiles_storage.py \
        templates/unopsis/reports.html \
        .github/ docs/sdlc/
git add -u                               # and only now the modified tracked files
git status --short                       # read it: nothing left under "??" that belongs in this commit
git ls-files db.sqlite3                  # must print the path, or CI fails on its own gate
```

`db.sqlite3` needs no `-f`: the `.gitignore` entry for it was removed on purpose, and the comment
left in its place explains why.

Then, before you push, run the gate yourself rather than discovering it in CI:

```bash
python manage.py check
python manage.py check --settings=inboxtriage.settings.production
python manage.py test
python manage.py collectstatic --noinput --settings=inboxtriage.settings.production
```

### 3. The CI gate

Every push to a branch with an open pull request, and every push to `main`, runs
[`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) on a fresh Ubuntu machine with
Python 3.12. It:

1. installs `requirements.txt` from scratch,
2. fails if `db.sqlite3` is missing from the repo, or if `.env` was ever committed,
3. writes a throwaway `.env` with a freshly generated `SECRET_KEY` (the project refuses to start
   without one -- see `inboxtriage/secrets_environment.py`),
4. runs `manage.py check`, then `check --settings=inboxtriage.settings.production`,
5. runs `manage.py test`,
6. runs `collectstatic` under production settings.

Those are the same commands rule 1 of the branching strategy already asks every one of us to run
by hand. The point of running them again in CI is that the machine has no `.env`, no virtualenv
and none of your uncommitted files, so a branch that only works because of something sitting
untracked on your laptop goes red here instead of going red for the next person who clones.

**A red X means do not merge.** Fix it on the branch and push again; the same checks re-run.

> Honest note: we have not turned on GitHub's branch-protection rules, so nothing *physically*
> stops a merge while CI is red. The gate is the red X plus this agreement. If the repo owner
> enables "require status checks to pass" on `main`, nothing else in this document changes.

### 4. Review

Open a pull request into `main`. GitHub fills the description from
[`.github/pull_request_template.md`](../../.github/pull_request_template.md) -- fill it in rather
than deleting it, because the reviewer is reading it in a hurry.

One other teammate reads the diff and either approves or asks a question. We are a four-person
course project, so "review" means a real look at the change, not a formal sign-off process:
does the code do what the description says, is anything committed that should not be, and would
the reviewer be able to maintain it.

### 5-6. Merge and push

Once CI is green and a teammate has approved, merge with a merge commit so the branch stays
visible in the history:

```bash
# On GitHub: "Merge pull request" -> Create a merge commit (not squash, not rebase), then
git switch main
git pull

# or locally:
git switch main
git pull
git merge --no-ff feature/<topic>
git push
```

Then delete the branch. It has done its job and the merge commit remembers it.

### 7. Deploy to PythonAnywhere

Deployment is **manual and deliberate**: CI does not deploy. One person does it, after a merge
that is worth putting live, from a Bash console on PythonAnywhere:

```bash
cd ~/5_Unopsis
git pull                                # the same main CI just went green on
pip install -r requirements.txt         # only if requirements.txt changed
python manage.py migrate                # only if there are new migrations
python manage.py collectstatic --noinput --settings=inboxtriage.settings.production
# then press "Reload" on the PythonAnywhere Web tab
```

Two things the server needs that git does not carry:

- **`.env`.** It is git-ignored, so it is created once on the server from `.env.example`, with its
  own `SECRET_KEY` and with `ALLOWED_HOSTS` set to the real domain. It is never copied from a
  laptop and never pasted into a chat.
- **Production settings.** The WSGI file points at `inboxtriage.settings.production`, which is what
  gives us `DEBUG=False` and hashed static filenames.

We deploy only from `main`, never from a feature branch. If a deploy goes wrong, the fix is a
normal branch, pull request and merge -- then deploy again. We do not edit files on the server.

## What this process is not

Kept here so nobody reads more into the diagram than is there:

- **No automatic deploy.** Step 7 is a human typing commands. A GitHub Action could do it with an
  API token, and we decided the token was not worth it for a course project.
- **No staging environment.** `--settings=inboxtriage.settings.production` on a laptop is the
  closest we get to rehearsing production, and CI runs it on every change.
- **No develop/release/hotfix branches.** Same reasoning as the branching strategy: a team our size
  does not need them yet.
- **No automated linting or coverage thresholds.** The gate is `check`, `test` and `collectstatic`.
  We would rather have three checks everyone trusts than ten that people learn to ignore.
