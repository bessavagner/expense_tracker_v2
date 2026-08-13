"""Authentication backend that refuses locked-out credentials.

Subclasses allauth's backend, not Django's `ModelBackend`. That is the whole
substance of it: from E05 the identifier is an email address, and resolving an
address to a user is allauth's job. Inheriting from `ModelBackend` would leave
the lockout attached to a lookup nothing performs any more — and every
existing lockout test would keep passing, because they call `authenticate()`
with a username directly.

Enforcing here rather than in a view means the lockout follows
`authenticate()` wherever it is called from: the allauth login form, the
Django admin login form, a management command. allauth's own `login_failed`
rate limit does not cover the admin form; this does.
"""

from allauth.account.auth_backends import AuthenticationBackend

from core.security import client_ip, is_locked


def identifier_from(credentials: dict) -> str:
    """The thing a lockout counts against, out of whatever was submitted.

    allauth's login form keys the credential by the *derived* login method, so
    with `ACCOUNT_LOGIN_METHODS = {"email"}` the key is `email` — not
    `username`, which is what Django's own admin form sends and what E01's
    `LoginAttempt` rows were written under. Both doors have to land on the same
    string or the two halves of the lockout count separate budgets.
    """
    return credentials.get("email") or credentials.get("username") or credentials.get("login") or ""


class LockoutAuthenticationBackend(AuthenticationBackend):
    """allauth's backend, but it will not check a locked credential's password.

    Returns ``None`` rather than raising, so the caller stays on the ordinary
    "invalid credentials" path and a locked-out attacker learns nothing about
    whether the password was right.
    """

    def authenticate(self, request, **credentials):
        if is_locked(identifier_from(credentials), client_ip(request)):
            return None
        return super().authenticate(request, **credentials)
