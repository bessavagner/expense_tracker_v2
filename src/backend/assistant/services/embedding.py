import os

from openai import AsyncOpenAI

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536

async_client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY", "sk-not-set"))


async def get_embedding(text: str, *, scope=None) -> list[float] | None:
    """Get embedding vector for text using OpenAI API. Returns None on error.

    ``scope`` is the ``AgentScope`` of the interaction this embedding serves.
    Optional because the semantic index can be rebuilt outside any request —
    ``UsageRecord.interaction`` is nullable for exactly that case (E07 S07-1).
    """
    from assistant.metering import Timer, record_usage
    from assistant.models import UsageKind

    async def meter(usage, latency_ms, *, ok):
        if scope is None:
            return
        await record_usage(
            interaction=getattr(scope, "interaction", None),
            household=scope.household,
            user=scope.user,
            kind=UsageKind.EMBEDDING,
            model=EMBEDDING_MODEL,
            usage=usage,
            latency_ms=latency_ms,
            ok=ok,
        )

    timer = Timer()
    try:
        with timer:
            response = await async_client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=text,
            )
    except Exception:
        await meter(None, timer.ms, ok=False)
        return None
    await meter(_TokenCounts(response.usage), timer.ms, ok=True)
    return response.data[0].embedding


class _TokenCounts:
    """Adapts the embeddings endpoint's usage to what `record_usage` reads.

    OpenAI names them ``prompt_tokens``/``total_tokens`` here and
    ``input_tokens``/``output_tokens`` on the chat endpoints. Handing the raw
    object over would record every embedding as zero tokens, which is
    indistinguishable from a free call and quietly understates the bill.
    """

    output_tokens = 0

    def __init__(self, usage):
        self.input_tokens = getattr(usage, "prompt_tokens", None) or 0
