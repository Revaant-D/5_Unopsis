"""
Forms for Unopsis.

Three forms, chosen to show the two halves of the GET/POST decision rather than to cover
every field on every model:

    ItemSearchForm    GET   -- a search whose result IS the link. The query lands in the URL
                              (?q=deadline&lane=needs_you), so the page can be bookmarked,
                              shared with a teammate, or reloaded, and it always comes back
                              with the same rows. Nothing is changed by running it, so it is
                              safe for the browser to re-issue it on refresh or back.

    PrivateLookupForm POST  -- the same *kind* of operation (a search) that must NOT be a
                              link. It looks people up by the handle they are reached on: a
                              personal phone number, a home email address. Those must not be
                              written into the address bar, the browser history, a bookmark,
                              a screen share, or the web server's access log, and a shareable
                              link to "everything Mom sent" is exactly what this product
                              promises not to create. POST keeps the query in the request
                              body, so the URL stays /insights/ and the result is not
                              reachable by anybody who later reads the link.

    ItemUpdateForm    POST  -- the modification. It writes to the database (a state change and
                              a draft reply), so it must be POST + {% csrf_token %}, and the
                              view redirects afterwards so a refresh cannot submit it twice.

A fourth, BriefItemCreateForm, is the plain create case: a ModelForm that adds a new item to
an existing brief.

Assignment 5 adds two more at the bottom of the file, and they are a deliberately different
kind of thing: UnopsisAuthenticationForm and SignUpForm are Django's own auth forms with our
styling on them, not forms this project designed. The reasoning is in the comment above them.
"""

from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User

from .models import Brief, BriefItem, Space


class ItemSearchForm(forms.Form):
    """
    The GET form. Every field is optional: an empty form means "no filter", which is how the
    page shows the full list. `required=False` everywhere is what lets ?q= alone be valid.
    """

    ANY = ""

    q = forms.CharField(
        required=False,
        label="Search titles and summaries",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "e.g. deadline, invoice, flights",
        }),
    )
    lane = forms.ChoiceField(
        required=False,
        label="Lane",
        choices=[(ANY, "Any lane")] + list(BriefItem.Lane.choices),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    state = forms.ChoiceField(
        required=False,
        label="State",
        choices=[(ANY, "Any state")] + list(BriefItem.State.choices),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    space = forms.ChoiceField(
        required=False,
        label="Space",
        choices=[(ANY, "Both spaces")] + list(Space.Kind.choices),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    author = forms.CharField(
        required=False,
        label="Cites a person",
        help_text="Spans the relationship: item -> messages -> author.",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Ramirez"}),
    )
    max_rank = forms.IntegerField(
        required=False,
        min_value=1,
        label="Top N per lane",
        help_text="Uses the rank__lte lookup.",
        widget=forms.NumberInput(attrs={"class": "form-control", "placeholder": "e.g. 2"}),
    )
    due_only = forms.BooleanField(
        required=False,
        label="Has a deadline",
        help_text="Uses deadline_at__isnull=False.",
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )


class PrivateLookupForm(forms.Form):
    """
    The POST form. One field, deliberately: the identifier a person is reached on.

    This is the query that must not become a URL. See the module docstring.
    """

    handle = forms.CharField(
        required=True,
        label="Handle, address or phone number",
        help_text="Sent by POST so it never appears in the URL, history or server log.",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "e.g. +1-630-555-0188 or lena@mail.example",
            "autocomplete": "off",
        }),
    )


class ItemUpdateForm(forms.ModelForm):
    """
    The write. A ModelForm over the two things a reader of a brief is actually allowed to
    change: what state the item is in, and the reply they are drafting.

    Nothing generated is editable here -- the summary, lane and rank are the system's record of
    what it decided, and letting the page overwrite them would desync an item from the messages
    cited as its evidence.
    """

    class Meta:
        model = BriefItem
        fields = ["state", "draft_body"]
        widgets = {
            "state": forms.Select(attrs={"class": "form-select"}),
            "draft_body": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Draft a reply. Nothing is ever sent on your behalf.",
            }),
        }
        labels = {"draft_body": "Draft reply"}


class BriefItemCreateForm(forms.ModelForm):
    """
    The create. Adds one item to an existing brief from the brief's own page.

    `brief` is not a field: it comes from the URL, so a POST cannot be retargeted at somebody
    else's brief by editing the form in the browser.
    """

    class Meta:
        model = BriefItem
        fields = ["title", "lane", "rank", "summary", "why", "deadline_at"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control",
                                            "placeholder": "What is this item about?"}),
            "lane": forms.Select(attrs={"class": "form-select"}),
            "rank": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "summary": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "why": forms.Textarea(attrs={"class": "form-control", "rows": 2,
                                         "placeholder": "Why did this surface? (optional)"}),
            "deadline_at": forms.DateTimeInput(attrs={"class": "form-control",
                                                      "type": "datetime-local"}),
        }

    def __init__(self, *args, brief: Brief = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.brief = brief
        self.fields["why"].required = False
        self.fields["deadline_at"].required = False

    def clean(self):
        """
        Check the model's two uniqueness constraints here so the user gets a form error
        instead of an IntegrityError page: one item per (brief, lane, rank) slot, and one
        item per (brief, title).
        """
        cleaned = super().clean()
        if not self.brief:
            return cleaned
        lane, rank, title = cleaned.get("lane"), cleaned.get("rank"), cleaned.get("title")
        if lane and rank and BriefItem.objects.filter(
            brief=self.brief, lane=lane, rank=rank
        ).exists():
            self.add_error("rank", f"This brief already has a #{rank} item in that lane.")
        if title and BriefItem.objects.filter(brief=self.brief, title=title).exists():
            self.add_error("title", "This brief already has an item with that title.")
        return cleaned

    def save(self, commit=True):
        item = super().save(commit=False)
        item.brief = self.brief
        if commit:
            item.save()
            self.save_m2m()
        return item


# ======================================================================================
# ASSIGNMENT 5, PART 1 -- the two authentication forms
# ======================================================================================
# Django already ships both of these (AuthenticationForm and UserCreationForm) and they
# already do the hard parts correctly: constant-time password checking, the is_active check,
# the "this account is inactive" message, uniqueness on username, the two-password
# confirmation, and running every validator in AUTH_PASSWORD_VALIDATORS. None of that is
# worth rewriting, and rewriting it is how a class project ends up with a login that accepts
# a four-character password.
#
# What the stock forms do NOT do is look like this site: their widgets render as bare
# <input> elements, which on a Bootstrap page are the unstyled boxes that make a login page
# look like the Django admin. So each subclass below changes exactly one thing -- the widget
# attributes -- and inherits every security decision untouched. Fields are styled in
# __init__ rather than redeclared, because redeclaring a field replaces its validators too.


class UnopsisAuthenticationForm(AuthenticationForm):
    """
    The login form: stock AuthenticationForm, wearing the site's input styling.

    autofocus on username and autocomplete hints on both fields are not decoration. They are
    what lets a password manager recognise this as a sign-in form and offer the saved
    credential, which is the single biggest thing a login page can do for the security of the
    people using it.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update({
            "class": "form-control",
            "autocomplete": "username",
            "autofocus": True,
            "placeholder": "your username",
        })
        self.fields["password"].widget.attrs.update({
            "class": "form-control",
            "autocomplete": "current-password",
            "placeholder": "your password",
        })


class SignUpForm(UserCreationForm):
    """
    The sign-up form: UserCreationForm plus an optional email address.

    Email is added for one concrete reason rather than for completeness. Part 2 of this
    assignment adds "Continue with Google", and allauth matches a Google identity to an
    existing account by email address; an account created here with no email can never be
    linked to the same person's Google login, so they end up with two accounts and half their
    data behind each. It stays OPTIONAL because requiring it would be a promise this project
    does not keep -- nothing here verifies an address or sends to it.

    Note what is NOT overridden: password1/password2 keep UserCreationForm's validation, so
    AUTH_PASSWORD_VALIDATORS in settings/base.py (minimum length, not-too-common, not entirely
    numeric, not similar to the username) is what decides whether a password is acceptable.
    """

    email = forms.EmailField(
        required=False,
        label="Email (optional)",
        help_text="Used later to match this account to a Google login. Nothing is sent to it.",
        widget=forms.EmailInput(attrs={
            "class": "form-control",
            "autocomplete": "email",
            "placeholder": "you@example.com",
        }),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update({
            "class": "form-control",
            "autocomplete": "username",
            "autofocus": True,
            "placeholder": "pick a username",
        })
        # "new-password" on BOTH password boxes is what tells a password manager to offer to
        # generate and save one, instead of trying to autofill the existing credential.
        for name in ("password1", "password2"):
            self.fields[name].widget.attrs.update({
                "class": "form-control",
                "autocomplete": "new-password",
            })
