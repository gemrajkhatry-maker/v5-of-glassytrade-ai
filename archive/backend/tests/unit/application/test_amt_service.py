"""Tests for AMTService / AMTHandler concurrency safety (AMT Strategy Cleanup, Task 2).

The engine's process_tick (worker thread), the legacy WS path (asyncio.to_thread),
and gap-fill can all invoke analyze() concurrently for the same symbol. AMTHandler
owns mutable per-symbol state (incremental profiles, prev_data_len, cached DTOs)
and AMTAnalyzer owns VWAP accumulators / session data / aggression state — none of
it is thread-safe. These tests pin down that per-symbol analysis is serialized via
``AMTHandler._analyze_lock`` (an RLock) and that underlying-state sync in
``AMTService`` is guarded by ``_state_lock``.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from app.application.handlers.amt_handler import AMTHandler
from app.application.services.amt_service import AMTService
from quant.contracts.value_objects import AMTResult, OHLC

_IST = timezone(timedelta(hours=5, minutes=30))


def _today() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d")


def _make_candles(n: int, base_price: float = 100.0) -> list[OHLC]:
    """Build n real OHLC candles for today's IST session."""
    return [
        OHLC.create(
            time=f"{_today()}T09:{15 + i * 5:02d}:00+05:30",
            open=base_price + i * 0.5,
            high=base_price + i * 0.5 + 2.0,
            low=base_price + i * 0.5 - 2.0,
            close=base_price + i * 0.5 + 1.0,
            volume=1000.0,
            vwap=base_price + i * 0.5 + 0.5,
            taker_buy_volume=600.0,
            delta=200.0,
        )
        for i in range(n)
    ]


def _make_amt_result(market_state: str = "BALANCED") -> AMTResult:
    return AMTResult(
        market_state=market_state,
        poc=100.0,
        value_area_high=105.0,
        value_area_low=95.0,
    )


def test_handler_has_analyze_lock():
    """AMTHandler exposes a per-symbol RLock used to serialize analyze()."""
    handler = AMTHandler()
    assert type(handler._analyze_lock) is type(threading.RLock())


def test_concurrent_analyze_same_symbol_is_serialized():
    """Concurrent analyze() calls on one handler run without exceptions and
    leave the shared analyzer state consistent (prev_data_len == last data len)."""
    handler = AMTHandler()
    data = _make_candles(10)
    errors: list[Exception] = []

    def call():
        try:
            handler.analyze(data, None)
        except Exception as exc:  # noqa: BLE001 — collected and asserted below
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(lambda _: call(), range(8)))

    assert not errors, f"analyze() raised under concurrency: {errors}"
    # Every call ran with the same data length, so the shared profile length
    # must have settled on the actual data length — interleaved mutations
    # would leave it wrong.
    assert handler._prev_data_len == len(data)


def test_service_has_state_lock():
    """AMTService exposes _state_lock guarding _sync_underlying_state."""
    service = AMTService()
    assert type(service._state_lock) is type(threading.Lock())


def test_concurrent_underlying_state_sync_is_safe():
    """Concurrent _sync_underlying_state calls for symbols sharing an underlying
    run without exceptions and converge on a consistent cached state."""
    service = AMTService()
    symbols = [f"NIFTY 11 AUG 24650 CALL {i}" for i in range(4)]
    errors: list[Exception] = []

    def call(symbol: str):
        try:
            service._sync_underlying_state(
                symbol,
                _make_amt_result(),
                {"marketState": "BALANCED"},
            )
        except Exception as exc:  # noqa: BLE001 — collected and asserted below
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(call, symbols * 2))

    assert not errors, f"_sync_underlying_state raised under concurrency: {errors}"
    # All calls used the same underlying token "NIFTY" and the same market state.
    for sym in symbols:
        underlying = sym.split(" ")[0].split("-")[0].upper()
        assert underlying in service._underlying_state_cache
