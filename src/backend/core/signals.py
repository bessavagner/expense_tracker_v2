"""Record failed logins; forget them on success."""

from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.dispatch import receiver

from core.auth_backends import identifier_from
from core.models import LoginAttempt
from core.security import client_ip, is_locked


@receiver(user_login_failed)
def record_login_failure(sender, credentials, request=None, **kwargs):
    # Read through the same helper the backend checks with. allauth keys the
    # credential by the derived login method (`email`), Django's admin form
    # sends `username`; counting one and refusing the other would mean the
    # login page could never actually reach the limit.
    username = identifier_from(credentials)
    ip = client_ip(request)
    # A locked-out attempt must not extend its own lockout. The backend already
    # refuses these without checking the password, so counting them would slide
    # the window forever and the lockout would never expire.
    if is_locked(username, ip):
        return
    LoginAttempt.objects.create(username=username, ip=ip)


@receiver(user_logged_in)
def clear_login_failures(sender, user, request=None, **kwargs):
    """Forget this account's failures — under either name it may be counted by.

    Rows are written under whatever identifier was submitted, and from E05 the
    login page submits an email while Django's admin form submits a username.
    Clearing only one of them would leave the other half of the budget spent:
    a member who mistypes their password nine times, succeeds, and is then
    locked out by their tenth attempt an hour later.
    """
    # Case-folded to match how the rows were written: `identifier_from`
    # lower-cases before counting, so a stored address with any capital in it
    # would otherwise never match its own failures and never be cleared.
    identifiers = {user.get_username().lower(), (user.email or "").lower()} - {""}
    LoginAttempt.objects.filter(username__in=identifiers).delete()
