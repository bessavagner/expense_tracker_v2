from django.contrib.auth.models import AbstractUser
from django.db import models


class CustomUser(AbstractUser):
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
