"""SubmissionHandler — OMS submission, sizing, and risk ceiling checks.

Extracted from DecisionLoop._translate_and_submit() for maintainability.
Encapsulates the submission pipeline:

    Contract Guard -> Execution Check -> Position Sizing -> Risk Ceilings
    -> OMS Submission -> Partial Fill Handling -> State Updates -> Event Emission

The SubmissionHandler is stateless with respect to engine mutable state — all
engine state is accessed and mutated through injected callbacks. This makes
it fully testable in isolation without constructing a QuantEngine.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from quant.decision.signal_builder import Signal, clamp_quantity
from quant.events import Event, PositionOpened, SignalApproved
from quant.execution.execution_model import ExecutionModel, signal_matches_contract
from quant.session_gates import bar_epoch_ms as _bar_epoch_ms, ist_dt as _ist_dt

logger = logging.getLogger(__name__)


def _as_counter(value: Any) -> int:
    """Coerce a diagnostic counter to int, defaulting to 0 when unusable."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


class SubmissionHandler:
    """Encapsulates the OMS submission pipeline.

    The submission handler validates the signal, sizes the position, checks
    risk ceilings, submits to the OMS, handles partial fills, updates engine
    state, and emits events.

    All engine mutable state is accessed through injected callbacks so the
    handler is fully testable in isolation.

    Parameters
    ----------
    config : dict
        Static configuration: symbol, contract_expiry, max_lots, execution_model,
        contract, execution_enabled.
    deps : dict
        Dependencies: risk, oms, get_portfolio_risk, get_position_manager,
        forecast_fn.
    state : dict
        Mutable state accessors/mutators: get_bar_index, get_entry_bar_index,
        set_entry_bar_index, get_latch, set_latch, clear_latch, pop_latch,
        get_open_trade_risk, set_open_trade_risk, get_exposure_state,
        set_exposure_state, set_entry_time_epoch, set_last_rejected_bar_index.
    emit : callable
        Function to emit events (Event -> None).
    latch_or_signal_block : callable
        Function to latch a blocked signal (signal, reason, bar_time) -> None.
    notify_advisor_position : callable
        Function to notify advisor of new position (bar, amt_dto, position) -> None.
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
        # Callbacks
        latch_or_signal_block: Callable[[Signal, str, str], None],
        notify_advisor_position: Callable[[Any, dict, Any], None],
    ) -> None:
        # --- Static configuration ---
        self._symbol: str = config["symbol"]
        self._contract_expiry = config.get("contract_expiry")
        self._max_lots: int | None = config.get("max_lots")
        self._execution_model = config.get("execution_model", ExecutionModel.LEGACY_TRANSLATED)
        self._contract = config.get("contract")
        self._execution_enabled: bool = config.get("execution_enabled", True)

        # --- Dependencies ---
        self._risk = deps["risk"]
        self._oms = deps["oms"]
        self._get_portfolio_risk = deps.get("get_portfolio_risk", lambda: deps.get("portfolio_risk"))
        self._get_position_manager = deps["get_position_manager"]
        self._forecast_fn = deps.get("forecast_fn")

        # --- Mutable state accessors/mutators ---
        self._get_bar_index = state["get_bar_index"]
        self._get_entry_bar_index = state["get_entry_bar_index"]
        self._set_entry_bar_index = state["set_entry_bar_index"]
        self._get_latch = state["get_latch"]
        self._set_latch = state["set_latch"]
        self._pop_latch = state.get("pop_latch")
        self._get_open_trade_risk = state.get("get_open_trade_risk", lambda: 0.0)
        self._set_open_trade_risk = state.get("set_open_trade_risk", lambda v: None)
        self._get_exposure_state = state.get("get_exposure_state")
        self._set_exposure_state = state.get("set_exposure_state")
        self._set_entry_time_epoch = state.get("set_entry_time_epoch")
        self._set_last_rejected_bar_index = state.get("set_last_rejected_bar_index")

        # --- Callbacks ---
        self._emit = emit
        self._latch_or_signal_block = latch_or_signal_block
        self._notify_advisor_position = notify_advisor_position

    # ---------------------------------------------------------------------
    # Properties
    # ---------------------------------------------------------------------

    @property
    def symbol(self) -> str:
        return self._symbol

    # ---------------------------------------------------------------------
    # Main entry point
    # ---------------------------------------------------------------------

    def submit(
        self,
        signal: Signal,
        bar: Any,
        amt_dto: dict,
        risk_st: Any,
        decision_reason: str,
    ) -> bool:
        """Size, ceiling-check and submit an approved signal, then emit fills.

        Returns True if submission succeeded, False if blocked or failed.
        """
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
            return False

        # Underlying observer engines stream charts/data but must not submit orders
        if not self._execution_enabled:
            logger.debug(
                "[EXECUTION_DISABLED] %s: approved signal not submitted (underlying observer engine)",
                self._symbol,
            )
            return False

        # Mirror position_manager's is_expiry source of truth
        _ist = _ist_dt(bar.time)
        contract_is_expiry = bool(
            self._contract_expiry is not None
            and _ist is not None and _ist.date() == self._contract_expiry
        )

        # Sizing is deterministic (House Money Protocol, SessionRisk is the
        # single authority). TimesFM forecasts feed exits/UI only — they must
        # not silently change position size.
        self._fresh_forecast()

        quantity = clamp_quantity(
            self._risk.position_size(
                signal.entry, signal.sl, lot_size=self._oms.lot_size,
                is_expiry=contract_is_expiry,
                max_lots=self._max_lots,
                side=signal.type,
            )
        )

        # Risk-budget guard: when the per-trade budget can't afford even ONE lot
        if quantity <= 0:
            zero_reason = f"risk budget affords 0 lots (lot={self._oms.lot_size})"
            self._latch_or_signal_block(signal, zero_reason, bar.time)
            return False

        if not self._apply_risk_ceilings(signal, bar, quantity):
            return False

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
            _pr = self._get_portfolio_risk()
            if _pr is not None:
                reserved = self._get_open_trade_risk()
                if reserved > 0:
                    _pr.release(reserved, symbol=self._symbol)
                self._set_open_trade_risk(0.0)
            return False

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
            decision_reason,
            risk_st.trades_today,
            risk_st.equity,
        )

        # Emit SignalApproved only after a successful submit
        self._emit(SignalApproved(symbol=self._symbol, time=bar.time, signal=signal))

        # Update engine state
        self._set_entry_bar_index(self._get_bar_index())
        if self._set_entry_time_epoch is not None:
            self._set_entry_time_epoch(_bar_epoch_ms(bar.time) / 1000.0)
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

        return True

    # ---------------------------------------------------------------------
    # Risk ceilings
    # ---------------------------------------------------------------------

    def _apply_risk_ceilings(self, signal: Signal, bar: Any, quantity: float) -> bool:
        """Cross-engine portfolio ceiling check + reservation.

        Returns True when the trade may proceed; on refusal it latches a
        SignalBlocked and returns False.
        """
        portfolio_risk = self._get_portfolio_risk()
        if portfolio_risk is not None:
            trade_risk = abs(float(signal.entry) - float(signal.sl)) * max(1.0, quantity)
            ok, why = portfolio_risk.can_accept(trade_risk, symbol=self._symbol)
            if not ok:
                self._latch_or_signal_block(signal, why, bar.time)
                if self._set_last_rejected_bar_index is not None:
                    self._set_last_rejected_bar_index()
                return False
            if not portfolio_risk.register_open(trade_risk, symbol=self._symbol):
                self._latch_or_signal_block(
                    signal, "portfolio cap breached between can_accept and register", bar.time,
                )
                if self._set_last_rejected_bar_index is not None:
                    self._set_last_rejected_bar_index()
                return False
            self._set_open_trade_risk(trade_risk)

        return True

    # ---------------------------------------------------------------------
    # Forecast
    # ---------------------------------------------------------------------

    def _fresh_forecast(self) -> Any:
        """Return the cached TimesFM forecast or None."""
        if self._forecast_fn is None:
            return None
        return self._forecast_fn()
