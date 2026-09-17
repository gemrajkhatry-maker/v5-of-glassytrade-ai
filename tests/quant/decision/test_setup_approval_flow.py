# tests/quant/decision/test_setup_approval_flow.py
"""Tests for Fabio Setup Approval Flows (Task 4)."""

import pytest
from quant.decision.context import DecisionContext
from quant.decision.decision_service import DecisionService
from quant.decision.setup_state import SetupEvidence
from quant.contracts.enums import MarketState
from quant.bars import Bar


def _bar():
    # Full-body bullish bar so the Gate-3 1-min candle-acceptance guard passes.
    return Bar(
        time="2026-08-19T10:00:00+05:30",
        open=99.3,
        high=100.7,
        low=99.3,
        close=100.5,
        volume=1000.0,
        buy_volume=600.0,
        sell_volume=400.0,
        delta=200.0,
    )


def evaluate_case(
    setup_type="TRIPLE_A",
    direction="LONG",
    absorption=True,
    accumulation=True,
    aggression=True,
    acceptance=True,
    rejection=False,
    drive_number=2,
    d1_rejected=True,
    at_lvn=True,
    lvn_level=100.5,
    cvd_agrees=True,
    evidence_age_bars=0,
    market_state=MarketState.IMBALANCED,
    outside_va=False,
):
    evidence = SetupEvidence(
        setup_type=setup_type,
        direction=direction,
        level=lvn_level if at_lvn else 0.0,
        absorption=absorption,
        accumulation=accumulation,
        aggression=aggression,
        acceptance=acceptance,
        rejection=rejection,
        drive_number=drive_number,
        d1_rejected=d1_rejected,
        cvd_agrees=cvd_agrees,
        evidence_age_bars=evidence_age_bars,
    ) if setup_type is not None else None

    ctx = DecisionContext(
        bar=_bar(),
        symbol="NIFTY",
        session_open=True,
        warmup_complete=True,
        position_open=False,
        cooldown_remaining_sec=0.0,
        risk_halted=False,
        consecutive_losses=0,
        agent_direction=direction,
        agent_probability=0.75,
        market_state=market_state,
        setup_evidence=evidence,
        vah=99.0,
        val=95.0,
        poc=97.0,
        vwap_upper_2=105.0,
        vwap_lower_2=90.0,
        cvd_slope=1.0 if cvd_agrees else -1.0,
        allow_trend=True,
        allow_reversion=True,
    )
    return DecisionService().evaluate(ctx)


def test_imbalanced_without_setup_returns_no_edge():
    assert evaluate_case(setup_type="NONE").approved is False


def test_triple_a_requires_absorption_accumulation_aggression():
    assert evaluate_case("TRIPLE_A", absorption=True, accumulation=False, aggression=True).approved is False
    assert evaluate_case("TRIPLE_A", absorption=True, accumulation=True, aggression=True, acceptance=True).approved is True


def test_second_drive_requires_d1_rejection_and_d2():
    assert evaluate_case("SECOND_DRIVE", d1_rejected=False, drive_number=2, rejection=True).approved is False
    assert evaluate_case("SECOND_DRIVE", d1_rejected=True, drive_number=2, rejection=True).approved is True


def test_lvn_sniper_requires_lvn_return_and_absorption():
    assert evaluate_case("LVN_SNIPER", at_lvn=False, absorption=True).approved is False
    assert evaluate_case("LVN_SNIPER", at_lvn=True, lvn_level=100.5, absorption=True).approved is True


def test_va_fade_requires_rejection_not_just_outside_va():
    assert evaluate_case("VA_FADE", outside_va=True, rejection=False, acceptance=True).approved is False
    assert evaluate_case("VA_FADE", outside_va=True, rejection=True, acceptance=False).approved is True


def test_conflicting_cvd_blocks_direction():
    assert evaluate_case("TRIPLE_A", direction="LONG", cvd_agrees=False).approved is False


def test_stale_evidence_returns_no_edge():
    assert evaluate_case("TRIPLE_A", evidence_age_bars=99).approved is False
