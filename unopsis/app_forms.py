"""Forms for the wireframe UI. The course forms in forms.py are not touched."""

from django import forms

from .ui import ACTIONS

# Where a button may send you afterwards. A fixed list -- never a URL from the request --
# so the action endpoint cannot be used as an open redirect.
RETURN_TO = ("brief", "next", "handled", "catchup", "caught-up")


class ItemActionForm(forms.Form):
    """One button press on a wireframe page: which action, and which page to land on."""

    action = forms.ChoiceField(choices=[(a, a) for a in ACTIONS])
    return_to = forms.ChoiceField(choices=[(r, r) for r in RETURN_TO], required=False)
