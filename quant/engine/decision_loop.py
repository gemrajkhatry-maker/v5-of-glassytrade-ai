"""DecisionLoop — entry evaluation, signal translation, and submission.

Extracted from QuantEngine (runtime.py) for maintainability and testability.
Encapsulates the decision pipeline:

    Entry Guards -> Context Build -> Strategy Evaluation -> Option Translation
    -> Risk Ceilings -> Sizing -> OMS Submission -> Event Emission

The DecisionLoop is stateless with respect to engine mutable state — all
engine state is accessed and mutated through injected callbacks. This makes
it fully testable in isolation without constructing a QuantEngine.
"""

from __future__ import annotations

import logging
from dataclasses import replace as _dc_replace
from typing import Any, Callable, Optional

from quant.bars import DEFAULT_INTERVAL_SEC
from quant.decision.context import DecisionContext
from quant.decision.context_builder import DecisionContextBuilder
from quant.decision.decision_service import QuantDecision
from quant.decision.signal_builder import Signal, clamp_quantity
from quant.events import (
    DecisionProduced,
    Event,
    PositionOpened,
    SignalApproved,
    SignalBlocked,
)
from quant.execution.execution_model import ExecutionModel, signal_matches_contract
from quant.session_gates import bar_epoch_ms as _bar_epoch_ms, ist_dt as _ist_dt

logger = logging.getLogger(__name__)


def _as_counter(value: Any) -> int:
    """Coerce a diagnostic counter to int, defaulting to 0 when unusable.

    A stubbed risk object (``MagicMock``) fabricates ANY attribute, so
    ``getattr(obj, "model_sizing_failures", 0)`` returns a mock rather than
    the ``0`` default. A non-numeric value reads as "no failure recorded".
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


class DecisionLoop:
    """Encapsulates the entry decision pipeline.

    The decision loop evaluates entry guards, builds a DecisionContext, asks
    the strategy whether to enter, translates signals for option contracts,
    checks risk ceilings, sizes the position, submits to the OMS, and emits
    the resulting events.

    All engine mutable state is accessed through injected callbacks so the
    loop is fully testable in isolation.

    Parameters
    ----------
    config : dict
        Static configuration: symbol, market, contract_expiry, tick_size,
        cooldown_bars, max_lots.
    deps : dict
        Dependencies: risk, portfolio_risk, oms, strategy, amt_engine,
        get_position_manager, execution_model, contract, underlying_gateway,
        execution_enabled, get_underlying_symbol.
    state : dict
        Mutable state accessors/mutators: get_bar_index, get_entry_bar_index,
        set_entry_bar_index, get_last_close_bar_index, get_latch, set_latch,
        clear_latch, get_cert_records, get_last_depth, get_recent_decisions,
        get_open_trade_risk, set_open_trade_risk, get_exposure_state,
        set_exposure_state.
    emit : callable
        Function to emit events (Event -> None).
    forecast_fn : callable, optional
        Returns a fresh TimesFM forecast or None.
    advisor : object, optional
        Advisor with an ``on_context`` method for decision notifications.
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
        self._max_lots: int | None = config.get("max_lots")

        # --- Dependencies ---
        self._risk = deps["risk"]
        self._portfolio_risk = deps.get("portfolio_risk")
        self._oms = deps["oms"]
        self._strategy = deps["strategy"]
        self._amt_engine = deps["amt_engine"]
        self._get_position_manager = deps["get_position_manager"]
        self._execution_model = deps.get("execution_model", ExecutionModel.LEGACY_TRANSLATED)
        self._contract = deps.get("contract")
        self._underlying_gateway = deps.get("underlying_gateway")
        self._execution_enabled: bool = deps.get("execution_enabled", True)
        self._get_underlying_symbol = deps.get("get_underlying_symbol")

        # --- Mutable state accessors/mutators ---
        self._get_bar_index = state["get_bar_index"]
        self._get_entry_bar_index = state["get_entry_bar_index"]
        self._set_entry_bar_index = state["set_entry_bar_index"]
        self._get_last_close_bar_index = state["get_last_close_bar_index"]
        self._get_latch = state["get_latch"]
        self._set_latch = state["set_latch"]
        self._clear_latch = state["clear_latch"]
        self._pop_latch = state.get("pop_latch")
        self._get_cert_records = state["get_cert_records"]
        self._get_last_depth = state.get("get_last_depth", lambda: None)
        self._get_recent_decisions = state.get("get_recent_decisions", lambda: [])
        self._get_open_trade_risk = state.get("get_open_trade_risk", lambda: 0.0)
        self._set_open_trade_risk = state.get("set_open_trade_risk")
        self._get_exposure_state = state.get("get_exposure_state")
        self._set_exposure_state = state.get("set_exposure_state")

        # --- Event emission ---
        self._emit = emit

        # --- Optional ---
        self._forecast_fn = forecast_fn
        self._advisor = advisor

        # --- Internal tracking ---
        # Debounce: tracks the bar index of the last rejection so repeated
        # blocked evaluations within 2 bars are suppressed.
        self._last_rejected_bar_index: int = -999

    # ---------------------------------------------------------------------
    # Properties for read-only access to configuration
    # ---------------------------------------------------------------------

    @property
    def symbol(self) -> str:
        return self._symbol

    # ---------------------------------------------------------------------
    # Main entry point
    # ---------------------------------------------------------------------

    def evaluate(
        self,
        amt_dto: dict,
        bar: Any,
        execution_bar: Any | None = None,
    ) -> Optional[QuantDecision]:
        """Run the full decision pipeline for a bar.

        1. Evaluate entry guards (exposure, debounce, risk halt, cooldown).
        2. Build the DecisionContext and ask the strategy.
        3. Record the decision (certification + event emission).
        4. If approved, translate (for options) and submit to the OMS.
        5. If rejected, clear the latch (market changed -> episodes stale).

        Returns the ``QuantDecision`` or ``None`` when an entry guard blocked
        before the strategy was consulted.
        """
        blocked, cooldown_remaining_sec = self._entry_guards(bar)
        if blocked:
            return None

        decision, ctx, amt_dto, risk_st = self._build_decision(
            amt_dto, bar, execution_bar, cooldown_remaining_sec,
        )

        # S1: record the decision itself — gates with pass/fail and reasons.
        self._record_cert_decision(decision, bar)

        self._emit(DecisionProduced(
            symbol=self._symbol, time=bar.time, decision=decision,
        ))

        # Notify advisor of the decision context
        self._notify_advisor_decision(ctx, amt_dto, execution_bar, cooldown_remaining_sec, risk_st)

        if decision.approved and decision.signal is not None:
            self._translate_and_submit(decision, bar, amt_dto, risk_st)
        else:
            # Market state changed — all open blocking episodes are stale.
            self._clear_latch()
            if decision.reason == "OPPOSING_TYPE":
                logger.debug(
                    "[DECISION EVAL] %s: approved=False reason=OPPOSING_TYPE phase=%s",
                    self._symbol,
                    decision.phase,
                )
            else:
                logger.info(
                    "[DECISION EVAL] %s: approved=False reason=%s phase=%s blocked=%s",
                    self._symbol,
                    decision.reason,
                    decision.phase,
                    decision.block_reasons,
                )

        return decision

    # ---------------------------------------------------------------------
    # Entry guards
    # ---------------------------------------------------------------------

    def _entry_guards(self, bar: Any) -> tuple[bool, float]:
        """Debounce, risk-halt and post-trade cooldown gates.

        Returns ``(blocked, cooldown_remaining_sec)``; the halt and cooldown
        branches emit their DecisionProduced, the debounce branch emits nothing.
        """
        # Broker may hold partial exposure after a timeout/cancel race. Until
        # reconciled, this engine must stay flat and reject new entries.
        if self._get_exposure_state is not None:
            exposure = self._get_exposure_state()
            if exposure is not None and not exposure.can_open_new_position:
                logger.error(
                    "[BLOCKED] %s: broker exposure requires reconciliation (%s)",
                    self._symbol, exposure.status,
                )
                return True, 0.0

        # Debounce repeated rejected entries to avoid log flood
        bar_index = self._get_bar_index()
        if (bar_index - self._last_rejected_bar_index) < 2:
            return True, 0.0

        # Guard 0: trade-count / risk halt check BEFORE building any context
        can_trade, no_trade_reason = self._risk.can_trade()
        if not can_trade:
            logger.info(
                "[BLOCKED] %s: %s (trades_today=%d)",
                self._symbol, no_trade_reason, self._risk.state().trades_today,
            )
            halted_decision = QuantDecision(
                approved=False,
                signal=None,
                reason="HALTED",
                phase="",
                gate_results=(),
                block_reasons=(f"Risk: {no_trade_reason}",),
                model_label="",
            )
            self._emit(DecisionProduced(
                symbol=self._symbol, time=bar.time, decision=halted_decision,
            ))
            return True, 0.0

        # Guard 1: post-trade cooldown (bars since last close)
        last_close_idx = self._get_last_close_bar_index()
        bars_since_close = (
            bar_index - last_close_idx
            if last_close_idx >= 0
            else self._cooldown_bars  # no trade yet -> no cooldown
        )
        cooldown_bars_remaining = max(0, self._cooldown_bars - bars_since_close)
        # Convert bars to seconds for the DecisionContext contract
        cooldown_remaining_sec = cooldown_bars_remaining * int(
            getattr(self._amt_engine, "interval_seconds", DEFAULT_INTERVAL_SEC)
            or DEFAULT_INTERVAL_SEC
        )
        if cooldown_bars_remaining > 0:
            logger.debug(
                "[COOLDOWN] %s: %d bars remaining before next entry",
                self._symbol, cooldown_bars_remaining,
            )
            cooldown_decision = QuantDecision(
                approved=False,
                signal=None,
                reason="COOLDOWN",
                phase="",
                gate_results=(),
                block_reasons=(f"Cooldown: {cooldown_bars_remaining} bars remaining",),
                model_label="",
            )
            self._emit(DecisionProduced(
                symbol=self._symbol, time=bar.time, decision=cooldown_decision,
            ))
            return True, cooldown_remaining_sec

        return False, cooldown_remaining_sec

    # ---------------------------------------------------------------------
    # Decision building
    # ---------------------------------------------------------------------

    def _build_decision(
        self,
        amt_dto: dict,
        bar: Any,
        execution_bar: Any | None,
        cooldown_remaining_sec: float,
    ) -> tuple[QuantDecision, DecisionContext, dict, Any]:
        """Build the DecisionContext, ask the strategy, translate to the option leg.

        Returns ``(decision, ctx, amt_dto, risk_st)``.
        """
        amt_dto = amt_dto or self._amt_engine.last_amt_dto or {}
        risk_st = self._risk.state()

        # S1 certification trace for context
        self._cert_trace(
            bar=bar,
            stage="context",
            market_data={
                "open": float(bar.open), "high": float(bar.high),
                "low": float(bar.low), "close": float(bar.close),
                "volume": float(bar.volume),
            },
            profile_data={
                "poc": amt_dto.get("poc"), "vah": amt_dto.get("valueAreaHigh"),
                "val": amt_dto.get("valueAreaLow"),
                "lvns": amt_dto.get("lvns") or [],
                "hvns": amt_dto.get("hvns") or [],
                "leg_lvn": amt_dto.get("legLvn"),
            },
            context={
                "market_state": amt_dto.get("marketState"),
                "profile_shape": amt_dto.get("profileShape"),
                "session_phase": "",
                "balance_ratio": amt_dto.get("balanceRatio"),
            },
        )

        ctx = self._build_context(bar, amt_dto, cooldown_remaining_sec)
        decision = self._strategy.should_enter(ctx)

        # If running on an option contract with underlying futures feed,
        # translate signal to option premium
        if decision.approved and decision.signal is not None and self._underlying_gateway is not None:
            decision = self._translate_signal_for_option(
                decision, ctx, execution_bar, bar,
            )

        return decision, ctx, amt_dto, risk_st

    def _build_context(
        self, bar: Any, amt_dto: dict, cooldown_remaining_sec: float,
    ) -> DecisionContext:
        """Build a DecisionContext from engine state.

        Single DecisionContext source shared by the flat-path ``evaluate()``
        and the positioned thesis-flip check.
        """
        eval_symbol = (
            self._get_underlying_symbol()
            if self._underlying_gateway is not None and self._get_underlying_symbol
            else self._symbol
        )
        pm = self._get_position_manager()
        active_pos = pm.current_position
        return DecisionContextBuilder().build(
            bar=bar,
            symbol=eval_symbol,
            market=self._market,
            contract_expiry=self._contract_expiry,
            tick_size=self._tick_size,
            bar_index=self._get_bar_index(),
            warm_bars=self._amt_engine.warm_bars,
            cooldown_remaining_sec=cooldown_remaining_sec,
            risk_state=self._risk.state(),
            amt_dto=amt_dto or self._amt_engine.last_amt_dto or {},
            order_book=self._get_last_depth(),
            position=active_pos,
            entry_bar_index=self._get_entry_bar_index(),
            recent_decisions=list(self._get_recent_decisions()),
        )

    def _translate_signal_for_option(
        self,
        decision: QuantDecision,
        ctx: DecisionContext,
        execution_bar: Any | None,
        bar: Any,
    ) -> QuantDecision:
        """Translate an underlying signal to option premium terms.

        When running on an option contract with an underlying futures feed,
        the strategy produces a signal on the underlying. This method
        translates it to the option contract's premium scale.
        """
        from quant.amt.session.selector import OptionSelector

        exec_bar = execution_bar or bar
        opt_ltp = float(exec_bar.close) if exec_bar and exec_bar.close > 0 else 0.0
        if opt_ltp <= 0:
            return decision

        delta = getattr(ctx, "option_delta", None)
        selector = OptionSelector()
        opt_signal = selector.translate_underlying_signal_to_option(
            signal=decision.signal,
            option_symbol=self._symbol,
            option_ltp=opt_ltp,
            delta=delta,
            tick_size=self._tick_size,
        )
        if opt_signal is None:
            return _dc_replace(
                decision,
                approved=False,
                signal=None,
                reason="OPPOSING_TYPE",
                block_reasons=("Signal direction opposes option contract type (Call vs Put)",),
            )
        return _dc_replace(decision, signal=opt_signal)

    # ---------------------------------------------------------------------
    # Signal translation and submission
    # ---------------------------------------------------------------------

    def _translate_and_submit(
        self, decision: QuantDecision, bar: Any, amt_dto: dict, risk_st: Any,
    ) -> None:
        """Size, ceiling-check and submit an approved signal, then emit fills."""
        signal = decision.signal

        # Independent execution contract guard
        if (
            self._execution_model is ExecutionModel.INDEPENDENT
            and self._contract is not None
            and not signal_matches_contract(getattr(signal, "symbol", None), self._symbol)
        ):
            logger.warning(
                "[INDEPENDENT_CONTRACT_GUARD] %s: rejected signal for %s",
                self._symbol,
                getattr(signal, "symbol", None),
            )
            self._latch_or_signal_block(
                signal,
                "independent execution requires signal and engine contract to match",
                bar.time,
            )
            return

        # Underlying observer engines stream charts/data but must not submit orders
        if not self._execution_enabled:
            logger.debug(
                "[EXECUTION_DISABLED] %s: approved signal not submitted (underlying observer engine)",
                self._symbol,
            )
            return

        # Mirror position_manager's is_expiry source of truth
        _ist = _ist_dt(bar.time)
        contract_is_expiry = bool(
            self._contract_expiry is not None
            and _ist is not None and _ist.date() == self._contract_expiry
        )

        # If strategy provides a TimesFM forecast, pass it for dynamic Kelly & VaR sizing
        tfm_fc = self._fresh_forecast()

        # Distinguish a model-sizing REFUSAL from a genuine budget-zero
        sizing_failures_before = _as_counter(
            getattr(self._risk, "model_sizing_failures", 0)
        )
        quantity = clamp_quantity(
            self._risk.position_size(
                signal.entry, signal.sl, lot_size=self._oms.lot_size,
                is_expiry=contract_is_expiry,
                max_lots=self._max_lots,
                forecast=tfm_fc,
                side=signal.type,
            )
        )

        # Risk-budget guard: when the per-trade budget can't afford even ONE lot
        if quantity <= 0:
            model_sizing_failed = (
                _as_counter(getattr(self._risk, "model_sizing_failures", 0))
                > sizing_failures_before
            )
            zero_reason = (
                "model sizing unavailable (TimesFM failure) — refusing entry"
                if model_sizing_failed
                else f"risk budget affords 0 lots (lot={self._oms.lot_size})"
            )
            self._latch_or_signal_block(signal, zero_reason, bar.time)
            return

        if not self._apply_risk_ceilings(signal, bar, quantity):
            return

        try:
            position = self._oms.submit(signal, quantity)
        except Exception:
            # C3: a broker/OMS submission failure must not kill the engine
            logger.exception(
                "[ENTRY FAILED] %s: OMS submit raised — skipping entry and "
                "unwinding risk reservation (engine stays alive)",
                self._symbol,
            )
            self._latch_or_signal_block(signal, "OMS submit raised — broker/OMS failure", bar.time)
            if self._portfolio_risk is not None:
                reserved = self._get_open_trade_risk()
                if reserved > 0:
                    self._portfolio_risk.release(reserved, symbol=self._symbol)
                self._set_open_trade_risk(0.0)
            return

        # Handle partial fills
        paper_fill = getattr(self._oms, "last_fill", None)
        try:
            is_partial = (
                paper_fill is not None
                and float(paper_fill.filled_quantity) < float(paper_fill.requested_quantity)
            )
        except (TypeError, ValueError, AttributeError):
            is_partial = False

        if is_partial:
            from quant.execution.exposure import ExposureState
            if self._set_exposure_state is not None:
                self._set_exposure_state(
                    ExposureState.none().partial_entry(
                        symbol=self._symbol,
                        order_id=paper_fill.order_id,
                        requested_qty=paper_fill.requested_quantity,
                        filled_qty=paper_fill.filled_quantity,
                        fill_price=paper_fill.fill_price,
                    )
                )
            logger.error(
                "[RECONCILIATION REQUIRED] %s: paper order %s partially filled (%s/%s)",
                self._symbol,
                paper_fill.order_id,
                paper_fill.filled_quantity,
                paper_fill.requested_quantity,
            )

        logger.info(
            "[SIGNAL EXECUTED] %s: %s %s @ %.2f (SL=%.2f, TP=%.2f, RR=%.2f) — %s | "
            "trades_today=%d equity=%.0f",
            self._symbol,
            signal.type,
            signal.symbol,
            signal.entry,
            signal.sl,
            signal.tp,
            signal.rr,
            decision.reason,
            risk_st.trades_today,
            risk_st.equity,
        )

        # Emit SignalApproved only after a successful submit
        self._emit(SignalApproved(symbol=self._symbol, time=bar.time, signal=signal))

        # Update engine state
        self._set_entry_bar_index(self._get_bar_index())
        if self._pop_latch is not None:
            self._pop_latch((getattr(signal, "symbol", "") or self._symbol, str(signal.type)))
        else:
            latch = self._get_latch()
            latch.pop((getattr(signal, "symbol", "") or self._symbol, str(signal.type)), None)

        pm = self._get_position_manager()
        pm.current_position = position
        self._emit(PositionOpened(symbol=self._symbol, time=bar.time, position=position))

        # Notify advisor of new open position
        self._notify_advisor_position(bar, amt_dto, position)

    def _apply_risk_ceilings(self, signal: Signal, bar: Any, quantity: float) -> bool:
        """Cross-engine portfolio ceiling check + reservation.

        Returns True when the trade may proceed; on refusal it latches a
        SignalBlocked and returns False.
        """
        if self._portfolio_risk is not None:
            trade_risk = abs(float(signal.entry) - float(signal.sl)) * max(1.0, quantity)
            ok, why = self._portfolio_risk.can_accept(trade_risk, symbol=self._symbol)
            if not ok:
                self._latch_or_signal_block(signal, why, bar.time)
                self._set_last_rejected_bar_index()
                return False
            if not self._portfolio_risk.register_open(trade_risk, symbol=self._symbol):
                self._latch_or_signal_block(
                    signal, "portfolio cap breached between can_accept and register", bar.time,
                )
                self._set_last_rejected_bar_index()
                return False
            self._set_open_trade_risk(trade_risk)

        return True

    # ---------------------------------------------------------------------
    # Latch / signal blocking
    # ---------------------------------------------------------------------

    def _latch_or_signal_block(self, signal: Signal, block_reason: str, bar_time: str) -> None:
        """Record a blocked approval. First occurrence of an episode (same
        signal blocked for the same reason) warns + emits SignalBlocked;
        repeats debug-log only. Episodes live per (signal symbol, side) key in
        the latch. Evaluation is never suppressed."""
        key = (getattr(signal, "symbol", "") or self._symbol, str(signal.type))
        latch = self._get_latch()
        if latch.get(key) == block_reason:
            logger.debug(
                "[SIGNAL BLOCKED] %s: %s %s @ %.2f — %s (repeat, latched)",
                self._symbol, signal.type, signal.symbol, signal.entry, block_reason,
            )
            return
        self._set_latch(key, block_reason)
        logger.warning(
            "[SIGNAL BLOCKED] %s: %s %s @ %.2f — %s",
            self._symbol, signal.type, signal.symbol, signal.entry, block_reason,
        )
        self._emit(SignalBlocked(
            symbol=self._symbol, time=bar_time, signal=signal, reason=block_reason,
        ))

    # ---------------------------------------------------------------------
    # Certification recording
    # ---------------------------------------------------------------------

    def _record_cert_decision(self, decision: QuantDecision, bar: Any) -> None:
        """Record the decision in the certification buffer (S1)."""
        try:
            cert_records = self._get_cert_records()
            cert_records.append({
                "symbol": self._symbol, "time": bar.time,
                "stage": "decision",
                "approved": decision.approved, "reason": decision.reason,
                "block_reasons": list(decision.block_reasons or ()),
                "gate_results": [
                    {"gate": g.gate if hasattr(g, 'gate') else getattr(g, 'name', '?'),
                     "passed": bool(getattr(g, 'passed', False))}
                    for g in (decision.gate_results or ())
                ],
                "signal": {
                    "type": decision.signal.type,
                    "entry": float(decision.signal.entry),
                    "sl": float(decision.signal.sl),
                    "tp": float(decision.signal.tp),
                    "rr": float(decision.signal.rr),
                } if decision.signal else None,
                "position_size": None,
            })
        except Exception as e:
            logger.debug(f"Certification decision record failed: {e}")

    def _cert_trace(self, bar: Any = None, stage: str = "", **fields: Any) -> None:
        """S1 decision traceability: append a certification record."""
        try:
            cert_records = self._get_cert_records()
            rec = {
                "symbol": self._symbol,
                "time": getattr(bar, "time", "") if bar else "",
                "stage": stage,
            }
            rec.update(fields)
            if bar is not None:
                rec["bar_index"] = self._get_bar_index()
            cert_records.append(rec)
        except Exception as e:
            logger.debug(f"Certification record append failed: {e}")

    # ---------------------------------------------------------------------
    # Advisor notifications
    # ---------------------------------------------------------------------

    def _notify_advisor_decision(
        self,
        ctx: DecisionContext,
        amt_dto: dict,
        execution_bar: Any | None,
        cooldown_remaining_sec: float,
        risk_st: Any,
    ) -> None:
        """Notify the advisor of the decision context."""
        if self._advisor is None:
            return
        try:
            # For option contracts, build context from the option AMT DTO
            if self._underlying_gateway is not None and execution_bar is not None:
                advisor_ctx = DecisionContextBuilder().build(
                    bar=execution_bar,
                    symbol=self._symbol,
                    market=self._market,
                    contract_expiry=self._contract_expiry,
                    tick_size=self._tick_size,
                    bar_index=self._get_bar_index(),
                    warm_bars=self._amt_engine.warm_bars,
                    cooldown_remaining_sec=cooldown_remaining_sec,
                    risk_state=risk_st,
                    amt_dto=amt_dto,
                    order_book=self._get_last_depth(),
                    position=None,
                    entry_bar_index=self._get_entry_bar_index(),
                    recent_decisions=list(self._get_recent_decisions()),
                )
                self._advisor.on_context(advisor_ctx)
            else:
                self._advisor.on_context(ctx)
        except Exception as e:
            logger.debug(f"Advisor context notification failed: {e}")

    def _notify_advisor_position(self, bar: Any, amt_dto: dict, position: Any) -> None:
        """Notify the advisor of a new open position."""
        if self._advisor is None:
            return
        try:
            pos_ctx = DecisionContextBuilder().build(
                bar=bar,
                symbol=self._symbol,
                market=self._market,
                contract_expiry=self._contract_expiry,
                tick_size=self._tick_size,
                bar_index=self._get_bar_index(),
                warm_bars=self._amt_engine.warm_bars,
                cooldown_remaining_sec=0.0,
                risk_state=self._risk.state(),
                amt_dto=amt_dto or self._amt_engine.last_amt_dto or {},
                order_book=self._get_last_depth(),
                position=position,
                entry_bar_index=self._get_entry_bar_index(),
                recent_decisions=list(self._get_recent_decisions()),
            )
            self._advisor.on_context(pos_ctx)
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

    def _set_last_rejected_bar_index(self) -> None:
        """Update the last-rejected bar index for debounce tracking."""
        self._last_rejected_bar_index = self._get_bar_index()
