"""Black-Scholes option pricing model.

Computes: delta, gamma, theta, vega, theoretical price, IV (Newton-Raphson).
Used for options strike selection and theta cost analysis.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Greeks:
    delta: float
    gamma: float
    theta: float  # Per year
    vega: float  # Per 1% vol change
    theoretical: float


def _norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    """Standard normal probability density function."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def black_scholes(
    S: float,  # Spot price (underlying)
    K: float,  # Strike price
    T: float,  # Time to expiry (in years)
    r: float,  # Risk-free rate (annual)
    sigma: float,  # Implied volatility (annual)
    option_type: str = "CE",  # "CE" or "PE"
) -> Greeks:
    """Compute Black-Scholes Greeks and theoretical price.

    T is in years: T = days_to_expiry / 365
    sigma is annualized volatility (e.g., 0.20 for 20%)
    """
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return Greeks(delta=0.0, gamma=0.0, theta=0.0, vega=0.0, theoretical=0.0)

    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    sqrt_t = math.sqrt(T)
    nd1 = _norm_pdf(d1)

    if option_type == "CE":
        delta = _norm_cdf(d1)
        theoretical = S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    else:
        delta = _norm_cdf(d1) - 1.0
        theoretical = K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)

    gamma = nd1 / (S * sigma * sqrt_t)
    theta_yearly = -(S * nd1 * sigma) / (2 * sqrt_t) - r * K * math.exp(-r * T) * _norm_cdf(d2 if option_type == "CE" else -d2)
    if option_type == "PE":
        theta_yearly = -(S * nd1 * sigma) / (2 * sqrt_t) + r * K * math.exp(-r * T) * _norm_cdf(-d2)
    vega = S * nd1 * sqrt_t / 100  # Per 1% vol change

    return Greeks(
        delta=delta,
        gamma=gamma,
        theta=theta_yearly / 365,  # Per day
        vega=vega,
        theoretical=theoretical,
    )


def implied_volatility(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    option_type: str = "CE",
    max_iter: int = 100,
    tol: float = 1e-6,
) -> float:
    """Compute implied volatility via Newton-Raphson.

    Returns IV or 0.0 if not convergent.
    """
    if market_price <= 0:
        return 0.0

    sigma = 0.3  # Initial guess

    for _ in range(max_iter):
        greeks = black_scholes(S, K, T, r, sigma, option_type)
        price = greeks.theoretical
        vega = greeks.vega * 100  # Convert back from per-1%

        diff = price - market_price
        if abs(diff) < tol:
            return sigma

        if vega <= 0:
            break

        sigma -= diff / vega
        sigma = max(0.01, min(sigma, 5.0))  # Clamp

    return 0.0  # Did not converge
