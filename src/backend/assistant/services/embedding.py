import os

from openai import AsyncOpenAI

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536

async_client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY", "sk-not-set"))


async def get_embedding(text: str) -> list[float] | None:
    """Get embedding vector for text using OpenAI API. Returns None on error."""
    try:
        response = await async_client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=text,
        )
        return response.data[0].embedding
    except Exception:
        return None
