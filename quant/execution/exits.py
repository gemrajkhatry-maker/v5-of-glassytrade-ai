"""Rule-based exit engine: spread blowout, SL, TP, CVD-kill, trailing, and time-stop.

Pure and deterministic. No imports from backend/ or app/.
"""

from __future__ import annotations
import logging

from quant.contracts.enums import MarketState

from dataclasses import dataclass


from quant.execution.exit_rules import get_session_time_stop
from quant.execution.order import Position

logger = logging.getLogger(__name__)

# Model-risk failures observed since process start. The TimesFM exit authority
# is allowed to degrade to deterministic rules, but it must never do so
# silently: a degraded session has to be distinguishable from a healthy one.
MODEL_RISK_FAILURES = 0

# TimesFM *entry sizing* failures observed since process start (Finding 1 of
# the D-12 review). Distinct from MODEL_RISK_FAILURES (exit-side degradation):
# a sizing failure refuses the entry, so it must be visible to operators
# instead of looking like a genuine risk-budget-zero rejection.
MODEL_SIZING_FAILURES = 0


@dataclass(frozen=True)
class ExitDecision:
    should_exit: bool
    reason: str          # "" | "SL" | "TP1" | "TP2" | "TRAIL" | "TIME" | "CVD_KILL" | "SPREAD_BLOWOUT" | "BREAKEVEN"
    close_price: float
    trail_stop: float | None = None
    # Fraction of the CURRENT position size to close. None (or 1.0) means a
    # full close. < 1.0 means a tiered take-profit partial (spec §13.3).
    partial_fraction: float | None = None
    # Applied by PositionManager only AFTER a successful OMS fill so a failed
    # close cannot burn the tier / arm BE on an unfilled order.
    pending_tp_tier: int | None = None
    pending_breakeven: float | None = None


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

    def is_risk_free(self, position: Position, mark: float | None = None) -> bool:
        """True when BE is armed AND the mark is at or better than the fill.

        Spec §13.2: pyramiding requires the base trade to be risk-free. A
        CVD-armed BE floor on a still-losing mark does not qualify.
        """
        be_floor = self._breakeven.get(position._id)
        if be_floor is None:
            return False
        fill = float(getattr(position, "open_price", 0) or 0)
        if fill <= 0:
            fill = float(position.order.signal.entry) if position.order and position.order.signal else 0.0
        if fill <= 0:
            return False
        long = position.size > 0
        # Protective floor must itself be at/better than fill.
        if long and float(be_floor) < fill - 1e-9:
            return False
        if (not long) and float(be_floor) > fill + 1e-9:
            return False
        px = float(mark) if mark is not None else fill
        if long:
            return px >= fill - 1e-9
        return px <= fill + 1e-9

    def evaluate_price_event(
        self,
        position: Position,
        *,
        last: float,
        high: float,
        low: float,
        source: str = "tick",
        amt_dto: dict | None = None,
        **kwargs,
    ):
        """Canonical exit evaluation for tick or bar — same prices, same reason."""
        return self.evaluate(
            position,
            bar_close=last,
            bar_high=high,
            bar_low=low,
            amt_dto=amt_dto,
            **kwargs,
        )

    def apply_pending_tp(self, position: Position, decision: ExitDecision) -> None:
        """Commit TP tier / BE only after a successful OMS fill."""
        if decision.pending_tp_tier is not None:
            self._tp_tier[position._id] = int(decision.pending_tp_tier)
        if decision.pending_breakeven is not None:
            self._breakeven[position._id] = float(decision.pending_breakeven)

    def restore_stop_state(
        self,
        position: Position,
        *,
        breakeven: float | None = None,
        trail_stop: float | None = None,
        tp_tier: int = 0,
    ) -> None:
        """Rehydrate ExitEngine stop state after process restart."""
        if breakeven is not None and float(breakeven) > 0:
            self._breakeven[position._id] = float(breakeven)
        if trail_stop is not None and float(trail_stop) > 0:
            tr = _Trail(active=True, stop=float(trail_stop))
            self._trail[position._id] = tr
        if tp_tier:
            self._tp_tier[position._id] = int(tp_tier)

    def session_budget_multiplier(self) -> float:
        if self._timesfm_risk is None:
            return 1.0
        return self._timesfm_risk.get_session_budget_multiplier()

    @property
    def model_risk_failures(self) -> int:
        """Count of model-risk-authority failures seen this process."""
        return MODEL_RISK_FAILURES

    def evaluate(
        self,
        position: Position,
        state: dict | float | None = None,
        bar_index: int = 0,
        bar_high: float | None = None,
        bar_low: float | None = None,
        *,
        amt_dto: dict | None = None,
        snapshot=None,
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
        global MODEL_RISK_FAILURES
        from quant.execution.exit_checks import (
            check_spread_blowout, check_cvd_kill,
            check_stacked_imbalance_tighten, check_take_profit_tiers,
            check_trailing_stop, check_time_stop,
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
        if str(getattr(market_state, "value", market_state)).upper() == "CHOP":
            self.last_exit_source = "DETERMINISTIC:CHOP_MARKET"
            return ExitDecision(True, "CHOP_MARKET", close)
        long = position.size > 0
        side = "LONG" if long else "SHORT"
        sl = float(position.order.signal.sl)
        # BE / R / risk-free use the actual fill, not the signal quote.
        fill = float(getattr(position, "open_price", 0) or 0)
        entry = fill if fill > 0 else float(position.order.signal.entry)
        low = close if bar_low is None else bar_low
        high = close if bar_high is None else bar_high
        risk = abs(entry - sl)

        # Rule 1: Spread blowout
        r = check_spread_blowout(position, close, best_bid, best_ask, is_expiry, self.spread_max_pct)
        if r:
            self.last_exit_source = f"DETERMINISTIC:{r.reason}"
            return r

        # TimesFM is advisory only — never write stop state or force exits
        # from forecasts (Wave 6). Forecasts may still be inspected for UI
        # elsewhere; the bar path stays deterministic.

        # Rule 2: protective stop — the TIGHTEST of raw SL, breakeven floor and
        # active trail. The bar path previously checked the raw frozen SL first,
        # so a bar sweeping both the SL and the trail booked SL at the worse
        # price while the identical tick breach booked TRAIL. One resolver, one
        # price, one exit_source for the same economic event.
        #
        # PRECEDENCE (pinned by tests/quant/execution/test_exits_trailing.py:
        # test_protective_stop_wins_when_one_bar_satisfies_both):
        # when a single bar's range satisfies BOTH this protective stop and a TP
        # tier (Rule 4), the PROTECTIVE STOP wins. This matches the tick path
        # (PositionManager.manage_tick_exit checks the merged stop before the
        # tier targets). A bar that reaches TP without breaching the protective
        # stop still books the TP tier — the reorder does not suppress TPs.
        be_floor = self._breakeven.get(position._id)
        tr = self._trail.get(position._id)
        trail_stop = tr.stop if (tr and tr.active) else None
        from quant.execution.protective_stop import resolve_protective_stop
        protective, protective_reason = resolve_protective_stop(
            sl, be_floor, trail_stop, side,
        )

        breached = (long and low <= protective) or (not long and high >= protective)
        if breached and protective_reason != "SL":
            self.last_exit_source = f"DETERMINISTIC:{protective_reason}"
            # trail_stop labels the ACTIVE trailing stop only. A breakeven floor
            # is not a trail, and an SL is the raw frozen stop, so both pass
            # None here (no production consumer reads it for those reasons —
            # the reason string carries the label).
            label = protective if protective_reason == "TRAIL" else None
            return ExitDecision(True, protective_reason, protective, trail_stop=label)
        if breached:
            self.last_exit_source = "DETERMINISTIC:SL"
            return ExitDecision(True, "SL", float(sl))

        # Rule 2b: Opposing stacked imbalance — tighten SL to BE (never exit).
        # Runs AFTER protective stop so a real SL breach still books first.
        si_src = snapshot if snapshot is not None else dto
        if check_stacked_imbalance_tighten(position, si_src):
            self._breakeven[position._id] = entry
            self.last_exit_source = "DETERMINISTIC:STACKED_IMBALANCE_TIGHTEN"

        # Rule 3: CVD kill
        r = check_cvd_kill(position, dto, self.cvd_kill_threshold)
        if r:
            self.last_exit_source = f"DETERMINISTIC:{r.reason}"
            return ExitDecision(True, r.reason, close)

        # Rule 4: Take-profit tiers — do NOT mutate tier/BE until OMS succeeds
        # (PositionManager calls apply_pending_tp after a successful fill).
        tier = self._tp_tier.get(position._id, 0)
        r, new_tier = check_take_profit_tiers(position, high, low, tier, entry)
        if r:
            pending_be = entry if r.reason == "TP1" else None
            self.last_exit_source = f"DETERMINISTIC:{r.reason}"
            return ExitDecision(
                True, r.reason, r.close_price,
                partial_fraction=r.partial_fraction,
                pending_tp_tier=new_tier,
                pending_breakeven=pending_be,
            )
        # Advance expected tier cursor only when no exit fired this bar
        # (same as prior behaviour for non-exit path).
        self._tp_tier[position._id] = new_tier

        # Rule 4b: advance the trailing/breakeven stores for the NEXT bar.
        # The breach check for THIS bar already ran above, against the tightest
        # protective level, so this call only ratchets state forward.
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
                elif tr.active and tr.stop is not None:
                    # Single trail authority (D-16). Deterministic advance may
                    # only tighten what is already written, never loosen it.
                    trail_stop = (
                        max(float(trail_stop), float(tr.stop)) if long
                        else min(float(trail_stop), float(tr.stop))
                    )
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
