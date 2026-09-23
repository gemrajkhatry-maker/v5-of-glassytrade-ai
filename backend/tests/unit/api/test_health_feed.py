"""Wave 2 / health feed block — surface feed silence, drops, poll fallback.

Blocker B-3: a starved/silent feed hid behind an "ok" /health. The coordinator
block must expose the shared MultiplexedMarketFeed snapshot and degrade when
silent symbols accumulate while the market is open, the WS→REST poll fallback
runs past 60s, or the producer thread is dead.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.api.routers import health as health_mod


class _FeedCoordinator:
    """Double exposing the coordinator surface /health reads."""

    def __init__(
        self,
        silent: list[str] | None = None,
        drops: dict[str, int] | None = None,
        poll_fallback: bool = False,
        poll_age: float | None = None,
        producer_alive: bool = True,
        started: bool = True,
    ) -> None:
        self.started = started
        self._silent = silent or []
        self._drops = drops or {}
        self._poll_fallback = poll_fallback
        self._poll_age = poll_age
        self._producer_alive = producer_alive

    def symbols(self) -> list[str]:
        return ["X"]

    def crashed_engines(self) -> list[str]:
        return []

    def stale_engines(self) -> list[str]:
        return []

    def feed_health(self) -> dict:
        return {
            "silentSymbols": list(self._silent),
            "dropCounts": dict(self._drops),
            "pollFallback": self._poll_fallback,
            "pollFallbackAgeSec": self._poll_age,
            "producerAlive": self._producer_alive,
        }


def _request(coordinator) -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(coordinator=coordinator))
    )


def _storage() -> SimpleNamespace:
    return SimpleNamespace(kv_set=lambda *a, **k: None)


async def _call_health(coordinator, monkeypatch) -> dict:
    monkeypatch.setenv("GLASSYTRADE_ENV", "paper")
    monkeypatch.delenv("TRADING_MODE", raising=False)
    return await health_mod.health_check(
        _request(coordinator), broker=object(), storage=_storage(), config=object()
    )


@pytest.mark.asyncio
async def test_health_exposes_feed_silence_and_drops(monkeypatch):
    """checks.feed carries silentSymbols + dropCounts; silence degrades when open."""
    monkeypatch.setattr(health_mod, "is_market_open", lambda *a, **k: True)
    coord = _FeedCoordinator(
        silent=["X"], drops={"late_tick:X": 3}, producer_alive=True
    )
    payload = await _call_health(coord, monkeypatch)

    feed = payload["checks"]["feed"]
    assert feed["silentSymbols"] == ["X"]
    assert feed["dropCounts"]["late_tick:X"] == 3
    assert feed["pollFallback"] is False
    assert feed["producerAlive"] is True
    # Silent symbol while market open → degraded (not ok).
    assert payload["status"] == "degraded"


@pytest.mark.asyncio
async def test_health_feed_silent_while_market_closed_stays_ok(monkeypatch):
    """Silence after close is expected — must not force degraded."""
    monkeypatch.setattr(health_mod, "is_market_open", lambda *a, **k: False)
    coord = _FeedCoordinator(silent=["X"], producer_alive=True)
    payload = await _call_health(coord, monkeypatch)

    assert payload["checks"]["feed"]["silentSymbols"] == ["X"]
    assert payload["status"] == "ok"


@pytest.mark.asyncio
async def test_health_feed_poll_fallback_over_60s_degrades(monkeypatch):
    monkeypatch.setattr(health_mod, "is_market_open", lambda *a, **k: False)
    coord = _FeedCoordinator(poll_fallback=True, poll_age=61.0)
    payload = await _call_health(coord, monkeypatch)

    assert payload["checks"]["feed"]["pollFallback"] is True
    assert payload["status"] == "degraded"


@pytest.mark.asyncio
async def test_health_feed_dead_producer_degrades(monkeypatch):
    monkeypatch.setattr(health_mod, "is_market_open", lambda *a, **k: False)
    coord = _FeedCoordinator(producer_alive=False)
    payload = await _call_health(coord, monkeypatch)

    assert payload["checks"]["feed"]["producerAlive"] is False
    assert payload["status"] == "degraded"


@pytest.mark.asyncio
async def test_health_without_coordinator_has_no_feed_block(monkeypatch):
    monkeypatch.setenv("GLASSYTRADE_ENV", "paper")
    monkeypatch.delenv("TRADING_MODE", raising=False)
    payload = await health_mod.health_check(
        _request(None), broker=object(), storage=_storage(), config=object()
    )
    assert "feed" not in payload["checks"]
