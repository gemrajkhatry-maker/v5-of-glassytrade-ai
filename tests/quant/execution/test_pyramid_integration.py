"""Tests for portfolio scale-in integration."""


def test_portfolio_add_to_position():
    """Portfolio.add_to_position scales into winning position."""
    from quant.contracts.aggregates import Portfolio

    portfolio = Portfolio.create_default()

    # Create a mock signal
    from quant.contracts.entities import Signal, SignalType, Source, SetupType
    import time

    signal = Signal.create(
        type=SignalType.BUY,
        price=100.0,
        reason="Test",
        stop_loss=98.0,
        take_profit=104.0,
        timestamp=str(time.time()),
        setup=SetupType.MEAN_REVERSION,
        source=Source.AMT,
    )

    # Open position with 40% scale (first entry)
    position = portfolio.open_position(signal, "NIFTY", scale_fraction=0.4)
    assert position is not None
    assert position.size > 0

    # Add 30% (second entry)
    success = portfolio.add_to_position(position.id, 0.3, 101.0)
    assert success

    # Add 30% (third entry)
    success = portfolio.add_to_position(position.id, 0.3, 102.0)
    assert success


def test_refused_add_leaves_no_ghost():
    """A portfolio-risk refusal leaves no counted-but-unreserved ghost pyramid."""
    from unittest.mock import MagicMock

    from quant.bars import Bar
    from quant.decision.signal_builder import Signal
    from quant.execution.exits import ExitEngine
    from quant.execution.oms import PaperOMS
    from quant.execution.order import Order, Position
    from quant.execution.risk import SessionRisk
    from quant.position_manager import PositionManager

    refusing = MagicMock()
    refusing.can_accept.return_value = (False, "cap exceeded")

    oms = PaperOMS(lot_size=1.0)
    pm = PositionManager(
        oms=oms, exits=ExitEngine(),
        risk=SessionRisk(storage=None, symbol="S"),
        emit_fn=lambda e: None,
        symbol="S", market="MCX", contract_expiry=None, tick_size=0.05,
        portfolio_risk=refusing,
    )

    sig = Signal(type="LONG", reason="r", entry=100.0, sl=99.0, tp=104.0, rr=2.0,
                 model_label="Triple-A", symbol="S", timestamp="t0")
    pos = Position(order=Order(sig, 10.0), open_price=100.0, open_time="t0", size=10.0)
    pm._exits.evaluate(pos, bar_close=101.0, bar_index=3, bar_high=101.0, bar_low=100.9)
    assert pm._exits.is_risk_free(pos)

    dto = {"legLvn": 100.0, "absorptionSide": "SELL_ABSORBED"}
    pm.check_pyramid(
        dto,
        Bar(time="t1", open=100.0, high=100.05, low=99.95, close=100.05, volume=100),
        pos,
        bar_index=5,
    )

    assert len(pm.pyramid_positions) == 0
    assert pm.pyramid_count == 0
