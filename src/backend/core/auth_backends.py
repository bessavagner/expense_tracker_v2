"""Authentication backend that refuses locked-out credentials."""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

from core.security import client_ip, is_locked


class LockoutModelBackend(ModelBackend):
    """``ModelBackend`` that will not check the password of a locked account.

    Enforcing here rather than in a view means the lockout follows
    ``authenticate()`` wherever it is called from: the Django admin login today,
    the real login view E05 adds tomorrow. Returning ``None`` (rather than
    raising) keeps the caller on the ordinary "invalid credentials" path, so a
    locked-out attacker learns nothing about whether the password was right.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(get_user_model().USERNAME_FIELD)
        if is_locked(username, client_ip(request)):
            return None
        return super().authenticate(request, username=username, password=password, **kwargs)
