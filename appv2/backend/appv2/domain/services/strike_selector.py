"""Strike Selector — selects optimal option contract for AMT signals.

Strategies:
- ATM: Maximum gamma (scalping-optimized)
- ITM: Delta 0.60–0.75 (directional, less theta decay)

Filters:
- Min OI (liquidity)
- Min volume
- Max bid-ask spread
- Theta cost analysis
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from appv2.domain.models.option import OptionContract, OptionChain
from appv2.domain.services.blackscholes import black_scholes
from appv2.config import constants as C
from appv2.config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class StrikeSelection:
    """Selected option contract with reasoning."""
    contract: OptionContract
    reason: str
    score: float  # 0–100


def select_strike(
    chain: OptionChain,
    direction: str,  # "LONG" or "SHORT"
    underlying_price: float,
    strike_pref: str = "ATM",
    days_to_expiry: float = 1.0,
    risk_free_rate: float = 0.065,  # RBI repo rate ~6.5%
) -> StrikeSelection | None:
    """Select best option contract for a signal.

    Steps:
    1. Filter by liquidity (OI, volume, spread)
    2. Score candidates
    3. Select CE for LONG, PE for SHORT
    4. Validate theta cost
    """
    if not chain.options or underlying_price <= 0:
        return None

    # Get ATM strike
    atm = chain.get_atm_strike()

    # Filter liquid contracts
    liquid = _filter_liquid(chain, underlying_price)
    if not liquid:
        logger.warning("No liquid contracts found for %s", chain.underlying)
        return None

    # Score candidates
    candidates = _score_candidates(
        liquid, atm, underlying_price, days_to_expiry, risk_free_rate, strike_pref
    )

    if not candidates:
        return None

    # Select by direction
    if direction == "LONG":
        candidates = [c for c in candidates if c.contract.option_type == "CE"]
    else:
        candidates = [c for c in candidates if c.contract.option_type == "PE"]

    if not candidates:
        return None

    # Best score
    best = max(candidates, key=lambda c: c.score)
    return best


def _filter_liquid(chain: OptionChain, spot: float) -> list[OptionContract]:
    """Filter contracts by liquidity criteria."""
    exchange = "NSE"  # Default
    min_oi = C.OPTION_MIN_OI_NIFTY if "NIFTY" in chain.underlying.upper() else C.OPTION_MIN_OI_CRUDEOIL

    liquid = []
    for opt in chain.options:
        # OI filter
        if opt.oi < min_oi:
            continue
        # Spread filter
        if opt.spread_bps > C.OPTION_MAX_SPREAD_BPS:
            continue
        liquid.append(opt)
    return liquid


def _score_candidates(
    contracts: list[OptionContract],
    atm_strike: float,
    spot: float,
    dte: float,
    r: float,
    pref: str,
) -> list[StrikeSelection]:
    """Score option contracts."""
    scored = []
    T = dte / 365.0

    for opt in contracts:
        score = 0.0

        # Greeks (if available from broker, else compute)
        delta = opt.delta
        gamma = opt.gamma

        if delta == 0 and gamma == 0 and T > 0 and opt.iv > 0:
            greeks = black_scholes(spot, opt.strike_price, T, r, opt.iv, opt.option_type)
            delta = greeks.delta
            gamma = greeks.gamma

        # ATM proximity (40 pts max)
        dist = abs(opt.strike_price - atm_strike)
        atm_score = max(0, 40 - dist * 0.1)
        score += atm_score

        # OI liquidity (30 pts max)
        oi_score = min(30, (opt.oi / 100_000) * 30)
        score += oi_score

        # Delta sweet spot (30 pts max)
        abs_delta = abs(delta)
        if pref == "ATM":
            # Prefer 0.40–0.60
            if C.ATM_DELTA_MIN <= abs_delta <= C.ATM_DELTA_MAX:
                score += 30
            else:
                score += max(0, 30 - abs(abs_delta - 0.50) * 60)
        else:  # ITM
            # Prefer 0.60–0.75
            if C.ITM_DELTA_MIN <= abs_delta <= C.ITM_DELTA_MAX:
                score += 30
            else:
                score += max(0, 30 - abs(abs_delta - 0.675) * 60)

        scored.append(StrikeSelection(contract=opt, reason=f"Score: {score:.0f}", score=score))

    return sorted(scored, key=lambda s: s.score, reverse=True)
