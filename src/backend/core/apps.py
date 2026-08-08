from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "core"

    def ready(self):
        # Imported for the side effect of registering the login-failure receivers.
        from core import signals  # noqa: F401
