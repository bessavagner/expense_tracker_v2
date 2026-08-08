"""Record failed logins; forget them on success."""

from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.dispatch import receiver

from core.models import LoginAttempt
from core.security import client_ip, is_locked


@receiver(user_login_failed)
def record_login_failure(sender, credentials, request=None, **kwargs):
    username = credentials.get("username") or ""
    ip = client_ip(request)
    # A locked-out attempt must not extend its own lockout. The backend already
    # refuses these without checking the password, so counting them would slide
    # the window forever and the lockout would never expire.
    if is_locked(username, ip):
        return
    LoginAttempt.objects.create(username=username, ip=ip)


@receiver(user_logged_in)
def clear_login_failures(sender, user, request=None, **kwargs):
    LoginAttempt.objects.filter(username=user.get_username()).delete()
