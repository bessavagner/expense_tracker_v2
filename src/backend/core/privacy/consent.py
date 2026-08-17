"""Asking, recording and honouring consent for the AI leg.

The product's core — the ledger — runs on execução de contrato and needs no
permission beyond signing up. The assistant does not: it sends what a person
writes, says and photographs to OpenAI, and plan decision D3 puts that on
consentimento (LGPD art. 7º, I).

Which means it has to be refusable. This module is the whole of that: one
boolean, asked at the chat chokepoint, flipped from the Privacidade tab.
"""

from django.utils import timezone

from core.models import Consent, ConsentPurpose

#: What the assistant answers when consent is absent. Rendered by the chat
#: widget as the assistant's own reply — `ChatWidget.tsx` reads `{error}` off
#: any non-OK response — so it is written as a sentence to a person, not as an
#: error code.
AI_CONSENT_REQUIRED = (
    "Para usar o assistente eu preciso da sua autorização para enviar o que "
    "você escreve, fala ou fotografa à OpenAI, que é quem processa isso. "
    "Você autoriza em Conta → Privacidade, e pode voltar atrás quando quiser. "
    "O resto do aplicativo funciona normalmente sem isso."
)


def has_ai_consent(user) -> bool:
    """True when ``user`` has authorised the AI processing.

    Fails closed on every missing input — an anonymous visitor, ``None``, a
    user with no row — because a consent check that raises turns the request it
    was meant to refuse into a 500. Same rule as ``accounts.permissions.is_owner``.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return Consent.objects.filter(
        user=user, purpose=ConsentPurpose.AI_ASSISTANT, granted=True
    ).exists()


async def ahas_ai_consent(user) -> bool:
    """The async form. ``assistant.views.chat_view`` is async and resolves its
    user with ``aget_user``, so it cannot call the sync one."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return await Consent.objects.filter(
        user=user, purpose=ConsentPurpose.AI_ASSISTANT, granted=True
    ).aexists()


def set_ai_consent(user, *, granted: bool) -> Consent:
    """Record a decision, keeping both timestamps.

    ``granted_at`` survives a revocation on purpose: the pair of dates is the
    evidence, and overwriting the first one would destroy half of it.
    """
    now = timezone.now()
    consent, _ = Consent.objects.get_or_create(user=user, purpose=ConsentPurpose.AI_ASSISTANT)
    consent.granted = granted
    if granted:
        consent.granted_at = now
        consent.revoked_at = None
    else:
        consent.revoked_at = now
    consent.save(update_fields=["granted", "granted_at", "revoked_at", "updated_at"])
    return consent
