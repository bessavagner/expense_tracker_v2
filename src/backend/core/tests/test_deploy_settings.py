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
