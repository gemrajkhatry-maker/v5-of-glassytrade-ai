"""Gate 3 — the Triple-A edge (Fabio: absorption -> accumulation -> aggression)."""

from quant.amt.orderflow.aggression import canonical_absorption_direction
from quant.contracts.enums import MarketState

from quant.decision.context import DecisionContext
from quant.decision.result import GateResult

# Fresh absorption window (bars): the absorption must be recent enough to back
# the breakout — older footprints are re-tested, not traded through.
_ABSORPTION_MAX_AGE_BARS = 5

# Depth-derived order-flow aggression (Fabio's A3): |OBI| above this threshold
# with the price beyond the matching VWAP band is an aggression confirmation.
# OBI is the live order-book imbalance ([-1, 1]) computed by the AMT analyzer
# from the Dhan 5-level depth snapshot.
_OBI_AGGRESSION_THRESHOLD = 0.20

# Fabio's 1-minute acceptance rule: an entry must be a full-body candle close in
# the trade direction, NOT a wick probe or a mid-candle entry. Entry signals fire
# mid-bar on the live tape, which is exactly when a probe looks like a breakout
# and then rejects back through the range — putting the structural stop on the
# wrong side of the sweep.
#
#   * the body must be at least _FULL_BODY_MIN_RATIO of the bar's range;
#   * the close must sit in the outer (1 - _CLOSE_NEAR_EXTREME_MIN) of the range.
#
# A bar with no range is INDETERMINATE and is NOT blocked: synthetic fixtures,
# halted instruments and thin contracts all legitimately print zero-range bars,
# and refusing them would disable trading rather than filter probes.
_FULL_BODY_MIN_RATIO = 0.6
_CLOSE_NEAR_EXTREME_MIN = 0.75


def _opposing_absorption(ctx: DecisionContext) -> bool:
    """True when the absorption reading contradicts the trade direction.

    Review finding P0-5: the aggregate aggression score counts activity, not
    agreement, and ``compute.py`` marks ``cvd_confirmed``/``footprint_confirmed``
    without regard to sign. The absorption side IS directional, so a setup whose
    own footprint says the opposite (hidden seller absorbing buys while going
    LONG) must not be actionable. Unknown sides do not block here — the scorer
    already refuses them credit.
    """
    direction = str(getattr(ctx, "agent_direction", "") or "").upper()
    if direction not in ("LONG", "SHORT"):
        return False
    canonical = canonical_absorption_direction(getattr(ctx, "absorption_side", ""))
    return canonical is not None and canonical != direction


def _candle_acceptance(ctx: DecisionContext) -> GateResult | None:
    """Reject wick probes and mid-candle entries (1-minute acceptance rule).

    Returns ``None`` when the bar is an acceptable full-body close in the trade
    direction, or when the bar carries no range (indeterminate).
    """
    bar = ctx.bar
    if bar is None:
        return None
    open_px = float(bar.open)
    high = float(bar.high)
    low = float(bar.low)
    close = float(bar.close)
    span = high - low
    if span <= 0:
        return None  # indeterminate: cannot judge a zero-range bar

    direction = str(getattr(ctx, "agent_direction", "") or "").upper()
    body = close - open_px
    body_ratio = abs(body) / span

    if direction == "LONG":
        if body <= 0:
            return GateResult(3, False, "1-min candle closed down — no bullish body")
        if (close - low) / span < _CLOSE_NEAR_EXTREME_MIN:
            return GateResult(
                3, False,
                f"Wick probe rejected: close not near the high "
                f"({(close - low) / span:.0%} of range < {_CLOSE_NEAR_EXTREME_MIN:.0%})",
            )
    elif direction == "SHORT":
        if body >= 0:
            return GateResult(3, False, "1-min candle closed up — no bearish body")
        if (high - close) / span < _CLOSE_NEAR_EXTREME_MIN:
            return GateResult(
                3, False,
                f"Wick probe rejected: close not near the low "
                f"({(high - close) / span:.0%} of range < {_CLOSE_NEAR_EXTREME_MIN:.0%})",
            )
    else:
        return None

    if body_ratio < _FULL_BODY_MIN_RATIO:
        return GateResult(
            3, False,
            f"Mid-candle probe rejected: body {body_ratio:.0%} of range "
            f"< {_FULL_BODY_MIN_RATIO:.0%}",
        )
    return None


def _check_guards(ctx: DecisionContext) -> GateResult | None:
    """Pre-check guards that veto entry before setup evaluation."""
    if ctx.bar is None:
        return GateResult(3, False, "No bar")
    if _opposing_absorption(ctx):
        return GateResult(
            3,
            False,
            f"Opposing absorption: {ctx.absorption_side} is {canonical_absorption_direction(ctx.absorption_side)} "
            f"evidence, not {ctx.agent_direction}",
        )
    si_dir = getattr(ctx, "stacked_imbalance_direction", "")
    if si_dir and ctx.agent_direction:
        if (ctx.agent_direction == "LONG" and si_dir == "SELL") or (ctx.agent_direction == "SHORT" and si_dir == "BUY"):
            mag = getattr(ctx, "stacked_imbalance_magnitude", 0)
            lo = getattr(ctx, "stacked_imbalance_price_low", 0.0)
            hi = getattr(ctx, "stacked_imbalance_price_high", 0.0)
            return GateResult(3, False, f"Opposing stacked {si_dir} imbalance x{mag} at {lo:.2f}-{hi:.2f}")
    if getattr(ctx, "contested_bubble_zone", False):
        return GateResult(3, False, "Contested bubble zone — both sides stacked, stay flat")
    if ctx.agent_direction not in ("LONG", "SHORT"):
        return GateResult(3, False, "No direction")
    ms_val = getattr(ctx.market_state, "value", ctx.market_state)
    if ms_val in (MarketState.DEAD.value, "DEAD", "DEAD_MARKET"):
        return GateResult(3, False, "Dead market — no edge")
    close_px = float(ctx.bar.close) if ctx.bar else 0.0
    if ctx.agent_direction == "LONG" and ctx.vwap_upper_2 > 0 and close_px > ctx.vwap_upper_2:
        return GateResult(3, False, f"Anti-Climax: LONG rejected at +{abs(ctx.vwap_std):.1f}σ extension")
    if ctx.agent_direction == "SHORT" and ctx.vwap_lower_2 > 0 and close_px < ctx.vwap_lower_2:
        return GateResult(3, False, f"Anti-Climax: SHORT rejected at -{abs(ctx.vwap_std):.1f}σ extension")
    acceptance = _candle_acceptance(ctx)
    if acceptance:
        return acceptance
    if getattr(ctx, "drive_number", 0) >= 3 and not getattr(ctx, "drive_entry_valid", False):
        return GateResult(3, False, f"Drive count exhausted ({ctx.drive_number})")
    cvd_slope = ctx.cvd_slope
    market = getattr(ctx, "market", "NSE")
    cvd_block_neg = -0.3 if str(market).upper() == "MCX" else -0.5
    cvd_block_pos = 0.3 if str(market).upper() == "MCX" else 0.5
    if ctx.agent_direction == "LONG" and cvd_slope < cvd_block_neg:
        return GateResult(3, False, f"CVD slope aggressively negative ({cvd_slope:.2f}) conflicts with LONG")
    if ctx.agent_direction == "SHORT" and cvd_slope > cvd_block_pos:
        return GateResult(3, False, f"CVD slope aggressively positive ({cvd_slope:.2f}) conflicts with SHORT")
    return None


def _check_setup_paths(ctx: DecisionContext, cvd_slope: float) -> GateResult | None:
    """Check each setup path (evidence, Triple-A, drive, LVN, initiative)."""
    if getattr(ctx, "setup_evidence", None) is not None:
        ev = ctx.setup_evidence
        if ev.is_complete():
            if ev.direction and ev.direction != ctx.agent_direction:
                return GateResult(3, False, f"Evidence direction {ev.direction} conflicts with trade direction {ctx.agent_direction}")
            return GateResult(3, True, f"{ev.setup_type} confirmed")
    phase = getattr(ctx, "triple_a_phase", "") or ""
    tsignal = getattr(ctx, "triple_a_signal", "") or ""
    if phase == "AGGRESSION" and tsignal == ctx.agent_direction:
        if not getattr(ctx, "allow_trend", True):
            # ponytail: gate-1 owns evidence-gated paths; here we catch the evidence-free ones
            return GateResult(3, False, "Trend continuation blocked in reversion-only phase")
        return GateResult(3, True, f"Triple-A AGGRESSION {tsignal}")
    if ctx.drive_entry_valid:
        return GateResult(3, True, "Second Drive reclaim confirmed")
    leg_lvn = getattr(ctx, "leg_lvn", 0.0) or 0.0
    if leg_lvn > 0 and ctx.bar:
        tick = ctx.tick_size if ctx.tick_size and ctx.tick_size > 0 else 0.05
        price = float(ctx.bar.close)
        if abs(price - leg_lvn) <= 2.0 * tick:
            # Canonical absorption mapping (SELL_ABSORBED->LONG, BUY_ABSORBED->SHORT).
            # Opposing sides are already vetoed in _check_guards.
            absorbed = canonical_absorption_direction(ctx.absorption_side)
            if absorbed == "LONG" and ctx.agent_direction == "LONG" and cvd_slope >= -0.2:
                if not getattr(ctx, "allow_trend", True):
                    return GateResult(3, False, "Trend continuation blocked in reversion-only phase")
                return GateResult(3, True, f"LVN Sniper LONG @ {leg_lvn:.2f}")
            if absorbed == "SHORT" and ctx.agent_direction == "SHORT" and cvd_slope <= 0.2:
                if not getattr(ctx, "allow_trend", True):
                    return GateResult(3, False, "Trend continuation blocked in reversion-only phase")
                return GateResult(3, True, f"LVN Sniper SHORT @ {leg_lvn:.2f}")
    break_dir = getattr(ctx, "break_direction", "") or ""
    break_type = getattr(ctx, "break_type", "") or ""
    if break_type == "INITIATIVE":
        if break_dir == "UP" and ctx.agent_direction == "LONG" and cvd_slope > -0.2:
            if not getattr(ctx, "allow_trend", True):
                return GateResult(3, False, "Trend continuation blocked in reversion-only phase")
            return GateResult(3, True, "Initiative upside breakout confirmed")
        if break_dir == "DOWN" and ctx.agent_direction == "SHORT" and cvd_slope < 0.2:
            if not getattr(ctx, "allow_trend", True):
                return GateResult(3, False, "Trend continuation blocked in reversion-only phase")
            return GateResult(3, True, "Initiative downside breakdown confirmed")
    # Fabio Playbook #4: trapped-volume squeeze -> enter on first retest of trapped level
    sq_dir = getattr(ctx, "squeeze_direction", "") or ""
    if sq_dir and ctx.agent_direction == sq_dir:
        trapped = float(getattr(ctx, "squeeze_trapped_level", 0.0) or 0.0)
        tick = (ctx.tick_size if ctx.tick_size and ctx.tick_size > 0 else 0.05)
        retested = ctx.bar and trapped > 0 and abs(float(ctx.bar.close) - trapped) <= 3.0 * tick
        if retested or getattr(ctx, "pullback_confirmed", False):
            if ctx.agent_direction == "LONG" and cvd_slope >= -0.1:
                if not getattr(ctx, "allow_trend", True):
                    return GateResult(3, False, "Trend continuation blocked in reversion-only phase")
                return GateResult(3, True, f"Squeeze {sq_dir} retest @{trapped:.2f}")
            if ctx.agent_direction == "SHORT" and cvd_slope <= 0.1:
                if not getattr(ctx, "allow_trend", True):
                    return GateResult(3, False, "Trend continuation blocked in reversion-only phase")
                return GateResult(3, True, f"Squeeze {sq_dir} retest @{trapped:.2f}")
    return None


def gate_triple_a_edge(ctx: DecisionContext) -> GateResult:
    """Gate 3: Triple-A edge — the institutional entry trigger (Fabio Valentini).

    Three valid canonical paths: Triple-A AGGRESSION, IB Second Drive, LVN Sniper.
    Guards: volume bubble, contested zone, anti-climax, drive exhaustion, CVD direction.
    """
    r = _check_guards(ctx)
    if r: return r
    r = _check_setup_paths(ctx, ctx.cvd_slope)
    if r: return r
    return GateResult(3, False, "No Triple-A edge: no valid setup")
