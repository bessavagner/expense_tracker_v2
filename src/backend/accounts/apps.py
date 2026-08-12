from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "accounts"

    def ready(self):
        # E04 phase 2-3 only. Removed in phase 4 — see accounts/bridge.py.
        from accounts import bridge

        bridge.connect()
