# Google sign-in: the setup a human has to do

Assignment 5, Part 2. Everything in the code is finished; what is left is the half that lives
in somebody's Google account and in the server's `.env`, because neither belongs in a
repository.

Read this once before clicking anything. The one step people redo three times is the redirect
URI, and this explains why.

---

## 0. What the code already does, so you know what you are configuring

* `django-allauth` is installed and configured in `inboxtriage/settings/base.py`.
* The Google routes exist at **`/accounts/google/login/`** (the button posts here) and
  **`/accounts/google/login/callback/`** (Google sends the visitor back here).
* The client id and secret are read from `.env` as `GOOGLE_OAUTH_CLIENT_ID` and
  `GOOGLE_OAUTH_CLIENT_SECRET`. **Nothing is hard-coded and no hostname appears anywhere in
  the code.**
* If those two values are missing, the site still runs: the login and sign-up pages show a
  greyed-out "Continue with Google" with a one-line explanation, and username/password login
  is unaffected. So a broken-looking button almost always means "the `.env` on that machine
  has no credentials", not "the code is wrong".

---

## 1. Create the credentials in Google Cloud Console

Do this once, in **one** Google account, and share the resulting pair with the team through
something that is not GitHub.

1. Go to <https://console.cloud.google.com/>.
2. **Create a project** (top bar, project picker, *New project*). Name it something like
   `unopsis-info490`. Wait for it to finish creating and make sure the project picker now
   shows it — every step below applies to the *selected* project, and configuring the wrong
   one is a quiet way to lose twenty minutes.
3. In the left menu: **APIs & Services → OAuth consent screen**.
   * User type: **External**. ("Internal" is only available to Google Workspace organisations
     and would lock the grader out.)
   * App name: `Unopsis`. User support email and developer contact email: your own address.
     Nothing else on that page is required.
   * Scopes: add **`.../auth/userinfo.email`** and **`.../auth/userinfo.profile`** (and
     `openid` if it is offered). These are the only scopes the site asks for — see
     `SOCIALACCOUNT_PROVIDERS` in `inboxtriage/settings/base.py`. No Gmail, no Drive.
   * **Test users:** while the app's publishing status is *Testing*, only the Google accounts
     listed here can sign in — everybody else gets "Access blocked: Unopsis has not completed
     the Google verification process". **Add the grader's address and every teammate's
     address.** This is the single most common reason a deployed Google button "fails" for
     the person marking it while working perfectly for the person who built it. Alternatively
     press **Publish app**, which removes the allow-list for the basic email/profile scopes
     without needing a verification review.
4. **APIs & Services → Credentials → Create credentials → OAuth client ID**.
   * Application type: **Web application**.
   * Name: `Unopsis web` (internal label only; nobody sees it).
   * **Authorised JavaScript origins:** leave empty. This site does no browser-side Google
     calls; the whole handshake is server-to-server.
   * **Authorised redirect URIs:** add the ones in section 2 below.
5. Press **Create**. Google shows the **Client ID** and **Client secret** once, in a dialog.
   Copy both now — the secret can be re-downloaded later, but it is easier to not need to.

---

## 2. The redirect URIs — add both

Google compares the redirect URI it is sent against this list **character for character**. A
trailing slash, `http` vs `https`, and `127.0.0.1` vs `localhost` are three different entries
as far as Google is concerned, and the failure in every case is the same unhelpful
`Error 400: redirect_uri_mismatch` page. Paste these; do not retype them.

**For local development — all three, literally:**

```
http://127.0.0.1:8000/accounts/google/login/callback/
http://localhost:8000/accounts/google/login/callback/
```

(Both, because `python manage.py runserver` prints `127.0.0.1:8000` but people type
`localhost:8000`, and Google treats them as different sites. `http` is correct here: Google
allows plain HTTP for loopback addresses only.)

**For the deployed site — fill in the domain, keep everything else exactly as written:**

```
https://<your-pythonanywhere-domain>/accounts/google/login/callback/
```

`<your-pythonanywhere-domain>` is the host PythonAnywhere gave the web app, normally
`<username>.pythonanywhere.com`. It is written as a placeholder here, and nowhere else in this
repository at all, because the deployed hostname was not known when this was built and because
a domain hard-coded in tracked code is a domain somebody has to remember to change.

Note the **`https`**. The deployed site is served over TLS, and Google refuses an `http`
redirect URI on a public domain. The code already produces `https`: PythonAnywhere terminates
TLS at its proxy and forwards plain HTTP, and `SECURE_PROXY_SSL_HEADER` in
`inboxtriage/settings/production.py` is what makes Django build the callback URL as `https`
anyway. If that line is ever removed, Google will start rejecting the callback.

You can add and remove redirect URIs on an existing client at any time — **APIs & Services →
Credentials → click the client → Authorised redirect URIs**. Changes take a few minutes to
propagate. So it is fine to create the credentials now with only the localhost entries and add
the production one on deployment day.

---

## 3. Put the credentials in `.env`

### On your laptop

`.env` sits next to `manage.py` and is git-ignored. `.env.example` (which IS committed) holds
the placeholders; copy the two lines across and replace the values:

```
GOOGLE_OAUTH_CLIENT_ID=123456789012-abcdefghijklmnop.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-xxxxxxxxxxxxxxxxxxxx
```

No quotes, no spaces around `=`. A value pasted with quotes around it is a value Google will
not recognise, and the error it returns (`invalid_client`) says nothing about quoting.

Restart `runserver` afterwards — `.env` is read once at start-up.

### On PythonAnywhere

`.env` is **not** in the repository, so `git pull` will never create or update it. Create or
edit it on the server, in the project folder (Files tab, or `nano ~/5_Unopsis/.env` in a Bash
console), with the same two lines **plus** the deployed hostname in `ALLOWED_HOSTS`:

```
SECRET_KEY=<a long random value, different from the local one>
ALLOWED_HOSTS=localhost,127.0.0.1,<your-pythonanywhere-domain>
GOOGLE_OAUTH_CLIENT_ID=...apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-...
```

`ALLOWED_HOSTS` does double duty: `production.py` derives `CSRF_TRUSTED_ORIGINS` from it. If
the deployed domain is missing there, every page works and then **every** login POST — form or
Google — fails with `403 Origin checking failed`.

Then press **Reload** on the Web tab. Nothing in a `.env` takes effect until the web app
restarts.

**Never commit a real client id or secret.** `.env` is git-ignored; `.env.example` is not and
must only ever hold placeholders.

---

## 4. The Django "Sites" row

`django.contrib.sites` is installed and `SITE_ID = 1`. Its migration creates one row whose
domain is `example.com`.

**As this project is configured today, that row is not used for Google sign-in and does not
need editing.** The Google credentials come from settings (i.e. from `.env`), and allauth only
filters *database-stored* social applications by Site.

It matters the moment somebody prefers to configure Google through `/admin/` instead:

* The `SocialApp` row has to be attached to the Site whose id is `SITE_ID`, **and that Site's
  domain has to be the deployed domain** (`<your-pythonanywhere-domain>`, no scheme, no
  trailing slash — edit it at `/admin/sites/site/1/`). With a stale `example.com` there,
  allauth finds no application for the current site and the "Continue with Google" button
  silently disappears in production, with no error on any page or in any log. That is a
  genuinely nasty half-hour.
* **Do not configure Google in both places.** allauth blends the settings-backed and
  database-backed applications, finds two for `google`, and raises at login time.

The `.env` route is the one this project uses, on purpose: `db.sqlite3` is committed to this
repository (Assignment 4 required it), so a client secret stored in the database would be
pushed to GitHub.

---

## 5. Deployment checklist

In order, on the server:

1. `git pull`
2. `pip install -r requirements.txt` — this release adds `django-allauth[socialaccount]`,
   which pulls in `oauthlib`, `PyJWT` and `cryptography` (~20 MB).
3. Edit `.env`: `ALLOWED_HOSTS` with the deployed domain, plus the two `GOOGLE_OAUTH_*` lines.
4. `python manage.py migrate --settings=inboxtriage.settings.production` — allauth adds 15
   tables and `django.contrib.sites` adds one. (If the committed `db.sqlite3` already carries
   them, this is a no-op, which is the point of running it anyway.)
5. `python manage.py collectstatic --noinput --settings=inboxtriage.settings.production`
6. In Google Cloud Console, add
   `https://<your-pythonanywhere-domain>/accounts/google/login/callback/` to the client's
   authorised redirect URIs, and make sure the grader's Google address is a **test user** (or
   that the consent screen is published).
7. Make sure the production database has at least one real account:
   `python manage.py createsuperuser --settings=inboxtriage.settings.production`. Create it on
   the server, never locally — `db.sqlite3` is committed, so a user created on a laptop gets
   pushed to GitHub with its password hash.
8. **Reload** on the Web tab.
9. Open `https://<your-pythonanywhere-domain>/accounts/login/` and press
   **Continue with Google**.

---

## 6. When it does not work

| What you see | What it almost always is |
| --- | --- |
| `Error 400: redirect_uri_mismatch` | The URI in section 2 is not registered, or differs by a slash / `http` vs `https` / `localhost` vs `127.0.0.1`. The error page shows the exact URI Google was sent — compare it character by character with the console entry. |
| `Access blocked: … has not completed the Google verification process` | The signing-in address is not a **test user** on the consent screen, and the app is still in *Testing*. Add them, or publish the app. |
| `Error 401: invalid_client` | Wrong client id or secret, or one of them pasted with quotes or a stray space. Re-copy both from the console. |
| The button is greyed out and says "Google sign-in is switched off" | No `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` in that machine's `.env` — or the web app was not reloaded after they were added. |
| The button is missing entirely | You are on a page that is not login or sign-up, or you are already signed in. |
| `403 Origin checking failed` after pressing a login button | The deployed domain is missing from `ALLOWED_HOSTS` in the server's `.env`. See section 3. |
| "Multiple apps" / `MultipleObjectsReturned` at login | Google is configured in `.env` **and** as a `SocialApp` in `/admin/`. Delete one. See section 4. |
| The callback times out on PythonAnywhere | Free accounts reach the internet through a proxy with a host allow-list. Confirm from a Bash console on the server that `accounts.google.com`, `oauth2.googleapis.com` and `www.googleapis.com` are reachable; if they are not, the account's allow-list has to be extended or the plan upgraded. Worth checking **before** deployment day. |

---

## 7. What signing in with Google actually creates

The first time somebody uses the button, allauth creates an ordinary `auth.User` from the name
and verified email address Google returns, plus a `SocialAccount` row linking that Google
identity to it. Every later sign-in recognises the link and logs into the same account.

Two consequences worth knowing:

* **That account has no usable password.** Its owner signs in with the button, not with the
  form. If they need a password, an admin can set one at `/admin/auth/user/`.
* **No Google tokens are stored** (`SOCIALACCOUNT_STORE_TOKENS = False`). The site asks Google
  who somebody is, once, at sign-in, and never acts on their behalf afterwards — which is also
  why no long-lived credential ends up in the committed `db.sqlite3`.
