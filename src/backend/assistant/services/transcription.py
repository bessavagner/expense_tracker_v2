"""Transcrição de áudio via API da OpenAI (sem chaves novas; reusa OPENAI_API_KEY).

Isolado do PydanticAI de propósito: chama o SDK da OpenAI diretamente, então o
guard de testes ``ALLOW_MODEL_REQUESTS = False`` NÃO cobre estas chamadas — os
testes injetam um cliente fake via o parâmetro ``client``.
"""

from django.conf import settings
from openai import AsyncOpenAI

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
) -> str:
    """Transcreve ``data`` (bytes de áudio) para texto pt-BR.

    Args:
        data: bytes do arquivo de áudio.
        filename: nome original (ajuda o SDK a inferir o formato).
        content_type: mime real do upload (ex.: "audio/webm").
        client: cliente OpenAI injetável (testes); default usa o singleton.
    """
    client = client or _get_client()
    result = await client.audio.transcriptions.create(
        model=settings.LLM_TRANSCRIBE_MODEL,
        file=(filename, data, content_type),
        language="pt",
    )
    return result.text.strip()
