"""Tick handler — processes incoming market ticks.

Extracted from QuantEngine._run_inner() for maintainability.
Handles both option contracts (with underlying feed) and direct futures.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from quant.aggregator import BarAggregator
    from quant.amt_engine import AMTEngine
    from quant.state_machine import EngineState

logger = logging.getLogger(__name__)


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
        
        # Cached state (for option path)
        self._last_underlying_bar = None
        self._underlying_amt_dto = None
        self._option_amt_dto = None
    
    def process_tick(self, tick: Any) -> None:
        """Process a single market tick.
        
        This is the main entry point called by QuantEngine._run_inner().
        Handles both option contracts (with underlying feed) and direct futures.
        """
        state = self._get_state()
        
        # 0. Tick-level fast SL/TP protection
        if state.position is not None:
            self._manage_tick_exit(float(tick.price), str(tick.time))
        
        # Hotpath tracing
        if self._hotpath_callback is not None:
            self._hotpath_callback(
                self.symbol, "tick",
                str(tick.time), float(tick.price), "option",
            )
        
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
        
        # Depth/book update
        if tick.depth is not None and self._depth_callback is not None:
            self._depth_callback(tick.depth)
    
    def _process_option_tick(self, tick: Any, state: Any) -> None:
        """Process tick for option contracts with underlying feed.
        
        Option ticks feed option candles, underlying ticks feed AMT auction structure.
        """
        # 1. Micro-trigger: option's own ticks feed 1-min micro aggregator
        if self._micro_aggregator is not None:
            micro_bar = self._micro_aggregator.add_tick(tick)
            if micro_bar is not None and state.position is None:
                if self._underlying_amt_dto and self._last_underlying_bar is not None:
                    self._decide(
                        self._underlying_amt_dto,
                        self._last_underlying_bar,
                        micro_bar,
                    )
        
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
                    if self._underlying_amt_dto and self._last_underlying_bar is not None:
                        self._decide(
                            self._underlying_amt_dto,
                            self._last_underlying_bar,
                            option_bar,
                        )
        
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
        # Micro-trigger evaluation
        if self._micro_aggregator is not None:
            micro_bar = self._micro_aggregator.add_tick(tick)
            if micro_bar is not None and state.position is None:
                amt_dto = self._amt_engine.last_amt_dto
                if amt_dto:
                    self._decide(amt_dto, micro_bar, None)
        
        # Macro-bar aggregation
        bar = self._macro_aggregator.add_tick(tick)
        self._amt_engine.on_tick(tick, self._macro_aggregator.current_bar)
        
        if bar is not None:
            self._on_bar_closed(bar)
