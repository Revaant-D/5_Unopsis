# Deploying Unopsis to PythonAnywhere

Written against this repository as it actually stands, so it differs from the generic
PythonAnywhere tutorial in four places that would otherwise cost you an hour each. Read the
**Four things the generic guide gets wrong** section before you start.

Replace `<you>` with your PythonAnywhere username everywhere below. Your site will be at
`https://<you>.pythonanywhere.com`.

---

## Four things the generic guide gets wrong for this project

| | |
|---|---|
| **`.env` is NOT in the clone** | It is git-ignored, on purpose. The project refuses to start without `SECRET_KEY`, so the clone alone will not boot. You create `.env` by hand on the server — step 3. |
| **Do NOT run `migrate` or `createsuperuser`** | `db.sqlite3` is committed for this course, already migrated (including the allauth tables) and already carrying the instructor's `tester` account. The assignment says to skip those steps when the database is pushed, and running `createsuperuser` would just add a third account nobody asked for. |
| **The Django *Sites* row must be changed** | It currently says `example.com`. allauth matches the Google callback against it, so if you skip step 5, password login works, Google login works locally, and Google login fails **only in production** — the most expensive way to find a one-line bug. |
| **Disk is tight** | The free tier gives 512 MB. This virtualenv is ~262 MB (vl-convert 66, Django 39, numpy 34, matplotlib 33) plus ~25 MB of project. That fits, with roughly 200 MB to spare — but do not install anything you do not need. |

---

## 1. Clone

Open a **Bash console** from the PythonAnywhere dashboard.

```bash
cd ~
git clone https://github.com/Revaant-D/5_Unopsis.git
cd 5_Unopsis
```

The repository is public, so no credentials are needed.

## 2. Virtualenv

```bash
mkvirtualenv --python=/usr/bin/python3.10 unopsis     # auto-activates; later use: workon unopsis
pip install -r requirements-production.txt
```

`requirements-production.txt` is `requirements.txt` without the Assignment 6 AI libraries:
torch alone is bigger than the free plan's 512 MB quota. The server therefore runs with
`AI_LOCAL_ENABLED=False` (below), and the AI lab's triage uses the rule-based fallback there.

This takes a few minutes — matplotlib and vl-convert are large. Any Python **3.10 or newer**
available on your account works; Django 5.2 requires at least 3.10.

## 3. Create `.env` (the step the clone cannot do for you)

```bash
cd ~/5_Unopsis
python -c "import secrets; print(secrets.token_urlsafe(50))"   # copy the output
nano .env
```

Paste this, with your own key and username:

```
SECRET_KEY=<the long random string you just generated>
ALLOWED_HOSTS=localhost,127.0.0.1,<you>.pythonanywhere.com
OPENAI_API_KEY=dummy-key-not-real
GOOGLE_OAUTH_CLIENT_ID=
GOOGLE_OAUTH_CLIENT_SECRET=
AI_LOCAL_ENABLED=False
GROQ_API_KEY=
```

Save with `Ctrl-O`, `Enter`, then `Ctrl-X`.

Leave the two Google values empty for now — the site runs fine without them and the
"Continue with Google" button renders disabled with an explanation. Fill them in at step 7.

**If you forget the hostname in `ALLOWED_HOSTS`, every page answers `DisallowedHost`.** That is
the single most common first failure.

## 4. Static files

```bash
python manage.py collectstatic --noinput --settings=inboxtriage.settings.production
```

Expect ~134 files. This also writes `staticfiles/staticfiles.json`, the manifest that gives each
file its cache-busting hashed name.

## 5. Point the Sites row at your domain (needed for Google login)

```bash
python manage.py shell --settings=inboxtriage.settings.production -c "
from django.contrib.sites.models import Site
s = Site.objects.get(pk=1)
s.domain = '<you>.pythonanywhere.com'
s.name = 'Unopsis'
s.save()
print('Site is now:', s.domain)
"
```

## 6. Configure the Web tab

Dashboard → **Web** → **Add a new web app** → **Manual configuration** → the same Python version
you used in step 2. (Manual configuration, *not* the "Django" option — that scaffolds a new
project over the top of yours.)

Then set these four things:

**Source code:** `/home/<you>/5_Unopsis`

**Virtualenv:** `/home/<you>/.virtualenvs/unopsis`

**WSGI configuration file** — click the link and replace the whole file with:

```python
import os
import sys

path = '/home/<you>/5_Unopsis'
if path not in sys.path:
    sys.path.insert(0, path)

os.environ['DJANGO_SETTINGS_MODULE'] = 'inboxtriage.settings.production'

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

**Static files:**

| URL | Directory |
|---|---|
| `/static/` | `/home/<you>/5_Unopsis/staticfiles` |

Then press the big green **Reload** button.

## 7. Google OAuth

Follow [`google-oauth-setup.md`](google-oauth-setup.md). Register **both** redirect URIs:

```
http://127.0.0.1:8000/accounts/google/login/callback/
https://<you>.pythonanywhere.com/accounts/google/login/callback/
```

Then put the real values into `.env` on the server and **Reload** again. Two traps:

- While the consent screen is in **Testing**, only Google accounts added as *test users* can
  sign in. Add the instructor's address or Part 2 fails for the one person who has to see it.
- If you changed the domain in step 5 after creating the credentials, reload again.

## 8. Verify

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://<you>.pythonanywhere.com/
curl -s https://<you>.pythonanywhere.com/api/insights/items-by-lane/
curl -s -o /dev/null -w "%{http_code}\n" https://<you>.pythonanywhere.com/reports/   # expect 302
```

Expected: `200` on the landing page, clean JSON from the public feed, and `302` on `/reports/`
because it now requires a login. Then in a browser:

- sign in as `tester` / `uiuc12345` and confirm the briefs, charts and reports render
- sign out, confirm the protected nav links disappear
- click **Continue with Google**

## 9. Finish the assignment

- Put your production URL into `docs/a5/vega_lite_chart.txt` in place of
  `<your-pythonanywhere-domain>`, and commit it — the instructor pastes that file into the
  Vega-Lite editor, and it must point at a live API.
- Run the three demo scripts against production to regenerate their output:
  ```bash
  cd docs/a5/alternative_uses
  UNOPSIS_API=https://<you>.pythonanywhere.com python 01_python_aggregation.py
  ```
- Capture the screenshots listed in `docs/a5/screenshots/README.md`.
- Give the instructor account `mohitg27` access on the PythonAnywhere **Web** tab.

---

## When something breaks

| What you see | What it is |
|---|---|
| `DisallowedHost at /` | The hostname is missing from `ALLOWED_HOSTS` in the server's `.env`. Step 3. |
| `ImproperlyConfigured: Set the SECRET_KEY` | No `.env` on the server, or it is in the wrong folder. It belongs next to `manage.py`. |
| Pages load but look unstyled | The static mapping in step 6 is wrong, or `collectstatic` was not run. |
| `SocialApp.DoesNotExist` on Google login | No credentials in `.env`, or the Sites row does not match the domain. Steps 5 and 7. |
| Changes do nothing | You did not press **Reload**. Nothing on the Web tab takes effect until you do. |
| `/api/deadlines/holidays/` fails in production | Free PythonAnywhere accounts reach the internet through a proxy allow-list, and `date.nager.at` may not be on it. Test it early — this is Part 2 of A4 and it is outside our control. Check the error log before assuming it is our bug. |

Server logs: the **Web** tab links an error log and a server log. The error log is the one with
the traceback.
