from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "accounts"

    def ready(self):
        # Imported for the @receiver side effect. Not re-exported: nothing
        # should import from here.
        from accounts import signals  # noqa: F401
