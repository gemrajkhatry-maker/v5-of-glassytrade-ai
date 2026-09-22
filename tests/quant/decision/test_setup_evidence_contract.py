"""Stage 2 contract: SetupEvidence.is_complete is the only Gate-3 certificate.

Counterexamples from the AMT playbook audit must all return False. Location /
LVN / breakout rules live on the evidence object, not a second copy in gates_edge.
"""

from __future__ import annotations

from quant.decision.setup_state import SetupEvidence


def test_balanced_far_from_lvn_is_incomplete():
    """BALANCED context + 100 ticks from LVN must not certify LVN_SNIPER."""
    ev = SetupEvidence(
        setup_type="LVN_SNIPER",
        direction="LONG",
        level=100.0,
        absorption=True,
        cvd_agrees=True,
        price=105.0,  # 100 ticks at 0.05
        tick_size=0.05,
        lvn_proximity_ok=False,
        price_location="IN_VA",
    )
    assert ev.is_complete() is False


def test_triple_a_long_below_vwap_inside_box_is_incomplete():
    ev = SetupEvidence(
        setup_type="TRIPLE_A",
        direction="LONG",
        absorption=True,
        accumulation=True,
        aggression=True,
        acceptance=True,
        cvd_agrees=True,
        price_location="INSIDE_BOX",
        breakout_beyond_cluster=True,
        lvn_proximity_ok=True,
        price=99.0,
        session_vwap=100.0,
        tick_size=0.05,
    )
    assert ev.is_complete() is False


def test_va_fade_close_still_outside_val_is_incomplete():
    """Genuine rejection below VAL whose micro candle still closes outside."""
    ev = SetupEvidence(
        setup_type="VA_FADE",
        direction="LONG",
        rejection=True,
        acceptance=False,
        cvd_agrees=True,
        price_location="BELOW_VAL",
        price=99.0,
    )
    assert ev.is_complete() is False


def test_second_drive_without_departure_is_incomplete():
    ev = SetupEvidence(
        setup_type="SECOND_DRIVE",
        direction="LONG",
        drive_number=2,
        d1_rejected=True,
        rejection=True,
        cvd_agrees=True,
        departed_and_reapproached=False,
    )
    assert ev.is_complete() is False


def test_complete_triple_a_requires_breakout_and_lvn():
    incomplete = SetupEvidence(
        setup_type="TRIPLE_A",
        direction="LONG",
        absorption=True,
        accumulation=True,
        aggression=True,
        acceptance=True,
        cvd_agrees=True,
        price_location="ABOVE_VAH",
        breakout_beyond_cluster=False,
        lvn_proximity_ok=True,
        price=101.0,
        session_vwap=100.0,
        tick_size=0.05,
    )
    assert incomplete.is_complete() is False

    complete = SetupEvidence(
        setup_type="TRIPLE_A",
        direction="LONG",
        absorption=True,
        accumulation=True,
        aggression=True,
        acceptance=True,
        cvd_agrees=True,
        price_location="ABOVE_VAH",
        breakout_beyond_cluster=True,
        lvn_proximity_ok=True,
        price=101.0,
        session_vwap=100.0,
        tick_size=0.05,
    )
    assert complete.is_complete() is True
