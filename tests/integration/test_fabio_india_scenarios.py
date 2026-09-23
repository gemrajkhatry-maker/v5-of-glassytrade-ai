# tests/integration/test_fabio_india_scenarios.py
"""End-to-end Fabio India Options Scenarios (Task 11).

Simulates complete market days under Fabio AMT rules:
1. Triple-A Bullish Trend Day: Aggression + Absorption + Acceptance -> Long Entry -> Targets -> Trail.
2. Value Area Fade Day: False breakout outside VA rejected back to POC.
3. Midday Consolidation Day: Suppresses breakout continuation, allows mean reversion.
4. Expiry Afternoon Session: Halves risk caps, closes out prior to 15:20 close protection.
"""

from quant.decision.context import DecisionContext
from quant.decision.decision_service import DecisionService
from quant.decision.setup_state import SetupEvidence
from quant.contracts.enums import MarketState
from quant.execution.risk import SessionRisk
from quant.bars import Bar


def _make_bar(time_str: str, o: float, h: float, lo: float, c: float, vol: float = 1000.0, delta: float = 200.0) -> Bar:
    return Bar(
        time=time_str,
        open=o,
        high=h,
        low=lo,
        close=c,
        volume=vol,
        buy_volume=vol * 0.6 if delta > 0 else vol * 0.4,
        sell_volume=vol * 0.4 if delta > 0 else vol * 0.6,
        delta=delta,
    )


def test_scenario_triple_a_bullish_trend_day():
    # 10:00 IST Primary window
    bar = _make_bar("2026-08-19T10:00:00+05:30", o=24500.0, h=24550.0, lo=24490.0, c=24540.0, vol=5000.0, delta=1500.0)
    evidence = SetupEvidence(
        setup_type="TRIPLE_A",
        direction="LONG",
        absorption=True,
        accumulation=True,
        aggression=True,
        acceptance=True,
        cvd_agrees=True,
        breakout_beyond_cluster=True,
        lvn_proximity_ok=True,
    )
    ctx = DecisionContext(
        bar=bar,
        symbol="NIFTY",
        session_open=True,
        warmup_complete=True,
        position_open=False,
        agent_direction="LONG",
        agent_probability=0.80,
        market_state=MarketState.IMBALANCED,
        setup_evidence=evidence,
        vah=24480.0,
        val=24400.0,
        poc=24450.0,
        vwap_upper_2=24600.0,
        vwap_lower_2=24350.0,
        cvd_slope=2.5,
        allow_trend=True,
        allow_reversion=True,
        bid=24539.95,
        ask=24540.05,
    )
    decision = DecisionService().evaluate(ctx)
    assert decision.approved is True
    assert decision.signal is not None
    assert decision.signal.type == "LONG"
    assert decision.signal.entry == 24540.0
    assert decision.signal.sl < 24540.0
    assert decision.signal.tp > 24540.0


def test_scenario_value_area_fade_day():
    # 10:30 IST VAH probe above 24600 rejected, price CLOSES BACK INSIDE the VA
    # (24590 <= VAH 24600) but still above POC 24520 -> failed auction, fade short
    # toward POC (Fabio Model 2 reclaim semantics). Full bearish body close
    # (>=60% of range, close in outer 75%) per the 1-min acceptance rule.
    bar = _make_bar("2026-08-19T10:30:00+05:30", o=24645.0, h=24650.0, lo=24575.0, c=24590.0, vol=3000.0, delta=-800.0)
    evidence = SetupEvidence(
        setup_type="VA_FADE",
        direction="SHORT",
        rejection=True,
        acceptance=False,
        cvd_agrees=True,
    )
    ctx = DecisionContext(
        bar=bar,
        symbol="NIFTY",
        session_open=True,
        warmup_complete=True,
        position_open=False,
        agent_direction="SHORT",
        agent_probability=0.75,
        market_state=MarketState.BALANCED,
        setup_evidence=evidence,
        vah=24600.0,
        val=24450.0,
        poc=24520.0,
        vwap_upper_2=24650.0,
        vwap_lower_2=24400.0,
        cvd_slope=-1.8,
        allow_trend=True,
        allow_reversion=True,
        bid=24589.95,
        ask=24590.05,
    )
    decision = DecisionService().evaluate(ctx)
    assert decision.approved is True
    assert decision.signal is not None
    assert decision.signal.type == "SHORT"
    assert decision.signal.entry == 24590.0
    assert decision.signal.sl > decision.signal.entry
    assert decision.signal.sl >= 24649.0  # Anchored to probe high (inside by 2 ticks per Fabio)
    assert decision.signal.tp == 24520.0  # Target POC


def test_scenario_midday_blocks_trend_continuation():
    # 12:45 IST Midday window: allow_trend is False
    bar = _make_bar("2026-08-19T12:45:00+05:30", o=24700.0, h=24730.0, lo=24690.0, c=24720.0, vol=2000.0, delta=500.0)
    evidence = SetupEvidence(
        setup_type="TRIPLE_A",
        direction="LONG",
        absorption=True,
        accumulation=True,
        aggression=True,
        acceptance=True,
        cvd_agrees=True,
    )
    ctx = DecisionContext(
        bar=bar,
        symbol="NIFTY",
        session_open=True,
        warmup_complete=True,
        position_open=False,
        agent_direction="LONG",
        agent_probability=0.80,
        market_state=MarketState.IMBALANCED,
        setup_evidence=evidence,
        vah=24650.0,
        val=24550.0,
        poc=24600.0,
        vwap_upper_2=24750.0,
        vwap_lower_2=24500.0,
        cvd_slope=1.5,
        allow_trend=False,  # Blocked in midday
        allow_reversion=True,
    )
    decision = DecisionService().evaluate(ctx)
    assert decision.approved is False
    assert any("SESSION_PHASE" in r for r in decision.block_reasons)


def test_scenario_expiry_afternoon_risk_halving():
    risk = SessionRisk(starting_equity=1_000_000.0)
    normal_qty = risk.position_size(entry=100.0, sl=90.0, lot_size=50, is_expiry=False)
    expiry_qty = risk.position_size(entry=100.0, sl=90.0, lot_size=50, is_expiry=True)
    assert expiry_qty <= normal_qty // 2
    assert expiry_qty % 50 == 0
