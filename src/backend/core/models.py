from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class CustomUser(AbstractUser):
    # AbstractUser leaves this blank-able and non-unique. E05 makes the address
    # the login identifier, so it has to be exactly one account's. `username`
    # stays — ten models and every historical migration reference it — but
    # allauth derives it from the email and no screen shows it.
    email = models.EmailField("endereço de e-mail", unique=True)

    class Meta:
        verbose_name = "user"
        verbose_name_plural = "users"

    def __str__(self):
        return self.username


class LoginAttempt(models.Model):
    """A failed authentication, kept only long enough to enforce a lockout.

    Not a security audit log — E17 owns that. Rows here exist to be counted
    inside a short rolling window and are deleted on a successful login.
    """

    username = models.CharField(max_length=254)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "tentativa de login"
        verbose_name_plural = "tentativas de login"
        indexes = [
            models.Index(fields=["username", "-created_at"], name="login_username_recent_idx"),
            models.Index(fields=["ip", "-created_at"], name="login_ip_recent_idx"),
        ]

    def __str__(self):
        return f"{self.username}@{self.ip} {self.created_at:%Y-%m-%d %H:%M}"


class AdminAccessLog(models.Model):
    """One row per staff request that admin actually answered.

    S05-5: 'staff access to customer data is logged with actor, target, and
    timestamp'. Distinct from `LoginAttempt`, which is a lockout counter that
    gets deleted on success — these rows are kept.

    Refused requests are deliberately absent: a 404 for a non-staff user means
    nothing was disclosed, and logging those would drown the rows that record
    a human actually reading someone's money.
    """

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    path = models.CharField(max_length=500)
    method = models.CharField(max_length=10)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "acesso administrativo"
        verbose_name_plural = "acessos administrativos"
        indexes = [
            models.Index(fields=["actor", "-created_at"], name="adminlog_actor_recent_idx"),
        ]

    def __str__(self):
        return f"{self.actor} {self.method} {self.path} @ {self.created_at:%Y-%m-%d %H:%M}"
