# tests/quant/decision/test_setup_evidence_cleanup.py
"""Phase 4: setup-evidence cleanup + single strategy seam.

1. ``_build_setup_evidence`` derives evidence ONLY from live DTO keys. The
   legacy ``setupType``/``setupDirection``/``cvdAgrees`` reads removed from
   context_builder had NO producer (repo-wide grep), so the VA_FADE/LVN_SNIPER
   fall-through arms and the direction fallback silently depended on keys that
   never arrived. The analyzer's ``setup`` regime key (``TREND_MODEL`` /
   ``MEAN_REVERSION`` / ``RESPONSIVE_FADE``) is a different taxonomy — a
   market-regime label, not a playbook detection — and must NOT fabricate
   playbook evidence.

2. The thesis-flip (positioned opposing-signal) evaluation routes through the
   SAME strategy ``should_enter`` seam entries use, with
   ``allow_positioned=True`` — so a swapped-in strategy governs both.
"""
from __future__ import annotations

import pytest

from quant.decision.context_builder import DecisionContextBuilder


def _evidence(amt_dto: dict, agent_direction: str | None = None,
              nearest_leg_lvn: float = 0.0):
    return DecisionContextBuilder()._build_setup_evidence(
        amt_dto, agent_direction, nearest_leg_lvn
    )


class TestSetupEvidenceLiveKeys:
    def test_regime_setup_key_does_not_fabricate_playbook_evidence(self):
        """The analyzer's regime key (`setup`) must not create VA_FADE or any
        other playbook evidence — it is a regime label, not a detection."""
        ev = _evidence({"setup": "TREND_MODEL"}, agent_direction="LONG")
        assert ev is None

        ev = _evidence({"setup": "MEAN_REVERSION"}, agent_direction="SHORT")
        assert ev is None

    def test_dead_setup_keys_produce_no_evidence(self):
        """Even if a stale `setupType` arrived, evidence stays None without
        supporting live signals (the old fall-through is gone)."""
        ev = _evidence({"setupType": "VA_FADE", "setupDirection": "LONG",
                        "cvdAgrees": True})
        assert ev is None

    def test_va_fade_fires_from_rejection_keys(self):
        ev = _evidence({"rejectionAtHigh": True, "cvdSlope": -0.5},
                       agent_direction="SHORT")
        assert ev is not None
        assert ev.setup_type == "VA_FADE"
        assert ev.direction == "SHORT"
        assert ev.cvd_agrees is True

        ev = _evidence({"rejectionAtLow": True, "cvdSlope": 0.5},
                       agent_direction="LONG")
        assert ev is not None
        assert ev.setup_type == "VA_FADE"
        assert ev.direction == "LONG"

    def test_second_drive_fires_from_drive_keys(self):
        ev = _evidence({"isSecondDrive": True, "driveNumber": 2,
                        "rejectionAtHigh": True})
        assert ev is not None
        assert ev.setup_type == "SECOND_DRIVE"
        assert ev.drive_number == 2

    def test_triple_a_fires_from_aggression_plus_acceptance(self):
        ev = _evidence({"tripleAPhase": "AGGRESSION", "tripleASignal": "LONG",
                        "acceptanceAbove": 105.0})
        assert ev is not None
        assert ev.setup_type == "TRIPLE_A"
        assert ev.direction == "LONG"

    def test_lvn_sniper_fires_from_absorption_plus_leg_lvn(self):
        ev = _evidence({"absorptionSide": "SELL_ABSORBED"}, nearest_leg_lvn=99.5)
        assert ev is not None
        assert ev.setup_type == "LVN_SNIPER"
        assert ev.direction == "LONG"
        assert ev.level == 99.5

    def test_cvd_agrees_derived_from_direction_and_cvd_slope(self):
        # cvd_agrees is computed from the resolved direction + cvdSlope; the
        # rejection key only makes evidence exist so the flag is inspectable.
        # LONG requires cvd >= -0.2
        ev = _evidence({"rejectionAtHigh": True, "cvdSlope": -0.1},
                       agent_direction="LONG")
        assert ev.cvd_agrees is True
        ev = _evidence({"rejectionAtHigh": True, "cvdSlope": -1.0},
                       agent_direction="LONG")
        assert ev.cvd_agrees is False
        # SHORT requires cvd <= 0.2
        ev = _evidence({"rejectionAtHigh": True, "cvdSlope": 0.1},
                       agent_direction="SHORT")
        assert ev.cvd_agrees is True
        ev = _evidence({"rejectionAtHigh": True, "cvdSlope": 1.0},
                       agent_direction="SHORT")
        assert ev.cvd_agrees is False


class TestStrategySeamForFlips:
    def test_should_enter_forwards_allow_positioned(self):
        """The default strategy forwards allow_positioned to the decision
        service — one seam for entries and thesis-flip exits."""
        from quant.decision.decision_service import QuantDecision
        from quant.strategies.amt_scalping import AmtScalpingStrategy

        class _Recorder:
            def __init__(self):
                self.calls = []

            def evaluate(self, ctx, *, allow_positioned=False):
                self.calls.append(allow_positioned)
                return QuantDecision(False, None, "NO_EDGE", "", ())

        recorder = _Recorder()
        strategy = AmtScalpingStrategy(decision_service=recorder)
        strategy.should_enter(None, allow_positioned=True)
        strategy.should_enter(None)
        assert recorder.calls == [True, False]