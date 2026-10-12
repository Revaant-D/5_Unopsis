"""
Make db.sqlite3 safe to commit.

Run with:  python manage.py scrub_db            (show what would go, change nothing)
           python manage.py scrub_db --apply    (actually delete)

WHY THIS COMMAND EXISTS. This repository commits its SQLite database on purpose -- .gitignore
says so, at length -- so that cloning the repo is all it takes to get the demo data, on a
grader's laptop and on PythonAnywhere alike. That was a fair trade in Assignment 4, when the
file held briefs, items and invented messages and nothing else.

Assignment 5 changed what is in the file, and therefore changed the trade. The database now
has an auth_user table with password hashes and real email addresses in it, and a
django_session table. The session table is the sharp one: a Django session_key IS the literal
value of the sessionid cookie. Commit a populated django_session and anybody who can read the
repository can paste a key into a cookie and be signed in on the deployed site, as that user,
with no password -- which defeats the entire authentication layer this assignment adds. They
do not expire for two weeks.

The table fills up by accident, not by carelessness: every `runserver` you log into while
testing writes a row, and `git add db.sqlite3` takes them all. So the defence cannot be
"remember not to", it has to be a command somebody runs, and this is it.

`clearsessions` is NOT the same thing. Django's built-in deletes only rows that have already
EXPIRED, which is the opposite of the set that matters here: a session that has expired cannot
be replayed, and a fresh one can.

WHAT IT DOES NOT DO. It does not touch auth_user. Deleting accounts is not reversible, the
superuser rows in this file are the team's own, and a command that quietly removed them would
be a worse surprise than the one it is preventing. It reports them instead, so the decision --
rotate the passwords, or ship a database with no accounts and run `createsuperuser` on the
server -- stays with a person. It also reports any SocialApp or SocialToken rows, because a
Google client secret configured through /admin/ would be stored in exactly those tables and
would then be committed in this file; this project configures Google through settings instead
(SOCIALACCOUNT_PROVIDERS in settings/base.py, fed from .env), so finding rows there means
somebody took the other path and the secret needs rotating.

DRY RUN BY DEFAULT. --apply is required to delete anything, because the one thing worse than
forgetting to run this before a commit is running it by reflex against a database you meant
to keep.
"""

from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Report (or with --apply, remove) rows that must not be committed in db.sqlite3."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually delete. Without it this command only reports.",
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        sessions = Session.objects.count()

        # ---- the part this command owns: sessions -------------------------------------
        if sessions:
            verb = "Deleting" if apply else "Would delete"
            self.stdout.write(self.style.WARNING(
                f"{verb} {sessions} django_session row(s). Each one is a live sessionid "
                f"cookie value: committed, it is a password-free login to the deployed site."
            ))
            if apply:
                with transaction.atomic():
                    Session.objects.all().delete()
                self.stdout.write(self.style.SUCCESS("django_session is now empty."))
        else:
            self.stdout.write(self.style.SUCCESS("django_session is empty. Good."))

        # ---- the parts a person has to decide about -----------------------------------
        accounts = list(User.objects.values_list("username", "email", "is_superuser"))
        if accounts:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                f"{len(accounts)} account(s) are in this file, with their password hashes. "
                f"This command does not delete accounts -- decide, do not let it decide:"
            ))
            for username, email, is_superuser in accounts:
                role = "superuser" if is_superuser else "user"
                self.stdout.write(f"    {username:<20} {email or '(no email)':<30} {role}")
            self.stdout.write(
                "  Either rotate these passwords before committing, or commit a database with "
                "no accounts and run `createsuperuser` on the server."
            )

        self._report_social_rows()

    def _report_social_rows(self):
        """
        Flag anything that would carry a Google secret into version control.

        Imported lazily and guarded: allauth IS a hard dependency of this project, but a
        reporting command that cannot run because an optional-looking import failed is a
        command nobody runs, and the session scrub above is the part that must never be
        blocked by this part.
        """
        try:
            from allauth.socialaccount.models import SocialApp, SocialToken
        except ImportError:  # pragma: no cover
            return

        apps = SocialApp.objects.count()
        tokens = SocialToken.objects.count()
        if not apps and not tokens:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS(
                "No SocialApp or SocialToken rows: the Google credentials are coming from "
                "settings/.env, which is where they belong."
            ))
            return

        self.stdout.write("")
        self.stdout.write(self.style.ERROR(
            f"STOP: {apps} SocialApp and {tokens} SocialToken row(s) are in this file. A "
            f"SocialApp row holds the Google CLIENT SECRET in plain text, and this database "
            f"is committed. Delete them, configure Google through .env instead (see "
            f"docs/a5/google-oauth-setup.md), and rotate the secret in the Google Cloud "
            f"console -- it must be assumed published."
        ))
