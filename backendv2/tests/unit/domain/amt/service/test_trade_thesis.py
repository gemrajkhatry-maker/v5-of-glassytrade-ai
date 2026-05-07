"""Tests for trade thesis builder — execution-grade trade thesis functions."""
import pytest
from app.domain.amt.service.trade_thesis import (
    TradeThesis,
    build_trade_thesis,
    infer_location,
    infer_aggression_trigger,
    validate_trade_thesis,
    setup_family_for,
)
from app.domain.trading.model.enums import SetupType
from app.domain.trading.model.value_objects import AMTResult, OHLC


def _make_ohlc(
    time: str = "2025-01-01T09:30:00",
    open: float = 100.0,
    high: float = 102.0,
    low: float = 99.0,
    close: float = 101.0,
    volume: float = 500.0,
    delta: float = 100.0,
) -> OHLC:
    return OHLC.create(
        time=time,
        open=open,
        high=high,
        low=low,
        close=close,
        volume=volume,
        delta=delta,
    )


def _make_amt_result(
    market_state: str = "BALANCED",
    poc: float = 101.0,
    value_area_high: float = 103.0,
    value_area_low: float = 99.0,
    liquidity_sweep: str = "",
    aggression: float = 0.0,
    cvd_slope: float = 0.0,
    ofi: float = 0.0,
    ib_high: float = 102.5,
    ib_low: float = 99.5,
    **kwargs,
) -> AMTResult:
    return AMTResult(
        market_state=market_state,
        poc=poc,
        value_area_high=value_area_high,
        value_area_low=value_area_low,
        liquidity_sweep=liquidity_sweep,
        aggression=aggression,
        cvd_slope=cvd_slope,
        ofi=ofi,
        ib_high=ib_high,
        ib_low=ib_low,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# build_trade_thesis() tests
# ---------------------------------------------------------------------------


class TestBuildTradeThesis:
    """Tests for build_trade_thesis()."""

    def test_complete_thesis_all_fields_populated(self):
        """Build a complete thesis with all fields populated."""
        tick = _make_ohlc(close=101.0, volume=500.0, delta=100.0)
        amt = _make_amt_result(
            market_state="BALANCED",
            poc=101.0,
            value_area_high=103.0,
            value_area_low=99.0,
            liquidity_sweep="SELL_SWEEP",
        )
        thesis = build_trade_thesis(
            tick=tick,
            amt_result=amt,
            setup_type=SetupType.MEAN_REVERSION,
            session_context="RTH",
            invalidation_level=98.5,
        )

        assert thesis.market_state == "BALANCED"
        assert thesis.location_level > 0
        assert thesis.aggression_trigger == "SELL_SWEEP"
        assert thesis.session_context == "RTH"
        assert thesis.invalidation_level == 98.5
        assert thesis.setup_family == "return_to_value"
        assert thesis.is_complete is True

    def test_missing_market_state_yields_incomplete(self):
        """Missing market state results in incomplete thesis."""
        tick = _make_ohlc(close=101.0)
        amt = _make_amt_result(market_state="UNKNOWN")
        thesis = build_trade_thesis(
            tick=tick,
            amt_result=amt,
            setup_type=SetupType.TREND_MODEL,
            session_context="RTH",
            invalidation_level=98.5,
        )

        assert thesis.market_state == "UNKNOWN"
        assert thesis.is_complete is False

    def test_mid_range_entry_detected(self):
        """Price between VAH and VAL returns VA boundary fallback (not MID_RANGE)."""
        tick = _make_ohlc(close=100.0)
        amt = _make_amt_result(
            poc=90.0,
            value_area_high=110.0,
            value_area_low=50.0,
            ib_high=108.0,
            ib_low=52.0,
            # Price=100 is far from poc=90 (diff=10), far from IB levels
            # va_range=60, threshold=min(max(21, 0.25), 1.5)=1.5, |100-90|=10 > 1.5
        )
        location_type, location_level = infer_location(tick.close, amt)

        # Should fallback to a VA boundary, not MID_RANGE
        assert location_type in ("VAH", "VAL")
        assert location_level > 0

    def test_strong_thesis_with_clear_setup_and_aggression(self):
        """Strong thesis with liquidity sweep and trend setup."""
        tick = _make_ohlc(close=101.5, volume=1000.0, delta=300.0)
        amt = _make_amt_result(
            market_state="IMBALANCED",
            poc=101.5,
            value_area_high=104.0,
            value_area_low=98.0,
            liquidity_sweep="BUY_SWEEP",
            aggression=0.8,
        )
        thesis = build_trade_thesis(
            tick=tick,
            amt_result=amt,
            setup_type=SetupType.TREND_MODEL,
            session_context="AM_SESSION",
            invalidation_level=97.0,
        )

        assert thesis.is_complete is True
        assert thesis.market_state == "IMBALANCED"
        assert thesis.aggression_trigger == "BUY_SWEEP"
        assert thesis.setup_family == "imbalance_continuation"


# ---------------------------------------------------------------------------
# infer_location() tests
# ---------------------------------------------------------------------------


class TestInferLocation:
    """Tests for infer_location()."""

    def test_near_poc_returns_poc(self):
        """Price near POC returns POC as location."""
        amt = _make_amt_result(
            poc=100.0,
            value_area_high=105.0,
            value_area_low=95.0,
        )
        location_type, location_level = infer_location(price=100.1, amt_result=amt)

        assert location_type == "POC"
        assert location_level == 100.0

    def test_fallback_to_va_boundary_when_far_from_poc(self):
        """When far from POC, falls back to nearest VA boundary."""
        amt = _make_amt_result(
            poc=100.0,
            value_area_high=110.0,
            value_area_low=90.0,
        )
        # Price=105 is far from POC=100 (diff=5)
        # va_range=20, threshold=min(max(7, 0.2625), 1.575)=1.575, |105-100|=5 > 1.575
        # 105 is closer to VAH=110 than to VAL=90
        location_type, location_level = infer_location(price=105.0, amt_result=amt)

        assert location_type in ("VAH", "VAL")
        assert location_level > 0

    def test_uses_ib_high_low_when_closer(self):
        """IB high/low used when price is closer to IB than other levels."""
        amt = _make_amt_result(
            poc=100.0,
            value_area_high=120.0,
            value_area_low=80.0,
            ib_high=105.0,
            ib_low=95.0,
        )
        # Price very close to IB high
        location_type, location_level = infer_location(price=105.05, amt_result=amt)

        assert location_type == "IB_HIGH"
        assert location_level == 105.0


# ---------------------------------------------------------------------------
# infer_aggression_trigger() tests
# ---------------------------------------------------------------------------


class TestInferAggressionTrigger:
    """Tests for infer_aggression_trigger()."""

    def test_liquidity_sweep_detected(self):
        """Liquidity sweep is the highest-priority trigger."""
        tick = _make_ohlc()
        amt = _make_amt_result(liquidity_sweep="SELL_SWEEP")

        trigger = infer_aggression_trigger(tick, amt)

        assert trigger == "SELL_SWEEP"

    def test_delta_expansion_trigger(self):
        """Delta expansion triggers when delta_ratio is high enough."""
        tick = _make_ohlc(volume=500.0, delta=100.0)  # delta_ratio = 0.2
        amt = _make_amt_result(aggression=0.7)

        trigger = infer_aggression_trigger(tick, amt)

        assert trigger == "DELTA_EXPANSION"

    def test_fallback_to_default(self):
        """When no specific signals, falls back to a default aggression."""
        tick = _make_ohlc(volume=50.0, delta=0.0)
        amt = _make_amt_result()

        trigger = infer_aggression_trigger(tick, amt)

        # Should never return empty string
        assert trigger != ""
        assert isinstance(trigger, str)


# ---------------------------------------------------------------------------
# validate_trade_thesis() tests
# ---------------------------------------------------------------------------


class TestValidateTradeThesis:
    """Tests for validate_trade_thesis()."""

    def test_complete_thesis_passes_validation(self):
        """A complete thesis with all fields passes validation."""
        thesis = TradeThesis(
            market_state="BALANCED",
            location_type="POC",
            location_level=100.0,
            aggression_trigger="SELL_SWEEP",
            session_context="RTH",
            invalidation_level=98.0,
            setup_family="return_to_value",
        )

        valid, reason = validate_trade_thesis(thesis)

        assert valid is True
        assert reason == ""

    def test_missing_state_fails_validation(self):
        """Missing or invalid market state fails validation."""
        thesis = TradeThesis(
            market_state="UNKNOWN",
            location_type="POC",
            location_level=100.0,
            aggression_trigger="SELL_SWEEP",
            session_context="RTH",
            invalidation_level=98.0,
        )

        valid, reason = validate_trade_thesis(thesis)

        assert valid is False
        assert reason == "missing_state"

    def test_missing_setup_fails_validation(self):
        """Empty aggression_trigger (missing setup signal) fails validation."""
        thesis = TradeThesis(
            market_state="BALANCED",
            location_type="POC",
            location_level=100.0,
            aggression_trigger="",
            session_context="RTH",
            invalidation_level=98.0,
        )

        valid, reason = validate_trade_thesis(thesis)

        assert valid is False
        assert reason == "missing_aggression"

    def test_none_thesis_fails_validation(self):
        """None thesis fails with missing_state."""
        valid, reason = validate_trade_thesis(None)

        assert valid is False
        assert reason == "missing_state"

    def test_dict_thesis_validated_correctly(self):
        """A dict thesis is converted and validated."""
        thesis_dict = {
            "market_state": "IMBALANCED",
            "location_type": "VAH",
            "location_level": 105.0,
            "aggression_trigger": "BUY_SWEEP",
            "session_context": "PM_SESSION",
            "invalidation_level": 102.0,
            "setup_family": "imbalance_continuation",
        }

        valid, reason = validate_trade_thesis(thesis_dict)

        assert valid is True
        assert reason == ""

    def test_mid_range_entry_fails_validation(self):
        """MID_RANGE location type fails validation."""
        thesis = TradeThesis(
            market_state="BALANCED",
            location_type="MID_RANGE",
            location_level=0.0,
            aggression_trigger="SELL_SWEEP",
            session_context="RTH",
            invalidation_level=98.0,
        )

        valid, reason = validate_trade_thesis(thesis)

        assert valid is False
        assert reason == "mid_range_entry"


# ---------------------------------------------------------------------------
# setup_family_for() tests
# ---------------------------------------------------------------------------


class TestSetupFamilyFor:
    """Tests for setup_family_for()."""

    def test_mean_reversion_family(self):
        """MEAN_REVERSION maps to return_to_value."""
        assert setup_family_for(SetupType.MEAN_REVERSION) == "return_to_value"

    def test_trend_model_family(self):
        """TREND_MODEL maps to imbalance_continuation."""
        assert setup_family_for(SetupType.TREND_MODEL) == "imbalance_continuation"

    def test_responsive_fade_family(self):
        """RESPONSIVE_FADE maps to its own lowercased value."""
        assert setup_family_for(SetupType.RESPONSIVE_FADE) == "responsive_fade"
