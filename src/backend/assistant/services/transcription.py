"""Transcrição de áudio via API da OpenAI (sem chaves novas; reusa OPENAI_API_KEY).

Isolado do PydanticAI de propósito: chama o SDK da OpenAI diretamente, então o
guard de testes ``ALLOW_MODEL_REQUESTS = False`` NÃO cobre estas chamadas — os
testes injetam um cliente fake via o parâmetro ``client``.
"""

import logging

from django.conf import settings
from openai import AsyncOpenAI

from assistant.metering import Timer

logger = logging.getLogger(__name__)

# Singleton preguiçoso: evita construir o cliente na importação (que exigiria
# OPENAI_API_KEY presente já no import de views.py). É criado no primeiro uso real.
_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI()  # lê OPENAI_API_KEY do ambiente
    return _client


async def transcribe_audio(
    data: bytes,
    filename: str,
    content_type: str,
    *,
    client: AsyncOpenAI | None = None,
    scope=None,
) -> str:
    """Transcreve ``data`` (bytes de áudio) para texto pt-BR.

    Args:
        data: bytes do arquivo de áudio.
        filename: nome original (ajuda o SDK a inferir o formato).
        content_type: mime real do upload (ex.: "audio/webm").
        client: cliente OpenAI injetável (testes); default usa o singleton.
        scope: ``AgentScope`` da interação; quando dado, CADA tentativa vira uma
            linha em ``UsageRecord`` (E07 S07-2).

    Tenta ``LLM_TRANSCRIBE_MODEL`` e, em caso de falha (ex.: o modelo rejeita o
    webm/opus do navegador como "corrupted or unsupported"), recorre a
    ``LLM_TRANSCRIBE_FALLBACK_MODEL`` (whisper-1, mais tolerante). Só relança a
    exceção se TODOS os modelos falharem.
    """
    client = client or _get_client()

    models = [settings.LLM_TRANSCRIBE_MODEL]
    fallback = getattr(settings, "LLM_TRANSCRIBE_FALLBACK_MODEL", "")
    if fallback and fallback not in models:
        models.append(fallback)

    last_exc: Exception | None = None
    for model in models:
        timer = Timer()
        try:
            with timer:
                result = await client.audio.transcriptions.create(
                    model=model,
                    file=(filename, data, content_type),
                    language="pt",
                )
            await _meter(scope, model, getattr(result, "usage", None), timer.ms, ok=True)
            return result.text.strip()
        except Exception as exc:
            last_exc = exc
            # Metered even though it failed: the provider processed the request
            # and charged for it. This loop is why E07's DoD has a box of its
            # own for "the transcription fallback bills twice" — the browser's
            # webm/opus routinely trips the primary model.
            await _meter(scope, model, None, timer.ms, ok=False)
            logger.warning(
                "Transcrição falhou (modelo=%s, content_type=%s, %d bytes): %s",
                model,
                content_type,
                len(data),
                exc,
            )

    raise last_exc


async def _meter(scope, model: str, usage, latency_ms: int, *, ok: bool) -> None:
    """Record one transcription attempt, if we know whose it was.

    ``cost_usd`` will be ``None``: providers price transcription per MINUTE of
    audio, and ``ModelPrice`` models token pricing only. That gap is deliberate
    and bounded — a transcription is roughly two orders of magnitude cheaper
    than a vision call (E01), so it does not move p50/p90/p99. Documented in
    the runbook and asserted by ``test_pricing_gaps_are_declared``.
    """
    if scope is None:
        return
    from assistant.metering import record_usage
    from assistant.models import UsageKind

    await record_usage(
        interaction=getattr(scope, "interaction", None),
        household=scope.household,
        user=scope.user,
        kind=UsageKind.TRANSCRIPTION,
        model=model,
        usage=usage,
        latency_ms=latency_ms,
        ok=ok,
    )
