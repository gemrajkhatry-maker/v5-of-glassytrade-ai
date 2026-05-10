"""Tests for Black-Scholes Options Greeks Calculation."""
import math
import pytest

from brokersv2.analytics.options.greeks import (
    GreeksResult,
    calculate_greeks,
    calculate_iv,
    black_scholes_price,
)


class TestBlackScholesPrice:
    """Tests for Black-Scholes option pricing."""

    def test_call_option_price_basic(self) -> None:
        """Basic call option price calculation."""
        price = black_scholes_price(
            spot=100.0,
            strike=100.0,
            time_to_expiry=0.25,
            volatility=0.2,
            risk_free_rate=0.05,
            option_type="CE",
        )
        # ATM call should have positive value
        assert price > 0
        assert price < 100  # Should be less than spot

    def test_put_option_price_basic(self) -> None:
        """Basic put option price calculation."""
        price = black_scholes_price(
            spot=100.0,
            strike=100.0,
            time_to_expiry=0.25,
            volatility=0.2,
            risk_free_rate=0.05,
            option_type="PE",
        )
        # ATM put should have positive value
        assert price > 0
        assert price < 100  # Should be less than strike

    def test_call_price_intrinsic_value(self) -> None:
        """Deep ITM call price approaches intrinsic value."""
        price = black_scholes_price(
            spot=100.0,
            strike=50.0,
            time_to_expiry=0.01,
            volatility=0.2,
            risk_free_rate=0.05,
            option_type="CE",
        )
        # Should be close to intrinsic value (100 - 50 = 50)
        assert price > 49.0
        assert price < 51.0

    def test_put_price_intrinsic_value(self) -> None:
        """Deep ITM put price approaches intrinsic value."""
        price = black_scholes_price(
            spot=100.0,
            strike=150.0,
            time_to_expiry=0.01,
            volatility=0.2,
            risk_free_rate=0.05,
            option_type="PE",
        )
        # Should be close to intrinsic value (150 - 100 = 50)
        assert price > 49.0
        assert price < 51.0

    def test_call_price_increases_with_volatility(self) -> None:
        """Call price increases with higher volatility."""
        price_low_vol = black_scholes_price(
            spot=100.0,
            strike=100.0,
            time_to_expiry=0.25,
            volatility=0.1,
            risk_free_rate=0.05,
            option_type="CE",
        )
        price_high_vol = black_scholes_price(
            spot=100.0,
            strike=100.0,
            time_to_expiry=0.25,
            volatility=0.4,
            risk_free_rate=0.05,
            option_type="CE",
        )
        assert price_high_vol > price_low_vol

    def test_option_price_decreases_with_time(self) -> None:
        """Option price decreases as expiry approaches (time decay)."""
        price_long = black_scholes_price(
            spot=100.0,
            strike=100.0,
            time_to_expiry=0.5,
            volatility=0.2,
            risk_free_rate=0.05,
            option_type="CE",
        )
        price_short = black_scholes_price(
            spot=100.0,
            strike=100.0,
            time_to_expiry=0.1,
            volatility=0.2,
            risk_free_rate=0.05,
            option_type="CE",
        )
        assert price_long > price_short


class TestGreeksCalculation:
    """Tests for Greeks calculation invariants."""

    def test_call_delta_in_range(self) -> None:
        """Call delta must be between 0 and 1."""
        greeks = calculate_greeks(
            spot=100.0,
            strike=100.0,
            time_to_expiry=0.25,
            volatility=0.2,
            risk_free_rate=0.05,
            option_type="CE",
        )
        assert 0.0 <= greeks.delta <= 1.0

    def test_put_delta_negative_range(self) -> None:
        """Put delta must be between -1 and 0."""
        greeks = calculate_greeks(
            spot=100.0,
            strike=100.0,
            time_to_expiry=0.25,
            volatility=0.2,
            risk_free_rate=0.05,
            option_type="PE",
        )
        assert -1.0 <= greeks.delta <= 0.0

    def test_gamma_positive(self) -> None:
        """Gamma must be positive for both CE and PE."""
        greeks_ce = calculate_greeks(
            spot=100.0,
            strike=100.0,
            time_to_expiry=0.25,
            volatility=0.2,
            risk_free_rate=0.05,
            option_type="CE",
        )
        greeks_pe = calculate_greeks(
            spot=100.0,
            strike=100.0,
            time_to_expiry=0.25,
            volatility=0.2,
            risk_free_rate=0.05,
            option_type="PE",
        )
        assert greeks_ce.gamma > 0
        assert greeks_pe.gamma > 0
        # Gamma should be same for CE and PE at same strike
        assert abs(greeks_ce.gamma - greeks_pe.gamma) < 0.0001

    def test_theta_negative(self) -> None:
        """Theta must be negative (time decay)."""
        greeks = calculate_greeks(
            spot=100.0,
            strike=100.0,
            time_to_expiry=0.25,
            volatility=0.2,
            risk_free_rate=0.05,
            option_type="CE",
        )
        assert greeks.theta < 0

    def test_vega_positive(self) -> None:
        """Vega must be positive."""
        greeks = calculate_greeks(
            spot=100.0,
            strike=100.0,
            time_to_expiry=0.25,
            volatility=0.2,
            risk_free_rate=0.05,
            option_type="CE",
        )
        assert greeks.vega > 0

    def test_rho_positive_for_calls(self) -> None:
        """Rho must be positive for calls."""
        greeks = calculate_greeks(
            spot=100.0,
            strike=100.0,
            time_to_expiry=0.25,
            volatility=0.2,
            risk_free_rate=0.05,
            option_type="CE",
        )
        assert greeks.rho > 0

    def test_rho_negative_for_puts(self) -> None:
        """Rho must be negative for puts."""
        greeks = calculate_greeks(
            spot=100.0,
            strike=100.0,
            time_to_expiry=0.25,
            volatility=0.2,
            risk_free_rate=0.05,
            option_type="PE",
        )
        assert greeks.rho < 0


class TestGreeksBoundaryConditions:
    """Tests for Greeks at boundary conditions."""

    def test_atm_gamma_max(self) -> None:
        """Gamma should be maximum at ATM."""
        gamma_otm = calculate_greeks(
            spot=100.0,
            strike=120.0,
            time_to_expiry=0.25,
            volatility=0.2,
            risk_free_rate=0.05,
            option_type="CE",
        ).gamma
        gamma_atm = calculate_greeks(
            spot=100.0,
            strike=100.0,
            time_to_expiry=0.25,
            volatility=0.2,
            risk_free_rate=0.05,
            option_type="CE",
        ).gamma
        gamma_itm = calculate_greeks(
            spot=100.0,
            strike=80.0,
            time_to_expiry=0.25,
            volatility=0.2,
            risk_free_rate=0.05,
            option_type="CE",
        ).gamma
        assert gamma_atm > gamma_otm
        assert gamma_atm > gamma_itm

    def test_delta_approaches_one_deep_itm_call(self) -> None:
        """Call delta approaches 1.0 deep ITM."""
        greeks = calculate_greeks(
            spot=100.0,
            strike=50.0,
            time_to_expiry=0.25,
            volatility=0.2,
            risk_free_rate=0.05,
            option_type="CE",
        )
        assert greeks.delta > 0.95

    def test_delta_approaches_zero_deep_otm_call(self) -> None:
        """Call delta approaches 0.0 deep OTM."""
        greeks = calculate_greeks(
            spot=100.0,
            strike=150.0,
            time_to_expiry=0.25,
            volatility=0.2,
            risk_free_rate=0.05,
            option_type="CE",
        )
        assert greeks.delta < 0.05

    def test_delta_approaches_minus_one_deep_itm_put(self) -> None:
        """Put delta approaches -1.0 deep ITM."""
        greeks = calculate_greeks(
            spot=100.0,
            strike=150.0,
            time_to_expiry=0.25,
            volatility=0.2,
            risk_free_rate=0.05,
            option_type="PE",
        )
        assert greeks.delta < -0.95

    def test_delta_approaches_zero_deep_otm_put(self) -> None:
        """Put delta approaches 0.0 deep OTM."""
        greeks = calculate_greeks(
            spot=100.0,
            strike=50.0,
            time_to_expiry=0.25,
            volatility=0.2,
            risk_free_rate=0.05,
            option_type="PE",
        )
        assert greeks.delta > -0.05

    def test_theta_approaches_zero_far_expiry(self) -> None:
        """Theta approaches 0 when far from expiry."""
        greeks = calculate_greeks(
            spot=100.0,
            strike=100.0,
            time_to_expiry=2.0,
            volatility=0.2,
            risk_free_rate=0.05,
            option_type="CE",
        )
        # Theta should be less negative (closer to 0)
        assert greeks.theta > -5.0

    def test_theta_large_negative_near_expiry(self) -> None:
        """Theta becomes very negative near expiry."""
        greeks = calculate_greeks(
            spot=100.0,
            strike=100.0,
            time_to_expiry=0.01,
            volatility=0.2,
            risk_free_rate=0.05,
            option_type="CE",
        )
        # Theta should be more negative (per-day value)
        assert greeks.theta < -0.05


class TestIVCalculation:
    """Tests for implied volatility calculation."""

    def test_iv_recovery(self) -> None:
        """Can recover IV from known option price."""
        # Calculate price with known IV
        market_price = black_scholes_price(
            spot=100.0,
            strike=100.0,
            time_to_expiry=0.25,
            volatility=0.25,
            risk_free_rate=0.05,
            option_type="CE",
        )

        # Recover IV from price
        recovered_iv = calculate_iv(
            market_price=market_price,
            spot=100.0,
            strike=100.0,
            time_to_expiry=0.25,
            risk_free_rate=0.05,
            option_type="CE",
        )

        # Should recover original IV (within tolerance)
        assert abs(recovered_iv - 0.25) < 0.01

    def test_iv_positive(self) -> None:
        """IV must be positive."""
        iv = calculate_iv(
            market_price=3.5,
            spot=100.0,
            strike=100.0,
            time_to_expiry=0.25,
            risk_free_rate=0.05,
            option_type="CE",
        )
        assert iv > 0

    def test_iv_increases_with_price(self) -> None:
        """Higher option price implies higher IV."""
        iv_low = calculate_iv(
            market_price=2.0,
            spot=100.0,
            strike=100.0,
            time_to_expiry=0.25,
            risk_free_rate=0.05,
            option_type="CE",
        )
        iv_high = calculate_iv(
            market_price=5.0,
            spot=100.0,
            strike=100.0,
            time_to_expiry=0.25,
            risk_free_rate=0.05,
            option_type="CE",
        )
        assert iv_high > iv_low


class TestGreeksResult:
    """Tests for GreeksResult immutability."""

    def test_greeks_result_is_immutable(self) -> None:
        """GreeksResult is frozen and cannot be modified."""
        greeks = calculate_greeks(
            spot=100.0,
            strike=100.0,
            time_to_expiry=0.25,
            volatility=0.2,
            risk_free_rate=0.05,
            option_type="CE",
        )
        with pytest.raises(Exception):
            greeks.delta = 0.5

    def test_greeks_result_has_all_fields(self) -> None:
        """GreeksResult has all required Greek fields."""
        greeks = calculate_greeks(
            spot=100.0,
            strike=100.0,
            time_to_expiry=0.25,
            volatility=0.2,
            risk_free_rate=0.05,
            option_type="CE",
        )
        assert hasattr(greeks, 'delta')
        assert hasattr(greeks, 'gamma')
        assert hasattr(greeks, 'theta')
        assert hasattr(greeks, 'vega')
        assert hasattr(greeks, 'rho')
        assert hasattr(greeks, 'implied_vol')
