from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "core"

    def ready(self):
        # Imported for the side effect of registering the login-failure receivers.
        from core import signals  # noqa: F401

        # Imported for the side effect of registering the retention sweep.
        # `core.tasks` is a package here, so `core` cannot have the
        # `core/tasks.py` module that `autodiscover` would otherwise find.
        from core.privacy import retention  # noqa: F401

        # Import every app's `tasks` module so its @task_handler decorators
        # have run. Without this, a name is only registered if something
        # happened to import the module first — which is exactly the kind of
        # order dependence that works locally and 404s in production.
        from core.tasks.registry import autodiscover

        autodiscover()
