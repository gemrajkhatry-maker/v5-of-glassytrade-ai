"""SessionEventRouter — Routes trading events to appropriate handlers.

Responsibilities:
- Route tick events to handlers (LLM, gate coordinator, exit handler)
- Coordinate agent pipeline execution
- Execute entry signals via EntryCoordinator
- Handle exit callbacks via ExitCoordinator
"""

from __future__ import annotations

from dataclasses import replace
import logging
import time as _time_mod
from typing import TYPE_CHECKING, Any

from app.config import settings
from app.shared.config_features import Feature, feature_enabled
from app.domain.constants import (
    AGENT_DECISION_THRESHOLD,
    CONFIDENCE_HIGH_THRESHOLD,
)
from app.core.async_boundary import ensure_sync_adapter_result
from app.shared.parsing import is_mcx_symbol
from app.domain.probability.features import extract_features
from app.domain.probability.agent_pipeline import run_agent_pipeline
from app.domain.probability.regime_hysteresis_store import RegimeHysteresisStore
from app.domain.constants import MIN_AGGRESSION_SCORE, MAX_CUSHION_TICKS, MIN_RR_RATIO
from app.domain.fabio_ai.services.session_context import get_session_info as _get_si
from app.domain.fabio_ai.services.entry_gates.gate_runner import run_gate_pipeline
from app.domain.fabio_ai.services.entry_gates.signal_builder import build_entry_signal
from app.domain.services.short_signal_gates import evaluate_short_gates

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
        self._regime_hysteresis_store = RegimeHysteresisStore()

    @staticmethod
    def _is_critical_amt_inflection(
        symbol: str,
        amt_result: AMTResult,
        live_price: float,
    ) -> bool:
        """Check if price is at a critical AMT inflection point requiring priority evaluation.

        Fabio AMT: when price is at IB High/Low with extreme VWAP deviation,
        the probability engine must NEVER be silent.
        """
        ib_high = amt_result.ib_high
        ib_low = amt_result.ib_low
        vwap_dev = amt_result.vwap_deviation_sigmas or 0.0
        has_acceptance = amt_result.acceptance_above or amt_result.acceptance_below

        # At IB High/Low test (within 1%)
        at_ib_high = ib_high > 0 and abs(live_price - ib_high) / ib_high < 0.01
        at_ib_low = ib_low > 0 and abs(live_price - ib_low) / ib_low < 0.01

        # Extreme VWAP deviation
        is_extreme = abs(vwap_dev) >= 2.0

        return (at_ib_high or at_ib_low) and (is_extreme or has_acceptance)

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
        _series = (
            list(event.agent_series)
            if len(getattr(event, "agent_series", ())) >= 20
            else list(event.data)
        )
        _use_underlying_series = len(getattr(event, "agent_series", ())) >= 20

        # Fabio AMT: Priority trigger for critical inflection points
        _tick_price = event.tick.close if event.tick else 0
        is_critical_inflection = self._is_critical_amt_inflection(
            event.symbol, amt_result, _tick_price,
        )

        if not self._probability_engine.is_ready():
            if is_critical_inflection:
                log.warning(
                    "CRITICAL: %s at IB extreme but probability engine not ready",
                    event.symbol,
                )
            return None

        if len(_series) < 20 and not is_critical_inflection:
            return None

        # At critical inflection points, log priority evaluation
        if is_critical_inflection and len(_series) < 20:
            log.info(
                "PRIORITY TRIGGER: %s at critical AMT inflection — forcing evaluation with %d candles",
                event.symbol,
                len(_series),
            )
        try:
            is_mcx = is_mcx_symbol(event.symbol)
            _regime_tick = _series[-1] if _use_underlying_series else event.tick
            features = extract_features(
                _series,
                amt_result,
                event.tick,
                event.order_book,
                is_mcx=is_mcx,
                align_volume_with_data=_use_underlying_series,
            )
            tick_size = (
                exchange_config.get_tick_size(event.symbol)
                if exchange_config
                else 0.05
            )
            agent_decision = run_agent_pipeline(
                data=_series,
                amt_result=amt_result,
                tick=_regime_tick,
                probability_engine=self._probability_engine,
                features=features,
                order_book=event.order_book,
                tick_size=tick_size,
                symbol=event.symbol,
                tick_age_seconds=1.0,
                hysteresis_store=self._regime_hysteresis_store,
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
        if not self._lifecycle_handler.has_managed_positions(
            event.symbol, session.portfolio
        ):
            return

        with session._lock:
            last_overseer_time = session._last_overseer_time
            overseer_running = session._overseer_running
            ai_running = session._ai_running

        # Enforce the 15s cooldown + single-flight guard BEFORE enqueuing.
        # Previously the old unused run_overseer var (trading_session.py:839)
        # computed this but nothing consumed it — overseer fired every tick.
        if not self._overseer_handler.should_run(
            last_overseer_time=last_overseer_time,
            overseer_running=overseer_running,
            ai_running=ai_running,
            has_position=True,
        ):
            return

        # Snapshot session risk state so the worker can render a complete
        # [Risk] section in the overseer prompt (risk_tier, daily_pnl,
        # consecutive_losses, daily_loss_pct).
        risk_state: dict = {}
        try:
            srm = self._risk_coordinator.get_session_risk_manager(event.symbol)
            capital = float(getattr(settings, "CAPITAL", 0.0) or 0.0)
            risk_state = {
                "risk_tier": srm.risk_tier.name,
                "daily_pnl": float(srm.session_pnl),
                "consecutive_losses": int(srm.consecutive_losses),
                "daily_loss_pct": (
                    float(srm.session_pnl) / capital if capital > 0 else 0.0
                ),
            }
        except Exception:
            log.debug("Risk state unavailable for overseer — using defaults", exc_info=True)

        _mkt = exchange
        if _mkt in ("NFO", "BSE"):
            _mkt = "NSE"
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
                log.debug("Footprint candle extraction failed for overseer", exc_info=True)
        self._overseer_handler.run_overseer(
            session,
            event.symbol,
            event.tick,
            amt_result,
            session_info=_si,
            footprint_candle=_fp_candle,
            risk_state=risk_state,
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
                event.symbol, session.portfolio
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
            scalp_enabled: Whether scalping is enabled
        """
        _last_exec_mono = getattr(session, "_last_exec_mono", 0)
        _time_since_last = _time_mod.monotonic() - _last_exec_mono
        _can_execute = _time_since_last > 60

        # Candle-close cursor: advance on EVERY closed candle so is_new_candle
        # stays meaningful regardless of gate outcomes (audit defect C.2). The
        # previous write lived inside the signal-build branch and was never
        # reached when gates blocked, making is_new_candle always True.
        session._last_entry_candle_time = event.tick.time

        if run_entry and _can_execute:
            srm = self._risk_coordinator.get_session_risk_manager(event.symbol)
            if srm and not srm.can_trade:
                log.info(
                    "ENTRY BLOCKED: %s — session risk: %s",
                    event.symbol,
                    srm.halt_reason,
                )
                return

            tick_size = (
                exchange_config.get_tick_size(event.symbol)
                if exchange_config
                else 0.05
            )
            cvd_slope = float(getattr(amt_result, "cvd_slope", 0.0))
            aggression_score = float(getattr(amt_result, "aggression", 0.0))
            cvd_conflict = (
                (exec_dir == "LONG" and cvd_slope < 0.0)
                or (exec_dir == "SHORT" and cvd_slope > 0.0)
            )

            (
                gate_passed,
                gate_reason,
                gate_detail,
                soft_gates_passed,
                soft_gates_total,
            ) = run_gate_pipeline(
                data=list(event.data),
                amt_result=amt_result,
                tick=event.tick,
                market_state=amt_result.market_state,
                drive_number=getattr(amt_result, "drive_number", 0),
                drive_entry_valid=getattr(amt_result, "drive_entry_valid", False),
                aggression_score=aggression_score,
                cvd_conflict=cvd_conflict,
                is_risk_halted=False,
                halt_reason="",
                tick_age_seconds=1.0,
                symbol=event.symbol,
                max_distance_to_level_ticks=exchange_config.max_distance_to_level_ticks
                if exchange_config
                else 3.0,
                probing_aggression_threshold=MIN_AGGRESSION_SCORE,
                min_aggression_score=MIN_AGGRESSION_SCORE,
                max_cushion_ticks=MAX_CUSHION_TICKS,
                min_rr_ratio=MIN_RR_RATIO,
                tick_size=tick_size,
                pcr=getattr(amt_result, "pcr", 1.0),  # Pass PCR for NSE options bias
                oi_walls=getattr(amt_result, "oi_walls", []),  # Pass OI walls for NSE protection levels
                favor_strategy=getattr(amt_result, "session_favor_strategy", "NEUTRAL"),  # Session strategy filter
            )
            session.aggressionBlocked = (
                cvd_conflict
                and not gate_passed
                and aggression_score < MIN_AGGRESSION_SCORE
            )
            session.last_gate_score = {
                "passed": soft_gates_passed,
                "total": soft_gates_total,
            }

            if gate_passed:
                if scalp_enabled:
                    from app.domain.services.scalp_gate_pipeline import ScalpContext, evaluate_scalp_gates

                    mtf_bias = getattr(amt_result, "mtf_alignment", "")
                    if not mtf_bias:
                        mtf_bias = getattr(amt_result, "session_favor_strategy", "")
                    scalp_ctx = ScalpContext(
                        symbol=event.symbol,
                        current_time=event.tick.time,
                        mtf_bias=mtf_bias,
                        distance_to_level_ticks=getattr(amt_result, "cushion_ticks", 0.0),
                        risk_tier=(
                            getattr(srm.risk_tier, "name", "NORMAL")
                            if srm
                            else "NORMAL"
                        ),
                        portfolio_utilization=(
                            session.portfolio.utilization
                            if hasattr(session.portfolio, "utilization")
                            else 0.0
                        ),
                        open_positions=sum(
                            1 for pos in session.portfolio.positions if pos.is_open
                        ),
                        position_size=sum(
                            float(getattr(pos, "size", 0.0))
                            for pos in session.portfolio.positions
                            if pos.is_open
                        ),
                    )
                    scalp_results = evaluate_scalp_gates(scalp_ctx)
                    scalp_failures = [r for r in scalp_results if not r.passed]
                    if scalp_failures:
                        gate_passed = False
                        gate_reason = "Scalp gate checks failed"
                        gate_detail = "; ".join(
                            f"{result.gate.value}:{result.detail}" for result in scalp_failures
                        )
                        log.info(
                            "SCALP BLOCKED: %s — %s",
                            event.symbol,
                            gate_detail,
                        )
                        if self._gate_tracker:
                            self._gate_tracker.record(
                                event.symbol, "scalp_gate_pipeline", False
                            )
                if gate_passed and self._gate_tracker:
                    self._gate_tracker.record(event.symbol, "gate_pipeline", True)

                if exec_dir == "SHORT":
                    short_ok, short_results = evaluate_short_gates(
                        short_enabled=feature_enabled(settings, Feature.SHORT_SIGNALS),
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
                _tick_trace_id = getattr(event, "tick_trace_id", "")
                if _tick_trace_id:
                    _meta = signal.metadata if isinstance(signal.metadata, dict) else {}
                    signal.metadata = _meta
                    signal.metadata["tick_trace_id"] = _tick_trace_id
                if signal:
                    session._last_exec_mono = _time_mod.monotonic()
                    ad = getattr(session, "_agent_decision", None)
                    if ad is not None:
                        try:
                            session._agent_decision = replace(
                                ad,
                                stop_loss=float(signal.stop_loss),
                                take_profit=float(signal.take_profit),
                            )
                        except Exception:
                            log.debug(
                                "Failed to persist signal stop/tp into agent decision",
                                exc_info=True,
                            )
                    log.info(
                        "EXECUTING: %s dir=%s P=%.3f via AMT pipeline",
                        event.symbol,
                        exec_dir,
                        exec_prob,
                    )
                    self._entry_coordinator.execute_signal(
                        event.symbol,
                        signal,
                        session,
                    )
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
                tick_trace_id=getattr(event, "tick_trace_id", ""),
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
            session_risk_pct=getattr(srm, "stop_loss_pct", None) if srm else None,
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
        tick_trace_id: str = "",
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
                    tick_trace_id=tick_trace_id,
                )
            else:
                self._signal_tracker.track_gate_block(
                    symbol=event.symbol,
                    gate_name=gate_reason or "GATE_BLOCKED",
                    gate_reason=gate_reason or "FLAT",
                    gate_detail=gate_detail or "",
                    market_state=amt_result.market_state,
                    price=float(event.tick.close),
                    poc=float(amt_result.poc),
                    vah=float(amt_result.value_area_high),
                    val=float(amt_result.value_area_low),
                    cvd_slope=float(amt_result.cvd_slope),
                    aggression_score=float(amt_result.aggression),
                    tick_trace_id=tick_trace_id,
                )
        except Exception:
            log.debug("AMT tracking failed (non-critical)", exc_info=True)

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
        self._exit_coordinator.on_position_closed(symbol, pos_id, session=session)

        # Delete from persistent storage
        if self._storage:
            try:
                delete_id = pos_id or symbol
                ensure_sync_adapter_result(
                    "storage.delete_open_position",
                    self._storage.delete_open_position,
                    delete_id,
                )
            except Exception as e:
                log.error("Failed to delete closed position %s: %e", pos_id or symbol, e)
