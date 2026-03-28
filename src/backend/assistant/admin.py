from django.contrib import admin

from assistant.models import ChatMessage, MemoryRule


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "content_preview", "created_at")
    list_filter = ("role", "created_at")
    search_fields = ("content",)

    def content_preview(self, obj):
        return obj.content[:80]

    content_preview.short_description = "Conteúdo"


@admin.register(MemoryRule)
class MemoryRuleAdmin(admin.ModelAdmin):
    list_display = ("user", "trigger", "field", "value", "confidence", "source", "last_used_at")
    list_filter = ("source", "field")
    search_fields = ("trigger", "value")
    readonly_fields = ("created_at", "last_used_at")
