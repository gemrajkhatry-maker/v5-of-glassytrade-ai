"""IMBALANCED requires acceptance beyond VA, not just a probe (Fabio acceptance rule).

A probe beyond VA that closes back inside is a rejected probe (mean-reversion
context), NOT IMBALANCED.  Only acceptance (close beyond VA) triggers IMBALANCED.
"""

from quant.amt.market.state_engine import detect_market_state
from quant.contracts.enums import MarketState
from quant.contracts.constants import BALANCE_RATIO_THRESHOLD


def _state_result(**kw):
    """Call detect_market_state with sensible defaults, overridden by kw."""
    defaults = dict(
        price=100.0,
        poc=100.0,
        vah=102.0,
        val=98.0,
        tick_size=0.10,
        has_displacement=False,
        has_acceptance=False,
        balance_ratio=BALANCE_RATIO_THRESHOLD,
    )
    defaults.update(kw)
    return detect_market_state(**defaults)


class TestProbeRejectionIsNotImbalanced:
    """Probe beyond VA that closes back inside -> BALANCED (mean reversion)."""

    def test_probe_above_vah_rejects_is_not_imbalanced(self):
        """Price probed above VAH (high=103 > vah=102) but closed at 100 (inside VA).

        With displacement active (the probe triggered a displacement leg),
        the rejection should suppress IMBALANCED from the probe alone.
        """
        result = _state_result(
            price=100.0,          # close inside VA
            vah=102.0,
            val=98.0,
            has_displacement=True,
            has_acceptance=False,
            balance_ratio=BALANCE_RATIO_THRESHOLD,
            bar_high=103.0,       # probed above VAH
            bar_low=99.0,
        )
        assert result.state != MarketState.IMBALANCED, (
            f"Got {result.state.value}, expected non-IMBALANCED for rejected probe above VAH"
        )

    def test_probe_below_val_rejects_is_not_imbalanced(self):
        """Price probed below VAL (low=96 < val=98) but closed at 100 (inside VA)."""
        result = _state_result(
            price=100.0,          # close inside VA
            vah=102.0,
            val=98.0,
            has_displacement=True,
            has_acceptance=False,
            balance_ratio=BALANCE_RATIO_THRESHOLD,
            bar_high=101.0,
            bar_low=96.0,         # probed below VAL
        )
        assert result.state != MarketState.IMBALANCED, (
            f"Got {result.state.value}, expected non-IMBALANCED for rejected probe below VAL"
        )

    def test_probe_both_sides_rejects_is_not_imbalanced(self):
        """Price probed both above VAH and below VAL but closed inside VA."""
        result = _state_result(
            price=100.0,
            vah=102.0,
            val=98.0,
            has_displacement=True,
            has_acceptance=False,
            balance_ratio=BALANCE_RATIO_THRESHOLD,
            bar_high=105.0,       # probed well above VAH
            bar_low=95.0,         # probed well below VAL
        )
        assert result.state != MarketState.IMBALANCED


class TestAcceptanceBeyondVAIsImbalanced:
    """Close beyond VA (acceptance) -> IMBALANCED (trend context)."""

    def test_acceptance_above_vah_is_imbalanced(self):
        """Price closed above VAH -> IMBALANCED."""
        result = _state_result(
            price=103.0,          # close above VAH=102
            vah=102.0,
            val=98.0,
            has_displacement=True,
            has_acceptance=True,
            balance_ratio=0.3,    # low balance ratio
            bar_high=104.0,
            bar_low=101.0,
        )
        assert result.state == MarketState.IMBALANCED

    def test_acceptance_below_val_is_imbalanced(self):
        """Price closed below VAL -> IMBALANCED."""
        result = _state_result(
            price=97.0,           # close below VAL=98
            vah=102.0,
            val=98.0,
            has_displacement=True,
            has_acceptance=True,
            balance_ratio=0.3,
            bar_high=101.0,
            bar_low=96.0,
        )
        assert result.state == MarketState.IMBALANCED


class TestProbeRejectionZoneIsNotOutsideVA:
    """Probe rejection zone should not be OUTSIDE_VA."""

    def test_probe_above_zone_is_not_outside_va(self):
        """When probe rejects above, zone should not be OUTSIDE_VA."""
        result = _state_result(
            price=100.0,          # close inside VA
            vah=102.0,
            val=98.0,
            has_displacement=False,
            has_acceptance=False,
            balance_ratio=BALANCE_RATIO_THRESHOLD,
            bar_high=103.0,       # probed above VAH
            bar_low=99.0,
        )
        assert result.zone != "OUTSIDE_VA"


class TestBackwardCompatibility:
    """Without bar_high/bar_low, behavior is unchanged."""

    def test_outside_va_still_imbalanced_without_bar_context(self):
        """Price outside VA without bar context -> IMBALANCED (backward compat)."""
        result = _state_result(
            price=106.0,          # close above VAH
            vah=105.0,
            val=95.0,
            has_displacement=False,
            has_acceptance=False,
            balance_ratio=BALANCE_RATIO_THRESHOLD,
        )
        assert result.state == MarketState.IMBALANCED
        assert result.zone == "OUTSIDE_VA"

    def test_inside_va_balanced_without_bar_context(self):
        """Price inside VA without bar context -> BALANCED (backward compat)."""
        result = _state_result(
            price=100.0,
            vah=105.0,
            val=95.0,
            has_displacement=False,
            has_acceptance=False,
            balance_ratio=BALANCE_RATIO_THRESHOLD,
        )
        assert result.state == MarketState.BALANCED
