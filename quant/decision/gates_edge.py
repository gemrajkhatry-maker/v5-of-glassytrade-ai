"""Gate 3 — the Triple-A edge (Fabio: absorption -> accumulation -> aggression)."""

from quant.amt.orderflow.aggression import canonical_absorption_direction, AggressionScorer
from quant.contracts.enums import MarketState

from quant.decision.context import DecisionContext
from quant.decision.result import GateResult

# _ABSORPTION_MAX_AGE_BARS: fresh absorption window (bars); the absorption must
# be recent enough to back the breakout — older footprints are re-tested, not
# traded through. Imported from quant.contracts.constants.

# _OBI_AGGRESSION_THRESHOLD: depth-derived order-flow aggression (Fabio's A3);
# |OBI| above this threshold with the price beyond the matching VWAP band is
# an aggression confirmation. Imported from quant.contracts.constants.

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


def rescore_aggression_with_direction(ctx: DecisionContext) -> float:
    """Re-compute aggression score with the resolved strategy candidate direction.

    The AMT engine computes raw aggression components WITHOUT direction gating
    (since it runs before the strategy direction is resolved). This function
    applies the direction gating using the resolved agent_direction from the
    DecisionContext, ensuring the aggression score reflects the actual trade
    direction, not the observed bar delta.

    Returns the direction-gated aggression score (0.0 to 4.5).
    """
    components = getattr(ctx, "aggression_components", None)
    if not components:
        return 0.0

    direction = str(getattr(ctx, "agent_direction", "") or "").upper()
    if direction not in ("LONG", "SHORT"):
        return 0.0

    cvd_state = getattr(ctx, "cvd_state", None)
    cvd_slope = (
        cvd_state.slope if hasattr(cvd_state, "slope")
        else (cvd_state.get("slope") if isinstance(cvd_state, dict) else None)
    ) if cvd_state else None
    ofi_result = getattr(ctx, "ofi_result", None)
    ofi = (
        ofi_result.ofi if hasattr(ofi_result, "ofi")
        else (ofi_result.get("ofi") if isinstance(ofi_result, dict) else None)
    ) if ofi_result else None
    norm_delta = getattr(ctx, "norm_delta", None)
    absorption_side = getattr(ctx, "absorption_side", "")

    scorer = AggressionScorer()
    result = scorer.score(
        footprint_confirmed=components.get("footprint_confirmed", False),
        cvd_confirmed=components.get("cvd_confirmed", False),
        big_trade_confirmed=components.get("big_trade_confirmed", False),
        absorption_detected=components.get("absorption_detected", False),
        ofi_aligned=components.get("ofi_aligned", False),
        confluence_bonus=components.get("confluence_bonus", False),
        volume_bubble_near=components.get("volume_bubble_near", False),
        direction=direction,
        cvd_slope=cvd_slope,
        ofi=ofi,
        norm_delta=norm_delta,
        absorption_side=absorption_side,
    )
    return result.score


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
    # vwap_std is σ in PRICE units; report true σ-multiples for the veto reason.
    sigma_mult = 0.0
    if ctx.vwap_std and ctx.vwap_std > 0 and ctx.session_vwap > 0:
        sigma_mult = abs(close_px - ctx.session_vwap) / ctx.vwap_std
    if ctx.agent_direction == "LONG" and ctx.vwap_upper_2 > 0 and close_px > ctx.vwap_upper_2:
        return GateResult(3, False, f"Anti-Climax: LONG rejected at +{sigma_mult:.1f}σ extension")
    if ctx.agent_direction == "SHORT" and ctx.vwap_lower_2 > 0 and close_px < ctx.vwap_lower_2:
        return GateResult(3, False, f"Anti-Climax: SHORT rejected at -{sigma_mult:.1f}σ extension")
    acceptance = _candle_acceptance(ctx)
    if acceptance:
        return acceptance
    if getattr(ctx, "drive_number", 0) >= 3 and not getattr(ctx, "drive_entry_valid", False):
        return GateResult(3, False, f"Drive count exhausted ({ctx.drive_number})")
    cvd_slope = ctx.cvd_slope
    market = getattr(ctx, "market", "NSE")
    # Doc: NSE tighter (−0.3), MCX looser (−0.5) — was inverted.
    cvd_block_neg = -0.5 if str(market).upper() == "MCX" else -0.3
    cvd_block_pos = 0.5 if str(market).upper() == "MCX" else 0.3
    # Lagging persisted CVD must not alone veto when this bar's fresh delta
    # agrees with the trade direction (absorption→breakout sign-freeze).
    fresh_delta = float(getattr(ctx, "norm_delta", 0.0) or 0.0)
    if (
        ctx.agent_direction == "LONG"
        and cvd_slope < cvd_block_neg
        and fresh_delta <= 0
    ):
        return GateResult(3, False, f"CVD slope aggressively negative ({cvd_slope:.2f}) conflicts with LONG")
    if (
        ctx.agent_direction == "SHORT"
        and cvd_slope > cvd_block_pos
        and fresh_delta >= 0
    ):
        return GateResult(3, False, f"CVD slope aggressively positive ({cvd_slope:.2f}) conflicts with SHORT")

    # CVD divergence direction alignment — divergence must confirm the trade direction
    cvd_divergence = getattr(ctx, "cvd_divergence", "")
    if cvd_divergence:
        if ctx.agent_direction == "LONG" and cvd_divergence != "BULLISH_DIV":
            return GateResult(3, False, f"CVD divergence {cvd_divergence} conflicts with LONG")
        if ctx.agent_direction == "SHORT" and cvd_divergence != "BEARISH_DIV":
            return GateResult(3, False, f"CVD divergence {cvd_divergence} conflicts with SHORT")

    return None


def _pass(reason: str, setup_key: str = "") -> GateResult:
    """A passing Gate-3 result tagged with the setup that fired (model router)."""
    return GateResult(3, True, reason, setup_key=setup_key)


def _check_setup_paths(ctx: DecisionContext, cvd_slope: float) -> GateResult | None:
    """Check each setup path (evidence, Triple-A, drive, LVN, initiative).

    When setup_evidence is present, is_complete() is the sole location/LVN/
    breakout certificate — this gate only applies phase permissions.
    """
    price = float(ctx.bar.close) if ctx.bar else 0.0
    tick = ctx.tick_size if ctx.tick_size and ctx.tick_size > 0 else 0.05
    vwap = getattr(ctx, "session_vwap", 0.0) or (float(ctx.bar.vwap) if ctx.bar and getattr(ctx.bar, "vwap", 0.0) else 0.0)

    if getattr(ctx, "setup_evidence", None) is not None:
        ev = ctx.setup_evidence
        if not ev.is_complete():
            return GateResult(3, False, ev.rejection_reason() or "Incomplete setup evidence")
        if ev.direction and ev.direction != ctx.agent_direction:
            return GateResult(3, False, f"Evidence direction {ev.direction} conflicts with trade direction {ctx.agent_direction}")

        stype = str(ev.setup_type or "").upper()
        if stype in ("TRIPLE_A", "LVN_SNIPER") and not getattr(ctx, "allow_trend", True):
            return GateResult(3, False, "Trend continuation blocked in reversion-only phase")
        if stype in ("VA_FADE", "SECOND_DRIVE") and not getattr(ctx, "allow_reversion", True):
            return GateResult(3, False, "Mean-reversion blocked in trend-only phase")
        return _pass(f"{ev.setup_type} confirmed", stype)

    phase = getattr(ctx, "triple_a_phase", "") or ""
    tsignal = getattr(ctx, "triple_a_signal", "") or ""
    if phase == "AGGRESSION" and tsignal == ctx.agent_direction:
        if not getattr(ctx, "allow_trend", True):
            # ponytail: gate-1 owns evidence-gated paths; here we catch the evidence-free ones
            return GateResult(3, False, "Trend continuation blocked in reversion-only phase")
        # Spec §5.2 Layer 2: compression box breakout confirmation. When a
        # micro-balance range has formed (compression box detected), require
        # the breakout close to exceed the micro-VAH (LONG) or micro-VAL
        # (SHORT). This confirms a true out-of-balance condition — a close
        # inside the box is range rotation, not a tradable breakout.
        cb_bars = getattr(ctx, "compression_box_bars", 0) or 0
        if cb_bars >= 3:
            cb_vah = getattr(ctx, "compression_box_vah", 0.0) or 0.0
            cb_val = getattr(ctx, "compression_box_val", 0.0) or 0.0
            if ctx.agent_direction == "LONG" and cb_vah > 0 and price <= cb_vah:
                return GateResult(
                    3, False,
                    f"Triple-A LONG blocked: close {price:.2f} did not break "
                    f"compression box VAH {cb_vah:.2f} (bars={cb_bars})",
                )
            if ctx.agent_direction == "SHORT" and cb_val > 0 and price >= cb_val:
                return GateResult(
                    3, False,
                    f"Triple-A SHORT blocked: close {price:.2f} did not break "
                    f"compression box VAL {cb_val:.2f} (bars={cb_bars})",
                )
        # Fabio VWAP Bias: Trend continuation requires price on the correct side of session VWAP
        vwap = getattr(ctx, "session_vwap", 0.0) or (float(ctx.bar.vwap) if ctx.bar and getattr(ctx.bar, "vwap", 0.0) else 0.0)
        if vwap > 0:
            if ctx.agent_direction == "LONG" and price < vwap - 1.0 * tick:
                return GateResult(3, False, f"Triple-A LONG below session VWAP ({price:.2f} < {vwap:.2f}) violates auction bias")
            if ctx.agent_direction == "SHORT" and price > vwap + 1.0 * tick:
                return GateResult(3, False, f"Triple-A SHORT above session VWAP ({price:.2f} > {vwap:.2f}) violates auction bias")
        return _pass(f"Triple-A AGGRESSION {tsignal}", "TRIPLE_A")
    if ctx.drive_entry_valid:
        return _pass("Second Drive reclaim confirmed", "SECOND_DRIVE")
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
                return _pass(f"LVN Sniper LONG @ {leg_lvn:.2f}", "LVN_SNIPER")
            if absorbed == "SHORT" and ctx.agent_direction == "SHORT" and cvd_slope <= 0.2:
                if not getattr(ctx, "allow_trend", True):
                    return GateResult(3, False, "Trend continuation blocked in reversion-only phase")
                return _pass(f"LVN Sniper SHORT @ {leg_lvn:.2f}", "LVN_SNIPER")
    break_dir = getattr(ctx, "break_direction", "") or ""
    break_type = getattr(ctx, "break_type", "") or ""
    if break_type == "INITIATIVE":
        vwap = getattr(ctx, "session_vwap", 0.0) or (float(ctx.bar.vwap) if ctx.bar and getattr(ctx.bar, "vwap", 0.0) else 0.0)
        price = float(ctx.bar.close) if ctx.bar else 0.0
        tick = ctx.tick_size if ctx.tick_size and ctx.tick_size > 0 else 0.05
        fresh_delta = float(getattr(ctx, "norm_delta", 0.0) or 0.0)
        # CVD slope may lag through absorption→breakout; fresh bar delta can
        # confirm the initiative when persisted slope has not yet flipped.
        cvd_ok_long = cvd_slope > -0.2 or fresh_delta > 0.5
        cvd_ok_short = cvd_slope < 0.2 or fresh_delta < -0.5
        if break_dir == "UP" and ctx.agent_direction == "LONG" and cvd_ok_long:
            if not getattr(ctx, "allow_trend", True):
                return GateResult(3, False, "Trend continuation blocked in reversion-only phase")
            if vwap > 0 and price < vwap - 1.0 * tick:
                return GateResult(3, False, f"Initiative upside breakout below session VWAP ({price:.2f} < {vwap:.2f})")
            return _pass("Initiative upside breakout confirmed", "INITIATIVE")
        if break_dir == "DOWN" and ctx.agent_direction == "SHORT" and cvd_ok_short:
            if not getattr(ctx, "allow_trend", True):
                return GateResult(3, False, "Trend continuation blocked in reversion-only phase")
            if vwap > 0 and price > vwap + 1.0 * tick:
                return GateResult(3, False, f"Initiative downside breakdown above session VWAP ({price:.2f} > {vwap:.2f})")
            return _pass("Initiative downside breakdown confirmed", "INITIATIVE")
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
                return _pass(f"Squeeze {sq_dir} retest @{trapped:.2f}", "SQUEEZE")
            if ctx.agent_direction == "SHORT" and cvd_slope <= 0.1:
                if not getattr(ctx, "allow_trend", True):
                    return GateResult(3, False, "Trend continuation blocked in reversion-only phase")
                return _pass(f"Squeeze {sq_dir} retest @{trapped:.2f}", "SQUEEZE")
    return None


def gate_triple_a_edge(ctx: DecisionContext) -> GateResult:
    """Gate 3: Triple-A edge — the institutional entry trigger (Fabio Valentini).

    Three valid canonical paths: Triple-A AGGRESSION, IB Second Drive, LVN Sniper.
    Guards: volume bubble, contested zone, anti-climax, drive exhaustion, CVD direction.

    The aggression score is re-computed with the resolved strategy candidate
    direction (agent_direction) to ensure it reflects the actual trade direction,
    not the observed bar delta.
    """
    # Re-score aggression with the resolved strategy direction.
    # This ensures the aggression score reflects the actual candidate trade
    # direction, not the observed bar delta (which the AMT engine uses
    # since it runs before the strategy direction is resolved).
    rescore_aggression_with_direction(ctx)

    r = _check_guards(ctx)
    if r:
        return r
    r = _check_setup_paths(ctx, ctx.cvd_slope)
    if r:
        return r
    return GateResult(3, False, "No Triple-A edge: no valid setup")
