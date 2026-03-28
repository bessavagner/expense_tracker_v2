from django.utils import timezone

from assistant.models import MemoryRule

# Confidence thresholds
AUTO_APPLY = 0.9  # >= 0.9: apply silently
CONFIRM_APPLY = 0.7  # 0.7–0.9: apply with confirmation hint
# < 0.7: ask user before using


def find_matching_rules(user, message: str) -> list[MemoryRule]:
    """Find memory rules whose trigger appears in the message (case-insensitive substring)."""
    rules = MemoryRule.objects.filter(user=user)
    matched = []
    message_lower = message.lower()
    for rule in rules:
        if rule.trigger.lower() in message_lower:
            matched.append(rule)
    if matched:
        MemoryRule.objects.filter(pk__in=[r.pk for r in matched]).update(
            last_used_at=timezone.now()
        )
    return matched
