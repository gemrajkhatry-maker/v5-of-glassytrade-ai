"""Tests for notification adapters."""
import asyncio
import pytest
from app.infrastructure.adapters.null_notification_adapter import NullNotificationAdapter
from app.infrastructure.adapters.telegram_adapter import TelegramAdapter


def test_null_adapter_send_sync():
    adapter = NullNotificationAdapter()
    adapter.send_sync("test message", "INFO")  # should not raise


@pytest.mark.asyncio
async def test_null_adapter_send_async():
    adapter = NullNotificationAdapter()
    await adapter.send("test message", "WARNING")  # should not raise


@pytest.mark.asyncio
async def test_telegram_rate_limiting():
    """Telegram adapter rate-limits same-level messages."""
    import time
    adapter = TelegramAdapter("fake_token", "fake_chat")
    adapter._min_interval = 100.0  # force rate limit
    adapter._last_sent["INFO"] = time.monotonic()
    # Second send same level within interval — should be suppressed (no error)
    await adapter.send("test", "INFO")
