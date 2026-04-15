"""SessionEventRouter — Routes trading events to appropriate handlers.

Responsibilities:
- Route tick events to handlers (LLM, gate coordinator, exit handler)
- Coordinate agent pipeline execution
- Execute entry signals via EntryCoordinator
- Handle exit callbacks via ExitCoordinator
"""

from __future__ import annotations

import logging
import time as _time_mod
from typing import TYPE_CHECKING, Any

from app.config import settings
from app.domain.constants import (
    AGENT_DECISION_THRESHOLD,
    CONFIDENCE_HIGH_THRESHOLD,
)

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC, OrderBook, AMTResult
    from app.application.handlers.llm_entry_handler import LLMEntryHandler
    from app.application.handlers.trade_lifecycle_handler import TradeLifecycleHandler
    from app.application.handlers.llm_overseer_handler import LLMOverseerHandler
    from app.application.services.session_cache import SessionCache
    from app.application.services.entry_coordinator import EntryCoordinator
    from app.application.services.exit_coordinator import ExitCoordinator
    from app.domain.ports.broker import IBroker
    from app.domain.ports.storage import IStorage
    from app.application.services.session_risk_coordinator import SessionRiskCoordinator

log = logging.getLogger(__name__)


class SessionEventRouter:
    """Routes trading events to appropriate handlers.

    This class encapsulates all event routing logic that was previously in
    TradingSession. It provides a clean API for:
    - Running the micro-agent pipeline
    - Routing to overseer handler
    - Executing entry paths
    - Handling exit callbacks
    """

    def __init__(
        self,
        lifecycle_handler: TradeLifecycleHandler,
        llm_handler: LLMEntryHandler,
        overseer_handler: LLMOverseerHandler,
        entry_coordinator: EntryCoordinator,
        exit_coordinator: ExitCoordinator,
        broker: IBroker,
        storage: IStorage | None,
        risk_coordinator: SessionRiskCoordinator,
        probability_engine: Any,
        exchange_config: Any,
        exchange: str,
        allow_short: bool,
        gate_tracker: Any = None,
        signal_tracker: Any = None,
        scalp_enabled: bool = False,
    ) -> None:
        """Initialize the event router.

        Args:
            lifecycle_handler: Handler for trade lifecycle events
            llm_handler: Handler for LLM entry decisions
            overseer_handler: Handler for position oversight
            entry_coordinator: Coordinator for entry execution
            exit_coordinator: Coordinator for exit handling
            broker: Broker port for order execution
            storage: Storage port for persistence
            risk_coordinator: Coordinator for risk management
            probability_engine: Engine for probability inference
            exchange_config: Exchange configuration
            exchange: Exchange name (MCX, NSE, etc.)
            allow_short: Whether short positions are allowed
            gate_tracker: Optional tracker for gate rejections
            signal_tracker: Optional tracker for signals
            scalp_enabled: Whether scalping engine is enabled
        """
        self._lifecycle_handler = lifecycle_handler
        self._llm_handler = llm_handler
        self._overseer_handler = overseer_handler
        self._entry_coordinator = entry_coordinator
        self._exit_coordinator = exit_coordinator
        self._broker = broker
        self._storage = storage
        self._risk_coordinator = risk_coordinator
        self._probability_engine = probability_engine
        self._exchange_config = exchange_config
        self._exchange = exchange
        self._allow_short = allow_short
        self._gate_tracker = gate_tracker
        self._signal_tracker = signal_tracker
        self._scalp_enabled = scalp_enabled

    # ----- Agent Pipeline Routing -----

    def run_micro_agent_pipeline(
        self,
        event: Any,
        amt_result: AMTResult,
        exchange_config: Any,
    ) -> Any:
        """Run the micro-agent (LightGBM) pipeline for agent decision.

        Args:
            event: TickReceived event
            amt_result: AMT analysis result
            exchange_config: Exchange configuration for tick size

        Returns:
            AgentDecision or None
        """
        from app.shared.parsing import is_mcx_symbol

        if not self._probability_engine.is_ready() or len(list(event.data)) < 20:
            return None
        try:
            from app.domain.probability.features import extract_features
            from app.domain.probability.agent_pipeline import run_agent_pipeline

            is_mcx = is_mcx_symbol(event.symbol)
            features = extract_features(
                list(event.data),
                amt_result,
                event.tick,
                event.order_book,
                is_mcx=is_mcx,
            )
            tick_size = (
                exchange_config.get_tick_size(event.symbol)
                if exchange_config
                else 0.05
            )
            agent_decision = run_agent_pipeline(
                data=list(event.data),
                amt_result=amt_result,
                tick=event.tick,
                probability_engine=self._probability_engine,
                features=features,
                order_book=event.order_book,
                tick_size=tick_size,
                symbol=event.symbol,
                tick_age_seconds=1.0,
            )
            log.info(
                "Agent pipeline [%s]: dir=%s P=%.3f regime=%s timing=%s kelly=%.1f%% (%dus) — %s",
                event.symbol,
                agent_decision.direction,
                agent_decision.probability,
                agent_decision.regime,
                agent_decision.timing,
                agent_decision.size_fraction * 100,
                agent_decision.latency_us,
                agent_decision.rationale,
            )
            return agent_decision
        except (ValueError, RuntimeError) as e:
            log.warning(
                "Agent pipeline error for %s: %s",
                event.symbol,
                e,
                exc_info=True,
            )
            return None

    # ----- Overseer Routing -----

    def run_overseer_if_needed(
        self,
        session: Any,
        event: Any,
        amt_result: AMTResult,
        exchange: str,
    ) -> None:
        """Run overseer handler if positions exist.

        Args:
            session: Session state
            event: TickReceived event
            amt_result: AMT analysis result
            exchange: Exchange name
        """
        if not self._lifecycle_handler.has_managed_positions(event.symbol):
            return

        _mkt = exchange
        if _mkt in ("NFO", "BSE"):
            _mkt = "NSE"
        from app.domain.fabio_ai.services.session_context import (
            get_session_info as _get_si,
        )

        _si = _get_si(timestamp=event.tick.time, market=_mkt)
        _fp_candle = None
        _fp_domain = getattr(session, "_last_fp_domain", None)
        if _fp_domain:
            try:
                _fp_vals = (
                    list(_fp_domain.values())
                    if isinstance(_fp_domain, dict)
                    else None
                )
                _fp_candle = _fp_vals[-1] if _fp_vals else None
            except Exception:
                log.debug("Silent exception handled", exc_info=True)
        self._overseer_handler.run_overseer(
            session,
            event.symbol,
            event.tick,
            amt_result,
            session_info=_si,
            footprint_candle=_fp_candle,
        )

    # ----- LLM Trigger Check -----

    def should_trigger_llm(
        self,
        session: Any,
        has_position: bool,
        ai_running: bool,
        in_cooldown: bool,
        amt_result: AMTResult,
        event: Any,
        ai_time: float,
    ) -> bool:
        """Determine if LLM entry trigger should run.

        Args:
            session: Session state
            has_position: Whether there's an open position
            ai_running: Whether AI is currently running
            in_cooldown: Whether in cooldown period
            amt_result: AMT analysis result
            event: TickReceived event
            ai_time: Last AI run timestamp

        Returns:
            True if LLM should be triggered
        """
        return self._llm_handler.should_run(
            last_ai_time=ai_time,
            ai_running=ai_running,
            has_position=has_position,
            has_managed_positions=self._lifecycle_handler.has_managed_positions(
                event.symbol
            ),
            in_cooldown=in_cooldown,
            last_entry_time=session._last_entry_time,
            data=session.data,
            amt_result=amt_result,
            tick=event.tick,
            order_book=event.order_book,
        )

    def trigger_llm_entry(
        self,
        session: Any,
        symbol: str,
        tick: OHLC,
        amt_result: AMTResult,
    ) -> None:
        """Trigger LLM entry handler.

        Args:
            session: Session state
            symbol: Trading symbol
            tick: Current tick
            amt_result: AMT analysis result
        """
        self._llm_handler.run_entry(session, symbol, tick, amt_result)

    # ----- Entry Path Execution -----

    def execute_entry_path(
        self,
        event: Any,
        session: Any,
        amt_result: AMTResult,
        exec_dir: str,
        exec_prob: float,
        run_entry: bool,
        exchange_config: Any,
        allow_short: bool,
        risk_coordinator: SessionRiskCoordinator,
        scalp_enabled: bool,
    ) -> None:
        """Execute entry path: gate pipeline, SHORT gates, signal build, persist.

        Args:
            event: TickReceived event
            session: Session state
            amt_result: AMT analysis result
            exec_dir: Execution direction (LONG/SHORT)
            exec_prob: Execution probability
            run_entry: Whether entry should run
            exchange_config: Exchange configuration
            allow_short: Whether short positions allowed
            risk_coordinator: Risk coordinator for checks
            scalp_enabled: Whether scalping is enabled
        """
        _last_exec_mono = getattr(session, "_last_exec_mono", 0)
        _time_since_last = _time_mod.monotonic() - _last_exec_mono
        _can_execute = _time_since_last > 60

        if run_entry and _can_execute:
            srm = risk_coordinator.get_session_risk_manager(event.symbol)
            if srm and not srm.can_trade:
                log.info(
                    "ENTRY BLOCKED: %s — session risk: %s",
                    event.symbol,
                    srm.halt_reason,
                )
                return

            from app.domain.fabio_ai.services.entry_gate import run_gate_pipeline

            tick_size = (
                exchange_config.get_tick_size(event.symbol)
                if exchange_config
                else 0.05
            )

            gate_passed, gate_reason, gate_detail = run_gate_pipeline(
                data=list(event.data),
                amt_result=amt_result,
                tick=event.tick,
                market_state=amt_result.market_state,
                drive_number=getattr(amt_result, "drive_number", 0),
                drive_entry_valid=getattr(amt_result, "drive_entry_valid", False),
                aggression_score=amt_result.aggression,
                is_risk_halted=False,
                halt_reason="",
                tick_age_seconds=1.0,
                symbol=event.symbol,
                max_distance_to_level_ticks=exchange_config.max_distance_to_level_ticks
                if exchange_config
                else 3.0,
                probing_aggression_threshold=0.0,
                min_aggression_score=0.0,
                max_cushion_ticks=500.0,
                min_rr_ratio=0.1,
                tick_size=tick_size,
            )

            if gate_passed:
                if self._gate_tracker:
                    self._gate_tracker.record(event.symbol, "gate_pipeline", True)

                if exec_dir == "SHORT":
                    from app.domain.services.short_signal_gates import (
                        evaluate_short_gates,
                    )

                    short_ok, short_results = evaluate_short_gates(
                        short_enabled=getattr(settings, "SHORT_SIGNALS_ENABLED", False),
                        market_state=amt_result.market_state,
                        displacement_direction=getattr(
                            amt_result, "displacement_direction", ""
                        ),
                        failed_breakout=getattr(amt_result, "failed_breakout", False),
                        playbook=str(amt_result.setup or "return_to_value"),
                        ml_probability=exec_prob,
                        bid_volume=float(getattr(amt_result, "bid_volume", 0)),
                        ask_volume=float(getattr(amt_result, "ask_volume", 0)),
                        cvd_slope=float(getattr(amt_result, "cvd_slope", 0)),
                        delta_normalized=float(
                            getattr(amt_result, "delta_normalized", 0)
                        ),
                        contract_type="PE",
                    )
                    if not short_ok:
                        failed_gate = next(r for r in short_results if not r.passed)
                        log.info(
                            "SHORT BLOCKED: %s — %s (%s)",
                            event.symbol,
                            failed_gate.gate_name,
                            failed_gate.reason,
                        )
                        gate_passed = False
                        if self._gate_tracker:
                            self._gate_tracker.record(
                                event.symbol, failed_gate.gate_name, False
                            )

            if gate_passed:
                signal = self._build_entry_signal(
                    exec_dir,
                    event.tick,
                    amt_result,
                    exec_prob,
                    session,
                    tick_size,
                    scalp_enabled,
                    srm,
                    list(event.data),
                )
                if signal:
                    session._last_entry_candle_time = event.tick.time
                    session._last_exec_mono = _time_mod.monotonic()
                    log.info(
                        "EXECUTING: %s dir=%s P=%.3f via AMT pipeline",
                        event.symbol,
                        exec_dir,
                        exec_prob,
                    )
                    self._entry_coordinator.execute_signal(event.symbol, signal, session)
                    with session._lock:
                        session._pending_decision = None
                        session._pending_amt = None
                        session._pending_tick = None
                else:
                    log.info(
                        "ENTRY BLOCKED: %s — signal construction failed", event.symbol
                    )
            else:
                log.info(
                    "ENTRY BLOCKED: %s — gate %s (%s): %s",
                    event.symbol,
                    gate_passed,
                    gate_reason,
                    gate_detail,
                )
                if self._gate_tracker:
                    self._gate_tracker.record(
                        event.symbol, f"gate_{gate_passed}", False
                    )

            self._persist_gate_decision(
                event,
                amt_result,
                exec_dir,
                exec_prob,
                gate_passed,
                gate_reason,
                gate_detail,
            )
        elif run_entry and not _can_execute:
            log.debug(
                "COOLDOWN: %s waiting %.0fs before next trade",
                event.symbol,
                60 - _time_since_last,
            )

    def _build_entry_signal(
        self,
        exec_dir: str,
        tick: OHLC,
        amt_result: AMTResult,
        exec_prob: float,
        session: Any,
        tick_size: float,
        scalp_enabled: bool,
        srm: Any,
        data: list,
    ) -> Any:
        """Build an entry signal from the execution parameters.

        Args:
            exec_dir: Execution direction
            tick: Current tick
            amt_result: AMT result
            exec_prob: Execution probability
            session: Session state
            tick_size: Tick size for the instrument
            scalp_enabled: Whether scalping is enabled
            srm: Session risk manager
            data: Candle data

        Returns:
            Signal or None
        """
        from app.domain.fabio_ai.services.entry_gate import build_entry_signal

        return build_entry_signal(
            direction=exec_dir,
            tick=tick,
            amt_result=amt_result,
            ai_result={
                "rationale": f"AMT pipeline: {amt_result.market_state} {amt_result.aggression:.1f} aggression",
                "confidence": "High"
                if exec_prob >= CONFIDENCE_HIGH_THRESHOLD
                else "Medium",
                "market_state": amt_result.market_state,
            },
            setup_type=amt_result.setup or "MEAN_REVERSION",
            data=data,
            session_context=getattr(session._last_session_info, "session", ""),
            confidence="High"
            if exec_prob >= CONFIDENCE_HIGH_THRESHOLD
            else "Medium",
            tick_size=tick_size,
            inside_extreme=scalp_enabled,
            risk_sl_pct=srm.stop_loss_pct if srm else None,
        )

    def _persist_gate_decision(
        self,
        event: Any,
        amt_result: AMTResult,
        exec_dir: str,
        exec_prob: float,
        gate_passed: bool,
        gate_reason: str | None,
        gate_detail: str | None,
    ) -> None:
        """Persist gate decision via injected signal tracker.

        Args:
            event: TickReceived event
            amt_result: AMT result
            exec_dir: Execution direction
            exec_prob: Execution probability
            gate_passed: Whether gate passed
            gate_reason: Gate rejection reason
            gate_detail: Gate detail message
        """
        if not self._signal_tracker:
            return
        try:
            if gate_passed:
                self._signal_tracker.track_signal_generated(
                    symbol=event.symbol,
                    direction=exec_dir,
                    confidence="High"
                    if exec_prob >= CONFIDENCE_HIGH_THRESHOLD
                    else "Medium",
                    aggression_score=float(amt_result.aggression),
                    drive_number=getattr(amt_result, "drive_number", 0),
                    market_state=amt_result.market_state,
                    price=float(event.tick.close),
                    poc=float(amt_result.poc),
                    vah=float(amt_result.value_area_high),
                    val=float(amt_result.value_area_low),
                    cvd_slope=float(amt_result.cvd_slope),
                )
            else:
                self._signal_tracker.track_gate_block(
                    symbol=event.symbol,
                    gate_name=f"GATE_{gate_passed}",
                    gate_reason=gate_reason or "FLAT",
                    gate_detail=gate_detail or "",
                    market_state=amt_result.market_state,
                    price=float(event.tick.close),
                    poc=float(amt_result.poc),
                    vah=float(amt_result.value_area_high),
                    val=float(amt_result.value_area_low),
                    cvd_slope=float(amt_result.cvd_slope),
                    aggression_score=float(amt_result.aggression),
                )
        except Exception:
            pass  # Non-critical — tracking failure should not break pipeline

    # ----- Signal Execution -----

    def execute_signal(self, symbol: str, signal: Any, session: Any) -> None:
        """Execute a trade signal.

        Args:
            symbol: Trading symbol
            signal: Signal to execute
            session: Session state
        """
        self._entry_coordinator.execute_signal(symbol, signal, session)

    # ----- Exit Callbacks -----

    def on_partial_exit(
        self,
        pos_id: str,
        side: str,
        entry_price: float,
        exit_price: float,
        partial_pct: float,
        size_closed: float,
        size_remaining: float,
        realized_pnl: float,
    ) -> None:
        """Handle partial exit callback.

        Args:
            pos_id: Position ID
            side: Position side
            entry_price: Entry price
            exit_price: Exit price
            partial_pct: Percentage of position closed
            size_closed: Size closed
            size_remaining: Size remaining
            realized_pnl: Realized PnL
        """
        self._exit_coordinator.on_partial_exit(
            pos_id,
            side,
            entry_price,
            exit_price,
            partial_pct,
            size_closed,
            size_remaining,
            realized_pnl,
        )

    def on_stop_out(
        self,
        level: float,
        direction: str,
        symbol: str,
        exchange: str,
    ) -> None:
        """Handle stop out callback.

        Args:
            level: Stop level
            direction: Position direction
            symbol: Trading symbol
            exchange: Exchange name
        """
        self._exit_coordinator.on_stop_out(level, direction, symbol, exchange)

    def on_trade_closed(
        self,
        symbol: str,
        pnl: float,
        pos_id: str | None,
        session: Any,
    ) -> None:
        """Handle trade closed callback.

        Args:
            symbol: Trading symbol
            pnl: Realized PnL
            pos_id: Position ID
            session: Session state
        """
        if session and session.portfolio:
            self._risk_coordinator.record_trade_result(
                symbol, pnl, session.portfolio
            )
        self._exit_coordinator.on_position_closed(symbol, pos_id)

        # Delete from persistent storage
        if self._storage:
            try:
                delete_id = pos_id or symbol
                self._storage.delete_open_position(delete_id)
            except Exception as e:
                log.error("Failed to delete closed position %s: %e", pos_id or symbol, e)
