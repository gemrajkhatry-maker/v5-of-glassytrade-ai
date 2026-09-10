"""D-3: a pyramid-only force-close must not bypass the single release path."""

from quant.bars import Bar
from quant.decision.signal_builder import Signal
from quant.execution.exits import ExitEngine
from quant.execution.oms import PaperOMS
from quant.execution.order import Order, Position
from quant.execution.risk import SessionRisk
from quant.position_manager import PositionManager


def _pyramid():
    sig = Signal(type="LONG", reason="r", entry=100.0, sl=99.0, tp=103.0,
                 rr=3.0, model_label="Triple-A", symbol="SYM", timestamp="t0")
    return Position(order=Order(sig, 10.0), open_price=100.0, open_time="t0",
                    size=10.0, pyramid_level=1, is_pyramid=True)


def test_pyramid_only_close_stamps_exit_source():
    """A lingering pyramid add-on must be closed through _execute_full_close,
    so last_exit_source is stamped and the close is logged like any other."""
    events = []
    pm = PositionManager(
        oms=PaperOMS(lot_size=1.0),
        exits=ExitEngine(),
        risk=SessionRisk(storage=None, symbol="SYM"),
        emit_fn=events.append,
        symbol="SYM",
        market="NSE",
        contract_expiry=None,
        tick_size=0.05,
    )
    pm.pyramid_positions = [_pyramid()]
    pm.current_position = None

    # The runtime helper under test (extracted so it is callable in isolation).
    from quant.runtime import close_lingering_pyramids

    bar = Bar("2026-09-10T15:20:00", 100.0, 101.0, 99.0, 100.0, 10, 10)
    closed = close_lingering_pyramids(pm, 100.0, bar.time, "EOD_SQUARE_OFF")

    assert closed == 1
    assert pm.pyramid_positions == []
    # The stamp is the whole point: previously this path left it blank/stale.
    assert pm._exits.last_exit_source == "DETERMINISTIC:EOD_SQUARE_OFF"
    assert any(type(e).__name__ == "PositionClosed" for e in events)
