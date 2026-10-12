"""
Tests for Assignment 5, Part 2: "Continue with Google" via django-allauth.

  * AllauthWiringTests        allauth is installed the way it needs to be, its Google routes
                              exist at the two addresses the Google console has to be told
                              about, and mounting it under /accounts/ did not quietly take
                              over the login and sign-up pages Part 1 wrote
  * GoogleButtonTests         with credentials configured: the button is on both pages, it is
                              a POST form rather than a link, it carries ?next= through, and
                              pressing it really does leave for Google with our client id
  * GoogleNotConfiguredTests  with NO credentials -- a fresh clone, the CI machine, the server
                              on the day before somebody pastes the keys in -- every one of
                              those pages still renders, the checks still pass, and password
                              login still works

Why this is a separate file from tests.py rather than two more classes at the bottom of it.
tests.py is being edited by somebody else for Part 3 while this is being written, and a
merge conflict in a test file is the kind that gets resolved by deleting half of somebody's
assertions. Django's test runner discovers anything matching `test*.py` inside the app, so
these run as part of `python manage.py test` with nothing to register anywhere.

The credentials below are obvious fakes, supplied with @override_settings. Nothing here talks
to Google: the only request that would leave this machine is the token exchange, which
happens on the callback, and no test takes that step. The POST that "goes to Google" is
checked by reading the Location header of the redirect, which allauth builds locally.
"""

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.template.loader import get_template
from django.test import TestCase, override_settings
from django.urls import resolve, reverse

from .auth_views import SignUpView, UnopsisLoginView


# What settings/base.py builds when GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET are
# both present in .env. Written out here rather than imported so that the tests still describe
# the configured shape even if somebody edits the real settings.
GOOGLE_CONFIGURED = {
    "google": {
        "APP": {
            "client_id": "test-client-id.apps.googleusercontent.com",
            "secret": "not-a-real-secret",
            "key": "",
        },
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
        "OAUTH_PKCE_ENABLED": True,
    },
}

# And what it builds when either half is missing: the provider's options, but no application.
# This is the state of a fresh clone.
GOOGLE_NOT_CONFIGURED = {
    "google": {
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
        "OAUTH_PKCE_ENABLED": True,
    },
}


class AllauthWiringTests(TestCase):
    """
    The configuration, not the pages. Every assertion here stands for a failure that is
    invisible until the moment somebody actually presses the button -- which, in a deployed
    assignment, means invisible until the grader presses it.
    """

    def test_allauth_and_its_google_provider_are_installed(self):
        for app in [
            "allauth",
            "allauth.account",
            "allauth.socialaccount",
            "allauth.socialaccount.providers.google",
            # Not allauth's, but the brief asks for it and allauth changes behaviour when it
            # is present: database-stored social applications get filtered by Site.
            "django.contrib.sites",
        ]:
            self.assertIn(app, settings.INSTALLED_APPS)
        self.assertTrue(hasattr(settings, "SITE_ID"))

    def test_the_allauth_middleware_is_installed(self):
        # allauth.account.apps.AccountConfig.ready() raises ImproperlyConfigured without this,
        # so a missing line here does not fail a page -- it stops every management command,
        # this test run included, from starting at all. Asserted anyway so that the reason is
        # written down next to the requirement.
        self.assertIn(
            "allauth.account.middleware.AccountMiddleware", settings.MIDDLEWARE
        )

    def test_both_authentication_backends_are_declared_in_the_right_order(self):
        # Leaving AUTHENTICATION_BACKENDS unset is the single most common way to get a Google
        # button that works all the way to the consent screen and then fails on the way back.
        self.assertEqual(
            settings.AUTHENTICATION_BACKENDS,
            [
                "django.contrib.auth.backends.ModelBackend",
                "allauth.account.auth_backends.AuthenticationBackend",
            ],
        )
        # First place, specifically: login() and the test client's force_login() both fall
        # back to AUTHENTICATION_BACKENDS[0], and this project's primary login is a password.
        self.assertEqual(
            settings.AUTHENTICATION_BACKENDS[0],
            "django.contrib.auth.backends.ModelBackend",
        )

    def test_the_google_routes_are_at_the_addresses_the_console_must_be_given(self):
        # These two strings are copied into Google Cloud Console (with a scheme and host in
        # front). Google matches a redirect URI character for character, so a change here is a
        # change there -- which is exactly why it is pinned by a test.
        self.assertEqual(reverse("google_login"), "/accounts/google/login/")
        self.assertEqual(
            reverse("google_callback"), "/accounts/google/login/callback/"
        )

    def test_mounting_allauth_did_not_take_over_our_own_login_and_signup_pages(self):
        # allauth publishes account_login at /accounts/login/ too. unopsis.urls is included
        # first in inboxtriage/urls.py, so ours wins -- and "ours" is the assignment's
        # requirement to write a custom login page, so this is worth a test rather than a
        # comment. Reverse by allauth's name as well: anything inside allauth that redirects
        # to account_login must land on our page, not on a 404.
        self.assertIs(resolve("/accounts/login/").func.view_class, UnopsisLoginView)
        self.assertIs(resolve("/accounts/signup/").func.view_class, SignUpView)
        self.assertEqual(reverse("account_login"), "/accounts/login/")
        self.assertEqual(reverse("account_signup"), "/accounts/signup/")

    def test_allauths_own_pages_are_drawn_in_the_site_frame(self):
        # templates/allauth/layouts/base.html overrides the standalone HTML document allauth
        # ships, so its error and cancellation pages keep the site header, navigation and
        # footer. The check is which file Django finds first.
        template = get_template("allauth/layouts/base.html")
        self.assertTrue(
            template.origin.name.startswith(str(settings.BASE_DIR / "templates")),
            f"allauth/layouts/base.html resolved to {template.origin.name}; "
            "the project override is being shadowed by the one inside the package.",
        )

    def test_a_page_allauth_owns_really_comes_out_in_the_site_frame(self):
        # The test above proves Django finds our override; this one proves the override works
        # end to end, on a page nobody in this repository wrote. /accounts/password/reset/ is
        # allauth's, inherits allauth/layouts/entrance.html, and should still arrive wearing
        # the site header and navigation -- and NOT allauth's own bare "Menu:" list.
        response = self.client.get("/accounts/password/reset/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "site-nav")
        self.assertNotContains(response, "Menu:")

    def test_nothing_tries_to_open_an_smtp_connection(self):
        # allauth's password-reset page can be reached by typing the address. Django's default
        # mail backend would answer that POST with ConnectionRefusedError -- a 500 on a form
        # that worked. See the long note in settings/base.py: this is a dead end made quiet,
        # not a mail system.
        #
        # Read from the settings MODULE, not from django.conf.settings: the test runner
        # replaces EMAIL_BACKEND with the in-memory one for the duration of a test run (so
        # that tests can inspect mail.outbox), which would make this assertion test the test
        # runner rather than the deployed configuration.
        from inboxtriage.settings import base as base_settings

        self.assertEqual(
            base_settings.EMAIL_BACKEND,
            "django.core.mail.backends.console.EmailBackend",
        )

    def test_no_social_application_is_stored_in_the_committed_database(self):
        # The credentials come from .env on purpose: db.sqlite3 is committed to this
        # repository, so a SocialApp row holding the client secret would be published to
        # GitHub. (It would also collide: allauth blends the settings-backed and DB-backed
        # applications and raises when it finds two for one provider.)
        from allauth.socialaccount.models import SocialApp

        self.assertFalse(SocialApp.objects.exists())

    def test_google_tokens_are_not_kept(self):
        # Same reason as above, and a smaller attack surface: this site only needs Google to
        # say who somebody is, once.
        self.assertFalse(getattr(settings, "SOCIALACCOUNT_STORE_TOKENS", False))


@override_settings(SOCIALACCOUNT_PROVIDERS=GOOGLE_CONFIGURED)
class GoogleButtonTests(TestCase):
    """The button itself, on a site that has been given its credentials."""

    def test_the_login_page_offers_continue_with_google(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Continue with Google")
        self.assertContains(response, reverse("google_login"))

    def test_the_signup_page_offers_the_same_button(self):
        response = self.client.get(reverse("signup"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Continue with Google")
        self.assertContains(response, reverse("google_login"))

    def test_the_button_is_a_post_form_with_a_csrf_token(self):
        # Not a link. allauth refuses to start a login on GET (SOCIALACCOUNT_LOGIN_ON_GET is
        # False by default and we leave it there): a GET would let any page on the web push a
        # visitor into our OAuth flow, so allauth answers it with an extra confirmation page
        # instead. POSTing means one click for a real user and no extra page to explain.
        html = self.client.get(reverse("login")).content.decode()
        action = f'action="{reverse("google_login")}"'
        self.assertIn(action, html)
        form_start = html.index(action)
        form_end = html.index("</form>", form_start)
        self.assertIn('method="post"', html[:form_start][-200:])
        self.assertIn("csrfmiddlewaretoken", html[form_start:form_end])

    def test_the_button_carries_the_next_destination_through_google(self):
        # Somebody who asked for /reports/, got bounced to the login page and chose Google
        # should still end up on /reports/, not on the home page.
        response = self.client.get(reverse("login"), {"next": "/reports/"})
        self.assertContains(response, "next=%2Freports%2F")

    def test_pressing_the_button_leaves_for_google_with_our_client_id(self):
        # The furthest these tests follow the flow. allauth builds this redirect locally, so
        # nothing is sent anywhere; the assertions are about what Google would be shown.
        response = self.client.post(reverse("google_login"))
        self.assertEqual(response.status_code, 302)
        location = response["Location"]
        self.assertTrue(
            location.startswith("https://accounts.google.com/"),
            f"expected to be sent to Google, got {location}",
        )
        self.assertIn("client_id=test-client-id.apps.googleusercontent.com", location)
        # The redirect_uri allauth sends is built from the REQUEST, which is why no hostname
        # appears anywhere in this project's code and why the same deployment works on
        # localhost and on PythonAnywhere. What must match the console entry is the path.
        self.assertIn("redirect_uri=", location)
        self.assertIn("%2Faccounts%2Fgoogle%2Flogin%2Fcallback%2F", location)
        # The narrow scope we asked for, and PKCE.
        self.assertIn("scope=", location)
        self.assertIn("code_challenge=", location)

    def test_a_logged_in_visitor_is_not_shown_the_button_at_all(self):
        # redirect_authenticated_user on the login view: somebody already signed in is sent to
        # the site rather than to a page offering to sign them in again.
        User.objects.create_user("already-in", password="oauth-tests-pw-1")
        self.client.login(username="already-in", password="oauth-tests-pw-1")
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 302)


@override_settings(SOCIALACCOUNT_PROVIDERS=GOOGLE_NOT_CONFIGURED)
class GoogleNotConfiguredTests(TestCase):
    """
    The state of a clone with no credentials in .env -- which is the state of this repository
    as it sits on GitHub, of the CI machine, and of the production server between deploying
    and pasting the keys in. None of those is allowed to be a broken site.

    This is the half that is easy to skip and expensive to skip, because the obvious
    implementation -- always declare the application and let client_id be the empty string --
    passes every test above and ships a live-looking button that sends the visitor to a Google
    error page. And the other obvious implementation -- call {% provider_login_url 'google' %}
    unconditionally -- raises SocialApp.DoesNotExist mid-render, turning the LOGIN PAGE into a
    500. Degrading on purpose is the whole feature here.
    """

    def test_the_login_page_still_renders(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)

    def test_the_signup_page_still_renders(self):
        response = self.client.get(reverse("signup"))
        self.assertEqual(response.status_code, 200)

    def test_the_button_is_shown_disabled_and_says_why(self):
        # Shown rather than hidden: an unexplained absence is a longer debugging session than
        # a greyed-out control that names the missing setting.
        response = self.client.get(reverse("login"))
        self.assertContains(response, "Continue with Google")
        self.assertContains(response, "disabled")
        self.assertContains(response, "GOOGLE_OAUTH_CLIENT_ID")

    def test_nothing_on_the_page_links_to_the_google_login_route(self):
        # The important half: there must be no clickable path into a flow that cannot work.
        for route in ["login", "signup"]:
            with self.subTest(page=route):
                html = self.client.get(reverse(route)).content.decode()
                self.assertNotIn(f'action="{reverse("google_login")}"', html)

    def test_username_and_password_login_is_untouched(self):
        User.objects.create_user("no-google", password="oauth-tests-pw-2")
        response = self.client.post(
            reverse("login"),
            {"username": "no-google", "password": "oauth-tests-pw-2"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session["_auth_user_id"]), User.objects.get(username="no-google").pk)

    def test_the_system_checks_are_clean_with_no_credentials(self):
        # The CI workflow runs `manage.py check` under both settings modules on a machine with
        # no .env at all. call_command raises SystemCheckError on any error-level problem, so
        # this passing IS the assertion.
        call_command("check")
        call_command("check", settings="inboxtriage.settings.production")
