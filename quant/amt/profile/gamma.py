"""Gamma Exposure (GEX) calculator for options and underlying instruments.

Computes dealer gamma exposure per strike, total net GEX in ₹ Crores,
zero-gamma flip level, Call Wall, Put Wall, and Pin Strike from option chains.
Pure stdlib math — zero heavy dependencies.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence


@dataclass(frozen=True)
class StrikeGEX:
    strike: float
    call_gex: float   # ₹ Crores
    put_gex: float    # ₹ Crores (negative)
    net_gex: float    # ₹ Crores


@dataclass(frozen=True)
class GammaExposureResult:
    net_gex_crores: float
    regime: str  # "POSITIVE_GAMMA" | "NEGATIVE_GAMMA" | "NEUTRAL_GAMMA"
    zero_flip_level: float
    call_wall_strike: float
    put_wall_strike: float
    gamma_pin_strike: float
    strike_gex: tuple[StrikeGEX, ...] = field(default_factory=tuple)


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_gamma(spot: float, strike: float, iv: float, t_years: float) -> float:
    """Black-Scholes option Gamma (dDelta / dSpot)."""
    if spot <= 0 or strike <= 0 or iv <= 0 or t_years <= 0:
        return 0.0
    vol_sqrt_t = iv * math.sqrt(t_years)
    if vol_sqrt_t <= 0:
        return 0.0
    d1 = (math.log(spot / strike) + 0.5 * iv * iv * t_years) / vol_sqrt_t
    return _norm_pdf(d1) / (spot * vol_sqrt_t)


def compute_gamma_exposure(
    spot: float,
    strikes: Sequence[float],
    calls_oi: dict[float, int],
    puts_oi: dict[float, int],
    calls_iv: dict[float, float] | None = None,
    puts_iv: dict[float, float] | None = None,
    lot_size: int = 1,
    t_years: float = 7.0 / 365.0,  # default 7 DTE proxy if exact expiry omitted
    default_iv: float = 0.18,
) -> GammaExposureResult:
    """Calculate aggregate dealer GEX and structural strike levels.

    Units: 1 Crore = 10,000,000 Rupees.
    """
    if spot <= 0 or not strikes:
        return GammaExposureResult(
            net_gex_crores=0.0,
            regime="NEUTRAL_GAMMA",
            zero_flip_level=spot,
            call_wall_strike=spot,
            put_wall_strike=spot,
            gamma_pin_strike=spot,
            strike_gex=(),
        )

    c_iv_map = calls_iv or {}
    p_iv_map = puts_iv or {}
    
    strike_results: list[StrikeGEX] = []
    total_call_gex = 0.0
    total_put_gex = 0.0
    
    max_call_gex = -1.0
    call_wall = float(strikes[0])
    
    min_put_gex = 1.0  # Put GEX is negative, most negative is maximum put wall
    put_wall = float(strikes[0])
    
    max_abs_gamma = -1.0
    pin_strike = float(strikes[0])

    # Convert Rupee exposure to ₹ Crores
    multiplier = (spot * lot_size) / 10_000_000.0

    sorted_strikes = sorted(strikes)
    for k in sorted_strikes:
        c_oi = calls_oi.get(k, 0)
        p_oi = puts_oi.get(k, 0)
        
        c_iv = c_iv_map.get(k) or default_iv
        p_iv = p_iv_map.get(k) or default_iv
        if c_iv <= 0:
            c_iv = default_iv
        if p_iv <= 0:
            p_iv = default_iv

        gamma_c = bs_gamma(spot, k, c_iv, t_years)
        gamma_p = bs_gamma(spot, k, p_iv, t_years)

        # Dealer GEX convention:
        # Long Call OI -> Dealer Short Option -> Dealer Long Gamma (+)
        # Long Put OI  -> Dealer Short Option -> Dealer Short Gamma (-)
        call_gex = c_oi * gamma_c * multiplier
        put_gex = -p_oi * gamma_p * multiplier
        net_k = call_gex + put_gex

        strike_results.append(
            StrikeGEX(
                strike=k,
                call_gex=0.0 if abs(call_gex) < 1e-4 else round(call_gex, 4),
                put_gex=0.0 if abs(put_gex) < 1e-4 else round(put_gex, 4),
                net_gex=0.0 if abs(net_k) < 1e-4 else round(net_k, 4),
            )
        )

        total_call_gex += call_gex
        total_put_gex += put_gex

        if call_gex > max_call_gex:
            max_call_gex = call_gex
            call_wall = k

        if put_gex < min_put_gex:
            min_put_gex = put_gex
            put_wall = k

        total_abs_k = call_gex + abs(put_gex)
        if total_abs_k > max_abs_gamma:
            max_abs_gamma = total_abs_k
            pin_strike = k

    net_gex_crores = total_call_gex + total_put_gex
    if abs(net_gex_crores) < 1e-4:
        net_gex_crores = 0.0

    # Find Zero Gamma Flip Level by linear interpolation across cumulative net GEX
    zero_flip = spot
    cum_gex = 0.0
    prev_strike = sorted_strikes[0]
    prev_cum = 0.0
    flip_found = False

    for sg in strike_results:
        prev_cum = cum_gex
        cum_gex += sg.net_gex
        if (prev_cum < 0 <= cum_gex) or (prev_cum > 0 >= cum_gex):
            # Interpolate flip price
            denom = abs(cum_gex - prev_cum)
            if denom > 0:
                frac = abs(prev_cum) / denom
                zero_flip = prev_strike + frac * (sg.strike - prev_strike)
            else:
                zero_flip = sg.strike
            flip_found = True
            break
        prev_strike = sg.strike

    if not flip_found:
        zero_flip = pin_strike if pin_strike > 0 else spot

    # Regime determination (sensitive for commodities and index options alike)
    if net_gex_crores > 0.01 and spot >= zero_flip:
        regime = "POSITIVE_GAMMA"
    elif net_gex_crores < -0.01 and spot <= zero_flip:
        regime = "NEGATIVE_GAMMA"
    elif net_gex_crores > 0.05:
        regime = "POSITIVE_GAMMA"
    elif net_gex_crores < -0.05:
        regime = "NEGATIVE_GAMMA"
    else:
        regime = "NEUTRAL_GAMMA"

    return GammaExposureResult(
        net_gex_crores=round(net_gex_crores, 2),
        regime=regime,
        zero_flip_level=round(zero_flip, 2),
        call_wall_strike=round(call_wall, 2),
        put_wall_strike=round(put_wall, 2),
        gamma_pin_strike=round(pin_strike, 2),
        strike_gex=tuple(strike_results),
    )

