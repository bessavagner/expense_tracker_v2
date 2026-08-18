"""Email configuration, asserted rather than assumed.

The failure mode this guards against is silent: with no EMAIL_HOST set, Django
falls back to an SMTP backend pointed at localhost:25, where mail is accepted
by nothing and lost without an exception. A developer would see "verification
email sent" and no email.
"""

import importlib

from django.conf import settings


def _settings_with(monkeypatch, **env):
    """Re-import config.settings.base under a patched environment."""
    import config.settings.base as module

    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return importlib.reload(module)


class TestLocalDevelopmentSendsNothing:
    def test_no_email_host_means_the_console_backend(self, monkeypatch):
        monkeypatch.delenv("EMAIL_HOST", raising=False)
        reloaded = _settings_with(monkeypatch)
        assert reloaded.EMAIL_BACKEND == "django.core.mail.backends.console.EmailBackend"


class TestProductionUsesSmtp:
    def test_an_email_host_switches_to_smtp(self, monkeypatch):
        reloaded = _settings_with(monkeypatch, EMAIL_HOST="smtp.resend.com")
        assert reloaded.EMAIL_BACKEND == "django.core.mail.backends.smtp.EmailBackend"
        assert reloaded.EMAIL_PORT == 587
        assert reloaded.EMAIL_USE_TLS is True


class TestFromAddress:
    def test_there_is_a_default_from_address(self):
        assert settings.DEFAULT_FROM_EMAIL
        assert "@" in settings.DEFAULT_FROM_EMAIL
        # Django's own default satisfies both assertions above, so the test
        # would pass without anyone having configured anything.
        assert settings.DEFAULT_FROM_EMAIL != "webmaster@localhost"
