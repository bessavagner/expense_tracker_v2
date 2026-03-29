from unittest.mock import AsyncMock, patch

import pytest

from assistant.services.embedding import get_embedding


@pytest.mark.anyio
async def test_get_embedding_returns_vector():
    mock_response = AsyncMock()
    mock_response.data = [AsyncMock(embedding=[0.1] * 1536)]

    with patch("assistant.services.embedding.async_client") as mock_client:
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)
        result = await get_embedding("compra no supermercado")

    assert len(result) == 1536
    assert result[0] == 0.1
    mock_client.embeddings.create.assert_awaited_once_with(
        model="text-embedding-3-small",
        input="compra no supermercado",
    )


@pytest.mark.anyio
async def test_get_embedding_returns_none_on_error():
    with patch("assistant.services.embedding.async_client") as mock_client:
        mock_client.embeddings.create = AsyncMock(side_effect=Exception("API error"))
        result = await get_embedding("test")

    assert result is None
