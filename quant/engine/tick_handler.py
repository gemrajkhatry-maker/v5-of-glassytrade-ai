"""Tick handler — processes incoming market ticks.

Extracted from QuantEngine._run_inner() for maintainability.
Handles both option contracts (with underlying feed) and direct futures.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from math import isfinite
from typing import TYPE_CHECKING, Any, Callable

from quant.contracts.ports.telemetry import NULL_TELEMETRY
from quant.contracts.timezones import parse_bar_time

if TYPE_CHECKING:
    from quant.aggregator import BarAggregator
    from quant.amt_engine import AMTEngine
    from quant.state_machine import EngineState

logger = logging.getLogger(__name__)


def amt_observation_is_fresh(
    amt_dto: Mapping[str, Any] | None,
    decision_bar: Any,
    interval_seconds: Any,
    *,
    snapshot: Any | None = None,
) -> bool:
    """Apply the live-feed one-macro-bar freshness contract."""
    dto_time_value = (
        amt_dto.get("time")
        if isinstance(amt_dto, Mapping)
        else getattr(amt_dto, "time", None)
    )
    dto_time = parse_bar_time(
        dto_time_value or getattr(snapshot, "asof_time", None)
    )
    decision_time = parse_bar_time(getattr(decision_bar, "time", None))
    try:
        macro_seconds = int(interval_seconds)
    except (TypeError, ValueError, OverflowError):
        return False
    if dto_time is None or decision_time is None or macro_seconds <= 0:
        return False
    age_seconds = (decision_time - dto_time).total_seconds()
    return 0.0 <= age_seconds < 2 * macro_seconds


def underlying_observation_is_valid(bar: Any, amt_dto: Any) -> bool:
    """Require a timestamped, positive-price bar and meaningful AMT DTO."""
    if bar is None or not isinstance(amt_dto, Mapping) or not amt_dto:
        return False
    if parse_bar_time(getattr(bar, "time", None)) is None:
        return False
    try:
        close = float(getattr(bar, "close", 0.0) or 0.0)
    except (TypeError, ValueError, OverflowError):
        return False
    if not isfinite(close) or close <= 0.0:
        return False
    for key in ("poc", "valueAreaHigh", "valueAreaLow"):
        try:
            value = float(amt_dto.get(key, 0.0) or 0.0)
        except (TypeError, ValueError, OverflowError):
            continue
        if isfinite(value) and value > 0.0:
            return True
    return False


class TickHandler:
    """Processes incoming market ticks and orchestrates bar aggregation.
    
    Responsibilities:
    - Feed ticks to bar aggregators (macro and micro)
    - Trigger AMT analysis on bar close
    - Invoke decision evaluation at appropriate cadences
    - Manage tick-level exits for open positions
    - Handle both option contracts (with underlying feed) and direct futures
    
    This extraction captures the tick processing loop from QuantEngine._run_inner()
    (lines 761-854) for better testability and maintainability.
    """
    
    def __init__(
        self,
        symbol: str,
        macro_aggregator: BarAggregator,
        micro_aggregator: BarAggregator | None,
        amt_engine: AMTEngine,
        state_getter: Callable[[], EngineState],
        # Callbacks for delegation
        manage_tick_exit_callback: Callable[[float, str], None],
        decide_callback: Callable[[dict, Any, Any], None],
        on_bar_closed_callback: Callable[[Any], None],
        manage_exit_callback: Callable[[dict, Any], None],
        # Option-specific (None for futures)
        underlying_gateway: Any | None = None,
        underlying_aggregator: BarAggregator | None = None,
        micro_underlying_aggregator: BarAggregator | None = None,
        option_amt_engine: AMTEngine | None = None,
        # Live quote and depth updates
        live_quote_callback: Callable[[str, Any, Any], None] | None = None,
        depth_callback: Callable[[Any], None] | None = None,
        # Hotpath tracing
        hotpath_callback: Callable[[str, str, str, float, str], None] | None = None,
        # State tracking (for underlying bar updates)
        underlying_bar_setter: Callable[[Any], None] | None = None,
        underlying_amt_dto_setter: Callable[[dict], None] | None = None,
        option_amt_dto_setter: Callable[[dict], None] | None = None,
        bar_index_increaser: Callable[[], None] | None = None,
        bar_closed_emitter: Callable[[str, str, Any], None] | None = None,
        merged_amt_emitter: Callable[[dict, str], None] | None = None,
        # Range-mode live warmup (plan T8): only fires when micro is range-built
        range_tick_callback: Callable[[Any], None] | None = None,
        range_bar_closed_callback: Callable[[], None] | None = None,
        # Host-installed sink: record_tick() moves ticks_processed_total
        # once per real tick (default: no-op for bare embeddings).
        telemetry: Any | None = None,
    ):
        self.symbol = symbol
        self._macro_aggregator = macro_aggregator
        self._micro_aggregator = micro_aggregator
        self._amt_engine = amt_engine
        self._get_state = state_getter
        
        # Callbacks
        self._manage_tick_exit = manage_tick_exit_callback
        self._decide = decide_callback
        self._on_bar_closed = on_bar_closed_callback
        self._manage_exit = manage_exit_callback
        
        # Option-specific
        self._underlying_gateway = underlying_gateway
        self._underlying_aggregator = underlying_aggregator
        self._micro_underlying_aggregator = micro_underlying_aggregator
        self._option_amt_engine = option_amt_engine
        
        # Live quote and depth
        self._live_quote_callback = live_quote_callback
        self._depth_callback = depth_callback
        
        # Hotpath
        self._hotpath_callback = hotpath_callback
        
        # State tracking
        self._underlying_bar_setter = underlying_bar_setter
        self._underlying_amt_dto_setter = underlying_amt_dto_setter
        self._option_amt_dto_setter = option_amt_dto_setter
        self._bar_index_increaser = bar_index_increaser
        self._bar_closed_emitter = bar_closed_emitter
        self._merged_amt_emitter = merged_amt_emitter
        self._range_tick_callback = range_tick_callback
        self._range_bar_closed_callback = range_bar_closed_callback
        if telemetry is None:
            telemetry = NULL_TELEMETRY
        self.telemetry = telemetry
        
        # Cached state (for option path)
        self._last_underlying_bar = None
        self._underlying_amt_dto = None
        self._option_amt_dto = None
        self._underlying_unavailable_reported = False
        # Decision deferral counters (B-4b): reason -> count
        self._deferred_counts: dict[str, int] = {}

    def _defer_decision(self, reason: str) -> None:
        """Record a skipped decision evaluation (no behavior change)."""
        self._deferred_counts[reason] = self._deferred_counts.get(reason, 0) + 1
        logger.info(
            "DecisionDeferred reason=%s symbol=%s",
            reason, self.symbol,
        )

    def _range_micro(self) -> bool:
        return getattr(self._micro_aggregator, "range_size", None) is not None

    def _note_range_close(self, micro_bar: Any) -> None:
        """Count live range closes only — seed/synth bars never arrive here."""
        if micro_bar is not None and self._range_micro() and self._range_bar_closed_callback is not None:
            self._range_bar_closed_callback()

    def _decide_if_macro_fresh(
        self,
        amt_dto: dict,
        macro_bar: Any,
        execution_bar: Any,
        *,
        decision_bar: Any | None = None,
    ) -> bool:
        """Evaluate only while the AMT snapshot is at most one macro bar old."""
        fresh = amt_observation_is_fresh(
            amt_dto,
            decision_bar or execution_bar or macro_bar,
            getattr(self._macro_aggregator, "interval_seconds", 0),
            snapshot=getattr(self._amt_engine, "last_snapshot", None),
        )
        if not fresh:

            self._defer_decision("STALE_DTO")
            return False
        self._decide(amt_dto, macro_bar, execution_bar)
        return True

    def _report_underlying_unavailable(self, decision_bar: Any) -> None:
        if self._underlying_unavailable_reported:
            return
        decision = self._decide(
            self._underlying_amt_dto or {},
            decision_bar,
            decision_bar,
        )
        if getattr(decision, "reason", None) == "OPTION_UNDERLYING_UNAVAILABLE":
            self._underlying_unavailable_reported = True

    def _decide_at_option_boundary(self, decision_bar: Any) -> None:
        amt_dto = self._underlying_amt_dto
        underlying_bar = self._last_underlying_bar
        if (
            amt_dto
            and underlying_bar
            and underlying_observation_is_valid(underlying_bar, amt_dto)
            and self._decide_if_macro_fresh(
                amt_dto,
                underlying_bar,
                decision_bar,
            )
        ):
            self._underlying_unavailable_reported = False
            return
        self._report_underlying_unavailable(decision_bar)

    def process_tick(self, tick: Any) -> None:
        """Process a single market tick.
        
        This is the main entry point called by QuantEngine._run_inner().
        Handles both option contracts (with underlying feed) and direct futures.
        """
        self.telemetry.record_tick()
        state = self._get_state()
        
        # 0. Tick-level fast SL/TP protection
        if state.position is not None:
            self._manage_tick_exit(float(tick.price), str(tick.time))
        
        # Range-mode wall-clock start: first live tick anchors live_minutes
        if self._range_micro() and self._range_tick_callback is not None:
            self._range_tick_callback(tick)
        
        # Hotpath tracing
        if self._hotpath_callback is not None:
            self._hotpath_callback(
                self.symbol, "tick",
                str(tick.time), float(tick.price), "option",
            )

        if self._depth_callback is not None:
            self._depth_callback(getattr(tick, "depth", None))

        # Route to option or futures path
        if self._underlying_gateway is not None:
            self._process_option_tick(tick, state)
        else:
            self._process_futures_tick(tick, state)
        
        # Live quote update
        if self._live_quote_callback is not None:
            self._live_quote_callback(
                self.symbol, tick, self._macro_aggregator.current_bar
            )
        
    
    def _process_option_tick(self, tick: Any, state: Any) -> None:
        """Process tick for option contracts with underlying feed.
        
        Option ticks feed option candles, underlying ticks feed AMT auction structure.
        """
        # 1. Micro-trigger: option's own ticks feed 1-min micro aggregator
        if self._micro_aggregator is not None:
            micro_bar = self._micro_aggregator.add_tick(tick)
            self._note_range_close(micro_bar)
            if micro_bar is not None and state.position is None:
                self._decide_at_option_boundary(micro_bar)
        
        # Option's OWN ticks feed the option's 5m aggregator
        option_bar = self._macro_aggregator.add_tick(tick)
        if self._option_amt_engine is not None:
            self._option_amt_engine.on_tick(tick, self._macro_aggregator.current_bar)
        
        if option_bar is not None:
            # Bar index increment
            if self._bar_index_increaser is not None:
                self._bar_index_increaser()
            
            # Emit bar closed event
            if self._bar_closed_emitter is not None:
                self._bar_closed_emitter(self.symbol, option_bar.time, option_bar)
            
            # AMT analysis
            if self._option_amt_engine is not None:
                self._option_amt_dto = self._option_amt_engine.analyze(option_bar)
                if self._option_amt_dto_setter is not None:
                    self._option_amt_dto_setter(self._option_amt_dto)
                if self._merged_amt_emitter is not None:
                    self._merged_amt_emitter(self._option_amt_dto, option_bar.time)
                
                # Exit or entry decision
                if state.position is not None:
                    self._manage_exit(self._option_amt_dto, option_bar)
                elif self._micro_aggregator is None:
                    self._decide_at_option_boundary(option_bar)
        
        # 2. Underlying futures ticks feed the underlying aggregator and AMT engine
        if self._underlying_aggregator is not None:
            utick = self._underlying_gateway.try_next_tick()
            while utick is not None:
                # Hotpath tracing for underlying
                if self._hotpath_callback is not None:
                    self._hotpath_callback(
                        self.symbol, "tick",
                        str(utick.time), float(utick.price), "underlying",
                    )
                
                # Micro underlying aggregator
                if self._micro_underlying_aggregator is not None:
                    micro_ubar = self._micro_underlying_aggregator.add_tick(utick)
                    if micro_ubar is not None:
                        self._last_underlying_bar = micro_ubar
                        if self._underlying_bar_setter is not None:
                            self._underlying_bar_setter(micro_ubar)
                
                # Macro underlying aggregator
                ubar = self._underlying_aggregator.add_tick(utick)
                self._amt_engine.on_tick(utick, self._underlying_aggregator.current_bar)
                
                if ubar is not None:
                    self._last_underlying_bar = ubar
                    if self._underlying_bar_setter is not None:
                        self._underlying_bar_setter(ubar)
                    self._underlying_amt_dto = self._amt_engine.analyze(ubar)
                    if self._underlying_amt_dto_setter is not None:
                        self._underlying_amt_dto_setter(self._underlying_amt_dto)
                    if self._merged_amt_emitter is not None:
                        self._merged_amt_emitter(self._underlying_amt_dto, ubar.time)
                
                utick = self._underlying_gateway.try_next_tick()
    
    def _process_futures_tick(self, tick: Any, state: Any) -> None:
        """Process tick for direct futures (no underlying feed)."""
        # 1. Macro-bar aggregation: if the macro bar closes on this tick,
        # run AMT analysis first so micro decision evaluates on fresh macro context.
        bar = self._macro_aggregator.add_tick(tick)
        self._amt_engine.on_tick(tick, self._macro_aggregator.current_bar)
        if bar is not None:
            self._on_bar_closed(bar)

        # 2. Micro-trigger evaluation (using fresh macro analysis if macro closed)
        if self._micro_aggregator is not None:
            micro_bar = self._micro_aggregator.add_tick(tick)
            self._note_range_close(micro_bar)
            if micro_bar is not None and state.position is None:
                amt_dto = self._amt_engine.last_amt_dto
                if amt_dto:
                    self._decide_if_macro_fresh(
                        amt_dto, micro_bar, None, decision_bar=micro_bar
                    )
