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
        self._timesfm_risk = None
        self.last_exit_source: str = ""

    def pop_trail(self, position: Position) -> None:
        """Drop trailing/tier state for a closed position."""
        self._trail.pop(position._id, None)
        self._breakeven.pop(position._id, None)
        self._tp_tier.pop(position._id, None)
        if getattr(self, "_timesfm_risk", None) is not None:
            self._timesfm_risk.clear_position(position._id)

    def stop_state(self, position: Position) -> tuple[float | None, float | None]:
        """Current (breakeven_floor, trail_stop) for a position.

        Returns the BE floor price if armed (else None), and the active trailing
        stop price if one exists (else None). Used by callers to detect stop
        moves so every change can be audited via StopMoved events.
        """
        tr = self._trail.get(position._id)
        return self._breakeven.get(position._id), (tr.stop if tr and tr.active else None)

    def is_risk_free(self, position: Position) -> bool:
        """Return True when this position has reached the 0.8R breakeven floor.

        Used by the pyramid engine to authorize add-ons: per spec §13.2 the
        base trade must be risk-free (SL at entry or better) before any
        pyramid entry is permitted.
        """
        be_floor = self._breakeven.get(position._id)
        return be_floor is not None

    def session_budget_multiplier(self) -> float:
        if self._timesfm_risk is None:
            return 1.0
        return self._timesfm_risk.get_session_budget_multiplier()

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
        timesfm_forecast: object | None = None,
    ) -> ExitDecision:
        from quant.execution.exit_checks import (
            check_spread_blowout, check_stop_loss, check_cvd_kill,
            check_take_profit_tiers, check_trailing_stop, check_time_stop,
        )

        self.last_exit_source = ""
        if bar_close is not None:
            close = float(bar_close)
        elif isinstance(state, (int, float)):
            close = float(state)
            state = None
        else:
            close = 0.0

        dto = amt_dto or (state if isinstance(state, dict) else {})
        if market_state == MarketState.DEAD:
            self.last_exit_source = "DETERMINISTIC:DEAD_MARKET"
            return ExitDecision(True, "DEAD_MARKET", close)

        long = position.size > 0
        sl = float(position.order.signal.sl)
        entry = float(position.order.signal.entry)
        low = close if bar_low is None else bar_low
        high = close if bar_high is None else bar_high
        risk = abs(entry - sl)

        # Rule 1: Spread blowout
        r = check_spread_blowout(position, close, best_bid, best_ask, is_expiry, self.spread_max_pct)
        if r:
            self.last_exit_source = f"DETERMINISTIC:{r.reason}"
            return r

        # TimesFM Dynamic Risk & Monotonic Quantile Trailing Stop Evaluation
        if timesfm_forecast is not None:
            try:
                if self._timesfm_risk is None:
                    from quant.decision.timesfm_risk import TimesFMRiskAuthority
                    self._timesfm_risk = TimesFMRiskAuthority()

                side = "LONG" if long else "SHORT"
                tr = self._trail.get(position._id)
                current_active_sl = tr.stop if (tr and tr.active and tr.stop is not None) else sl

                eval_res = self._timesfm_risk.evaluate_exit(
                    position_id=position._id,
                    side=side,
                    entry=entry,
                    current_price=close,
                    bars_held=bar_index,
                    forecast=timesfm_forecast,
                    active_sl=current_active_sl,
                )

                # Monotonic quantile ratchet
                if eval_res.new_stop is not None:
                    if tr is None:
                        tr = _Trail()
                        self._trail[position._id] = tr
                    tr.active = True
                    tr.stop = eval_res.new_stop
                    if eval_res.is_risk_free:
                        self._breakeven[position._id] = eval_res.new_stop

                if eval_res.should_exit:
                    self.last_exit_source = f"TIMESFM_RISK_AUTHORITY:{eval_res.reason or eval_res.action}"
                    return ExitDecision(True, eval_res.reason, close, trail_stop=eval_res.new_stop)
            except Exception as exc:
                # Graceful fallback to deterministic exit rules on error
                pass

        # Rule 2: Stop-loss
        r = check_stop_loss(position, low, high)
        if r:
            self.last_exit_source = f"DETERMINISTIC:{r.reason}"
            return r

        # Rule 3: CVD kill
        r = check_cvd_kill(position, dto, self.cvd_kill_threshold)
        if r:
            self.last_exit_source = f"DETERMINISTIC:{r.reason}"
            return ExitDecision(True, r.reason, close)

        # Rule 4: Take-profit tiers
        tier = self._tp_tier.get(position._id, 0)
        r, new_tier = check_take_profit_tiers(position, high, low, tier, entry)
        if r:
            self._tp_tier[position._id] = new_tier
            if r.reason == "TP1":
                self._breakeven[position._id] = entry
            self.last_exit_source = f"DETERMINISTIC:{r.reason}"
            return r
        self._tp_tier[position._id] = new_tier

        # Rule 4b: Trailing stop + breakeven
        be_floor = self._breakeven.get(position._id)
        tr = self._trail.get(position._id)
        trail_stop = tr.stop if tr else None
        if risk > 0:
            r, be_floor, trail_stop = check_trailing_stop(
                position, close, low, high, sl, entry, risk, dto,
                session_vwap, self.trail_giveback_pct, self.vwap_adverse_drift_pct,
                self.cvd_be_threshold, be_floor, trail_stop,
            )
            if be_floor is not None:
                self._breakeven[position._id] = be_floor
            if trail_stop is not None:
                if tr is None:
                    tr = _Trail()
                    self._trail[position._id] = tr
                tr.active = True
                tr.stop = trail_stop
            if r:
                self.last_exit_source = f"DETERMINISTIC:{r.reason}"
                return r

        # Rule 5: Time stop
        r = check_time_stop(
            bar_index, self.time_stop_bars, session_phase, time_to_close,
            now_epoch, entry_time_epoch, market_state, is_expiry,
        )
        if r:
            self.last_exit_source = f"DETERMINISTIC:{r.reason}"
            return ExitDecision(True, r.reason, close)

        return ExitDecision(False, "", close)
