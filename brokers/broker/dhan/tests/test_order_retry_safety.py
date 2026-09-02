"""Regression tests for order POST retry safety."""

from unittest.mock import AsyncMock

import pytest

from brokers.broker.dhan.domain import DhanNetworkError
from brokers.broker.dhan.infrastructure import DhanHttpClient, RetryConfig
from brokers.broker.dhan.ports import HttpRequest


@pytest.mark.asyncio
async def test_order_post_network_ambiguity_is_not_retried():
    client = DhanHttpClient(
        base_url="https://api.dhan.co",
        access_token="test-token",
        retry_config=RetryConfig(max_retries=3, backoff_factor=0),
    )
    request = HttpRequest(method="POST", endpoint="/orders", json={"quantity": 1})
    attempts = 0

    async def ambiguous_request(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        raise DhanNetworkError("response lost after broker accepted request")

    client._execute_request = AsyncMock(side_effect=ambiguous_request)
    client._retry_config.get_delay = lambda attempt: 0

    with pytest.raises(DhanNetworkError):
        await client.request(request)

    assert attempts == 1
    await client.close()
