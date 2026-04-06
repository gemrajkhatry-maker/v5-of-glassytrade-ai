"""Tests for TradingEngine — standalone engine that streams market data and runs
the full trading pipeline independently of the frontend WebSocket.

All external dependencies (MarketDataPort, TradingSessionService, ServiceGraph)
are fully mocked so these tests run without network, GPU, or database access.
"""

from __future__ import annotations

import asyncio
import math
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.engine import (
    TradingEngine,
    SymbolCircuitBreaker,
    _validate_tick,
    _interval_to_seconds,
    _new_candle_state,
)
from app.domain.trading.models.value_objects import OHLC

IST = timezone(timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_ohlc(**overrides) -> OHLC:
    """Create a valid OHLC with sensible defaults."""
    defaults = {
        "time": "2025-01-15T10:00:00+05:30",
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.0,
        "volume": 1000.0,
        "vwap": 100.5,
        "taker_buy_volume": 600.0,
        "delta": 200.0,
    }
    defaults.update(overrides)
    return OHLC(**defaults)


def _make_graph(active_symbols: list[str] | None = None) -> MagicMock:
    """Create a mock ServiceGraph with all required attributes."""
    graph = MagicMock()
    graph.active_symbols = active_symbols or ["NIFTY-OPT"]

    # Market data mock (async methods)
    graph.market_data = MagicMock()
    graph.market_data.fetch_history = AsyncMock(return_value=[])

    # Session service mock
    graph.trading_session = MagicMock()
    graph.trading_session._sessions = {}
    graph.trading_session.get_or_create_session = MagicMock()

    return graph


def _make_engine(
    active_symbols: list[str] | None = None,
    graph: MagicMock | None = None,
) -> tuple[TradingEngine, MagicMock]:
    """Create TradingEngine with fully mocked ServiceGraph."""
    if graph is None:
        graph = _make_graph(active_symbols)
    engine = TradingEngine(graph)
    return engine, graph


# =====================================================================
# TE-01 to TE-06: Initialisation and lifecycle
# =====================================================================

class TestInitialisation:
    """TE-01: Engine initialises with correct defaults."""

    def test_te01_initial_state(self):
        """TE-01: Engine initialises with generation=0, running=False, empty states."""
        engine, graph = _make_engine(["SYM-A", "SYM-B"])
        assert engine._generation == 0
        assert engine._running is False
        assert engine._latest_states == {}
        assert engine._active_symbols == ["SYM-A", "SYM-B"]
        assert engine._stream_task is None
        assert engine._depth_task is None
        assert engine._watchdog_task is None
        assert engine._stale_watchdog_task is None

    def test_te01_generation_property(self):
        """TE-01: The generation property mirrors internal counter."""
        engine, _ = _make_engine()
        assert engine.generation == 0


class TestStartLifecycle:
    """TE-02 to TE-04: start() behaviour."""

    @pytest.mark.asyncio
    async def test_te02_double_start_is_idempotent(self):
        """TE-02: Calling start() twice does not duplicate tasks or re-seed."""
        engine, graph = _make_engine(["SYM"])
        history = [_make_ohlc() for _ in range(25)]
        graph.market_data.fetch_history = AsyncMock(return_value=history)

        mock_session = MagicMock()
        mock_session.data = []
        graph.trading_session.get_or_create_session.return_value = mock_session

        await engine.start()
        assert engine._running is True
        first_stream_task = engine._stream_task

        # Second start should be a no-op
        await engine.start()
        assert engine._stream_task is first_stream_task

        await engine.stop()

    @pytest.mark.asyncio
    async def test_te03_start_seeds_history(self):
        """TE-03: start() calls fetch_history for each active symbol."""
        engine, graph = _make_engine(["SYM-A", "SYM-B"])
        history = [_make_ohlc() for _ in range(25)]
        graph.market_data.fetch_history = AsyncMock(return_value=history)

        mock_session = MagicMock()
        mock_session.data = []
        graph.trading_session.get_or_create_session.return_value = mock_session

        await engine.start()
        assert graph.market_data.fetch_history.call_count == 2
        await engine.stop()

    @pytest.mark.asyncio
    async def test_te04_start_creates_background_tasks(self):
        """TE-04: start() creates all four background tasks."""
        engine, graph = _make_engine(["SYM"])
        graph.market_data.fetch_history = AsyncMock(return_value=[])

        await engine.start()
        assert engine._stream_task is not None
        assert engine._depth_task is not None
        assert engine._watchdog_task is not None
        assert engine._stale_watchdog_task is not None
        await engine.stop()


class TestStopLifecycle:
    """TE-05 to TE-06: stop() behaviour."""

    @pytest.mark.asyncio
    async def test_te05_stop_sets_running_false(self):
        """TE-05: stop() sets _running to False."""
        engine, graph = _make_engine(["SYM"])
        graph.market_data.fetch_history = AsyncMock(return_value=[])

        await engine.start()
        assert engine._running is True
        await engine.stop()
        assert engine._running is False

    @pytest.mark.asyncio
    async def test_te06_stop_is_idempotent(self):
        """TE-06: stop() on an engine that was never started raises no exception."""
        engine, _ = _make_engine()
        await engine.stop()  # Should not raise
        assert engine._running is False


# =====================================================================
# TE-07 to TE-10: Generation counter and wait_for_update
# =====================================================================

class TestGenerationCounter:
    """Tests for generation-based viewer notification."""

    def test_te07_generation_starts_at_zero(self):
        """TE-07: Generation counter starts at 0."""
        engine, _ = _make_engine()
        assert engine.generation == 0

    @pytest.mark.asyncio
    async def test_te08_notify_viewers_increments_generation(self):
        """TE-08: _notify_viewers(force=True) increments generation."""
        engine, _ = _make_engine()
        assert engine._generation == 0
        await engine._notify_viewers(force=True)
        assert engine._generation == 1
        await engine._notify_viewers(force=True)
        assert engine._generation == 2

    @pytest.mark.asyncio
    async def test_te09_wait_for_update_returns_new_gen(self):
        """TE-09: wait_for_update returns new generation after notify."""
        engine, _ = _make_engine()

        async def notify_after_delay():
            await asyncio.sleep(0.05)
            await engine._notify_viewers(force=True)

        task = asyncio.create_task(notify_after_delay())
        new_gen = await engine.wait_for_update(0, timeout=2.0)
        assert new_gen >= 1
        await task

    @pytest.mark.asyncio
    async def test_te10_wait_for_update_times_out(self):
        """TE-10: wait_for_update returns current gen on timeout (no notify)."""
        engine, _ = _make_engine()
        gen = await engine.wait_for_update(0, timeout=0.1)
        # No notify happened, so generation stays at 0
        assert gen == 0


# =====================================================================
# TE-11 to TE-14: State access methods
# =====================================================================

class TestStateAccess:
    """Tests for get_latest_state, get_all_latest_states, get_active_symbols."""

    def test_te11_get_latest_state_unknown_symbol(self):
        """TE-11: get_latest_state returns None for symbol not in states."""
        engine, _ = _make_engine()
        assert engine.get_latest_state("NONEXISTENT") is None

    def test_te12_get_latest_state_returns_independent_copy(self):
        """TE-12: get_latest_state returns a shallow copy; top-level scalar
        mutation does not affect engine.  Portfolio is deep-copied separately."""
        engine, _ = _make_engine()
        engine._latest_states["SYM"] = {"ltp": 100.0, "portfolio": {"positions": [1, 2]}}
        state = engine.get_latest_state("SYM")
        assert state is not None
        assert state["ltp"] == 100.0

        # Mutate the returned copy — scalars are independent via shallow copy
        state["ltp"] = 999.0
        assert engine._latest_states["SYM"]["ltp"] == 100.0

        # Portfolio is deep-copied so mutation is also independent
        state["portfolio"]["positions"].append(3)
        assert engine._latest_states["SYM"]["portfolio"]["positions"] == [1, 2]

    def test_te13_get_all_latest_states(self):
        """TE-13: get_all_latest_states returns all known symbol states."""
        engine, _ = _make_engine()
        engine._latest_states["A"] = {"ltp": 10}
        engine._latest_states["B"] = {"ltp": 20}
        result = engine.get_all_latest_states()
        assert set(result.keys()) == {"A", "B"}
        assert result["A"]["ltp"] == 10
        assert result["B"]["ltp"] == 20

    def test_te14_get_active_symbols_returns_copy(self):
        """TE-14: get_active_symbols returns a new list, not the internal reference."""
        engine, _ = _make_engine(["X", "Y"])
        syms = engine.get_active_symbols()
        assert syms == ["X", "Y"]
        syms.append("Z")
        assert engine.get_active_symbols() == ["X", "Y"]  # Unchanged


# =====================================================================
# TE-15 to TE-20: SymbolCircuitBreaker (mirrors existing tests)
# =====================================================================

class TestSymbolCircuitBreaker:
    """Tests for the per-symbol circuit breaker."""

    def test_te15_starts_closed(self):
        """TE-15: A new circuit breaker is closed for all symbols."""
        cb = SymbolCircuitBreaker(max_failures=3, cooldown_secs=10)
        assert not cb.is_open("GOLD")

    def test_te16_opens_after_max_failures(self):
        """TE-16: Circuit opens after max_failures consecutive failures."""
        cb = SymbolCircuitBreaker(max_failures=3, cooldown_secs=60)
        cb.record_failure("GOLD")
        cb.record_failure("GOLD")
        assert not cb.is_open("GOLD")
        cb.record_failure("GOLD")  # 3rd failure -> open
        assert cb.is_open("GOLD")

    def test_te17_success_resets_failures(self):
        """TE-17: record_success clears the failure counter."""
        cb = SymbolCircuitBreaker(max_failures=3, cooldown_secs=60)
        cb.record_failure("GOLD")
        cb.record_failure("GOLD")
        cb.record_success("GOLD")
        cb.record_failure("GOLD")
        cb.record_failure("GOLD")
        assert not cb.is_open("GOLD")  # Only 2 consecutive failures

    def test_te18_isolates_symbols(self):
        """TE-18: Failures on one symbol do not affect another."""
        cb = SymbolCircuitBreaker(max_failures=2, cooldown_secs=60)
        cb.record_failure("GOLD")
        cb.record_failure("GOLD")
        assert cb.is_open("GOLD")
        assert not cb.is_open("SILVER")

    def test_te19_closes_after_cooldown(self):
        """TE-19: Circuit closes (half-open) after cooldown expires."""
        cb = SymbolCircuitBreaker(max_failures=2, cooldown_secs=0.1)
        cb.record_failure("GOLD")
        cb.record_failure("GOLD")
        assert cb.is_open("GOLD")
        time.sleep(0.15)
        assert not cb.is_open("GOLD")

    def test_te20_half_open_reopens_on_failure(self):
        """TE-20: After cooldown, one more failure re-opens the circuit."""
        cb = SymbolCircuitBreaker(max_failures=2, cooldown_secs=0.1)
        cb.record_failure("GOLD")
        cb.record_failure("GOLD")
        time.sleep(0.15)
        assert not cb.is_open("GOLD")  # half-open
        cb.record_failure("GOLD")  # re-opens
        assert cb.is_open("GOLD")


# =====================================================================
# TE-21 to TE-25: _validate_tick
# =====================================================================

class TestValidateTick:
    """Tests for the module-level _validate_tick function."""

    def test_te21_rejects_nan_open(self):
        """TE-21: _validate_tick rejects NaN open price."""
        tick = _make_ohlc(open=float("nan"))
        assert _validate_tick(tick) is not None
        assert "open" in _validate_tick(tick)

    def test_te22_rejects_negative_close(self):
        """TE-22: _validate_tick rejects negative close price."""
        tick = _make_ohlc(close=-1.0)
        assert _validate_tick(tick) is not None
        assert "close" in _validate_tick(tick)

    def test_te23_rejects_high_less_than_low(self):
        """TE-23: _validate_tick rejects when high < low."""
        tick = _make_ohlc(high=98.0, low=100.0)
        result = _validate_tick(tick)
        assert result is not None
        assert "high" in result

    def test_te24_rejects_negative_volume(self):
        """TE-24: _validate_tick rejects negative volume."""
        tick = _make_ohlc(volume=-100.0)
        result = _validate_tick(tick)
        assert result is not None
        assert "volume" in result

    def test_te25_passes_valid_tick(self):
        """TE-25: _validate_tick returns None for a valid tick."""
        tick = _make_ohlc()
        assert _validate_tick(tick) is None

    def test_validate_tick_rejects_inf_high(self):
        """_validate_tick rejects Inf high price."""
        tick = _make_ohlc(high=float("inf"))
        assert _validate_tick(tick) is not None

    def test_validate_tick_rejects_zero_open(self):
        """_validate_tick rejects zero open price."""
        tick = _make_ohlc(open=0.0)
        assert _validate_tick(tick) is not None

    def test_validate_tick_rejects_inf_volume(self):
        """_validate_tick rejects Inf volume."""
        tick = _make_ohlc(volume=float("inf"))
        assert _validate_tick(tick) is not None

    def test_validate_tick_accepts_zero_volume(self):
        """_validate_tick accepts zero volume (valid: no trades yet)."""
        tick = _make_ohlc(volume=0.0)
        assert _validate_tick(tick) is None


# =====================================================================
# TE-26 to TE-28: _interval_to_seconds
# =====================================================================

class TestIntervalToSeconds:
    """Tests for the _interval_to_seconds helper."""

    def test_te26_minutes(self):
        """TE-26: 5m -> 300 seconds."""
        assert _interval_to_seconds("5m") == 300

    def test_te27_hours(self):
        """TE-27: 1h -> 3600 seconds."""
        assert _interval_to_seconds("1h") == 3600

    def test_te28_days(self):
        """TE-28: 1d -> 86400 seconds."""
        assert _interval_to_seconds("1d") == 86400

    def test_interval_1m(self):
        """1m -> 60 seconds."""
        assert _interval_to_seconds("1m") == 60

    def test_interval_15m(self):
        """15m -> 900 seconds."""
        assert _interval_to_seconds("15m") == 900

    def test_interval_4h(self):
        """4h -> 14400 seconds."""
        assert _interval_to_seconds("4h") == 14400

    def test_interval_unknown_unit_defaults_to_minutes(self):
        """Unknown unit suffix defaults to minutes."""
        assert _interval_to_seconds("3x") == 180


# =====================================================================
# TE-29: _new_candle_state
# =====================================================================

class TestNewCandleState:
    """Tests for the _new_candle_state factory."""

    def test_te29_fresh_state(self):
        """TE-29: _new_candle_state returns dict with expected keys and defaults."""
        state = _new_candle_state()
        assert state["start"] is None
        assert state["open"] == 0
        assert state["high"] == 0
        assert state["low"] == 0
        assert state["close"] == 0
        assert state["volume"] == 0
        assert state["buy_volume"] == 0
        assert state["oi"] == 0
        assert state["prev_cum_vol"] == -1
        assert state["candle_vol"] == 0
        assert state["prev_cum_buy"] == -1
        assert state["prev_cum_sell"] == -1
        assert state["candle_buy_vol"] == 0
        assert state["candle_sell_vol"] == 0

    def test_new_candle_state_returns_new_dict(self):
        """Each call to _new_candle_state returns a fresh dict."""
        s1 = _new_candle_state()
        s2 = _new_candle_state()
        assert s1 is not s2
        s1["open"] = 999
        assert s2["open"] == 0


# =====================================================================
# TE-30 to TE-36: Candle aggregation
# =====================================================================

class TestAggregateCandle:
    """Tests for TradingEngine._aggregate_candle logic."""

    def _make_engine_for_aggregation(self, interval: str = "5m") -> TradingEngine:
        """Create a TradingEngine wired for aggregation tests only."""
        graph = _make_graph(["TEST"])
        engine = TradingEngine(graph)
        engine._candle_states["TEST"] = _new_candle_state()
        engine._interval_secs = _interval_to_seconds(interval)
        return engine

    def test_te30_new_candle_on_start_change(self):
        """TE-30: First tick creates a candle with open=high=low=close=ltp."""
        engine = self._make_engine_for_aggregation("5m")
        now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=IST)
        result = engine._aggregate_candle("TEST", now, 100.0, 5000, 0, 0, 0)
        assert result is not None
        assert result.open == 100.0
        assert result.high == 100.0
        assert result.low == 100.0
        assert result.close == 100.0

    def test_te31_updates_within_candle(self):
        """TE-31: Subsequent ticks in the same candle update high/low/close."""
        engine = self._make_engine_for_aggregation("5m")
        now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=IST)

        # First tick
        engine._aggregate_candle("TEST", now, 100.0, 1000, 0, 0, 0)

        # Higher tick
        now2 = datetime(2025, 1, 15, 10, 0, 30, tzinfo=IST)
        result = engine._aggregate_candle("TEST", now2, 105.0, 1200, 0, 0, 0)
        assert result is not None
        assert result.open == 100.0
        assert result.high == 105.0
        assert result.close == 105.0

        # Lower tick
        now3 = datetime(2025, 1, 15, 10, 1, 0, tzinfo=IST)
        result = engine._aggregate_candle("TEST", now3, 97.0, 1500, 0, 0, 0)
        assert result is not None
        assert result.low == 97.0
        assert result.close == 97.0
        assert result.open == 100.0  # unchanged

    def test_te32_cumulative_volume(self):
        """TE-32: Candle volume is computed from cumulative volume deltas."""
        engine = self._make_engine_for_aggregation("5m")
        now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=IST)

        # First tick: establishes baseline (candle_vol = 0)
        result = engine._aggregate_candle("TEST", now, 100.0, 10000, 0, 0, 0)
        assert result is not None
        assert result.volume == 0.0  # First tick is baseline

        # Second tick: cumulative volume increased by 500
        now2 = datetime(2025, 1, 15, 10, 0, 30, tzinfo=IST)
        result = engine._aggregate_candle("TEST", now2, 101.0, 10500, 0, 0, 0)
        assert result is not None
        assert result.volume == 500.0

    def test_te33_cumulative_volume_reset(self):
        """TE-33: When cumulative volume resets (new session), candle_vol = 0."""
        engine = self._make_engine_for_aggregation("5m")
        now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=IST)

        # Establish baseline at 10000
        engine._aggregate_candle("TEST", now, 100.0, 10000, 0, 0, 0)

        # Normal increment
        now2 = datetime(2025, 1, 15, 10, 0, 30, tzinfo=IST)
        engine._aggregate_candle("TEST", now2, 101.0, 10200, 0, 0, 0)

        # Volume reset: new cumulative < previous
        now3 = datetime(2025, 1, 15, 10, 1, 0, tzinfo=IST)
        result = engine._aggregate_candle("TEST", now3, 102.0, 500, 0, 0, 0)
        assert result is not None
        # After reset, prev_cum_vol is reset, so candle_vol stays at 200 from before + 0
        # The reset path sets candle_vol = 0 for the new increment only
        # Volume should be 200 (from second tick) + 0 (from reset tick)
        assert result.volume == 200.0

    def test_te34_delta_from_buy_sell_quantities(self):
        """TE-34: Delta is computed from cumulative buy/sell quantities."""
        engine = self._make_engine_for_aggregation("5m")
        now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=IST)

        # First tick: establishes baseline
        engine._aggregate_candle("TEST", now, 100.0, 10000, 5000, 3000, 0)

        # Second tick: buy increased 200, sell increased 100 => delta = 100
        now2 = datetime(2025, 1, 15, 10, 0, 30, tzinfo=IST)
        result = engine._aggregate_candle("TEST", now2, 101.0, 10500, 5200, 3100, 0)
        assert result is not None
        # candle_buy_vol = 200, candle_sell_vol = 100 => delta = 100
        assert result.delta == 100.0

    def test_te35_fallback_body_ratio_delta(self):
        """TE-35: When buy/sell are zero, delta uses body-ratio fallback."""
        engine = self._make_engine_for_aggregation("5m")
        now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=IST)

        # First tick with zero buy/sell cumulative
        engine._aggregate_candle("TEST", now, 100.0, 10000, 0, 0, 0)

        # Second tick: cumulative volume grew but no buy/sell data
        now2 = datetime(2025, 1, 15, 10, 0, 30, tzinfo=IST)
        result = engine._aggregate_candle("TEST", now2, 105.0, 10500, 0, 0, 0)
        assert result is not None
        # Body ratio = (105 - 100) / (105 - 100) = 1.0, delta = 1.0 * 500 = 500
        # But candle_buy_vol and candle_sell_vol are both 0, so fallback fires
        # Both cum_buy and cum_sell remain 0 (initialized from first tick)
        # Since the candle starts at 100 and goes to 105 with high=105 low=100:
        # spread = high - low = 105 - 100 = 5
        # body_ratio = (close - open) / spread = (105 - 100) / 5 = 1.0
        # delta = body_ratio * volume = 1.0 * 500 = 500
        assert result.delta == pytest.approx(500.0, rel=0.01)

    def test_te36_candle_start_floors_to_interval(self):
        """TE-36: _candle_start floors timestamp to interval boundary."""
        engine = self._make_engine_for_aggregation("5m")
        # 10:03:27 should floor to 10:00:00 for 5m intervals
        ts = datetime(2025, 1, 15, 10, 3, 27, tzinfo=IST)
        start = engine._candle_start(ts)
        assert start.minute == 0
        assert start.second == 0

        # 10:07:59 should floor to 10:05:00
        ts2 = datetime(2025, 1, 15, 10, 7, 59, tzinfo=IST)
        start2 = engine._candle_start(ts2)
        assert start2.minute == 5
        assert start2.second == 0

    def test_aggregate_new_candle_boundary(self):
        """A tick in a new 5m window resets the candle state."""
        engine = self._make_engine_for_aggregation("5m")

        # First candle at 10:00
        t1 = datetime(2025, 1, 15, 10, 0, 0, tzinfo=IST)
        engine._aggregate_candle("TEST", t1, 100.0, 10000, 0, 0, 0)

        t2 = datetime(2025, 1, 15, 10, 2, 0, tzinfo=IST)
        engine._aggregate_candle("TEST", t2, 105.0, 10300, 0, 0, 0)

        # New candle at 10:05
        t3 = datetime(2025, 1, 15, 10, 5, 0, tzinfo=IST)
        result = engine._aggregate_candle("TEST", t3, 110.0, 10600, 0, 0, 0)
        assert result is not None
        # New candle: open should be 110, not carried from previous candle
        assert result.open == 110.0
        assert result.high == 110.0
        assert result.low == 110.0
        assert result.close == 110.0

    def test_aggregate_vwap_calculation(self):
        """VWAP is correctly computed as sum(price*vol) / sum(vol)."""
        engine = self._make_engine_for_aggregation("5m")
        now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=IST)

        # First tick: baseline
        engine._aggregate_candle("TEST", now, 100.0, 10000, 0, 0, 0)

        # Second tick: volume = 200, price = 100 => vwap_num = 0 + 100*0 (first) + ...
        # First tick: candle_vol=0, so vwap_num = 100*0 = 0, vwap_den = 0
        # VWAP defaults to ltp when vwap_den == 0
        now2 = datetime(2025, 1, 15, 10, 0, 30, tzinfo=IST)
        result = engine._aggregate_candle("TEST", now2, 102.0, 10200, 0, 0, 0)
        assert result is not None
        # vwap_num = 0 (from first tick with vol=0) + 102*200 = 20400
        # vwap_den = 0 + 200 = 200
        # vwap = 20400 / 200 = 102.0
        assert result.vwap == pytest.approx(102.0, rel=0.01)


# =====================================================================
# Additional: _update_throttled_state
# =====================================================================

class TestThrottledState:
    """Tests for _update_throttled_state merging behaviour."""

    def test_throttled_state_updates_ltp(self):
        """Throttled update sets ltp and tick on existing state."""
        engine, graph = _make_engine(["SYM"])
        graph.trading_session._sessions = {}

        # Provide a dummy ohlc_to_dto
        def mock_ohlc_to_dto(tick):
            return {"time": tick.time, "close": tick.close}

        tick = _make_ohlc(close=150.0)
        engine._latest_states["SYM"] = {"status": "seeded"}
        engine._update_throttled_state("SYM", tick, 150.0, 500, mock_ohlc_to_dto)

        state = engine._latest_states["SYM"]
        assert state["ltp"] == 150.0
        assert state["oi"] == 500
        assert state["status"] == "seeded"  # Preserved from previous state

    def test_throttled_state_merges_with_previous(self):
        """Throttled update preserves keys from previous full process_tick state."""
        engine, graph = _make_engine(["SYM"])
        graph.trading_session._sessions = {}

        engine._latest_states["SYM"] = {
            "genAIAnalysis": {"direction": "LONG"},
            "ltp": 100.0,
        }

        def mock_ohlc_to_dto(tick):
            return {"time": tick.time}

        tick = _make_ohlc(close=105.0)
        engine._update_throttled_state("SYM", tick, 105.0, 0, mock_ohlc_to_dto)

        state = engine._latest_states["SYM"]
        assert state["ltp"] == 105.0
        assert state["genAIAnalysis"]["direction"] == "LONG"


# =====================================================================
# Additional: get_history and get_depth
# =====================================================================

class TestHistoryAndDepth:
    """Tests for get_history and get_depth accessors."""

    def test_get_history_no_session(self):
        """get_history returns empty list for unknown symbol."""
        engine, graph = _make_engine()
        graph.trading_session._sessions = {}
        result = engine.get_history("UNKNOWN")
        assert result == []

    def test_get_depth_no_symbol(self):
        """get_depth returns None for unknown symbol."""
        engine, _ = _make_engine()
        assert engine.get_depth("UNKNOWN") is None

    def test_get_depth_returns_stored_book(self):
        """get_depth returns the stored OrderBook for a symbol."""
        from app.domain.trading.models.value_objects import OrderBook, OrderBookLevel
        engine, _ = _make_engine(["SYM"])
        book = OrderBook(
            bids=(OrderBookLevel(price=100.0, quantity=50.0),),
            asks=(OrderBookLevel(price=101.0, quantity=30.0),),
        )
        engine._current_depths["SYM"] = {"book": book}
        result = engine.get_depth("SYM")
        assert result is book
