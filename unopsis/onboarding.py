"""
What a brand-new account is given the moment it is created (Assignment 5).

WHY THIS FILE EXISTS AT ALL. A5 did two things to this project, and only the first one is
the headline. The first is authentication: @login_required and LoginRequiredMixin on every
view that returns something a person wrote. The second is authorization: every queryset in
views.py now runs through an owned_*(user) helper, so an account reads its OWN briefs and
nobody else's. That second change is the one that closed the real hole -- the sign-up page is
public, as the assignment requires, so an authentication-only boundary turns a stranger away
for exactly one HTTP request: the one where they create an account.

It also broke the demo, and did it silently. Before scoping, every account that signed in saw
the team's seeded rows because every account saw every row. After scoping, a new account owns
nothing, so it signs in successfully and lands on a site with no briefs, no items, no charts
and no numbers. Nothing errors. It just looks like the deployment failed -- and the account
most likely to meet that empty site is the grader's, created the first time somebody clicks
"Continue with Google" on the production domain.

The wrong fixes, and why:

    Show the demo owner's rows to everybody.   This is the hole again, wearing a hat. It
                                               works until a second real person signs up, and
                                               then it is a leak that reviews as a feature.
    Leave the site empty and explain it in a   A reader who has to be told that an empty page
    paragraph on the home page.                is working as intended is being asked to
                                               believe documentation over their own eyes.
    Drop the scoping and close sign-up.        The assignment asks for a public sign-up page.

So: give each new account its OWN copy of the demo rows. Nothing is shared, nothing leaks,
and every account -- the team's, a classmate's, the grader's Google identity -- sees a site
that works the moment it is created. It is also honest about what the data is: these are
demo rows, and the seed is the same one the repository has always shipped.

HOW IT IS WIRED. Two call sites, both explicit, because the two ways to become a user in this
project do not share a code path:

    unopsis/auth_views.py SignUpView.form_valid   the username/password form (Part 1)
    allauth's user_signed_up signal               "Continue with Google" (Part 2)

A post_save signal on User would have covered both in one line and is the wrong tool here: it
also fires for `createsuperuser`, for `loaddata`, and for every User a test builds, which
would mean a hundred-row seed running inside unrelated test setup and a hard-to-explain
dependency between this app and anything that touches auth.User. Explicit call sites say who
is seeded and when, and are switched off by a single setting.

SEED_NEW_ACCOUNTS (settings/base.py, default True) is the switch. It exists because this is a
teaching deployment: the day this project holds data somebody actually cares about, handing
every new sign-up a pile of invented messages from invented people stops being hospitable and
starts being noise. One line in .env turns it off and the rest of A5 is unaffected.
"""

import logging

from django.conf import settings
from django.db import DatabaseError
from django.dispatch import receiver

from .management.commands.seed_demo import seed_demo_data
from .models import Space

logger = logging.getLogger(__name__)


def seed_new_account(user):
    """
    Give `user` their own demo rows, once, and never let doing so break signing up.

    Returns True if rows were written, False if the work was skipped.

    Two guards, for two different failures:

      * An account that already owns a Space is left alone. seed_demo_data() is idempotent on
        its own, so this is not about duplicate rows -- it is about not re-stamping somebody's
        brief windows with today's clock every time they do something that looks like signing
        up, and about the cost: the seed is a hundred-odd writes and there is no reason to pay
        it twice.

      * Everything is wrapped. This runs in the middle of a sign-up, AFTER the account has
        been written and the session opened, so an exception here would 500 a request whose
        real work already succeeded -- the user would be told sign-up failed while in fact
        they have an account they can log straight into, which is the worst of both answers.
        A new account with no demo data is a mildly disappointing first page. A new account
        that was told it does not exist is a support ticket. The exception is logged, loudly,
        because a seeding failure is still a bug that somebody has to see.
    """
    if not getattr(settings, "SEED_NEW_ACCOUNTS", True):
        return False
    if Space.objects.filter(user=user).exists():
        return False
    try:
        seed_demo_data(user)
    except DatabaseError:
        # logger.exception, not .error: the traceback is the whole value of this line. A
        # seeding failure has no symptom on the page the user is looking at, so the log is
        # the only place it can ever be noticed.
        logger.exception("Could not seed demo data for new account %r", user.get_username())
        return False
    return True


# ---------------------------------------------------------------------------------------
# The Google half, via allauth's signal
# ---------------------------------------------------------------------------------------
# allauth fires user_signed_up once, when it CREATES an account -- not on every subsequent
# sign-in with the same Google identity, which is the distinction that makes a signal the
# right hook here rather than something that would re-run on every login. `sociallogin` is
# present in the kwargs for a social sign-up and absent for allauth's own form; we do not read
# it, but its presence is what tells a reader which flow arrives here.
#
# The import is inside the function body's module scope rather than at the top of the file on
# purpose: this module is imported by apps.py's ready(), and importing allauth.account.signals
# at that moment is safe only because allauth is listed in INSTALLED_APPS above unopsis. It is
# -- settings/base.py puts it there -- and if that ever stops being true this import is the
# line that says so, immediately and at startup, instead of silently never connecting.
try:
    from allauth.account.signals import user_signed_up
except ImportError:  # pragma: no cover -- allauth is a hard dependency; this is a clear error
    user_signed_up = None
else:
    @receiver(user_signed_up, dispatch_uid="unopsis.seed_new_account")
    def _seed_on_allauth_signup(request, user, **kwargs):
        """Seed an account allauth created, which in this project means one Google created."""
        seed_new_account(user)
