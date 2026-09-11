# tests/quant/execution/test_lot_aware_risk.py
"""Tests for Whole-Lot Aware Risk and Expiry Caps (Task 6)."""

import pytest
from datetime import datetime

from quant.bars import Bar
from quant.contracts.timezones import IST
from quant.decision.decision_service import QuantDecision
from quant.decision.signal_builder import Signal
from quant.execution.risk import SessionRisk
from quant.runtime import QuantEngine
from tests.helpers.synthetic import SyntheticGateway


def test_position_size_rounds_to_whole_lots():
    # Standard mode (0.5% risk): CONSERVATIVE tier uses 0.25% risk = ₹2,500
    # Pin a mid-week day: DAY_OF_WEEK_MULTIPLIER halves risk on Mon/Fri, so an unpinned day makes this assertion calendar-dependent.
    risk = SessionRisk(starting_equity=1_000_000.0, base_risk_pct=0.005, day_of_week=1)
    qty = risk.position_size(
        entry=100.0,
        sl=93.0,       # loss per unit = 7.0
        lot_size=15,   # loss per lot = 105.0 -> lots = floor(2500 / 105) = 23 lots
    )
    assert qty % 15 == 0
    assert qty == 23 * 15


def test_lot_rounding_never_exceeds_rupee_risk_cap():
    # Pin a mid-week day: DAY_OF_WEEK_MULTIPLIER halves risk on Mon/Fri, so an unpinned day makes this assertion calendar-dependent.
    risk = SessionRisk(starting_equity=1_000_000.0, base_risk_pct=0.005, day_of_week=1)
    qty = risk.position_size(
        entry=100.0,
        sl=93.0,
        lot_size=15,
        max_rupee_risk_cap=1_000.0,  # ₹1,000 cap
    )
    # loss per lot = 105.0 -> lots = floor(1000 / 105) = 9 lots
    assert qty == 9 * 15
    loss = (qty / 15) * 105.0
    assert loss <= 1000.0


def test_expiry_day_uses_reduced_risk():
    # Pin a mid-week day: DAY_OF_WEEK_MULTIPLIER halves risk on Mon/Fri, so an unpinned day makes this assertion calendar-dependent.
    risk = SessionRisk(starting_equity=1_000_000.0, base_risk_pct=0.005, day_of_week=1)
    normal_qty = risk.position_size(entry=100.0, sl=90.0, lot_size=25, is_expiry=False)
    expiry_qty = risk.position_size(entry=100.0, sl=90.0, lot_size=25, is_expiry=True)
    assert expiry_qty < normal_qty
    assert expiry_qty == normal_qty // 2


def _approved(symbol="SYM"):
    sig = Signal(type="LONG", reason="r", entry=100.0, sl=98.0, tp=102.0,
                 rr=2.0, model_label="Triple-A", symbol=symbol, timestamp="t0")
    return QuantDecision(approved=True, signal=sig, reason="Triple-A",
                         phase="", gate_results=(), block_reasons=(), model_label="Triple-A")


def _expiry_symbol(today):
    return f"SYM {today.day:02d} {today.strftime('%b').upper()} 100 CALL"


def test_position_size_honors_is_expiry_at_call_site():
    """Entry sizing is reachable only through the private _decide, so drive it
    directly and capture the is_expiry flag actually handed to SessionRisk."""
    today = datetime.now(IST).date()
    # ponytail: 00:30 keeps the bar within EventStore's 1h future-guard on
    # morning CI runs (12:00 IST is >1h ahead before ~11:00 → append raises).
    # Expiry compare uses the date part only, so the hour is not load-bearing.
    bar = Bar(time=f"{today.isoformat()}T00:30:00+05:30",
              open=100.0, high=100.0, low=100.0, close=100.0, volume=10)

    seen = []
    eng = QuantEngine(SyntheticGateway([]), _expiry_symbol(today), interval_seconds=1)
    eng._risk.position_size = lambda *a, **kw: seen.append(kw.get("is_expiry")) or 25.0
    eng._strategy.should_enter = lambda ctx: _approved(_expiry_symbol(today))
    eng._decide({}, bar)
    assert seen == [True], "expiry-day contract must pass is_expiry=True into sizing"

    seen2 = []
    eng2 = QuantEngine(SyntheticGateway([]), "SYM", interval_seconds=1)
    eng2._risk.position_size = lambda *a, **kw: seen2.append(kw.get("is_expiry")) or 25.0
    eng2._strategy.should_enter = lambda ctx: _approved("SYM")
    eng2._decide({}, Bar(time=f"{today.isoformat()}T00:30:00+05:30",
                         open=100.0, high=100.0, low=100.0, close=100.0, volume=10))
    assert seen2 == [False], "non-expiring contract must pass is_expiry=False into sizing"


def test_max_lots_cap_enforced():
    # Pin a mid-week day: DAY_OF_WEEK_MULTIPLIER halves risk on Mon/Fri, so an unpinned day makes this assertion calendar-dependent.
    risk = SessionRisk(starting_equity=1_000_000.0, base_risk_pct=0.005, day_of_week=1)
    # Without cap: lots = 23
    uncapped = risk.position_size(entry=100.0, sl=93.0, lot_size=15)
    assert uncapped == 23 * 15
    # With cap: max 5 lots
    capped = risk.position_size(entry=100.0, sl=93.0, lot_size=15, max_lots=5)
    assert capped == 5 * 15


def test_pyramid_position_size_is_half_risk():
    risk = SessionRisk(starting_equity=1_000_000.0)
    base_qty = risk.position_size(entry=100.0, sl=90.0, lot_size=25)
    pyr_qty = risk.pyramid_position_size(entry=100.0, sl=90.0, lot_size=25)
    assert pyr_qty <= base_qty // 2
    assert pyr_qty % 25 == 0


def test_rupee_risk_for_quantity_calculation():
    risk = SessionRisk()
    rupees = risk.rupee_risk_for_quantity(entry=100.0, sl=95.0, quantity=50.0)
    assert rupees == 250.0


def test_reset_session_restores_clean_state():
    risk = SessionRisk(starting_equity=500_000.0)
    risk.record_trade(-5000.0)
    assert risk.state().daily_pnl == -5000.0
    state = risk.reset_session(date="2026-08-21")
    assert state.daily_pnl == 0.0
    assert state.consecutive_losses == 0
    assert state.trades_today == 0
    assert state.halted is False
    assert state.equity == 500_000.0



def test_model_sizing_failure_refuses_instead_of_deploying_50pct(monkeypatch):
    """D-12: a raising model-sizing call used to fall through to the flat
    50%-of-equity deployment branch — a structurally different, non-risk-
    equivalent policy — with only a warning."""
    from quant.execution.risk import SessionRisk

    risk = SessionRisk(storage=None, symbol="SYM", base_risk_pct=0.05)

    import quant.decision.timesfm_sizing as sz

    class _Boom:
        def compute_size(self, **_k):
            raise RuntimeError("empty p10_path")

    monkeypatch.setattr(sz, "TimesFMPositionSizer", lambda *a, **k: _Boom())

    class _Fc:
        forecast_steps = ["LONG"] * 32

    qty = risk.position_size(100.0, 99.0, lot_size=1.0, forecast=_Fc(), side="LONG")
    assert qty == 0.0


def test_forecast_path_applies_expiry_and_day_of_week_cuts():
    """D-12: the expiry halving and the Mon/Fri multiplier were applied only
    on the static branches, so they never applied on the E2E (forecast) path."""
    import numpy as np

    from quant.decision.timesfm_agents import TimesFMForecast
    from quant.execution.risk import SessionRisk

    p50 = np.linspace(100.0, 104.0, 32)
    fc = TimesFMForecast(
        horizon=32, p50_path=p50, p10_path=p50 - 1.0, p90_path=p50 + 1.0,
        q_spread=2.0, mean_forecast=float(p50[-1]), pct_change=0.04,
        forecast_steps=["LONG"] * 32, curr_price=100.0, lat_ms=1.0,
    )

    normal = SessionRisk(storage=None, symbol="SYM", day_of_week=2)   # Wednesday
    qty_normal = normal.position_size(100.0, 99.0, lot_size=1.0, forecast=fc, side="LONG")

    expiry = SessionRisk(storage=None, symbol="SYM", day_of_week=2)
    qty_expiry = expiry.position_size(100.0, 99.0, lot_size=1.0, forecast=fc,
                                      side="LONG", is_expiry=True)

    assert qty_expiry == pytest.approx(qty_normal * 0.5)

    monday = SessionRisk(storage=None, symbol="SYM", day_of_week=0)
    qty_monday = monday.position_size(100.0, 99.0, lot_size=1.0, forecast=fc, side="LONG")
    assert qty_monday == pytest.approx(qty_normal * 0.5)


def test_model_sizing_failure_counted_and_still_refuses(monkeypatch):
    """Finding 1 (review of D-12): a raising model-sizing call must be
    distinguishable from a genuine budget-zero. The refuse path must bump an
    observable counter (per instance) and still return 0.0."""
    from quant.execution.risk import SessionRisk

    risk = SessionRisk(storage=None, symbol="SYM", base_risk_pct=0.05)
    assert risk.model_sizing_failures == 0

    import quant.decision.timesfm_sizing as sz

    class _Boom:
        def compute_size(self, **_k):
            raise RuntimeError("empty p10_path")

    monkeypatch.setattr(sz, "TimesFMPositionSizer", lambda *a, **k: _Boom())

    class _Fc:
        forecast_steps = ["LONG"] * 32

    qty = risk.position_size(100.0, 99.0, lot_size=1.0, forecast=_Fc(), side="LONG")
    assert qty == 0.0
    assert risk.model_sizing_failures == 1


def test_forecast_path_snaps_to_lots_before_expiry_cut():
    """Finding 2 (review of D-12): the forecast path must snap the model
    quantity to whole lots FIRST, then apply the expiry and day-of-week
    multipliers on the snapped value — same order as the static branches
    (which compute whole lots and multiply the returned qty by the Mon/Fri
    factor). Pinned with lot_size=75: the model returns 24975 (333 lots);
    snapping first then halving gives an exact 0.5 cut (12487.5), whereas the
    old snap-last order floored the halved value to 12450."""
    import numpy as np

    from quant.decision.timesfm_agents import TimesFMForecast
    from quant.execution.risk import SessionRisk

    p50 = np.linspace(100.0, 104.0, 32)
    fc = TimesFMForecast(
        horizon=32, p50_path=p50, p10_path=p50 - 1.0, p90_path=p50 + 1.0,
        q_spread=2.0, mean_forecast=float(p50[-1]), pct_change=0.04,
        forecast_steps=["LONG"] * 32, curr_price=100.0, lat_ms=1.0,
    )

    normal = SessionRisk(storage=None, symbol="SYM", day_of_week=2)  # Wednesday
    qty_normal = normal.position_size(100.0, 99.0, lot_size=75.0, forecast=fc, side="LONG")
    assert qty_normal == 24975.0  # snapped model size: 333 lots x 75

    expiry = SessionRisk(storage=None, symbol="SYM", day_of_week=2)
    qty_expiry = expiry.position_size(100.0, 99.0, lot_size=75.0, forecast=fc,
                                      side="LONG", is_expiry=True)
    # Snap first, then halve -> an exact 0.5 cut on the snapped value.
    assert qty_expiry == 12487.5

    monday = SessionRisk(storage=None, symbol="SYM", day_of_week=0)
    qty_monday = monday.position_size(100.0, 99.0, lot_size=75.0, forecast=fc, side="LONG")
    assert qty_monday == 12487.5


def test_model_sizing_failures_reset_with_session():
    from unittest.mock import patch
    import quant.decision.timesfm_sizing as sizing

    class Boom:
        def compute_size(self, **_kwargs):
            raise RuntimeError("test")

    risk = SessionRisk(storage=None, symbol="SYM", day_of_week=1)
    with patch.object(sizing, "TimesFMPositionSizer", lambda: Boom()):
        assert risk.position_size(100.0, 99.0, forecast=object()) == 0.0
    assert risk.model_sizing_failures == 1
    risk.reset_session()
    assert risk.model_sizing_failures == 0
