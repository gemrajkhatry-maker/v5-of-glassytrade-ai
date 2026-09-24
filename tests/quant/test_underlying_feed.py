"""Task 8 — underlying-futures AMT feed routing.

When an ``underlying_gateway`` is provided, its ticks drive the auction bars
(AMT), while the option contract's own ticks only update quotes/depth. Without
one, the engine falls back to running AMT on the option premium with a one-shot
startup warning.
"""

from datetime import timedelta

from quant.brokers.gateway import Tick
from quant.contracts.timezones import today_ist
from quant.events import BarClosed
from quant.runtime import QuantEngine
from tests.helpers.synthetic import SyntheticGateway
import quant.runtime as rt


def _future_option_symbol(underlying="NIFTY", strike=24600, option_type="CALL", days=30):
    expiry = today_ist() + timedelta(days=days)
    return (
        f"{underlying.upper()} {expiry.day} {expiry.strftime('%b').upper()} "
        f"{expiry.year} {strike} {option_type.upper()}"
    )


_CRUDEOIL_OPTION = _future_option_symbol("CRUDEOIL", 7450)
_NIFTY_OPTION = _future_option_symbol()
_NIFTY_OPTION_ALT = _future_option_symbol(strike=24700)


def _module_has_no_global_underlying_warned_flag() -> bool:
    """No module-global warning flag: warning state is per-engine."""
    return not hasattr(rt, "_UNDERLYING_WARNED")


def test_derive_underlying_symbol_parses_option():
    eng = QuantEngine(SyntheticGateway([]), _CRUDEOIL_OPTION,
                      interval_seconds=1, market="MCX")
    assert eng._underlying() == "CRUDEOIL"


def _quiet_option_ticks(n=6):
    return [Tick(f"o{i}", 45.0, 10, 6, 4) for i in range(n)]


def _futures_ticks(n=6):
    return [Tick(f"f{i}", 7450.0 + i, 100, 60, 40) for i in range(n)]


def test_underlying_feed_drives_bars_option_only_quotes():
    """With an underlying gateway, BarClosed prices follow the option contract stream,
    while AmtUpdated reflects the underlying futures auction structure."""
    from quant.events import AmtUpdated

    futures = SyntheticGateway(_futures_ticks())
    option = SyntheticGateway(_quiet_option_ticks())
    eng = QuantEngine(option, _CRUDEOIL_OPTION,
                      interval_seconds=1, market="MCX",
                      underlying_gateway=futures)
    trace = eng.run()

    bars = [e for e in trace if isinstance(e, BarClosed)]
    amt_updates = [e for e in trace if isinstance(e, AmtUpdated)]
    assert bars, "option ticks must close option bars"
    assert amt_updates, "underlying ticks must produce AMT updates"

    # Option bars must stay at option premium (45.0), NEVER corrupted by futures prices (7450)
    for e in bars:
        assert float(e.bar.close) == 45.0, "bar close must come from option feed"

    # AMT analysis must reflect the underlying futures levels
    for e in amt_updates:
        assert e.amt is not None
        assert "marketState" in e.amt


def test_underlying_feed_option_quotes_still_fire():
    """Option ticks continue to update projector quotes/depth."""
    option = SyntheticGateway(
        [Tick("o0", 45.0, 10, 6, 4, depth={"bids": [{"price": 44.9, "quantity": 5}],
                                            "asks": [{"price": 45.1, "quantity": 5}]})]
    )
    futures = SyntheticGateway(_futures_ticks(2))
    eng = QuantEngine(option, _CRUDEOIL_OPTION,
                      interval_seconds=1, market="MCX",
                      underlying_gateway=futures)
    eng.run()
    assert eng._last_depth is not None, "option depth must still be captured"


def test_no_underlying_feed_warns_once_per_engine_and_falls_back():
    """Option contract with no underlying gateway: one per-engine warning, AMT
    still runs on the option premium (fallback). No module-global flag."""
    assert _module_has_no_global_underlying_warned_flag()
    option = SyntheticGateway(_quiet_option_ticks())
    eng = QuantEngine(option, _NIFTY_OPTION,
                      interval_seconds=1, market="NSE")
    trace = eng.run()
    assert any(isinstance(e, BarClosed) for e in trace), "fallback must still produce bars"
    # The warning state is per-engine: the engine that ran the fallback has
    # set its own flag; a second engine must start unwarned.
    assert eng._underlying_warned is True, "startup warning must be emitted once per engine"
    eng2 = QuantEngine(SyntheticGateway(_quiet_option_ticks()), _NIFTY_OPTION_ALT,
                       interval_seconds=1, market="NSE")
    assert eng2._underlying_warned is False, "warning flag must not leak across engines"


def test_coordinator_option_without_underlying_is_observation_only(monkeypatch, tmp_path):
    from quant.multi_engine import QuantCoordinator

    monkeypatch.setattr(
        QuantCoordinator,
        "_start_engine_loop",
        lambda self, engine: None,
    )

    class _MarketData:
        def get_lot_size(self, symbol):
            return 65

    coordinator = QuantCoordinator(
        _MarketData(),
        config={
            "underlyings": ["NIFTY"],
            "n": 1,
            "contracts_file": str(tmp_path / "contracts.json"),
            "session_levels_file": str(tmp_path / "levels.json"),
        },
    )
    try:
        engine = coordinator._spawn_engine(_NIFTY_OPTION)
        assert engine is not None
        assert engine._underlying_gateway is None
        assert engine._decision_loop._execution_enabled is False
    finally:
        coordinator._stop_engine(_NIFTY_OPTION)
        coordinator._executor.shutdown(wait=False, cancel_futures=True)


def test_missing_underlying_option_blocks_before_strategy_approval():
    from unittest.mock import MagicMock

    from quant.bars import Bar
    from quant.decision.decision_service import QuantDecision
    from quant.decision.signal_builder import Signal
    from quant.events import DecisionProduced

    engine = QuantEngine(
        SyntheticGateway([]),
        _NIFTY_OPTION,
        interval_seconds=1,
        market="NSE",
    )
    signal = Signal(
        type="LONG", reason="test", entry=100.0, sl=95.0, tp=110.0,
        rr=2.0, model_label="test", symbol=_NIFTY_OPTION, timestamp="t0",
    )
    assert engine._execution_enabled is False
    strategy = MagicMock()
    strategy.should_enter.return_value = QuantDecision(
        approved=True, signal=signal, reason="Triple-A", phase="", gate_results=(),
        block_reasons=(), model_label="Triple-A",
    )
    engine._strategy = strategy
    telemetry = MagicMock()
    engine.telemetry = telemetry
    engine._decision_loop.telemetry = telemetry
    events = []
    engine._bus.subscribe(DecisionProduced, events.append)
    engine._bar_index = 10

    result = engine._decide(
        {},
        Bar(time="t300", open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0),
    )

    assert strategy.should_enter.call_count == 0
    assert result.approved is False
    assert result.reason == "OPTION_UNDERLYING_UNAVAILABLE"
    assert any(event.decision.reason == result.reason for event in events)
    assert all(event.decision.reason != "ENTRY_NOT_SUBMITTED" for event in events)
    telemetry.record_decision.assert_called_once_with(approved=False)


def _install_approving_option_strategy(engine, signal):
    from unittest.mock import MagicMock

    from quant.decision.decision_service import QuantDecision
    from quant.events import DecisionProduced

    engine.set_option_delta(0.55)
    strategy = MagicMock()
    strategy.should_enter.return_value = QuantDecision(
        approved=True,
        signal=signal,
        reason="probe",
        phase="",
        gate_results=(),
        block_reasons=(),
        model_label="probe",
    )
    engine._strategy = strategy
    telemetry = MagicMock()
    engine.telemetry = telemetry
    engine._decision_loop.telemetry = telemetry
    events = []
    engine._bus.subscribe(DecisionProduced, events.append)
    engine._bar_index = 10
    return strategy, telemetry, events


def test_attached_empty_underlying_blocks_before_strategy_and_submission():
    from quant.bars import Bar
    from quant.decision.signal_builder import Signal

    symbol = _NIFTY_OPTION
    engine = QuantEngine(
        SyntheticGateway([]),
        symbol,
        interval_seconds=300,
        market="NSE",
        underlying_gateway=SyntheticGateway([]),
    )
    signal = Signal(
        type="LONG", reason="probe", entry=25000.0, sl=24980.0, tp=25040.0,
        rr=2.0, model_label="probe", symbol="NIFTY FUT", timestamp="t0",
    )
    strategy, telemetry, events = _install_approving_option_strategy(engine, signal)

    result = engine._decide(
        {},
        Bar(
            time="2026-09-24T10:01:00+05:30",
            open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0,
        ),
    )

    assert result is not None
    assert result.approved is False
    assert result.reason == "OPTION_UNDERLYING_UNAVAILABLE"
    strategy.should_enter.assert_not_called()
    assert engine.state.position is None
    assert any(event.decision.reason == result.reason for event in events)
    telemetry.record_decision.assert_called_once_with(approved=False)


def test_attached_stale_underlying_blocks_before_strategy():
    from quant.bars import Bar
    from quant.decision.signal_builder import Signal

    engine = QuantEngine(
        SyntheticGateway([]),
        _NIFTY_OPTION,
        interval_seconds=300,
        market="NSE",
        underlying_gateway=SyntheticGateway([]),
    )
    engine._last_underlying_bar = Bar(
        time="2026-09-24T09:55:00+05:30",
        open=99.0, high=101.0, low=98.0, close=100.0, volume=10.0,
    )
    engine._underlying_amt_dto = {
        "time": "2026-09-24T09:55:00+05:30",
        "poc": 100.0,
        "valueAreaHigh": 101.0,
        "valueAreaLow": 99.0,
    }
    signal = Signal(
        type="LONG", reason="probe", entry=25000.0, sl=24980.0, tp=25040.0,
        rr=2.0, model_label="probe", symbol="NIFTY FUT", timestamp="t0",
    )
    strategy, telemetry, events = _install_approving_option_strategy(engine, signal)

    result = engine._decide(
        engine._underlying_amt_dto,
        engine._last_underlying_bar,
        Bar(
            time="2026-09-24T10:01:00+05:30",
            open=49.0, high=51.0, low=48.0, close=50.0, volume=1.0,
        ),
    )

    assert result is not None
    assert result.approved is False
    assert result.reason == "OPTION_UNDERLYING_UNAVAILABLE"
    strategy.should_enter.assert_not_called()
    assert engine.state.position is None
    assert any(event.decision.reason == result.reason for event in events)
    telemetry.record_decision.assert_called_once_with(approved=False)
