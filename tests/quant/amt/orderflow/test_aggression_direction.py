"""P0-5 — aggression evidence must agree with the trade direction.

The v6.0 specification clamps the aggression score to 0.0 when the net delta
slope opposes the trade direction, and no component may score when its own
evidence opposes. This is the fix for the review's P0-5: a large negative-delta
sell climax must never validate a LONG entry.

Legacy callers that pass no ``direction`` keep the additive FR-06 behaviour
unchanged, so the UI/journal read path is unaffected.
"""

from __future__ import annotations

import pytest

from quant.amt.orderflow.aggression import (
    AggressionScorer,
    PersistentAggressionScorer,
    canonical_absorption_direction,
)


class TestCanonicalAbsorptionDirection:
    """One source of truth for the absorption -> direction mapping."""

    def test_sell_absorbed_is_bullish(self):
        """Passive sellers absorbed = hidden buyer = LONG (the canonical mapping)."""
        assert canonical_absorption_direction("SELL_ABSORBED") == "LONG"

    def test_buy_absorbed_is_bearish(self):
        """Passive buyers absorbed = hidden seller = SHORT."""
        assert canonical_absorption_direction("BUY_ABSORBED") == "SHORT"

    def test_absent_or_unknown_side_is_none(self):
        for side in ("", "NONE", "UNKNOWN", None):
            assert canonical_absorption_direction(side) is None


class TestLegacyNonDirectionalPathUnchanged:
    """Callers with no trade direction must see byte-identical behaviour."""

    def test_additive_score_unchanged(self):
        result = AggressionScorer().score(
            footprint_confirmed=True,
            cvd_confirmed=True,
            big_trade_confirmed=True,
        )
        assert result.score == pytest.approx(3.0)
        assert result.confirmed is True
        assert result.direction_opposed is False

    def test_signed_inputs_are_ignored_without_direction(self):
        """Signed evidence is inert when no direction is asserted."""
        result = AggressionScorer().score(
            cvd_slope=-9.0,
            norm_delta=-0.8,
            footprint_confirmed=True,
            cvd_confirmed=True,
        )
        assert result.score == pytest.approx(2.0)


class TestOpposingSlopeClampsToZero:
    """Spec: score is clamped to 0.0 when the net delta slope opposes."""

    def test_long_with_negative_slope_clamps_to_zero(self):
        result = AggressionScorer().score(
            direction="LONG",
            cvd_slope=-8.0,
            footprint_confirmed=True,
            cvd_confirmed=True,
            big_trade_confirmed=True,
        )
        assert result.score == 0.0
        assert result.confirmed is False
        assert result.pyramid_eligible is False
        assert result.confidence == "LOW"
        assert result.direction_opposed is True

    def test_short_with_positive_slope_clamps_to_zero(self):
        result = AggressionScorer().score(
            direction="SHORT",
            cvd_slope=8.0,
            footprint_confirmed=True,
            cvd_confirmed=True,
            big_trade_confirmed=True,
        )
        assert result.score == 0.0
        assert result.confirmed is False
        assert result.direction_opposed is True

    def test_agreeing_slope_does_not_clamp(self):
        result = AggressionScorer().score(
            direction="LONG",
            cvd_slope=8.0,
            footprint_confirmed=True,
            cvd_confirmed=True,
            big_trade_confirmed=True,
        )
        assert result.score == pytest.approx(3.0)
        assert result.confirmed is True

    def test_flat_slope_does_not_clamp(self):
        result = AggressionScorer().score(
            direction="LONG",
            cvd_slope=0.0,
            footprint_confirmed=True,
            cvd_confirmed=True,
        )
        assert result.score == pytest.approx(2.0)
        assert result.direction_opposed is False


class TestComponentSignGating:
    """Each signed component scores only when it agrees with the direction."""

    def test_absorption_side_must_agree_with_long(self):
        agrees = AggressionScorer().score(
            direction="LONG", absorption_side="SELL_ABSORBED", absorption_detected=True
        )
        assert agrees.breakdown["absorption"] == pytest.approx(0.5)

        opposes = AggressionScorer().score(
            direction="LONG", absorption_side="BUY_ABSORBED", absorption_detected=True
        )
        assert opposes.breakdown["absorption"] == 0.0

    def test_absorption_side_must_agree_with_short(self):
        agrees = AggressionScorer().score(
            direction="SHORT", absorption_side="BUY_ABSORBED", absorption_detected=True
        )
        assert agrees.breakdown["absorption"] == pytest.approx(0.5)

        opposes = AggressionScorer().score(
            direction="SHORT", absorption_side="SELL_ABSORBED", absorption_detected=True
        )
        assert opposes.breakdown["absorption"] == 0.0

    def test_absorption_with_unknown_side_is_not_credited(self):
        result = AggressionScorer().score(
            direction="LONG", absorption_side="", absorption_detected=True
        )
        assert result.breakdown["absorption"] == 0.0

    def test_ofi_sign_must_agree(self):
        with_flow = AggressionScorer().score(direction="LONG", ofi=0.5, ofi_aligned=True)
        assert with_flow.breakdown["ofi"] == pytest.approx(0.5)

        against = AggressionScorer().score(direction="LONG", ofi=-0.5, ofi_aligned=True)
        assert against.breakdown["ofi"] == 0.0

    def test_footprint_delta_sign_must_agree(self):
        with_delta = AggressionScorer().score(
            direction="LONG", norm_delta=0.6, footprint_confirmed=True
        )
        assert with_delta.breakdown["footprint"] == pytest.approx(1.0)

        against = AggressionScorer().score(
            direction="LONG", norm_delta=-0.6, footprint_confirmed=True
        )
        assert against.breakdown["footprint"] == 0.0

    def test_unsupplied_numeric_inputs_do_not_gate_footprint_or_ofi(self):
        """Absent numeric evidence keeps the legacy additive credit."""
        result = AggressionScorer().score(
            direction="LONG",
            footprint_confirmed=True,
            ofi_aligned=True,
        )
        assert result.breakdown["footprint"] == pytest.approx(1.0)
        assert result.breakdown["ofi"] == pytest.approx(0.5)

    def test_absorption_without_a_readable_side_earns_no_credit(self):
        """Fail-closed: an unreadable side cannot be claimed as supporting flow.

        Under an asserted direction, absorbed volume with no side is unknown
        provenance, not evidence for the trade. It must not silently count.
        """
        result = AggressionScorer().score(direction="LONG", absorption_detected=True)
        assert result.breakdown["absorption"] == 0.0


class TestSellClimaxCannotValidateLong:
    """The review's exact P0-5 scenario."""

    def test_full_bearish_climax_scores_zero_for_long(self):
        result = AggressionScorer().score(
            direction="LONG",
            cvd_slope=-9.0,
            norm_delta=-0.8,
            absorption_side="BUY_ABSORBED",
            footprint_confirmed=True,
            cvd_confirmed=True,
            big_trade_confirmed=True,
            absorption_detected=True,
            ofi_aligned=True,
            confluence_bonus=True,
            volume_bubble_near=True,
        )
        assert result.score == 0.0
        assert result.confirmed is False
        assert result.pyramid_eligible is False

    def test_the_same_climax_is_high_confidence_for_short(self):
        result = AggressionScorer().score(
            direction="SHORT",
            cvd_slope=-9.0,
            norm_delta=-0.8,
            absorption_side="BUY_ABSORBED",
            footprint_confirmed=True,
            cvd_confirmed=True,
            big_trade_confirmed=True,
            absorption_detected=True,
            ofi_aligned=True,
            confluence_bonus=True,
            volume_bubble_near=True,
        )
        assert result.score >= 3.0
        assert result.pyramid_eligible is True


class TestPersistentScorerCarriesDirection:
    """The persistence filter must count only direction-consistent bars."""

    def test_opposing_flow_never_builds_a_confirmed_streak(self):
        scorer = PersistentAggressionScorer(persistence_bars=2)
        result = None
        for _ in range(5):
            result = scorer.score(
                direction="LONG",
                cvd_slope=-9.0,
                footprint_confirmed=True,
                cvd_confirmed=True,
            )
        assert result is not None
        assert result.confirmed is False
        assert result.score == 0.0

    def test_agreeing_flow_confirms_after_the_persistence_window(self):
        scorer = PersistentAggressionScorer(persistence_bars=2)
        scorer.score(direction="LONG", cvd_slope=9.0, footprint_confirmed=True, cvd_confirmed=True)
        result = scorer.score(
            direction="LONG", cvd_slope=9.0, footprint_confirmed=True, cvd_confirmed=True
        )
        assert result.confirmed is True
