# tests/quant/decision/test_setup_state.py
"""Tests for SetupEvidence and Fabio Setup State Transitions (Task 2)."""

import pytest
from quant.decision.setup_state import SetupEvidence


def test_imbalanced_regime_is_not_a_setup():
    evidence = SetupEvidence(setup_type="NONE", direction="LONG")
    assert evidence.is_complete() is False
    assert "No named setup" in evidence.rejection_reason()


def test_triple_a_requires_all_three_legs_and_acceptance():
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
        price=100.0,
        session_vwap=99.0,
    )
    assert evidence.is_complete() is True


def test_triple_a_without_accumulation_is_incomplete():
    evidence = SetupEvidence(
        setup_type="TRIPLE_A",
        direction="LONG",
        absorption=True,
        accumulation=False,
        aggression=True,
        acceptance=True,
        cvd_agrees=True,
        breakout_beyond_cluster=True,
        lvn_proximity_ok=True,
    )
    assert evidence.is_complete() is False
    assert "Accumulation" in evidence.rejection_reason()


def test_second_drive_requires_d1_rejection_and_d2():
    evidence = SetupEvidence(
        setup_type="SECOND_DRIVE",
        direction="LONG",
        drive_number=2,
        d1_rejected=True,
        rejection=True,
        cvd_agrees=True,
        departed_and_reapproached=True,
    )
    assert evidence.is_complete() is True


def test_second_drive_first_touch_rejected():
    evidence = SetupEvidence(
        setup_type="SECOND_DRIVE",
        direction="LONG",
        drive_number=1,
        d1_rejected=False,
        rejection=False,
        cvd_agrees=True,
        departed_and_reapproached=False,
    )
    assert evidence.is_complete() is False
    assert "Drive number 1 != 2" in evidence.rejection_reason()


def test_lvn_sniper_requires_lvn_return_and_absorption():
    evidence = SetupEvidence(
        setup_type="LVN_SNIPER",
        direction="LONG",
        level=100.5,
        absorption=True,
        cvd_agrees=True,
        price=100.5,
        tick_size=0.05,
    )
    assert evidence.is_complete() is True


def test_lvn_sniper_without_level_is_incomplete():
    evidence = SetupEvidence(
        setup_type="LVN_SNIPER",
        direction="LONG",
        level=0.0,
        absorption=True,
        cvd_agrees=True,
        price=100.0,
    )
    assert evidence.is_complete() is False
    assert "Missing LVN price level" in evidence.rejection_reason()


def test_va_fade_requires_rejection_and_no_acceptance():
    evidence = SetupEvidence(
        setup_type="VA_FADE",
        direction="SHORT",
        rejection=True,
        acceptance=False,
        cvd_agrees=True,
    )
    assert evidence.is_complete() is True


def test_va_fade_with_acceptance_is_breakout_not_fade():
    evidence = SetupEvidence(
        setup_type="VA_FADE",
        direction="SHORT",
        rejection=True,
        acceptance=True,
        cvd_agrees=True,
    )
    assert evidence.is_complete() is False
    assert "breakout, not fade" in evidence.rejection_reason()


def test_opposing_cvd_blocks_setup():
    evidence = SetupEvidence(
        setup_type="TRIPLE_A",
        direction="LONG",
        absorption=True,
        accumulation=True,
        aggression=True,
        acceptance=True,
        cvd_agrees=False,
    )
    assert evidence.is_complete() is False
    assert "CVD opposes" in evidence.rejection_reason()


def test_stale_evidence_is_incomplete():
    evidence = SetupEvidence(
        setup_type="TRIPLE_A",
        direction="LONG",
        absorption=True,
        accumulation=True,
        aggression=True,
        acceptance=True,
        cvd_agrees=True,
        evidence_age_bars=15,
    )
    assert evidence.is_complete() is False
    assert "Evidence too old" in evidence.rejection_reason()
