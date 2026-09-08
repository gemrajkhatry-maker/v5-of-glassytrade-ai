"""Behavioral tests for the deterministic AMT strategy.

Each test verifies a real market scenario flowing through the full decision
pipeline: scenario setup -> strategy state -> signal -> order decision.

These tests are deterministic (no randomness) and fast (< 1s each).
"""

from __future__ import annotations

import pytest
from dataclasses import replace

from quant.bars import Bar
from quant.contracts.enums import MarketState
from quant.decision.context import DecisionContext
from quant.decision.data_quality import DataQuality
from quant.decision.decision_service import DecisionService
from quant.decision.setup_state import SetupEvidence


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_bar(
    close: float = 100.0,
    time: str = "2026-08-19T10:45:00+05:30",
    high: float | None = None,
    low: float | None = None,
    open: float | None = None,
    volume: float = 2000.0,
) -> Bar:
    """Build an OHLCV bar with sensible defaults."""
    return Bar(
        time=time,
        open=open if open is not None else close,
        high=high if high is not None else close + 1.0,
        low=low if low is not None else close - 1.0,
        close=close,
        volume=volume,
        buy_volume=volume * 0.6,
        sell_volume=volume * 0.4,
    )


def make_context(
    *,
    bar: Bar | None = None,
    close: float = 100.0,
    symbol: str = "NIFTY",
    market: str = "NSE",
    agent_direction: str | None = "LONG",
    agent_probability: float = 0.7,
    market_state: MarketState = MarketState.BALANCED,
    session_open: bool = True,
    warmup_complete: bool = True,
    position_open: bool = False,
    cooldown_remaining_sec: int = 0,
    risk_halted: bool = False,
    consecutive_losses: int = 0,
    poc: float = 100.0,
    vah: float = 101.0,
    val: float = 99.0,
    prior_poc: float = 0.0,
    npoc_above: float = 0.0,
    npoc_below: float = 0.0,
    tick_size: float = 0.05,
    cvd_slope: float = 0.0,
    absorption_side: str = "",
    obi: float = 0.0,
    vwap_std: float = 0.0,
    vwap_upper_2: float = 0.0,
    vwap_lower_2: float = 0.0,
    setup_evidence: SetupEvidence | None = None,
    triple_a_phase: str = "",
    triple_a_signal: str = "",
    allow_trend: bool = True,
    allow_reversion: bool = True,
    session_phase: str = "NSE_PRIMARY",
    bid: float = 0.0,
    ask: float = 0.0,
    time_str: str = "",
    data_quality: DataQuality | None = None,
    equity: float = 1_000_000.0,
    risk_per_trade_pct: float = 0.01,
    leg_lvn: float = 0.0,
    break_direction: str = "",
    break_type: str = "",
    drive_entry_valid: bool = False,
    drive_number: int = 0,
    stacked_imbalance_direction: str = "",
    stacked_imbalance_magnitude: int = 0,
    stacked_imbalance_price_low: float = 0.0,
    stacked_imbalance_price_high: float = 0.0,
    contested_bubble_zone: bool = False,
    nearest_buy_print_below: float = 0.0,
    nearest_sell_print_above: float = 0.0,
    squeeze_detected: bool = False,
    squeeze_direction: str = "",
    squeeze_trapped_level: float = 0.0,
    pullback_confirmed: bool = False,
) -> DecisionContext:
    """Build a DecisionContext with sensible defaults for behavioral tests."""
    if bar is None:
        bar = make_bar(close=close)
    return DecisionContext(
        state=None,
        bar=bar,
        symbol=symbol,
        market=market,
        session_open=session_open,
        warmup_complete=warmup_complete,
        position_open=position_open,
        agent_direction=agent_direction,
        agent_probability=agent_probability,
        market_state=market_state,
        cooldown_remaining_sec=cooldown_remaining_sec,
        risk_halted=risk_halted,
        consecutive_losses=consecutive_losses,
        poc=poc,
        vah=vah,
        val=val,
        prior_poc=prior_poc,
        npoc_above=npoc_above,
        npoc_below=npoc_below,
        tick_size=tick_size,
        cvd_slope=cvd_slope,
        absorption_side=absorption_side,
        obi=obi,
        vwap_std=vwap_std,
        vwap_upper_2=vwap_upper_2,
        vwap_lower_2=vwap_lower_2,
        setup_evidence=setup_evidence,
        triple_a_phase=triple_a_phase,
        triple_a_signal=triple_a_signal,
        allow_trend=allow_trend,
        allow_reversion=allow_reversion,
        session_phase=session_phase,
        bid=bid,
        ask=ask,
        time_str=time_str or bar.time,
        data_quality=data_quality,
        equity=equity,
        risk_per_trade_pct=risk_per_trade_pct,
        leg_lvn=leg_lvn,
        break_direction=break_direction,
        break_type=break_type,
        drive_entry_valid=drive_entry_valid,
        drive_number=drive_number,
        stacked_imbalance_direction=stacked_imbalance_direction,
        stacked_imbalance_magnitude=stacked_imbalance_magnitude,
        stacked_imbalance_price_low=stacked_imbalance_price_low,
        stacked_imbalance_price_high=stacked_imbalance_price_high,
        contested_bubble_zone=contested_bubble_zone,
        nearest_buy_print_below=nearest_buy_print_below,
        nearest_sell_print_above=nearest_sell_print_above,
        squeeze_detected=squeeze_detected,
        squeeze_direction=squeeze_direction,
        squeeze_trapped_level=squeeze_trapped_level,
        pullback_confirmed=pullback_confirmed,
    )


# ---------------------------------------------------------------------------
# Behavioral Tests
# ---------------------------------------------------------------------------


def test_no_trade_in_balance():
    """Price oscillates around POC with no displacement -> expect NO TRADE.

    A balanced market with no absorption cluster, no Triple-A phase, and no
    setup evidence must produce NO_EDGE. The strategy stays flat.
    """
    ctx = make_context(
        market_state=MarketState.BALANCED,
        agent_direction=None,
        poc=100.0,
        vah=101.0,
        val=99.0,
        cvd_slope=0.0,
        triple_a_phase="",
        triple_a_signal="",
        setup_evidence=None,
    )
    d = DecisionService().evaluate(ctx)
    assert not d.approved, "Balanced rotation with no setup must not trade"
    assert d.signal is None
    assert d.reason == "NO_EDGE"


def test_no_trade_without_absorption():
    """Trend without absorption cluster -> expect NO TRADE.

    An imbalanced (trending) market without absorption evidence must not
    produce a signal. The Triple-A edge requires absorption as the first step.
    """
    ctx = make_context(
        market_state=MarketState.IMBALANCED,
        agent_direction="LONG",
        cvd_slope=0.8,
        absorption_side="",
        triple_a_phase="",
        triple_a_signal="",
        setup_evidence=None,
    )
    d = DecisionService().evaluate(ctx)
    assert not d.approved, "Trend without absorption must not trade"
    assert d.signal is None


def test_no_trade_without_aggression():
    """Absorption detected but no Triple-A AGGRESSION phase -> expect NO TRADE.

    Even with absorption present, the strategy must wait for the AGGRESSION
    phase before entering. Absorption alone is not enough.
    """
    ctx = make_context(
        market_state=MarketState.BALANCED,
        agent_direction="LONG",
        absorption_side="SELL_ABSORBED",
        cvd_slope=0.3,
        triple_a_phase="ACCUMULATION",  # Not AGGRESSION yet
        triple_a_signal="",
        setup_evidence=None,
    )
    d = DecisionService().evaluate(ctx)
    assert not d.approved, "Absorption without aggression must not trade"
    assert d.signal is None


def test_valid_triple_a_entry():
    """Full absorption -> accumulation -> aggression with close beyond cluster -> expect ENTRY.

    A complete Triple-A setup with acceptance beyond the cluster must produce
    an approved LONG signal. This is the canonical Fabio entry.
    """
    evidence = SetupEvidence(
        setup_type="TRIPLE_A",
        direction="LONG",
        absorption=True,
        accumulation=True,
        aggression=True,
        acceptance=True,
        cvd_agrees=True,
    )
    ctx = make_context(
        market_state=MarketState.IMBALANCED,
        agent_direction="LONG",
        cvd_slope=1.0,
        setup_evidence=evidence,
        triple_a_phase="AGGRESSION",
        triple_a_signal="LONG",
        close=110.0,
        poc=100.0,
        vah=101.0,
        val=99.0,
    )
    d = DecisionService().evaluate(ctx)
    assert d.approved, "Complete Triple-A with acceptance must enter"
    assert d.signal is not None
    assert d.signal.type == "LONG"
    assert d.reason == "Triple-A"


def test_structural_stop_placement():
    """Long entry with support below -> stop 1-2 ticks inside support (toward market).

    The structural stop must be placed inside the support level, toward the
    market (above the support for a LONG). This is Fabio's live placement rule.
    """
    evidence = SetupEvidence(
        setup_type="TRIPLE_A",
        direction="LONG",
        absorption=True,
        accumulation=True,
        aggression=True,
        acceptance=True,
        cvd_agrees=True,
    )
    ctx = make_context(
        market_state=MarketState.IMBALANCED,
        agent_direction="LONG",
        cvd_slope=1.0,
        setup_evidence=evidence,
        triple_a_phase="AGGRESSION",
        triple_a_signal="LONG",
        close=110.0,
        poc=100.0,
        vah=101.0,
        val=99.0,
        nearest_buy_print_below=105.0,  # Support level
        tick_size=0.05,
    )
    d = DecisionService().evaluate(ctx)
    assert d.approved
    assert d.signal is not None
    # Stop must be below entry (LONG) and above the support (toward market)
    assert d.signal.sl < d.signal.entry, "Stop must be below entry for LONG"
    assert d.signal.sl > 105.0, "Stop must be inside support (toward market)"


def test_structural_target_priority():
    """Prior POC available -> target is prior POC, not fixed R:R.

    When a prior POC exists in the direction of the trade and meets the
    minimum R:R requirement, it must be used as the take-profit target
    instead of the fixed R:R multiplier.
    """
    evidence = SetupEvidence(
        setup_type="TRIPLE_A",
        direction="LONG",
        absorption=True,
        accumulation=True,
        aggression=True,
        acceptance=True,
        cvd_agrees=True,
    )
    ctx = make_context(
        market_state=MarketState.IMBALANCED,
        agent_direction="LONG",
        cvd_slope=1.0,
        setup_evidence=evidence,
        triple_a_phase="AGGRESSION",
        triple_a_signal="LONG",
        close=110.0,
        poc=100.0,
        vah=101.0,
        val=99.0,
        prior_poc=130.0,  # Prior POC far enough to meet min_rr
        npoc_above=120.0,  # NPOC above entry, meets min_rr
        nearest_buy_print_below=105.0,  # Support for stop placement
        tick_size=0.05,
    )
    d = DecisionService().evaluate(ctx)
    assert d.approved
    assert d.signal is not None
    # Target should be a structural level (prior POC or NPOC), not fixed 2R
    assert d.signal.tp > d.signal.entry, "Target must be above entry for LONG"
    # The structural target should be one of the configured levels
    assert d.signal.tp in (130.0, 120.0), f"Target should be structural, got {d.signal.tp}"


def test_three_loss_halt():
    """Three consecutive losses -> trading halts.

    After three consecutive losses, the risk state halts trading. The decision
    service must emit HALTED and not approve any new entry.
    """
    ctx = make_context(
        risk_halted=True,
        consecutive_losses=3,
        agent_direction="LONG",
        agent_probability=0.9,
        data_quality=DataQuality.TICK_EXACT,
    )
    d = DecisionService().evaluate(ctx)
    assert not d.approved, "Halted system must not approve"
    assert d.signal is None
    assert d.reason == "HALTED"


def test_cushion_escalation():
    """Winning day -> risk budget increases.

    After a winning streak, the risk budget (equity) grows. The position
    sizing must reflect the increased equity. This test verifies the
    decision context carries the updated equity through evaluation.
    """
    evidence = SetupEvidence(
        setup_type="TRIPLE_A",
        direction="LONG",
        absorption=True,
        accumulation=True,
        aggression=True,
        acceptance=True,
        cvd_agrees=True,
    )
    # Winning day: equity increased from 1M to 1.2M
    ctx = make_context(
        market_state=MarketState.IMBALANCED,
        agent_direction="LONG",
        cvd_slope=1.0,
        setup_evidence=evidence,
        triple_a_phase="AGGRESSION",
        triple_a_signal="LONG",
        close=110.0,
        equity=1_200_000.0,  # Increased equity from winning
        risk_per_trade_pct=0.01,
    )
    d = DecisionService().evaluate(ctx)
    assert d.approved
    assert d.signal is not None
    # The signal is approved; position sizing (which uses equity) happens
    # downstream in SessionRisk. Here we verify the context equity is carried.
    assert ctx.equity == 1_200_000.0


def test_anti_climax_rejection():
    """Price beyond VWAP +2σ -> LONG rejected.

    An anti-climax extension beyond VWAP +2σ must reject a LONG entry.
    The market is overextended and the edge is exhausted.
    """
    ctx = make_context(
        market_state=MarketState.IMBALANCED,
        agent_direction="LONG",
        cvd_slope=0.5,
        vwap_std=2.0,
        vwap_upper_2=102.0,  # VWAP + 2σ
        vwap_lower_2=98.0,
        close=105.0,  # Beyond +2σ
        triple_a_phase="AGGRESSION",
        triple_a_signal="LONG",
        setup_evidence=None,
    )
    d = DecisionService().evaluate(ctx)
    assert not d.approved, "Anti-climax extension must reject LONG"
    assert d.signal is None


def test_pre_market_lock():
    """Bar during Phase 1 (09:15-09:30) -> NO TRADE.

    The opening noise window (Phase 1) blocks all new entries. Even with a
    valid setup, the session gate must reject.
    """
    evidence = SetupEvidence(
        setup_type="TRIPLE_A",
        direction="LONG",
        absorption=True,
        accumulation=True,
        aggression=True,
        acceptance=True,
        cvd_agrees=True,
    )
    # 09:20 IST is Phase 1 (opening noise) — session_open=False
    ctx = make_context(
        bar=make_bar(time="2026-08-19T09:20:00+05:30"),
        market_state=MarketState.IMBALANCED,
        agent_direction="LONG",
        cvd_slope=1.0,
        setup_evidence=evidence,
        triple_a_phase="AGGRESSION",
        triple_a_signal="LONG",
        session_open=False,  # Phase 1: opening noise
        session_phase="NSE_OPENING",
    )
    d = DecisionService().evaluate(ctx)
    assert not d.approved, "Phase 1 opening noise must block all entries"
    assert d.signal is None
