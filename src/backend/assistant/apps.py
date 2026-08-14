from django.apps import AppConfig


class AssistantConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "assistant"
    verbose_name = "Assistente IA"

    def ready(self):
        # Imported here, not at module scope: `ready()` is the first point at
        # which the app registry and settings are both usable.
        from assistant.tracing import configure_tracing

        configure_tracing()
