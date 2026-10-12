"""
The three authentication views: log in, sign up, log out (Assignment 5, Part 1).

Why this is a module of its own rather than three more views at the bottom of views.py.
views.py is 1,400 lines of this project's own subject matter -- briefs, lanes, charts, feeds.
Nothing in this file is about that subject. It is the front door: a thin layer over
django.contrib.auth whose whole job is to put OUR templates on Django's own login and signup
machinery. Keeping it separate means the next person can read all of the project's
authentication in eighty lines, and it keeps Part 2 (django-allauth, "Continue with Google")
in one predictable place to extend.

What is deliberately NOT written here:

    the password check          django.contrib.auth.authenticate() and the configured
                                password hashers do it, in constant time, against a hash
    the session                 login() rotates the session key on sign-in, which is what
                                stops a session-fixation attack
    the password rules          AUTH_PASSWORD_VALIDATORS in settings/base.py
    the "next" redirect         LoginView already validates ?next= against the current host
                                before redirecting, so a crafted ?next=https://evil.example
                                link cannot turn our login page into an open redirect

Every one of those is a thing that is easy to write and hard to write correctly, and a class
project is exactly where a hand-rolled version would look fine and be wrong. The views below
subclass Django's and override presentation only.

One Django 5 detail that surprises people and shapes templates/base.html: LogoutView answers
POST only. A plain <a href="/accounts/logout/"> returns 405. That is on purpose -- a GET
logout can be triggered by any <img src> on any page, so signing people out becomes a
one-line prank -- which is why the navigation bar carries a small POST form with a
{% csrf_token %} in it rather than a link.
"""

from django.conf import settings
from django.contrib import messages as flash
from django.contrib.auth import login as auth_login
from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import redirect, resolve_url
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.generic import CreateView

from .forms import SignUpForm, UnopsisAuthenticationForm
from .onboarding import seed_new_account


class UnopsisLoginView(LoginView):
    """
    GET /accounts/login/ renders our form; POST signs the user in.

    template_name points at templates/registration/login.html, which is also where Django
    would look by default -- it is named explicitly anyway, because "the default" is the kind
    of thing that quietly stops being true when Part 2 installs allauth and its template
    directory joins the search path ahead of ours.

    redirect_authenticated_user: a signed-in person who clicks a stale "Log in" link, or
    reaches for a bookmark, should land on the site rather than on a login form that would
    make them wonder whether they are signed in at all.
    """

    template_name = "registration/login.html"
    authentication_form = UnopsisAuthenticationForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        flash.success(self.request, f"Signed in as {form.get_user().get_username()}.")
        return response


class UnopsisLogoutView(LogoutView):
    """
    POST /accounts/logout/ ends the session and returns to LOGOUT_REDIRECT_URL (home).

    The confirmation message is added AFTER super().post() has run, which is the ordering
    that matters: logout() flushes the session, so a message stored before that call would be
    thrown away with it and the user would be signed out with no sign that anything happened.
    """

    def post(self, request, *args, **kwargs):
        was_signed_in = request.user.is_authenticated
        response = super().post(request, *args, **kwargs)
        if was_signed_in:
            flash.info(request, "Signed out. Public pages are still here when you need them.")
        return response


class SignUpView(CreateView):
    """
    GET /accounts/signup/ renders the form; POST creates the account and signs it straight in.

    Django ships LoginView and LogoutView but no signup view, because what an account IS
    differs from project to project. This is the smallest honest version: a CreateView over
    SignUpForm (itself UserCreationForm, so every password rule still applies), plus the one
    piece of courtesy a stock CreateView would miss -- logging the new account in. Making
    somebody type the password they just chose a second time, on a different page, is a
    needless cliff at the exact moment they have committed to the site.

    ?next= is honoured so that an anonymous visitor who was bounced off a protected page,
    then chose "Sign up" instead of "Log in", still arrives where they were going. It is run
    through url_has_allowed_host_and_scheme first for the same reason LoginView does: without
    that check, /accounts/signup/?next=https://evil.example would make this page a redirector
    that borrows our domain's credibility.
    """

    form_class = SignUpForm
    template_name = "registration/signup.html"

    def dispatch(self, request, *args, **kwargs):
        # Same courtesy as LoginView.redirect_authenticated_user: an account you are already
        # signed in to does not need a second one.
        if request.user.is_authenticated:
            return redirect(self.get_success_url())
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Passed through to the hidden <input name="next"> so the destination survives the
        # POST, exactly the way LoginView does it.
        context["next"] = self.request.GET.get("next", "")
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        # self.object is the User that CreateView just saved. Signing them in here is what
        # turns "account created" into "you are in".
        #
        # The explicit `backend=` is Part 2's doing and is not optional. login() normally
        # works out which authentication backend vouched for a user by reading the `.backend`
        # attribute that authenticate() leaves on them -- but nobody authenticated this user,
        # the signup form just created them, so there is no such attribute. While Django had
        # exactly one backend configured it shrugged and used that one. Part 2 added a second
        # (allauth's, for Google) to settings.AUTHENTICATION_BACKENDS, and from that moment
        # login() refuses to guess: it raises ValueError and the signup POST 500s, *after*
        # the account has been written to the database. Naming the backend says what is
        # actually true -- this account signs in with a username and a password.
        auth_login(
            self.request,
            self.object,
            backend="django.contrib.auth.backends.ModelBackend",
        )
        # The account exists and is signed in; now give it something to look at. A5 scoped
        # every queryset in views.py to its owner, so without this a new account's first view
        # of the site is six zeroes and five empty pages -- correct, and indistinguishable
        # from a broken deployment. seed_new_account() never raises: see its docstring for why
        # a seeding failure must not fail a sign-up that has already succeeded.
        #
        # The same call is made for "Continue with Google" by the user_signed_up receiver in
        # unopsis/onboarding.py, because the two ways into this site share no code path.
        seeded = seed_new_account(self.object)

        flash.success(
            self.request,
            f"Welcome, {self.object.get_username()}. Your account is ready."
            + (" We have put a set of demo briefs in it to look around."
               if seeded else ""),
        )
        return response

    def get_success_url(self):
        destination = self.request.POST.get("next") or self.request.GET.get("next")
        if destination and url_has_allowed_host_and_scheme(
            destination,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        ):
            return destination
        return resolve_url(settings.LOGIN_REDIRECT_URL)
