<!--
  GitHub fills a new pull request's description with this file.

  It exists because a pull request between teammates on a four-person course project is
  usually read in a hurry, on a phone, by somebody who did not write the code. The questions
  below are the ones a reviewer would otherwise have to ask in a comment and wait a day for.
  Delete any line that genuinely does not apply -- an honest short PR beats a padded one.
-->

## What this changes

<!-- One or two sentences in plain English. "Adds the brief detail page and its POST form",
     not "misc updates". The reviewer reads this before the diff. -->

## Why

<!-- The reason, not a restatement of the diff. Which part of the assignment, which bug,
     which teammate asked for it. -->

## Branch

<!-- e.g. feature/brief-detail or docs/sdlc -- see docs/branching_strategy/ -->

## How I checked it

- [ ] `python manage.py check` passes
- [ ] `python manage.py check --settings=inboxtriage.settings.production` passes
- [ ] `python manage.py test` passes locally
- [ ] I clicked through the pages this touches in the browser
- [ ] Screenshots added to `docs/screenshots/` if the UI changed

<!-- CI (.github/workflows/ci.yml) runs the first three again on a clean machine.
     Tick them anyway: finding a failure here is a minute, finding it in CI is ten. -->

## Secrets and data

- [ ] No secrets in the diff -- I ran `git status` and nothing from `.env` is staged
- [ ] If I changed the data model, migrations are included and `db.sqlite3` is up to date

## Anything the reviewer should look at closely

<!-- The part you are least sure about, a decision you could have made two ways, a file you
     touched that belongs to someone else's task. Say so here rather than hoping it is
     noticed. "Nothing" is a fine answer. -->
