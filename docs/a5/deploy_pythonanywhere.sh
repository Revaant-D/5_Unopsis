#!/usr/bin/env bash
# Deploy Unopsis to PythonAnywhere, end to end, from a PythonAnywhere Bash console.
#
#   1. Get an API token:  https://www.pythonanywhere.com/account/#api_token   (Create/Show)
#   2. In a PythonAnywhere Bash console:
#
#        curl -sL https://raw.githubusercontent.com/Revaant-D/5_Unopsis/main/docs/a5/deploy_pythonanywhere.sh -o deploy.sh
#        export PA_TOKEN='<paste the token>'
#        bash deploy.sh
#
# The token stays in your console. It is an API token, not your password: it is scoped and you
# can revoke it from the same page the moment this finishes.
#
# Safe to run twice. It will not overwrite an existing .env, and it skips anything already done.

set -euo pipefail

PA_USER="${PA_USER:-$(whoami)}"
DOMAIN="${PA_DOMAIN:-${PA_USER}.pythonanywhere.com}"
PROJECT="${HOME}/5_Unopsis"
VENV="${HOME}/.virtualenvs/unopsis"
REPO="https://github.com/Revaant-D/5_Unopsis.git"
API="https://www.pythonanywhere.com/api/v0/user/${PA_USER}"
SETTINGS="inboxtriage.settings.production"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[31mFAILED: %s\033[0m\n' "$*" >&2; exit 1; }

[ -n "${PA_TOKEN:-}" ] || die "PA_TOKEN is not set. Get one at https://www.pythonanywhere.com/account/#api_token then: export PA_TOKEN='...'"

api() {  # api METHOD PATH [curl args...]
  local method="$1" path="$2"; shift 2
  curl -sS -X "$method" -H "Authorization: Token ${PA_TOKEN}" "${API}${path}" "$@"
}

# ---------------------------------------------------------------- 1. code
say "1/8  Cloning the repository"
if [ -d "${PROJECT}/.git" ]; then
  git -C "$PROJECT" pull --ff-only && echo "    updated an existing clone"
else
  git clone "$REPO" "$PROJECT"
fi
cd "$PROJECT"

# ---------------------------------------------------------------- 2. python
say "2/8  Building the virtualenv"
PYBIN=""
for v in 3.13 3.12 3.11 3.10; do
  if command -v "python${v}" >/dev/null 2>&1; then PYBIN="$(command -v python${v})"; PYVER="$v"; break; fi
done
[ -n "$PYBIN" ] || die "no python3.10+ found on this account"
echo "    using $PYBIN"
[ -d "$VENV" ] || "$PYBIN" -m venv "$VENV"
# shellcheck disable=SC1091
source "${VENV}/bin/activate"
python -m pip install --quiet --upgrade pip
echo "    installing requirements (a few minutes: matplotlib and vl-convert are large)"
# requirements-production.txt = requirements.txt minus torch/transformers (A6), which do not
# fit in the free plan's 512 MB quota.
python -m pip install --quiet -r requirements-production.txt
echo "    done: $(du -sh "$VENV" | cut -f1) in $VENV"

# ---------------------------------------------------------------- 3. .env
say "3/8  Writing .env (git-ignored, so the clone cannot contain it)"
if [ -f .env ]; then
  echo "    .env already exists -- left untouched"
  grep -q "$DOMAIN" .env || echo "    WARNING: $DOMAIN is not in your ALLOWED_HOSTS line. Add it or every page 400s."
else
  SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(50))')"
  cat > .env <<ENV
SECRET_KEY=${SECRET}
ALLOWED_HOSTS=localhost,127.0.0.1,${DOMAIN}
OPENAI_API_KEY=dummy-key-not-real
GOOGLE_OAUTH_CLIENT_ID=
GOOGLE_OAUTH_CLIENT_SECRET=
AI_LOCAL_ENABLED=False
GROQ_API_KEY=
ENV
  chmod 600 .env
  echo "    created with a fresh SECRET_KEY and ALLOWED_HOSTS=...,${DOMAIN}"
fi

# ---------------------------------------------------------------- 4. static
say "4/8  collectstatic"
python manage.py collectstatic --noinput --settings="$SETTINGS" | tail -1

# ---------------------------------------------------------------- 5. sites row
say "5/8  Pointing the Django Sites row at ${DOMAIN} (allauth matches the OAuth callback against it)"
python manage.py shell --settings="$SETTINGS" -c "
from django.contrib.sites.models import Site
s = Site.objects.get(pk=1); s.domain = '${DOMAIN}'; s.name = 'Unopsis'; s.save()
print('    Site is now:', s.domain)"

# NOTE: migrate and createsuperuser are deliberately NOT run. db.sqlite3 is committed for this
# course, already migrated (allauth tables included) and already carries tester / uiuc12345.

# ---------------------------------------------------------------- 6. web app
say "6/8  Creating the web app through the API"
if api GET "/webapps/${DOMAIN}/" | grep -q '"domain_name"'; then
  echo "    web app already exists -- reconfiguring it"
else
  api POST "/webapps/" -d "domain_name=${DOMAIN}" -d "python_version=${PYVER}" >/dev/null
  echo "    created ${DOMAIN} on python ${PYVER}"
fi
api PATCH "/webapps/${DOMAIN}/" -d "virtualenv_path=${VENV}" -d "source_directory=${PROJECT}" >/dev/null
echo "    virtualenv -> ${VENV}"
echo "    source     -> ${PROJECT}"

say "7/8  WSGI file and static mapping"
WSGI_TMP="$(mktemp)"
cat > "$WSGI_TMP" <<WSGI
import os
import sys

path = '${PROJECT}'
if path not in sys.path:
    sys.path.insert(0, path)

os.environ['DJANGO_SETTINGS_MODULE'] = '${SETTINGS}'

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
WSGI
WSGI_PATH="/var/www/$(echo "$DOMAIN" | tr '.' '_')_wsgi.py"
api POST "/files/path${WSGI_PATH}" -F "content=@${WSGI_TMP}" >/dev/null
rm -f "$WSGI_TMP"
echo "    wrote ${WSGI_PATH}"

api POST "/webapps/${DOMAIN}/static_files/" -d "url=/static/" -d "path=${PROJECT}/staticfiles" >/dev/null 2>&1 || true
echo "    /static/ -> ${PROJECT}/staticfiles"

# ---------------------------------------------------------------- 8. reload + verify
say "8/8  Reloading and verifying"
api POST "/webapps/${DOMAIN}/reload/" >/dev/null
sleep 8

code()  { curl -s -o /dev/null -m 20 -w '%{http_code}' "https://${DOMAIN}$1"; }
printf '    %-34s %s  (expect 200)\n' "/"                              "$(code /)"
printf '    %-34s %s  (expect 200)\n' "/api/insights/items-by-lane/"   "$(code /api/insights/items-by-lane/)"
printf '    %-34s %s  (expect 302, login required)\n' "/reports/"      "$(code /reports/)"
printf '    %-34s %s  (expect 200)\n' "/accounts/login/"               "$(code /accounts/login/)"

echo
echo "    public feed says:"
curl -s -m 20 "https://${DOMAIN}/api/insights/items-by-lane/" | head -c 300
echo

cat <<DONE

------------------------------------------------------------------
Deployed:  https://${DOMAIN}
Sign in:   tester / uiuc12345

Still to do by hand:
  * Google OAuth -- docs/a5/google-oauth-setup.md. Register the redirect URI
      https://${DOMAIN}/accounts/google/login/callback/
    then put the client id and secret into ${PROJECT}/.env and reload.
  * Give the instructor account mohitg27 access on the Web tab.
  * Revoke this API token if you do not need it again:
      https://www.pythonanywhere.com/account/#api_token
------------------------------------------------------------------
DONE
