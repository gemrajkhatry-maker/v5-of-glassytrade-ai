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

    dto = {"legLvns": [100.0], "absorptionSide": "SELL_ABSORBED"}
    pm.check_pyramid(
        dto,
        Bar(time="t1", open=100.0, high=100.05, low=99.95, close=100.05, volume=100),
        pos,
        bar_index=5,
    )

    assert len(pm.pyramid_positions) == 0
    assert pm.pyramid_count == 0


# ---------------------------------------------------------------------------
# E11 risk release data-flow: each pyramid's OWN fill pnl (audit round 2)
# ---------------------------------------------------------------------------

import pytest

from quant.decision.signal_builder import Signal
from quant.execution.exits import ExitEngine, ExitDecision
from quant.execution.oms import PaperOMS
from quant.execution.portfolio_risk import PortfolioRiskAuthority
from quant.execution.risk import SessionRisk
from quant.position_manager import PositionManager


class SpiedPortfolioRisk(PortfolioRiskAuthority):
    """Captures every record_close call so tests can audit release pairing."""

    def __init__(self):
        super().__init__()
        self.realized_calls: list[tuple[float, float]] = []  # [(risk_i, pnl_i)]

    def record_close(
        self, risk_rupees: float, pnl: float,
        symbol: str = "", is_full_close: bool = False,
    ) -> None:
        self.realized_calls.append((float(risk_rupees), float(pnl)))
        super().record_close(risk_rupees, pnl, symbol=symbol, is_full_close=is_full_close)


def _two_pyramid_pm():
    spied = SpiedPortfolioRisk()
    oms = PaperOMS(lot_size=1.0)
    pm = PositionManager(
        oms=oms, exits=ExitEngine(),
        risk=SessionRisk(starting_equity=1_000_000),
        emit_fn=lambda e: None,
        symbol="S", market="NSE", contract_expiry=None, tick_size=0.05,
        portfolio_risk=spied,
    )
    sig = Signal(type="LONG", reason="r", entry=100.0, sl=99.0, tp=104.0, rr=2.0,
                 model_label="Triple-A", symbol="S", timestamp="t0")
    base_pos = pm._oms.submit(sig, 4.0)
    # Two add-ons at DIFFERENT entries/sizes -> distinct closing pnls at one price.
    pyr1 = pm._oms.add_pyramid(base=base_pos, entry_price=100.5, new_sl=100.2,
                               size=2.0, time="t1", pyramid_level=1)
    pyr2 = pm._oms.add_pyramid(base=base_pos, entry_price=101.0, new_sl=100.5,
                               size=1.0, time="t2", pyramid_level=2)
    pm.pyramid_positions = [pyr1, pyr2]
    pm.pyramid_count = 2
    pm._pyramid_open_risk = {pyr1._id: 0.6, pyr2._id: 1.0}
    return pm, base_pos, spied


def test_pyramid_release_uses_each_pyr_pnl():
    pm, base_pos, spied = _two_pyramid_pm()
    close_px = 103.0                       # pyr1 pnl = +5.0, pyr2 pnl = +2.0
    pm._execute_full_close(base_pos, ExitDecision(True, "TP", close_px), "t3")
    realized = spied.realized_calls        # [(risk_i, pnl_i), ...]
    assert len(realized) == 2
    pnls = sorted(p for _, p in realized)
    expected = sorted([float((close_px - 100.5) * 2.0),
                       float((close_px - 101.0) * 1.0)])
    assert pnls == pytest.approx(expected), \
        "each release must carry its own fill pnl"


def test_pyramid_reads_leg_lvn_from_the_dto_key_that_exists():
    """D-5: the DTO emits legLvns (plural). Reading legLvn (singular) made the
    pyramid guard return on every bar, making the whole engine inert."""
    from quant.position_manager import PositionManager
    from quant.execution.oms import PaperOMS
    from quant.execution.exits import ExitEngine
    from quant.execution.risk import SessionRisk

    pm = PositionManager(
        oms=PaperOMS(lot_size=1.0), exits=ExitEngine(),
        risk=SessionRisk(storage=None, symbol="SYM"), emit_fn=lambda e: None,
        symbol="SYM", market="NSE", contract_expiry=None, tick_size=0.05,
    )
    # The guard under test is the leg-LVN source line; assert the resolution
    # itself so the test does not depend on the rest of the pyramid ladder.
    resolved = pm._resolve_leg_lvn({"legLvns": [99.5, 101.25], "legLvn": None}, close_px=101.0)
    assert resolved == 101.25

    # The singular spelling is not a producer key: a DTO carrying only it has
    # no leg LVN, so the pyramid guard must return rather than invent one.
    assert pm._resolve_leg_lvn({"legLvn": 100.0}, close_px=100.0) == 0.0

    assert pm._resolve_leg_lvn({}, close_px=100.0) == 0.0

    from quant.contracts.value_objects import AMTResult

    typed = AMTResult(
        market_state="BALANCED", poc=100.0, value_area_high=101.0, value_area_low=99.0,
        leg_lvns=(99.5, 101.25),
    )
    assert pm._resolve_leg_lvn(typed, close_px=101.0) == 101.25
