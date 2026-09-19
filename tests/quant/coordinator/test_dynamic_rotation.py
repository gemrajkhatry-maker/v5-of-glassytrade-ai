"""Tests for dynamic rotation of dead/drifted option symbols in QuantCoordinator."""

import logging
import time

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from quant.multi_engine import QuantCoordinator
from quant.runtime import QuantEngine
from quant.bars import Bar
from quant.amt.session.scanner import ScanResult


def test_rotate_dead_symbols_skips_futures():
    """Futures underlyings are foundational macro feeds and must NEVER be rotated."""
    coord = QuantCoordinator.__new__(QuantCoordinator)
    coord._lock = MagicMock()
    coord._lifecycle_lock = MagicMock()
    coord._stop = MagicMock()
    coord._stop.is_set.return_value = False
    coord.config = {"exchange": "NSE"}

    mock_fut = MagicMock()
    coord._engines = {"NIFTY SEP FUT": mock_fut}

    rotated = coord.check_and_rotate_dead_symbols()
    assert rotated == []


def test_rotate_dead_symbols_skips_open_positions():
    """Option contracts with active open positions must NEVER be rotated.
    The guard keys off the REAL position authority (folded EngineState), not
    the phantom ``engine._position`` attribute a real QuantEngine never had."""
    coord = QuantCoordinator.__new__(QuantCoordinator)
    coord._lock = MagicMock()
    coord._lifecycle_lock = MagicMock()
    coord._stop = MagicMock()
    coord._stop.is_set.return_value = False
    coord.config = {"exchange": "NSE"}

    mock_opt = MagicMock()
    mock_opt.state = SimpleNamespace(position=object())  # Active position!

    coord._engines = {"NIFTY 1 SEP 24100 PUT": mock_opt}

    rotated = coord.check_and_rotate_dead_symbols()
    assert rotated == []


@patch("quant.amt.session.symbol_registry.is_market_open", return_value=True)
@patch("quant.amt.session.scanner.OptionScannerService.scan_top_n")
def test_rotate_dead_symbols_swaps_drifted_strike(mock_scan, mock_open):
    """When an option strike drifts > 2.5 steps from spot, it is swapped for an active ATM contract."""
    coord = QuantCoordinator.__new__(QuantCoordinator)
    coord._lock = MagicMock()
    coord._lifecycle_lock = MagicMock()
    coord._stop = MagicMock()
    coord._stop.is_set.return_value = False
    coord.config = {"exchange": "NSE", "expiry_index": 0, "strikes_around_atm": 3}
    coord.market_data = MagicMock()

    # Futures spot at 24500 (NIFTY step = 50)
    mock_fut = MagicMock()
    mock_fut._aggregator.current_bar = Bar(
        time="t1", open=24500.0, high=24500.0, low=24500.0, close=24500.0,
        volume=100, buy_volume=50, sell_volume=50, delta=0, oi=1000, vwap=24500.0,
    )

    # Option strike at 24100 (drift = 400 pts > 2.5 * 50 = 125 pts)
    mock_opt = MagicMock()
    mock_opt.state = SimpleNamespace(position=None, pyramids=())
    mock_opt._market = "NSE"
    mock_opt._last_tick_wall = 0.0

    coord._engines = {
        "NIFTY SEP FUT": mock_fut,
        "NIFTY 1 SEP 24100 PUT": mock_opt,
    }

    # Scanner returns replacement ATM contract
    mock_scan.return_value = [
        ScanResult(
            symbol="NIFTY 1 SEP 24500 PUT",
            underlying="NIFTY",
            strike=24500.0,
            option_type="PE",
            expiry="2026-09-01",
            ltp=120.0,
            oi=50000,
            volume=20000,
            spread=0.5,
            score=85.0,
        ),
    ]

    coord.switch_symbol = MagicMock(return_value=True)

    rotated = coord.check_and_rotate_dead_symbols(max_drift_steps=2.5)

    assert len(rotated) == 1
    assert rotated[0] == ("NIFTY 1 SEP 24100 PUT", "NIFTY 1 SEP 24500 PUT")
    coord.switch_symbol.assert_called_once_with("NIFTY 1 SEP 24100 PUT", "NIFTY 1 SEP 24500 PUT")


@patch("quant.amt.session.symbol_registry.is_market_open", return_value=True)
def test_rotate_dead_symbols_keeps_healthy_contract(mock_open):
    """When an option strike is near ATM and active, it must NOT be rotated."""
    coord = QuantCoordinator.__new__(QuantCoordinator)
    coord._lock = MagicMock()
    coord._lifecycle_lock = MagicMock()
    coord._stop = MagicMock()
    coord._stop.is_set.return_value = False
    coord.config = {"exchange": "NSE"}

    mock_fut = MagicMock()
    mock_fut._aggregator.current_bar = Bar(
        time="t1", open=14710.0, high=14710.0, low=14710.0, close=14710.0,
        volume=100, buy_volume=50, sell_volume=50, delta=0, oi=1000, vwap=14710.0,
    )

    mock_opt = MagicMock()
    mock_opt.state = SimpleNamespace(position=None, pyramids=())
    mock_opt._market = "NSE"
    mock_opt._last_tick_wall = time.monotonic()  # fresh tick!
    mock_opt.last_amt_dto = {"marketState": "BALANCED"}

    coord._engines = {
        "MIDCPNIFTY SEP FUT": mock_fut,
        "MIDCPNIFTY 29 SEP 14700 PUT": mock_opt,
    }

    rotated = coord.check_and_rotate_dead_symbols(max_drift_steps=2.5)
    assert rotated == [], "healthy contract must not be rotated"


# ---------------------------------------------------------------------------
# Rotation must read the ENGINE'S REAL AMT OUTPUT.
#
# Regression: the coordinator read an AMTEngine-private attribute
# (``getattr(engine, "last_amt_dto")``) that a real QuantEngine never had, so
# ``is_dead_state`` was permanently False and a dead contract could only rotate
# on strike drift. These tests drive a real QuantEngine whose AMT engine has
# analyzed a real candle series, so the DTO the coordinator reads is produced
# by the actual pipeline rather than hand-written in the test.
# ---------------------------------------------------------------------------


class _FakeGateway:
    """Minimal BrokerGateway — construction only; no ticks are consumed."""

    def subscribe(self, symbol: str) -> None:
        pass

    def next_tick(self):
        return None


def _real_option_engine(symbol: str, *, dead_premium: bool) -> QuantEngine:
    """A real QuantEngine whose AMT engine saw a real candle series.

    Feeds 25 completed 5-minute candles (enough for the dead-volume EMA) and
    only makes the newest candle's volume differ, so ``marketState`` comes from
    the same producer the live engine uses.
    """
    engine = QuantEngine(_FakeGateway(), symbol, interval_seconds=300)
    for i in range(25):
        volume = 0.0 if (dead_premium and i == 24) else 4000.0
        engine._amt_engine.analyze(
            Bar(
                time=str(1767225600 + i * 300), open=150.0, high=150.3, low=149.7,
                close=150.0, volume=volume, buy_volume=volume / 2,
                sell_volume=volume / 2, delta=0.0, oi=0.0, vwap=150.0,
            )
        )
    # Expose last_amt_dto at the engine level for the coordinator's rotation check
    engine.last_amt_dto = engine._amt_engine.last_amt_dto
    return engine


def _bare_coordinator(engines: dict):
    coord = QuantCoordinator.__new__(QuantCoordinator)
    coord._lock = MagicMock()
    coord._lifecycle_lock = MagicMock()
    coord._stop = MagicMock()
    coord._stop.is_set.return_value = False
    coord.config = {"exchange": "NSE", "expiry_index": 0, "strikes_around_atm": 3}
    coord.market_data = MagicMock()
    coord._engines = engines
    coord.switch_symbol = MagicMock(return_value=True)
    return coord


def _futures_engine_at(price: float):
    fut = MagicMock()
    fut._aggregator.current_bar = Bar(
        time="t1", open=price, high=price, low=price, close=price,
        volume=100, buy_volume=50, sell_volume=50, delta=0, oi=1000, vwap=price,
    )
    return fut


def _replacement(strike: float) -> ScanResult:
    return ScanResult(
        symbol=f"NIFTY 1 SEP {strike:.0f} PUT",
        underlying="NIFTY",
        strike=strike,
        option_type="PE",
        expiry="2026-09-01",
        ltp=120.0,
        oi=50000,
        volume=20000,
        spread=0.5,
        score=85.0,
    )


@patch("quant.amt.session.symbol_registry.is_market_open", return_value=True)
@patch("quant.amt.session.scanner.OptionScannerService.scan_top_n")
def test_rotate_dead_symbols_reads_real_engine_amt_output(mock_scan, mock_open, caplog):
    """A contract whose own tape is DEAD rotates, with no strike drift present."""
    symbol = "NIFTY 1 SEP 24100 PUT"
    engine = _real_option_engine(symbol, dead_premium=True)
    # The DTO the coordinator reads is the producer's, reached through the
    # engine's public accessor.
    assert engine.last_amt_dto["marketState"] == "DEAD"
    assert engine.last_amt_dto is engine._amt_engine.last_amt_dto
    engine._market = "NSE"
    engine._last_tick_wall = time.time()  # feed is fresh: only the state is dead

    coord = _bare_coordinator({
        "NIFTY SEP FUT": _futures_engine_at(24100.0),  # spot == strike: no drift
        symbol: engine,
    })
    mock_scan.return_value = [_replacement(24500.0)]

    with caplog.at_level(logging.INFO, logger="quant.multi_engine"):
        rotated = coord.check_and_rotate_dead_symbols(max_drift_steps=2.5)

    assert rotated == [(symbol, "NIFTY 1 SEP 24500 PUT")]
    assert "Dead market state" in caplog.text, caplog.text
    coord.switch_symbol.assert_called_once_with(symbol, "NIFTY 1 SEP 24500 PUT")


@patch("quant.amt.session.symbol_registry.is_market_open", return_value=True)
@patch("quant.amt.session.scanner.OptionScannerService.scan_top_n")
def test_rotate_dead_symbols_reports_stale_feed_when_both(mock_scan, mock_open, caplog):
    """Dead tape AND a 600s-silent feed is its own reason (the stale branch)."""
    symbol = "NIFTY 1 SEP 24100 PUT"
    engine = _real_option_engine(symbol, dead_premium=True)
    engine._market = "NSE"
    engine._last_tick_wall = time.time() - 3600.0

    coord = _bare_coordinator({
        "NIFTY SEP FUT": _futures_engine_at(24100.0),
        symbol: engine,
    })
    mock_scan.return_value = [_replacement(24500.0)]

    with caplog.at_level(logging.INFO, logger="quant.multi_engine"):
        rotated = coord.check_and_rotate_dead_symbols(max_drift_steps=2.5)

    assert rotated == [(symbol, "NIFTY 1 SEP 24500 PUT")]
    assert "stale feed" in caplog.text, caplog.text


@patch("quant.amt.session.symbol_registry.is_market_open", return_value=True)
@patch("quant.amt.session.scanner.OptionScannerService.scan_top_n")
def test_rotate_dead_symbols_keeps_live_contract_on_stale_feed(mock_scan, mock_open):
    """A stale feed alone is not a reason to rotate: the tape must be dead."""
    symbol = "NIFTY 1 SEP 24100 PUT"
    engine = _real_option_engine(symbol, dead_premium=False)
    assert engine.last_amt_dto["marketState"] != "DEAD"
    engine._market = "NSE"
    engine._last_tick_wall = time.time() - 3600.0

    coord = _bare_coordinator({
        "NIFTY SEP FUT": _futures_engine_at(24100.0),
        symbol: engine,
    })

    rotated = coord.check_and_rotate_dead_symbols(max_drift_steps=2.5)

    assert rotated == [], "a live contract must not rotate just because ticks paused"
    coord.switch_symbol.assert_not_called()
