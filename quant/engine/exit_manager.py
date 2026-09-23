"""ExitManager — bar-driven exits, tick-level fast exits, thesis-flip evaluation.

Extracted from QuantEngine (runtime.py) for maintainability and testability.
Encapsulates the full exit pipeline:

    Bar Exit: manage_exit() -> PositionManager.manage_exit()
              -> partial close (tiered TP) or full close
              -> release partial reserves
              -> book full close (cooldown + portfolio risk release)
              -> thesis flip evaluation (if position survived)

    Tick Exit: manage_tick_exit() -> PositionManager.manage_tick_exit()
               -> release partial reserves
               -> book full close (if fully closed)

    Thesis Flip: check_thesis_flip() -> strategy.should_enter(allow_positioned=True)
                 -> if opposing signal approved -> full close

    Full Close: execute_full_close() -> PositionManager._execute_full_close()
                -> close lingering pyramids
                -> book full close

The ExitManager is stateless with respect to engine mutable state — all
engine state is accessed and mutated through injected callbacks. This makes
it fully testable in isolation without constructing a QuantEngine.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from quant.bars import DEFAULT_INTERVAL_SEC
from quant.contracts.vocabulary import is_call_symbol, is_put_symbol
from quant.decision.context_builder import (
    DecisionContextBuilder,
    build_engine_context,
)
from quant.events import DecisionProduced, Event
from quant.execution.exits import ExitDecision

logger = logging.getLogger(__name__)


def close_lingering_pyramids(
    pm: Any,
    price: float,
    time_str: str,
    reason: str,
) -> int:
    """Close pyramid add-ons whose base position is already gone.

    Routes every add-on through ``PositionManager._execute_full_close`` — the
    ONLY full-close release path — so the exit-source stamp, the
    ``[POSITION CLOSED]`` log, the double-close guard and the portfolio-risk
    release all happen exactly as they do for the base position.

    Add-ons are closed with ``count_as_trade=False``: a pyramid-only flatten
    is bookkeeping on an already-realized round-trip, so it must not consume
    the session's trade budget (``trades_today``) nor move the win/loss
    streaks the consecutive-loss halt is built on.

    Returns the number of add-ons actually closed.
    """
    # Detach the add-ons before closing them: _execute_full_close sweeps
    # ``pm.pyramid_positions`` as part of its own pyramid handling, so leaving
    # the list attached would close each add-on twice.
    lingering = list(pm.pyramid_positions)
    pm.pyramid_positions = []
    closed = 0
    failed: list[object] = []
    for pyr_pos in lingering:
        pos_id = getattr(pyr_pos, "_id", None) or getattr(pyr_pos, "id", None)
        if pos_id is None:
            logger.error(
                "[EOD PYRAMID CLOSE] %s: add-on without an id cannot be closed "
                "through the release path — skipped (type=%s)",
                pm.symbol, type(pyr_pos).__name__,
            )
            failed.append(pyr_pos)
            continue
        try:
            fill = pm._execute_full_close(
                pyr_pos, ExitDecision(True, reason, float(price)), time_str,
                count_as_trade=False,
            )
        except Exception:
            logger.error(
                "[EOD PYRAMID CLOSE] %s: add-on %s failed to close — continuing",
                pm.symbol, str(pos_id)[:8], exc_info=True,
            )
            failed.append(pyr_pos)
            continue
        if fill is None:
            logger.error(
                "[EOD PYRAMID CLOSE] %s: add-on %s refused by the close guard "
                "— it may still be open at the broker; retrying next pass",
                pm.symbol, str(pos_id)[:8],
            )
            failed.append(pyr_pos)
            continue
        closed += 1
        # Because we detached the add-on, _execute_full_close's own E11 sweep
        # did not see it — release its reserved aggregate risk here.
        risk_i = pm._pyramid_open_risk.pop(pos_id, 0.0)
        portfolio_risk = getattr(pm, "_portfolio_risk", None)
        if portfolio_risk is not None:
            portfolio_risk.record_close(risk_i, float(fill.pnl))
    pm.pyramid_positions = failed
    pm.pyramid_count = len(failed)
    return closed


class ExitManager:
    """Encapsulates all exit evaluation and execution logic.

    The exit manager handles:
    - Bar-driven exit evaluation (SL, TP, trail, time stop, session close)
    - Tick-level fast exit (SL/TP breach detection)
    - Thesis flip evaluation (opposing signal exit)
    - Full close execution (base + pyramids)
    - Partial close execution (tiered TP)
    - Double-close guard
    - Portfolio risk reservation/release

    All engine mutable state is accessed through injected callbacks so the
    manager is fully testable in isolation.

    Parameters
    ----------
    config : dict
        Static configuration: symbol, market, contract_expiry, tick_size,
        cooldown_bars.
    deps : dict
        Dependencies: get_position_manager, portfolio_risk, strategy,
        amt_engine, aggregator, get_underlying_symbol, close_lock.
    state : dict
        Mutable state accessors/mutators: get_bar_index, get_entry_bar_index,
        get_entry_time_epoch, get_last_close_bar_index, set_last_close_bar_index,
        get_open_trade_risk, set_open_trade_risk, get_state, set_state,
        get_last_depth, get_recent_decisions, get_underlying_amt_dto,
        set_underlying_amt_dto, get_last_underlying_bar.
    emit : callable
        Function to emit events (Event -> None).
    forecast_fn : callable, optional
        Returns a fresh TimesFM forecast or None.
    advisor : object, optional
        Advisor with an ``on_context`` method for position management notifications.
    """

    def __init__(
        self,
        *,
        # Static configuration
        config: dict[str, Any],
        # Dependencies
        deps: dict[str, Any],
        # Mutable state accessors/mutators
        state: dict[str, Any],
        # Event emission
        emit: Callable[[Event], None],
        # Optional: TimesFM forecast
        forecast_fn: Callable[[], Any] | None = None,
        # Optional: advisor for context notifications
        advisor: Any | None = None,
    ) -> None:
        # --- Static configuration ---
        self._symbol: str = config["symbol"]
        self._market: str = config.get("market", "NSE")
        self._contract_expiry = config.get("contract_expiry")
        self._tick_size: float = config.get("tick_size", 0.05)
        self._cooldown_bars: int = config.get("cooldown_bars", 5)

        # --- Dependencies ---
        self._get_position_manager = deps["get_position_manager"]
        self._get_portfolio_risk = deps.get("get_portfolio_risk", lambda: deps.get("portfolio_risk"))
        self._strategy = deps["strategy"]
        self._amt_engine = deps["amt_engine"]
        self._aggregator = deps["aggregator"]
        self._get_underlying_symbol = deps.get("get_underlying_symbol")
        self._close_lock: threading.Lock = deps.get(
            "close_lock", threading.Lock()
        )
        self._underlying_gateway = deps.get("underlying_gateway")
        self._risk = deps.get("risk")
        self._greeks = deps.get("greeks")

        # --- Mutable state accessors/mutators ---
        self._get_bar_index = state["get_bar_index"]
        self._get_entry_bar_index = state["get_entry_bar_index"]
        self._get_entry_time_epoch = state.get("get_entry_time_epoch", lambda: 0.0)
        self._get_last_close_bar_index = state["get_last_close_bar_index"]
        self._set_last_close_bar_index = state["set_last_close_bar_index"]
        self._get_open_trade_risk = state.get("get_open_trade_risk", lambda: 0.0)
        self._set_open_trade_risk = state.get("set_open_trade_risk", lambda v: None)
        self._get_state = state["get_state"]
        self._set_state = state["set_state"]
        self._get_range_warmup = state.get(
            "get_range_warmup",
            lambda: (False, 0, 0.0),
        )
        self._get_last_depth = state.get("get_last_depth", lambda: None)
        self._get_recent_decisions = state.get("get_recent_decisions", lambda: [])
        self._get_underlying_amt_dto = state.get("get_underlying_amt_dto", lambda: None)
        self._get_last_underlying_bar = state.get("get_last_underlying_bar", lambda: None)
        self._get_option_amt_dto = state.get("get_option_amt_dto", lambda: None)

        # --- Event emission ---
        self._emit = emit

        # --- Optional ---
        self._forecast_fn = forecast_fn
        self._advisor = advisor

    # ---------------------------------------------------------------------
    # Properties
    # ---------------------------------------------------------------------

    @property
    def symbol(self) -> str:
        return self._symbol

    # ---------------------------------------------------------------------
    # Main entry points
    # ---------------------------------------------------------------------

    def manage_exit(self, amt_dto: dict, bar: Any) -> Any:
        """Bar-driven exit evaluation.

        Evaluates SL, TP, trail, time stop, session close via PositionManager.
        Handles partial closes (tiered TP) and full closes. After the exit
        evaluation, runs thesis-flip check if the position survived.

        Returns the surviving position (unchanged, reduced, or None if closed).
        """
        with self._close_lock:
            pm = self._get_position_manager()
            current_pos = pm.current_position
            was_open = current_pos is not None
            try:
                remaining = pm.manage_exit(
                    amt_dto=amt_dto,
                    bar=bar,
                    position=current_pos,
                    bar_index=self._get_bar_index(),
                    entry_bar_index=self._get_entry_bar_index(),
                    entry_time_epoch=self._get_entry_time_epoch(),
                )
            except Exception:
                # C3: a broker/OMS failure while exiting must not kill the engine
                # thread. Keep the position open so the exit is retried on the
                # next bar; the failure is loud so ops can intervene.
                logger.exception(
                    "[EXIT FAILED] %s: bar-exit OMS call raised — position kept "
                    "open, will retry next bar (engine stays alive)",
                    self._symbol,
                )
                return current_pos  # Return original position on failure

            # Survive / SL-ratchet: no lifecycle replace event — keep the book
            # on the returned survivor. Full close / partial: journal emit
            # already adopted pm.current_position inside _emit.
            if remaining is not None:
                pm.current_position = remaining
            self._release_partial_reserves(pm, remaining)
            if was_open and remaining is None:
                self._book_full_close()

        # Run advisor on position management state
        self._notify_advisor_exit(amt_dto, bar, remaining)

        # Thesis invalidation: normal exits ran first and the position
        # survived — evaluate a fresh contrary approval against it.
        if remaining is not None:
            self.check_thesis_flip(amt_dto, bar)

        return remaining

    def manage_tick_exit(self, tick_price: float, tick_time: str) -> None:
        """Tick-level fast stop-loss and take-profit breach check.

        Fast-path exit detection that runs on every tick, checking if the
        tick price breaches the protective stop (SL, breakeven, trail) or
        hits the take-profit target.
        """
        with self._close_lock:
            pm = self._get_position_manager()
            if pm.current_position is None:
                return
            # Clear per-call state to prevent stale values from triggering
            # duplicate reserve releases.
            pm.last_partial_fill = None
            pm.last_pyramid_pnl = 0.0
            # Adopt the survivor: a tick-path partial returns a NEW Position
            # with the reduced size.
            try:
                remaining = pm.manage_tick_exit(
                    pm.current_position, tick_price, tick_time,
                )
            except Exception:
                # C3: a broker/OMS failure while exiting must not kill the engine
                # thread. Keep the position open so the exit is retried on the
                # next tick/bar; the failure is loud so ops can intervene.
                logger.exception(
                    "[EXIT FAILED] %s: tick-exit OMS call raised — position kept "
                    "open, will retry next tick (engine stays alive)",
                    self._symbol,
                )
                return
            # Survive / partial: adopt survivor when present. Full close is
            # already cleared by PositionClosed inside _emit.
            if remaining is not None:
                pm.current_position = remaining
            self._release_partial_reserves(pm, remaining)
            if remaining is None:
                self._book_full_close()

    def check_thesis_flip(self, amt_dto: dict, bar: Any) -> None:
        """Opposing-signal exit (thesis invalidation).

        Runs ONLY after manage_exit declined to close (SL/spread/CVD/TP/
        trail/time priority preserved). Re-runs the unchanged decision
        pipeline with one bypass — gate 2's open-position blocker — through
        the existing DecisionService so SignalBuilder qualification holds.
        A fully-approved signal OPPOSITE the held side flattens now; a halt
        gates entries, not exits, so this still runs while risk-halted.
        """
        with self._close_lock:
            pm = self._get_position_manager()
            pos = pm.current_position
            if pos is None:
                return
            exec_bar = bar  # close settles on the caller bar (premium scale)
            # Basis parity: entries qualify on the UNDERLYING dto+bar whenever an
            # underlying feed drives decisions — evaluating the flip on the
            # option-side dto could approve on noise the entry qualification
            # never saw. The executed close still settles on the caller bar.
            flip_amt_dto = amt_dto
            flip_bar = bar
            if self._underlying_gateway is not None:
                flip_amt_dto = self._get_underlying_amt_dto()
                flip_bar = self._get_last_underlying_bar()
                if not flip_amt_dto or flip_bar is None:
                    logger.info(
                        "[THESIS FLIP] %s: skipped — underlying context "
                        "(entry basis) unavailable this bar",
                        self._symbol,
                    )
                    return
            bars_since_close = self._bars_since_close()
            cooldown_remaining_sec = self._cooldown_remaining_sec(bars_since_close)
            ctx = self._build_context(flip_bar, flip_amt_dto, cooldown_remaining_sec)
            # One strategy seam: the positioned flip evaluation goes through the
            # same should_enter entry point entries use (allow_positioned=True
            # bypasses gate 2's open-position blocker and the halt entry gate).
            decision = self._strategy.should_enter(ctx, allow_positioned=True)
            self._emit(DecisionProduced(
                symbol=self._symbol, time=bar.time, decision=decision,
            ))
            if not (decision.approved and decision.signal is not None):
                return
            signal = decision.signal
            held_side = "LONG" if pos.size > 0 else "SHORT"
            is_put = is_put_symbol(self._symbol)
            is_call = is_call_symbol(self._symbol)
            if is_put:
                held_thesis = "SHORT" if pos.size > 0 else "LONG"
            elif is_call:
                held_thesis = "LONG" if pos.size > 0 else "SHORT"
            else:
                held_thesis = held_side

            # Same-direction approvals (and NO_EDGE) do nothing.
            if signal.type == held_thesis:
                return

            # Fabio Structural Holding: do NOT flip an active trade on minor
            # drift / micro momentum. A genuine thesis flip requires structural
            # invalidation (BREAKOUT, TRIPLE_A, or confirmed VA_FADE).
            if str(signal.reason).upper() == "MODEL_MOMENTUM":
                logger.debug(
                    "[THESIS FLIP SKIPPED] %s: opposing %s is minor drift "
                    "(MODEL_MOMENTUM) — holding %s position",
                    self._symbol, signal.type, held_thesis,
                )
                return

            logger.info(
                "[THESIS FLIP] %s: fresh %s approval (%s @ %.2f RR=%.2f) opposes "
                "held %s thesis (pos %s @ %.2f) — flattening (OPPOSING_SIGNAL)",
                self._symbol, signal.type, signal.model_label,
                float(signal.entry), float(signal.rr), held_thesis,
                held_side,
                float(pos.open_price) if getattr(pos, "open_price", None) else 0.0,
            )
            pm._execute_full_close(
                pos,
                ExitDecision(True, "OPPOSING_SIGNAL", float(exec_bar.close)),
                exec_bar.time,
            )
            self._book_full_close()

    def execute_full_close(self, reason: str) -> bool:
        """Full close of the base position AND pyramid add-ons.

        EOD square-off backstop: the bar-driven SESSION_CLOSE (Phase 5) only
        fires when a bar closes. If bars stop flowing near the close (feed
        dead / engine starved), an open position would otherwise be carried
        overnight. The coordinator's EOD watchdog invokes this on the engine's
        behalf. Idempotent: returns False when nothing is open.
        """
        with self._close_lock:
            pm = self._get_position_manager()
            pos = pm.current_position
            if pos is None and not pm.pyramid_positions:
                return False
            bar = getattr(self._aggregator, "current_bar", None)
            if pos is not None:
                price = (
                    float(bar.close)
                    if bar is not None and bar.close
                    else float(pos.open_price)
                )
            else:
                price = float(bar.close) if bar is not None and bar.close else 0.0
            from quant.contracts.timezones import IST as _IST
            from datetime import datetime
            ts = datetime.now(tz=_IST).isoformat()
            if pos is not None:
                pm._execute_full_close(pos, ExitDecision(True, reason, price), ts)
                pyramid_closed = 0
            else:
                # Base already gone but pyramid add-ons linger
                pyramid_closed = close_lingering_pyramids(pm, price, ts, reason)
            # Post-close bookkeeping — one shared release path.
            self._book_full_close()
            logger.warning(
                "[EOD FORCE CLOSE] %s reason=%s price=%.2f pyramids_closed=%d",
                self._symbol, reason, price, pyramid_closed,
            )
            return True

    # ---------------------------------------------------------------------
    # Partial reserve release
    # ---------------------------------------------------------------------

    def _release_partial_reserves(self, pm: Any, remaining: Any) -> None:
        """Fractional portfolio-risk reserve release after a tiered partial
        exit — shared by the bar (manage_exit) and tick (manage_tick_exit)
        paths so both book the same fraction of reserved open risk."""
        portfolio_risk = self._get_portfolio_risk()
        if portfolio_risk is None:
            return
        if pm.last_partial_fill is not None:
            closed_sz = abs(pm.last_partial_fill.position.size)
            remaining_sz = abs(remaining.size) if remaining is not None else 0.0
            total_sz = closed_sz + remaining_sz
            fraction = closed_sz / total_sz if total_sz > 0 else 0.0
            open_trade_risk = self._get_open_trade_risk()
            release = open_trade_risk * fraction
            portfolio_risk.record_close(release, float(pm.last_partial_fill.pnl))
            self._set_open_trade_risk(open_trade_risk - release)
        # Pyramid add-on PnL is NOT booked here: _execute_full_close's E11
        # loop already pairs every add-on with its OWN fill pnl and risk_i —
        # re-releasing the aggregate last_pyramid_pnl would double-book it.

    # ---------------------------------------------------------------------
    # Full close bookkeeping
    # ---------------------------------------------------------------------

    def _book_full_close(self) -> None:
        """Shared post-full-close bookkeeping — the ONLY full-close release path.

        Called exactly once per full close by every close site (bar exit, tick
        exit, thesis-flip, EOD force-close): marks the cooldown bar index and
        releases the aggregate portfolio-risk reservation for the trade.
        """
        pm = self._get_position_manager()
        self._set_last_close_bar_index(self._get_bar_index())
        portfolio_risk = self._get_portfolio_risk()
        if portfolio_risk is not None:
            portfolio_risk.record_close(
                self._get_open_trade_risk(),
                float(getattr(pm.last_fill, "pnl", 0.0) or 0.0),
                symbol=self._symbol,
                is_full_close=True,
            )
            self._set_open_trade_risk(0.0)
        # Immediately notify advisor that position is closed
        self._notify_advisor_close()

    # ---------------------------------------------------------------------
    # Context building
    # ---------------------------------------------------------------------

    def _build_context(self, bar: Any, amt_dto: dict, cooldown_remaining_sec: float) -> Any:
        """Build a DecisionContext from engine state.

        Thin delegate to the single construction owner
        (``build_engine_context``) shared with DecisionLoop and QuantEngine —
        used by thesis-flip evaluation and advisor close notifications.
        """
        return build_engine_context(self, bar, amt_dto, cooldown_remaining_sec)

    # ---------------------------------------------------------------------
    # Advisor notifications
    # ---------------------------------------------------------------------

    def _notify_advisor_exit(self, amt_dto: dict, bar: Any, remaining: Any) -> None:
        """Notify the advisor of the exit evaluation result."""
        if self._advisor is None:
            return
        try:
            risk_st = self._risk.state() if self._risk else None
            active_pos = remaining or self._get_state().position
            option_amt_dto = self._get_option_amt_dto()
            last_underlying_bar = self._get_last_underlying_bar()
            if option_amt_dto is not None and last_underlying_bar is not None:
                advisor_ctx = DecisionContextBuilder(greeks=self._greeks).build(
                    bar=bar,
                    symbol=self._symbol,
                    market=self._market,
                    contract_expiry=self._contract_expiry,
                    tick_size=self._tick_size,
                    bar_index=self._get_bar_index(),
                    warm_bars=self._amt_engine.warm_bars,
                    cooldown_remaining_sec=0.0,
                    risk_state=risk_st,
                    amt_dto=option_amt_dto if option_amt_dto else amt_dto,
                    order_book=self._get_last_depth(),
                    position=active_pos,
                    entry_bar_index=self._get_entry_bar_index(),
                    recent_decisions=list(self._get_recent_decisions()),
                    contract_symbol=self._symbol,
                )
                self._advisor.on_context(advisor_ctx)
            else:
                advisor_ctx = DecisionContextBuilder(greeks=self._greeks).build(
                    bar=bar,
                    symbol=self._symbol,
                    market=self._market,
                    contract_expiry=self._contract_expiry,
                    tick_size=self._tick_size,
                    bar_index=self._get_bar_index(),
                    warm_bars=self._amt_engine.warm_bars,
                    cooldown_remaining_sec=0.0,
                    risk_state=risk_st,
                    amt_dto=amt_dto,
                    order_book=self._get_last_depth(),
                    position=active_pos,
                    entry_bar_index=self._get_entry_bar_index(),
                    recent_decisions=list(self._get_recent_decisions()),
                    contract_symbol=(
                        self._symbol if self._underlying_gateway is not None else None
                    ),
                )
                self._advisor.on_context(advisor_ctx)
        except Exception as e:
            logger.debug(f"Advisor context notification failed: {e}")

    def _notify_advisor_close(self) -> None:
        """Notify the advisor that a position has been fully closed."""
        if self._advisor is None:
            return
        try:
            cooldown_sec = float(
                self._cooldown_bars * int(
                    getattr(self._aggregator, "interval_seconds", DEFAULT_INTERVAL_SEC)
                    or DEFAULT_INTERVAL_SEC
                )
            )
            curr_bar = (
                getattr(self._aggregator, "current_bar", None)
                or getattr(self._get_state(), "last_bar", None)
            )
            if curr_bar is not None:
                close_ctx = self._build_context(
                    curr_bar, self._amt_engine.last_amt_dto or {}, cooldown_sec,
                )
                self._advisor.on_context(close_ctx)
        except Exception as e:
            logger.debug(f"Advisor context notification failed: {e}")

    # ---------------------------------------------------------------------
    # Forecast
    # ---------------------------------------------------------------------

    def _fresh_forecast(self) -> Any:
        """Return the cached TimesFM forecast unless it is stale (>1 bar old)."""
        if self._forecast_fn is None:
            return None
        return self._forecast_fn()

    # ---------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------

    def _bars_since_close(self) -> int:
        """Number of bars since the last full close."""
        last_close_idx = self._get_last_close_bar_index()
        bar_index = self._get_bar_index()
        return (
            bar_index - last_close_idx
            if last_close_idx >= 0
            else self._cooldown_bars  # no trade yet -> no cooldown
        )

    def _cooldown_remaining_sec(self, bars_since_close: int) -> float:
        """Convert bars-since-close to cooldown seconds remaining."""
        cooldown_bars_remaining = max(0, self._cooldown_bars - bars_since_close)
        return cooldown_bars_remaining * int(
            getattr(self._aggregator, "interval_seconds", DEFAULT_INTERVAL_SEC)
            or DEFAULT_INTERVAL_SEC
        )

    def _set_state_with_position(self, position: Any) -> None:
        """Update the engine state with a new position value."""
        current_state = self._get_state()
        self._set_state(current_state.with_position(position))
