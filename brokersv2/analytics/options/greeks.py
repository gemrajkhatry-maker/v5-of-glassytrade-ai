"""Black-Scholes Options Greeks Calculation."""

import math
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class GreeksResult:
    """Options Greeks calculation result."""
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float
    implied_vol: float = 0.0


def _norm_cdf(x: float) -> float:
    """Cumulative distribution function for standard normal distribution."""
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0


def _norm_pdf(x: float) -> float:
    """Probability density function for standard normal distribution."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def black_scholes_price(
    spot: float,
    strike: float,
    time_to_expiry: float,
    volatility: float,
    risk_free_rate: float,
    option_type: str,
    dividend_yield: float = 0.013,
) -> float:
    """
    Calculate Black-Scholes option price using the Merton continuous-dividend model.

    Args:
        spot: Current underlying price
        strike: Option strike price
        time_to_expiry: Time to expiry in years
        volatility: Implied volatility (annualized)
        risk_free_rate: Risk-free interest rate (e.g. 0.065 for 6.5%)
        option_type: "CE" for call, "PE" for put
        dividend_yield: Continuous dividend yield (default 0.013 = NIFTY ~1.3%)

    Returns:
        Option price
    """
    if time_to_expiry <= 0:
        if option_type == "CE":
            return max(0.0, spot - strike)
        else:
            return max(0.0, strike - spot)

    # Merton adjustment: discount spot by dividend yield
    adj_spot = spot * math.exp(-dividend_yield * time_to_expiry)

    d1 = (
        math.log(adj_spot / strike)
        + (risk_free_rate + 0.5 * volatility**2) * time_to_expiry
    ) / (volatility * math.sqrt(time_to_expiry))

    d2 = d1 - volatility * math.sqrt(time_to_expiry)

    if option_type == "CE":
        price = adj_spot * _norm_cdf(d1) - strike * math.exp(
            -risk_free_rate * time_to_expiry
        ) * _norm_cdf(d2)
    else:
        price = strike * math.exp(-risk_free_rate * time_to_expiry) * _norm_cdf(
            -d2
        ) - adj_spot * _norm_cdf(-d1)

    return max(0.0, price)


def calculate_greeks(
    spot: float,
    strike: float,
    time_to_expiry: float,
    volatility: float,
    risk_free_rate: float,
    option_type: str,
    dividend_yield: float = 0.013,
) -> GreeksResult:
    """
    Calculate all options Greeks using the Merton continuous-dividend model.

    Args:
        spot: Current underlying price
        strike: Option strike price
        time_to_expiry: Time to expiry in years
        volatility: Implied volatility (annualized)
        risk_free_rate: Risk-free interest rate (e.g. 0.065 for 6.5%)
        option_type: "CE" for call, "PE" for put
        dividend_yield: Continuous dividend yield (default 0.013 = NIFTY ~1.3%)

    Returns:
        GreeksResult with delta, gamma, theta, vega, rho
    """
    if time_to_expiry <= 0:
        return GreeksResult(delta=0.0, gamma=0.0, theta=0.0, vega=0.0, rho=0.0)

    # Merton adjustment: discount spot by dividend yield
    adj_spot = spot * math.exp(-dividend_yield * time_to_expiry)

    d1 = (
        math.log(adj_spot / strike)
        + (risk_free_rate + 0.5 * volatility**2) * time_to_expiry
    ) / (volatility * math.sqrt(time_to_expiry))

    d2 = d1 - volatility * math.sqrt(time_to_expiry)

    # Gamma (same for call and put)
    gamma = _norm_pdf(d1) / (adj_spot * volatility * math.sqrt(time_to_expiry))

    # Vega (same for call and put)
    vega = adj_spot * _norm_pdf(d1) * math.sqrt(time_to_expiry) / 100.0

    if option_type == "CE":
        delta = math.exp(-dividend_yield * time_to_expiry) * _norm_cdf(d1)
        theta = (
            -(adj_spot * _norm_pdf(d1) * volatility) / (2.0 * math.sqrt(time_to_expiry))
            - risk_free_rate * strike * math.exp(-risk_free_rate * time_to_expiry) * _norm_cdf(d2)
            + dividend_yield * adj_spot * _norm_cdf(d1)
        ) / 252.0  # trading days denominator (not calendar)
        rho = (
            strike * time_to_expiry * math.exp(-risk_free_rate * time_to_expiry) * _norm_cdf(d2)
        ) / 100.0
    else:
        delta = math.exp(-dividend_yield * time_to_expiry) * (_norm_cdf(d1) - 1.0)
        theta = (
            -(adj_spot * _norm_pdf(d1) * volatility) / (2.0 * math.sqrt(time_to_expiry))
            + risk_free_rate * strike * math.exp(-risk_free_rate * time_to_expiry) * _norm_cdf(-d2)
            - dividend_yield * adj_spot * _norm_cdf(-d1)
        ) / 252.0  # trading days denominator
        rho = (
            -strike * time_to_expiry * math.exp(-risk_free_rate * time_to_expiry) * _norm_cdf(-d2)
        ) / 100.0

    return GreeksResult(
        delta=delta,
        gamma=gamma,
        theta=theta,
        vega=vega,
        rho=rho,
    )


def calculate_iv(
    market_price: float,
    spot: float,
    strike: float,
    time_to_expiry: float,
    risk_free_rate: float,
    option_type: str,
    tolerance: float = 0.0001,
    max_iterations: int = 100,
    dividend_yield: float = 0.013,
) -> float:
    """
    Calculate implied volatility using bisection method (Merton model).

    Args:
        market_price: Market price of the option
        spot: Current underlying price
        strike: Option strike price
        time_to_expiry: Time to expiry in years
        risk_free_rate: Risk-free interest rate
        option_type: "CE" for call, "PE" for put
        tolerance: Convergence tolerance
        max_iterations: Maximum iterations
        dividend_yield: Continuous dividend yield (default 0.013 = NIFTY ~1.3%)

    Returns:
        Implied volatility

    Raises:
        ValueError: If IV cannot be found
    """
    # Bisection method
    low_vol = 0.001
    high_vol = 5.0

    for _ in range(max_iterations):
        mid_vol = (low_vol + high_vol) / 2.0

        theoretical_price = black_scholes_price(
            spot, strike, time_to_expiry, mid_vol, risk_free_rate, option_type,
            dividend_yield=dividend_yield,
        )
        
        price_diff = theoretical_price - market_price
        
        if abs(price_diff) < tolerance:
            return mid_vol
        
        if price_diff > 0:
            # Theoretical price too high, reduce volatility
            high_vol = mid_vol
        else:
            # Theoretical price too low, increase volatility
            low_vol = mid_vol
    
    raise ValueError(
        f"IV calculation failed to converge after {max_iterations} iterations"
    )


def _map_option_type(option_type) -> str:
    """Map option type to CE/PE format."""
    if hasattr(option_type, 'value'):
        # Enum - map call/put to CE/PE
        val = option_type.value.lower()
        return "CE" if val == "call" else "PE"
    elif isinstance(option_type, str):
        val = option_type.lower()
        if val in ["call", "c", "ce"]:
            return "CE"
        else:
            return "PE"
    return "CE"  # default to call


class GreeksCalculator:
    """Calculator class for options Greeks (instance methods for test compatibility)."""
    
    def delta(
        self,
        underlying_price: float,
        strike: float,
        time_to_expiry: float,
        volatility: float,
        risk_free_rate: float,
        option_type,
    ) -> float:
        """Calculate option delta.

        Args:
            time_to_expiry: Calendar days to expiry.  Converted to years
                (÷365) before being passed to the Black-Scholes formula.
                Theta output from calculate_greeks is expressed per trading
                day (÷252) — these are intentionally different denominators.
        """
        # Calendar days → years (Black-Scholes convention)
        time_in_years = time_to_expiry / 365.0
        
        # Map option type to CE/PE format
        opt_type = _map_option_type(option_type)
        
        result = calculate_greeks(
            underlying_price, strike, time_in_years, volatility, risk_free_rate, opt_type
        )
        return result.delta
    
    def gamma(
        self,
        underlying_price: float,
        strike: float,
        time_to_expiry: float,
        volatility: float,
        risk_free_rate: float,
        option_type=None,
    ) -> float:
        """Calculate option gamma. time_to_expiry in calendar DAYS."""
        time_in_years = time_to_expiry / 365.0
        opt_type = _map_option_type(option_type) if option_type else "CE"
        result = calculate_greeks(
            underlying_price, strike, time_in_years, volatility, risk_free_rate, opt_type
        )
        return result.gamma
    
    def theta(
        self,
        underlying_price: float,
        strike: float,
        time_to_expiry: float,
        volatility: float,
        risk_free_rate: float,
        option_type=None,
    ) -> float:
        """Calculate option theta. time_to_expiry in calendar DAYS.
        Returns theta per trading day (÷252 denominator in BS formula)."""
        time_in_years = time_to_expiry / 365.0
        opt_type = _map_option_type(option_type) if option_type else "CE"
        result = calculate_greeks(
            underlying_price, strike, time_in_years, volatility, risk_free_rate, opt_type
        )
        return result.theta
    
    def vega(
        self,
        underlying_price: float,
        strike: float,
        time_to_expiry: float,
        volatility: float,
        risk_free_rate: float,
        option_type=None,
    ) -> float:
        """Calculate option vega. time_to_expiry in calendar DAYS."""
        time_in_years = time_to_expiry / 365.0
        opt_type = _map_option_type(option_type) if option_type else "CE"
        result = calculate_greeks(
            underlying_price, strike, time_in_years, volatility, risk_free_rate, opt_type
        )
        return result.vega
    
    def calculate_all_greeks(
        self,
        symbol: str,
        underlying_price: float,
        strike: float,
        time_to_expiry: float,
        volatility: float,
        risk_free_rate: float,
        option_type,
    ) -> 'GreeksSnapshot':
        """Calculate all Greeks and return as snapshot.
        
        Args:
            time_to_expiry: Time to expiry in DAYS
        """
        from brokersv2.analytics.options.events import GreeksSnapshot
        from datetime import datetime, timezone
        
        time_in_years = time_to_expiry / 365.0
        opt_type = _map_option_type(option_type)
        
        result = calculate_greeks(
            underlying_price, strike, time_in_years, volatility, risk_free_rate, opt_type
        )
        
        return GreeksSnapshot(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            delta=result.delta,
            gamma=result.gamma,
            theta=result.theta,
            vega=result.vega,
            rho=result.rho,
            underlying_price=underlying_price,
            strike=strike,
        )
