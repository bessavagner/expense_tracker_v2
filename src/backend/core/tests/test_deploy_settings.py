"""Tests for production-readiness: ASGI wiring and deploy security settings.

The security settings live inside an ``if not DEBUG:`` block in
``config/settings.py``. They are therefore exercised by importing the settings
in a subprocess with ``DEBUG=False`` and running Django's ``check --deploy``,
which is the closest thing to how the settings behave in production.
"""

import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


class TestAsgiConfig:
    """ASGI must be wired so the assistant SSE streaming works in production."""

    def test_asgi_application_setting_points_to_asgi(self):
        assert settings.ASGI_APPLICATION == "config.asgi.application"

    def test_asgi_application_is_importable_and_callable(self):
        from config.asgi import application

        assert callable(application)


class TestAsgiWarmUp:
    """Boot must pay the URLconf import cost, not the first request.

    Cloud Run routes the first request as soon as the container's port opens.
    Django imports the URLconf (and with it every view module, including the
    LLM SDKs) lazily on that first request, which stranded ~14s of import work
    *after* the startup probe had already passed.
    """

    def test_warm_up_populates_urlconf_and_reverse_cache(self):
        from django.urls import clear_url_caches, get_resolver

        from config.warmup import warm_up

        clear_url_caches()
        try:
            resolver = get_resolver()
            assert "url_patterns" not in resolver.__dict__

            warm_up()

            assert "url_patterns" in resolver.__dict__
            assert resolver._reverse_dict, "reverse cache should be populated"
        finally:
            # Leave a clean resolver behind for the rest of the suite.
            clear_url_caches()

    def test_importing_asgi_preloads_the_urlconf(self):
        """Importing config.asgi alone must leave the URLconf already resolved."""
        code = (
            "import config.asgi;"
            "from django.urls import get_resolver;"
            "print('PRELOADED', 'url_patterns' in get_resolver().__dict__)"
        )
        env = dict(os.environ)
        env["DJANGO_SETTINGS_MODULE"] = "config.settings"
        result = subprocess.run(  # noqa: S603 — fixed argv, trusted input
            [sys.executable, "-c", code],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
        )
        assert "PRELOADED True" in result.stdout, (
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )


def _run_deploy_check(extra_env):
    """Run ``manage.py check --deploy`` in a subprocess with DEBUG=False."""
    env = dict(os.environ)
    # python-dotenv (load_dotenv) does NOT override existing env vars, so these win
    # over the dev .env that ships DEBUG=True.
    env.update(
        {
            "DEBUG": "False",
            # Long, varied key so security.W009 doesn't add noise to the output.
            "SECRET_KEY": "aZ9_kQ2w-pR7x!mN4tB6vC8yE0sG1hJ3lD5fH7uI9oP2qW4eR6tY8u0",
            "ALLOWED_HOSTS": "example.com",
            "CSRF_TRUSTED_ORIGINS": "https://example.com",
            "DJANGO_SETTINGS_MODULE": "config.settings",
        }
    )
    env.update(extra_env)
    return subprocess.run(  # noqa: S603 — fixed argv, trusted input (sys.executable)
        [sys.executable, "manage.py", "check", "--deploy"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )


class TestDeploySecurityChecks:
    """``check --deploy`` must not flag HSTS / cookie / SSL security issues in prod."""

    def test_no_hsts_warnings(self):
        result = _run_deploy_check({})
        output = result.stdout + result.stderr
        # HSTS-related deploy warnings must be absent once configured.
        for code in ("security.W004", "security.W005", "security.W021"):
            assert code not in output, f"{code} present:\n{output}"

    def test_no_cookie_or_ssl_warnings(self):
        result = _run_deploy_check({})
        output = result.stdout + result.stderr
        for code in ("security.W008", "security.W012", "security.W016"):
            assert code not in output, f"{code} present:\n{output}"


class TestCookieSameSite:
    """SameSite must be stated, not inherited.

    Django's current default is ``Lax`` and ``Lax`` is what this app wants — the
    React widget and the Android TWA are both same-origin. The point of pinning
    it is that a Django default change, or an ``os.environ`` override applied by
    mistake, becomes a failing test rather than a silent CSRF weakening.
    """

    def test_session_cookie_samesite_is_lax(self):
        assert settings.SESSION_COOKIE_SAMESITE == "Lax"

    def test_csrf_cookie_samesite_is_lax(self):
        assert settings.CSRF_COOKIE_SAMESITE == "Lax"

    def test_samesite_settings_are_stated_in_settings_source(self):
        """Source-level guard: stated, not merely inherited from the framework default.

        Django's built-in default for both settings is already ``Lax``, so the
        two assertions above cannot go red if the lines were deleted — they
        would keep passing on the inherited default. Only a check on the
        settings module's own source text distinguishes "stated" from
        "inherited".
        """
        settings_source = (BACKEND_DIR / "config" / "settings.py").read_text(encoding="utf-8")
        assert 'SESSION_COOKIE_SAMESITE = "Lax"' in settings_source
        assert 'CSRF_COOKIE_SAMESITE = "Lax"' in settings_source
