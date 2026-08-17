"""A deploy check, so the notice cannot go live half-filled.

Django's check framework rather than a startup assertion: `--deploy` is already
in this project's Definition-of-Done vocabulary (`INDEX.md` §7), and a check
that runs there is a check somebody actually runs.

A notice that says "Controlador: " with nothing after it is worse than no
notice — it looks compliant and identifies nobody.
"""

from django.conf import settings
from django.core.checks import Error, Tags, register

REQUIRED = ("name", "cnpj", "address", "email")


@register(Tags.security, deploy=True)
def check_privacy_controller(app_configs, **kwargs):
    blank = [key for key in REQUIRED if not (settings.PRIVACY_CONTROLLER.get(key) or "").strip()]
    if not blank:
        return []
    return [
        Error(
            "The privacy notice has no controller: "
            f"{', '.join(blank)} {'is' if len(blank) == 1 else 'are'} blank.",
            hint=(
                "Set PRIVACY_CONTROLLER_NAME, PRIVACY_CONTROLLER_CNPJ, "
                "PRIVACY_CONTROLLER_ADDRESS and PRIVACY_CONTACT_EMAIL. LGPD art. 41 "
                "requires the controller to be identified and reachable; a notice "
                "that names nobody is not a notice."
            ),
            id="E13.001",
        )
    ]
