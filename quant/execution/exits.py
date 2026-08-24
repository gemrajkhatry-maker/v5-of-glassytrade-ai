"""Rule-based exit engine: spread blowout, SL, TP, CVD-kill, trailing, and time-stop.

Pure and deterministic. No imports from backend/ or app/.
"""

from __future__ import annotations
from quant.contracts.enums import MarketState

from dataclasses import dataclass


from quant.execution.exit_rules import get_session_time_stop
from quant.execution.order import Position


@dataclass(frozen=True)
class ExitDecision:
    should_exit: bool
    reason: str          # "" | "SL" | "TP1" | "TP2" | "TRAIL" | "TIME" | "CVD_KILL" | "SPREAD_BLOWOUT" | "BREAKEVEN"
    close_price: float
    trail_stop: float | None = None
    # Fraction of the CURRENT position size to close. None (or 1.0) means a
    # full close. < 1.0 means a tiered take-profit partial (spec §13.3).
    partial_fraction: float | None = None


@dataclass
class _Trail:
    active: bool = False
    stop: float | None = None


class ExitEngine:
    """Rule-based exit engine.

    CVD_KILL semantics: a kill fires only when the cvd slope crosses the
    adverse side of a NEGATIVE threshold, i.e. LONG exits when
    ``cvd_slope < -threshold`` and SHORT exits when ``cvd_slope > threshold``.
    A positive threshold therefore never kills on a favorable-side slope.
    Default ``cvd_kill_threshold=float("inf")`` disables CVD_KILL entirely
    unless it is explicitly enabled (threshold=0.0 would kill on ANY adverse
    slope, which is too twitchy for noise).
    """

    def __init__(
        self,
        time_stop_bars: int = 30,
        cvd_kill_threshold: float = float("inf"),
        trail_giveback_pct: float = 0.20,
        spread_max_pct: float = 0.03,
        cvd_be_threshold: float = 2.0,
        vwap_adverse_drift_pct: float = 0.03,
    ) -> None:
        self.time_stop_bars = time_stop_bars
        self.cvd_kill_threshold = cvd_kill_threshold
        self.trail_giveback_pct = trail_giveback_pct
        self.spread_max_pct = spread_max_pct
        self.cvd_be_threshold = cvd_be_threshold
        # VWAP adverse drift threshold: when a LONG position trades this
        # fraction below session VWAP (or SHORT above), tighten trailing
        # aggressively.  3% is the default — Fabio's rule: if price drifts
        # more than 1 VA-width from VWAP without a structural reason, the
        # thesis is weakened.
        self.vwap_adverse_drift_pct = vwap_adverse_drift_pct
        # Trailing state is keyed by position._id (UUID) to prevent GC-recycling hazards.
        self._trail: dict[str, _Trail] = {}
        self._breakeven: dict[str, float | None] = {}  # position._id -> BE floor price
        # TP tier reached so far: 0=none, 1=TP1 fired, 2=TP2 fired (runner active).
        # close_partial() preserves position._id across partial fills, so this
        # survives the TP1 -> TP2 transition on the same underlying trade.
        self._tp_tier: dict[str, int] = {}

    def pop_trail(self, position: Position) -> None:
        """Drop trailing/tier state for a closed position."""
        self._trail.pop(position._id, None)
        self._breakeven.pop(position._id, None)
        self._tp_tier.pop(position._id, None)

    def is_risk_free(self, position: Position) -> bool:
        """Return True when this position has reached the 0.8R breakeven floor.

        Used by the pyramid engine to authorize add-ons: per spec §13.2 the
        base trade must be risk-free (SL at entry or better) before any
        pyramid entry is permitted.
        """
        be_floor = self._breakeven.get(position._id)
        return be_floor is not None

    def evaluate(
        self,
        position: Position,
        state: dict | float | None = None,
        bar_index: int = 0,
        bar_high: float | None = None,
        bar_low: float | None = None,
        *,
        amt_dto: dict | None = None,
        best_bid: float | None = None,
        best_ask: float | None = None,
        market_state: MarketState = MarketState.BALANCED,
        session_phase: str = "",
        is_expiry: bool = False,
        time_to_close: float = 0.0,
        entry_time_epoch: float = 0.0,
        now_epoch: float = 0.0,
        bar_close: float | None = None,
        session_vwap: float = 0.0,
    ) -> ExitDecision:
        if bar_close is not None:
            close = float(bar_close)
        elif isinstance(state, (int, float)):
            close = float(state)
            state = None
        else:
            close = 0.0

        dto = amt_dto or (state if isinstance(state, dict) else {})
        if market_state == MarketState.DEAD:
            return ExitDecision(True, "DEAD_MARKET", close)
        long = position.size > 0
        sl = float(position.order.signal.sl)
        tp = float(position.order.signal.tp)
        low = close if bar_low is None else bar_low
        high = close if bar_high is None else bar_high

        # 1. Spread blowout — the book is untradeable, get out at mid.
        # On expiry day, allowable spread is halved (e.g. 1.5% instead of 3.0%).
        effective_spread_pct = (self.spread_max_pct * 0.5) if is_expiry else self.spread_max_pct
        if (
            best_bid is not None
            and best_ask is not None
            and close > 0
            and (best_ask - best_bid) / close >= effective_spread_pct
        ):
            return ExitDecision(True, "SPREAD_BLOWOUT", (best_bid + best_ask) / 2)

        # 2. Hard stop-loss (fills at SL or worse if gapped)
        if long and low <= sl:
            return ExitDecision(True, "SL", sl)
        if not long and high >= sl:
            return ExitDecision(True, "SL", sl)

        # 3. Auction thesis invalidation (CVD kill)
        slope = float(dto.get("cvdSlope") or 0.0)
        if long and slope < -self.cvd_kill_threshold:
            return ExitDecision(True, "CVD_KILL", close)
        if not long and slope > self.cvd_kill_threshold:
            return ExitDecision(True, "CVD_KILL", close)

        # 4. Structural target (Take Profit) — tiered per spec §13.3:
        #    TP1 = 50% of position at the structural target (`tp`); arms
        #         breakeven immediately (SL -> entry) on the runner.
        #    TP2 = 25% at 2x the TP1 R-multiple, leaving a 25% runner that
        #         the trailing-stop logic below manages.
        #    ponytail: spec's TP2 trigger is "macro VA extreme / CVD
        #    divergence" — approximated here as 2x the TP1 distance since
        #    that detector isn't wired into ExitEngine. Upgrade path: pass
        #    macro VA extreme through `amt_dto` and trigger on that instead.
        entry = float(position.order.signal.entry)
        tier = self._tp_tier.get(position._id, 0)
        if tier == 0:
            if (long and high >= tp) or (not long and low <= tp):
                self._tp_tier[position._id] = 1
                self._breakeven[position._id] = entry
                return ExitDecision(True, "TP1", tp, partial_fraction=0.5)
        elif tier == 1:
            r = abs(tp - entry)
            tp2 = entry + 2.0 * r if long else entry - 2.0 * r
            if (long and high >= tp2) or (not long and low <= tp2):
                self._tp_tier[position._id] = 2
                return ExitDecision(True, "TP2", tp2, partial_fraction=0.5)

        # 3b. Breakeven logic — Fabio: move SL to entry at 1R or on CVD confirmation.
        # The breakeven floor ensures the trail can never drop below entry once armed.
        risk = abs(entry - sl)
        be_floor = self._breakeven.get(position._id)

        if risk > 0:
            profit = (close - entry) if long else (entry - close)
            
            # CVD-based early breakeven: if profit > 0 and CVD slope strongly
            # confirms direction, lock in breakeven immediately (Fabio Gap #5).
            cvd_slope = float(dto.get("cvdSlope") or 0.0)
            if be_floor is None and profit > 0:
                cvd_confirms = (
                    (long and cvd_slope > self.cvd_be_threshold)
                    or (not long and cvd_slope < -self.cvd_be_threshold)
                )
                if cvd_confirms:
                    be_floor = entry
                    self._breakeven[position._id] = be_floor
            
            # Standard 0.8R breakeven: once profit reaches 0.8R, floor at entry.
            # Spec §13.1: "Price breaks +0.8R advance → SL ← entry_price instantly."
            # Triggers before full 1R to lock in risk-free status early and enable pyramiding.
            if be_floor is None and profit >= risk * 0.8:
                be_floor = entry
                self._breakeven[position._id] = be_floor

        # 4. Trailing stop — only once the trade has reached 1R profit.
        #    VWAP-adverse-drift: when price drifts beyond the threshold
        #    fraction from session VWAP against the position direction,
        #    tighten trailing to 50% of the normal giveback (Fabio: if
        #    price can't hold above/below VWAP, the thesis is weakened).
        tr = self._trail.get(position._id)
        if risk > 0:
            # Ratchet ONLY at/above 1R; once armed, enforce on every bar so a
            # giveback below 1R can't silently ride back to the original SL.
            if profit >= risk:
                if tr is None:
                    tr = _Trail()
                    self._trail[position._id] = tr
                tr.active = True

                # VWAP-adverse drift detection: tighten trailing when price
                # drifts against position direction beyond the threshold.
                effective_giveback = self.trail_giveback_pct
                if session_vwap > 0 and entry > 0:
                    vwap_drift = abs(close - session_vwap) / entry
                    adverse = (
                        (long and close < session_vwap)
                        or (not long and close > session_vwap)
                    )
                    if adverse and vwap_drift > self.vwap_adverse_drift_pct:
                        # Tighten: 50% of normal giveback — lock profit faster
                        effective_giveback = self.trail_giveback_pct * 0.5

                candidate = (
                    close - effective_giveback * profit
                    if long
                    else close + effective_giveback * profit
                )
                # Never loosen below the original stop-loss.
                candidate = max(candidate, sl) if long else min(candidate, sl)
                
                # Enforce breakeven floor from step 3b
                if be_floor is not None:
                    candidate = max(candidate, be_floor) if long else min(candidate, be_floor)

                if tr.stop is None:
                    tr.stop = candidate
                else:
                    # Monotonicity: long trails only rise, short only fall.
                    tr.stop = max(tr.stop, candidate) if long else min(tr.stop, candidate)

            # 4b. VWAP adverse-drift early exit: when price has drifted
            #     more than 2× the threshold from VWAP against the
            #     position direction AND profit is positive but < 1R,
            #     exit immediately — the thesis is invalidated before
            #     the trailing stop would normally arm.
            if 0 < profit < risk and session_vwap > 0 and entry > 0:
                vwap_drift = abs(close - session_vwap) / entry
                adverse = (
                    (long and close < session_vwap)
                    or (not long and close > session_vwap)
                )
                if adverse and vwap_drift > 2.0 * self.vwap_adverse_drift_pct:
                    return ExitDecision(True, "VWAP_DRIFT", close)
            
            # Check breakeven stop (armed by CVD before 1R)
            if be_floor is not None and tr is None:
                if (long and low <= be_floor) or (not long and high >= be_floor):
                    return ExitDecision(True, "BREAKEVEN", close)

            if tr is not None and tr.stop is not None:
                if (long and low <= tr.stop) or (not long and high >= tr.stop):
                    return ExitDecision(True, "TRAIL", close, trail_stop=tr.stop)

        # 5. Time stop — session-aware when the context is present.
        if session_phase and time_to_close > 0 and now_epoch and entry_time_epoch:
            max_hold = get_session_time_stop(market_state, session_phase, is_expiry, time_to_close)
            if now_epoch - entry_time_epoch >= max_hold:
                return ExitDecision(True, "TIME", close)
        elif bar_index >= self.time_stop_bars:
            return ExitDecision(True, "TIME", close)

        return ExitDecision(False, "", close)
