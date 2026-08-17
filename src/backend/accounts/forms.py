"""Forms for the account surface.

Only one for now. E13 and E15 add their own here rather than to
`finances.forms`, which is about money.
"""

from django import forms

from core.models import CustomUser


class ProfileForm(forms.ModelForm):
    """A user's display name, and nothing else.

    Bound to `first_name` on purpose: `AbstractUser` already carries the
    column and nothing has ever written to it, so a display name costs no
    migration. Blank is valid — `CustomUser.display_name` falls back to the
    email, which is what every account looks like on day one.
    """

    class Meta:
        model = CustomUser
        fields = ["first_name"]
        labels = {"first_name": "Nome"}
