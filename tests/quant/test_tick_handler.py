"""Verify TickHandler extraction from runtime.py."""

import logging
from unittest.mock import MagicMock, Mock

from quant.brokers.gateway import Tick
from quant.contracts.value_objects import OrderBook, OrderBookLevel
from quant.engine.tick_handler import TickHandler
from quant.runtime import QuantEngine
from quant.state import LiveQuoteCache
from tests.helpers.synthetic import SyntheticGateway


class TestTickHandlerExists:
    """Basic existence tests."""
    
    def test_tick_handler_class_exists(self):
        """Ensure TickHandler class exists."""
        assert TickHandler is not None
    
    def test_tick_handler_has_process_tick_method(self):
        """Ensure process_tick method exists and is callable."""
        handler = self._create_minimal_handler()
        assert callable(handler.process_tick)
    
    def _create_minimal_handler(self):
        """Create a minimal TickHandler with mocked dependencies."""
        return TickHandler(
            symbol="NIFTY24SEPFUT",
            macro_aggregator=MagicMock(),
            micro_aggregator=None,
            amt_engine=MagicMock(),
            state_getter=lambda: MagicMock(position=None),
            manage_tick_exit_callback=MagicMock(),
            decide_callback=MagicMock(),
            on_bar_closed_callback=MagicMock(),
            manage_exit_callback=MagicMock(),
        )


class TestTickHandlerFuturesPath:
    """Test the futures (direct instrument) tick processing path."""
    
    def test_futures_tick_feeds_macro_aggregator(self):
        """Ensure futures ticks are fed to the macro aggregator."""
        macro_agg = MagicMock()
        macro_agg.add_tick.return_value = None  # No bar closed yet
        macro_agg.current_bar = MagicMock()
        
        amt_engine = MagicMock()
        amt_engine.last_amt_dto = None
        
        handler = TickHandler(
            symbol="NIFTY24SEPFUT",
            macro_aggregator=macro_agg,
            micro_aggregator=None,
            amt_engine=amt_engine,
            state_getter=lambda: MagicMock(position=None),
            manage_tick_exit_callback=MagicMock(),
            decide_callback=MagicMock(),
            on_bar_closed_callback=MagicMock(),
            manage_exit_callback=MagicMock(),
        )
        
        tick = Mock()
        tick.price = 20000.0
        tick.time = "2026-09-16T10:00:00"
        tick.depth = None
        
        handler.process_tick(tick)
        
        # Verify macro aggregator was called
        macro_agg.add_tick.assert_called_once_with(tick)
        amt_engine.on_tick.assert_called_once_with(tick, macro_agg.current_bar)
    
    def test_futures_bar_closed_triggers_on_bar_closed(self):
        """Ensure bar close triggers on_bar_closed callback."""
        macro_agg = MagicMock()
        bar = Mock()
        bar.time = "2026-09-16T10:05:00"
        macro_agg.add_tick.return_value = bar  # Bar closed
        macro_agg.current_bar = MagicMock()
        
        on_bar_closed = MagicMock()
        
        handler = TickHandler(
            symbol="NIFTY24SEPFUT",
            macro_aggregator=macro_agg,
            micro_aggregator=None,
            amt_engine=MagicMock(),
            state_getter=lambda: MagicMock(position=None),
            manage_tick_exit_callback=MagicMock(),
            decide_callback=MagicMock(),
            on_bar_closed_callback=on_bar_closed,
            manage_exit_callback=MagicMock(),
        )
        
        tick = Mock()
        tick.price = 20000.0
        tick.time = "2026-09-16T10:05:00"
        tick.depth = None
        
        handler.process_tick(tick)
        
        # Verify on_bar_closed was called
        on_bar_closed.assert_called_once_with(bar)
    
    def test_futures_micro_bar_triggers_decide_when_flat(self):
        """Ensure micro-bar close triggers decide callback when flat."""
        micro_agg = MagicMock()
        micro_bar = Mock()
        micro_bar.time = "2026-09-16T10:01:00+05:30"
        micro_agg.add_tick.return_value = micro_bar  # Micro-bar closed
        
        amt_engine = MagicMock()
        amt_dto = {"poc": 20000.0, "time": "2026-09-16T10:00:00+05:30"}
        amt_engine.last_amt_dto = amt_dto
        
        decide = MagicMock()
        macro_agg = MagicMock()
        macro_agg.interval_seconds = 300
        
        handler = TickHandler(
            symbol="NIFTY24SEPFUT",
            macro_aggregator=macro_agg,
            micro_aggregator=micro_agg,
            amt_engine=amt_engine,
            state_getter=lambda: MagicMock(position=None),  # Flat
            manage_tick_exit_callback=MagicMock(),
            decide_callback=decide,
            on_bar_closed_callback=MagicMock(),
            manage_exit_callback=MagicMock(),
        )
        
        tick = Mock()
        tick.price = 20000.0
        tick.time = "2026-09-16T10:01:00"
        tick.depth = None
        
        handler.process_tick(tick)
        
        # Verify decide was called with amt_dto and micro_bar
        decide.assert_called_once_with(amt_dto, micro_bar, None)
    
    def test_futures_micro_bar_skips_decide_when_positioned(self):
        """Ensure micro-bar close does NOT trigger decide when positioned."""
        micro_agg = MagicMock()
        micro_bar = Mock()
        micro_agg.add_tick.return_value = micro_bar
        
        decide = MagicMock()
        
        handler = TickHandler(
            symbol="NIFTY24SEPFUT",
            macro_aggregator=MagicMock(),
            micro_aggregator=micro_agg,
            amt_engine=MagicMock(),
            state_getter=lambda: MagicMock(position=MagicMock()),  # Positioned
            manage_tick_exit_callback=MagicMock(),
            decide_callback=decide,
            on_bar_closed_callback=MagicMock(),
            manage_exit_callback=MagicMock(),
        )
        
        tick = Mock()
        tick.price = 20000.0
        tick.time = "2026-09-16T10:01:00"
        tick.depth = None
        
        handler.process_tick(tick)
        
        # Verify decide was NOT called
        decide.assert_not_called()

    def test_macro_fresh_decide_uses_snapshot_asof_time_without_dto_time(self):
        """Freshness can use last_snapshot.asof_time when dto omits time."""
        micro_agg = MagicMock()
        micro_bar = Mock()
        micro_bar.time = "2026-09-16T10:01:00+05:30"
        micro_agg.add_tick.return_value = micro_bar

        amt_engine = MagicMock()
        snap = Mock()
        snap.asof_time = "2026-09-16T10:00:00+05:30"
        amt_engine.last_snapshot = snap
        amt_dto = {"poc": 20000.0}
        amt_engine.last_amt_dto = amt_dto

        decide = MagicMock()
        macro_agg = MagicMock()
        macro_agg.interval_seconds = 300

        handler = TickHandler(
            symbol="NIFTY24SEPFUT",
            macro_aggregator=macro_agg,
            micro_aggregator=micro_agg,
            amt_engine=amt_engine,
            state_getter=lambda: MagicMock(position=None),
            manage_tick_exit_callback=MagicMock(),
            decide_callback=decide,
            on_bar_closed_callback=MagicMock(),
            manage_exit_callback=MagicMock(),
        )

        tick = Mock()
        tick.price = 20000.0
        tick.time = "2026-09-16T10:01:00"
        tick.depth = None

        handler.process_tick(tick)

        decide.assert_called_once_with(amt_dto, micro_bar, None)


class TestDecideIfMacroFreshDeferred:
    """DecisionDeferred observability for stale/unparseable AMT DTO (B-4b)."""

    def _make_handler(self, amt_dto, micro_bar, *, macro_seconds=300):
        micro_agg = MagicMock()
        micro_agg.add_tick.return_value = micro_bar
        amt_engine = MagicMock()
        amt_engine.last_amt_dto = amt_dto
        amt_engine.last_snapshot = None
        macro_agg = MagicMock()
        macro_agg.interval_seconds = macro_seconds
        return TickHandler(
            symbol="NIFTY24SEPFUT",
            macro_aggregator=macro_agg,
            micro_aggregator=micro_agg,
            amt_engine=amt_engine,
            state_getter=lambda: MagicMock(position=None),
            manage_tick_exit_callback=MagicMock(),
            decide_callback=MagicMock(),
            on_bar_closed_callback=MagicMock(),
            manage_exit_callback=MagicMock(),
        )

    def test_stale_dto_defers_with_logged_reason(self, caplog):
        """A DTO older than one macro bar skips decide and logs DecisionDeferred."""
        micro_bar = Mock()
        micro_bar.time = "2026-09-16T10:10:00+05:30"
        # DTO is 10 min old; macro interval is 5 min -> stale.
        handler = self._make_handler({"time": "2026-09-16T10:00:00+05:30"}, micro_bar)

        with caplog.at_level(logging.INFO, logger="quant.engine.tick_handler"):
            result = handler._decide_if_macro_fresh(
                {"time": "2026-09-16T10:00:00+05:30"}, Mock(), micro_bar
            )

        assert result is False
        assert handler._decide.call_count == 0
        deferred = [
            r for r in caplog.records
            if "DecisionDeferred" in r.message and "reason=STALE_DTO" in r.message
        ]
        assert deferred, "expected DecisionDeferred reason=STALE_DTO log"
        assert handler._deferred_counts.get("STALE_DTO") == 1

    def test_unparseable_dto_defers_with_logged_reason(self, caplog):
        """A DTO with no usable time skips decide and logs DecisionDeferred."""
        micro_bar = Mock()
        micro_bar.time = "2026-09-16T10:01:00+05:30"
        handler = self._make_handler({"time": "not-a-timestamp"}, micro_bar)

        with caplog.at_level(logging.INFO, logger="quant.engine.tick_handler"):
            result = handler._decide_if_macro_fresh(
                {"time": "not-a-timestamp"}, Mock(), micro_bar
            )

        assert result is False
        deferred = [
            r for r in caplog.records
            if "DecisionDeferred" in r.message and "reason=STALE_DTO" in r.message
        ]
        assert deferred, "expected DecisionDeferred reason=STALE_DTO log"
        assert handler._deferred_counts.get("STALE_DTO") == 1

    def test_fresh_dto_defers_nothing(self, caplog):
        """Fresh DTO decides normally — no DecisionDeferred logged."""
        micro_bar = Mock()
        micro_bar.time = "2026-09-16T10:01:00+05:30"
        handler = self._make_handler({"time": "2026-09-16T10:00:00+05:30"}, micro_bar)

        with caplog.at_level(logging.INFO, logger="quant.engine.tick_handler"):
            result = handler._decide_if_macro_fresh(
                {"time": "2026-09-16T10:00:00+05:30"}, Mock(), micro_bar
            )

        assert result is True
        assert handler._decide.call_count == 1
        assert not [r for r in caplog.records if "DecisionDeferred" in r.message]
        assert "STALE_DTO" not in handler._deferred_counts


class TestTickHandlerPositioned:
    """Test tick-level exit management when positioned."""
    
    def test_positioned_tick_triggers_manage_tick_exit(self):
        """Ensure tick-level exit is triggered when positioned."""
        manage_tick_exit = MagicMock()
        
        handler = TickHandler(
            symbol="NIFTY24SEPFUT",
            macro_aggregator=MagicMock(),
            micro_aggregator=None,
            amt_engine=MagicMock(),
            state_getter=lambda: MagicMock(position=MagicMock()),  # Positioned
            manage_tick_exit_callback=manage_tick_exit,
            decide_callback=MagicMock(),
            on_bar_closed_callback=MagicMock(),
            manage_exit_callback=MagicMock(),
        )
        
        tick = Mock()
        tick.price = 20000.0
        tick.time = "2026-09-16T10:00:00"
        tick.depth = None
        
        handler.process_tick(tick)
        
        # Verify manage_tick_exit was called with price and time
        manage_tick_exit.assert_called_once_with(20000.0, "2026-09-16T10:00:00")
    
    def test_flat_tick_skips_manage_tick_exit(self):
        """Ensure tick-level exit is NOT triggered when flat."""
        manage_tick_exit = MagicMock()
        
        handler = TickHandler(
            symbol="NIFTY24SEPFUT",
            macro_aggregator=MagicMock(),
            micro_aggregator=None,
            amt_engine=MagicMock(),
            state_getter=lambda: MagicMock(position=None),  # Flat
            manage_tick_exit_callback=manage_tick_exit,
            decide_callback=MagicMock(),
            on_bar_closed_callback=MagicMock(),
            manage_exit_callback=MagicMock(),
        )
        
        tick = Mock()
        tick.price = 20000.0
        tick.time = "2026-09-16T10:00:00"
        tick.depth = None
        
        handler.process_tick(tick)
        
        # Verify manage_tick_exit was NOT called
        manage_tick_exit.assert_not_called()


class TestTickHandlerLiveQuote:
    """Test live quote and depth updates."""
    
    def test_live_quote_callback_invoked(self):
        """Ensure live quote callback is invoked on every tick."""
        live_quote = MagicMock()
        
        handler = TickHandler(
            symbol="NIFTY24SEPFUT",
            macro_aggregator=MagicMock(),
            micro_aggregator=None,
            amt_engine=MagicMock(),
            state_getter=lambda: MagicMock(position=None),
            manage_tick_exit_callback=MagicMock(),
            decide_callback=MagicMock(),
            on_bar_closed_callback=MagicMock(),
            manage_exit_callback=MagicMock(),
            live_quote_callback=live_quote,
        )
        
        tick = Mock()
        tick.price = 20000.0
        tick.time = "2026-09-16T10:00:00"
        tick.depth = None
        
        handler.process_tick(tick)
        
        # Verify live quote callback was called
        live_quote.assert_called_once()
    
    def test_depth_callback_invoked_when_depth_present(self):
        """Ensure depth callback is invoked when tick has depth."""
        depth_callback = MagicMock()
        
        handler = TickHandler(
            symbol="NIFTY24SEPFUT",
            macro_aggregator=MagicMock(),
            micro_aggregator=None,
            amt_engine=MagicMock(),
            state_getter=lambda: MagicMock(position=None),
            manage_tick_exit_callback=MagicMock(),
            decide_callback=MagicMock(),
            on_bar_closed_callback=MagicMock(),
            manage_exit_callback=MagicMock(),
            depth_callback=depth_callback,
        )
        
        tick = Mock()
        tick.price = 20000.0
        tick.time = "2026-09-16T10:00:00"
        tick.depth = {"bids": [(20000.0, 100)], "asks": [(20001.0, 50)]}
        
        handler.process_tick(tick)
        
        # Verify depth callback was called
        depth_callback.assert_called_once_with(tick.depth)
    
    def test_depth_callback_clears_when_no_depth(self):
        depth_callback = MagicMock()

        handler = TickHandler(
            symbol="NIFTY24SEPFUT",
            macro_aggregator=MagicMock(),
            micro_aggregator=None,
            amt_engine=MagicMock(),
            state_getter=lambda: MagicMock(position=None),
            manage_tick_exit_callback=MagicMock(),
            decide_callback=MagicMock(),
            on_bar_closed_callback=MagicMock(),
            manage_exit_callback=MagicMock(),
            depth_callback=depth_callback,
        )

        tick = Mock()
        tick.price = 20000.0
        tick.time = "2026-09-16T10:00:00"
        tick.depth = None

        handler.process_tick(tick)

        depth_callback.assert_called_once_with(None)

    def test_depth_callback_clears_before_amt_work(self):
        events = []
        macro_aggregator = MagicMock()
        macro_aggregator.current_bar = MagicMock()
        amt_engine = MagicMock()
        amt_engine.on_tick.side_effect = lambda *_: events.append("amt")
        depth_callback = MagicMock(
            side_effect=lambda depth: events.append("depth"),
        )
        handler = TickHandler(
            symbol="NIFTY24SEPFUT",
            macro_aggregator=macro_aggregator,
            micro_aggregator=None,
            amt_engine=amt_engine,
            state_getter=lambda: MagicMock(position=None),
            manage_tick_exit_callback=MagicMock(),
            decide_callback=MagicMock(),
            on_bar_closed_callback=MagicMock(),
            manage_exit_callback=MagicMock(),
            depth_callback=depth_callback,
        )

        handler.process_tick(
            Tick(time="2026-09-16T10:00:00", price=20000.0, volume=1.0)
        )

        assert events == ["depth", "amt"]
        depth_callback.assert_called_once_with(None)

    def test_depthless_tick_clears_engine_depth_before_amt_analysis(self):
        engine = QuantEngine(SyntheticGateway([]), "NIFTY", interval_seconds=1)
        engine._last_depth = OrderBook(
            bids=(OrderBookLevel(19999.95, 100),),
            asks=(OrderBookLevel(20000.05, 100),),
        )
        observed = []
        engine._amt_engine.on_tick = MagicMock(
            side_effect=lambda *_: observed.append(engine._last_depth),
        )
        handler = engine._create_tick_handler()

        handler.process_tick(
            Tick(time="2026-09-16T10:00:00", price=20000.0, volume=1.0)
        )

        assert observed == [None]
        assert engine._last_depth is None
        assert engine._decision_loop._get_last_depth() is None

    def test_depthless_tick_clears_cached_depth(self):
        cache = LiveQuoteCache()
        cache.on_quote(
            "NIFTY24SEPFUT",
            Tick(
                time="2026-09-16T10:00:00",
                price=20000.0,
                volume=1.0,
                depth={"bids": [], "asks": []},
            ),
        )
        handler = TickHandler(
            symbol="NIFTY24SEPFUT",
            macro_aggregator=MagicMock(),
            micro_aggregator=None,
            amt_engine=MagicMock(),
            state_getter=lambda: MagicMock(position=None),
            manage_tick_exit_callback=MagicMock(),
            decide_callback=MagicMock(),
            on_bar_closed_callback=MagicMock(),
            manage_exit_callback=MagicMock(),
            live_quote_callback=cache.on_quote,
        )

        handler.process_tick(
            Tick(
                time="2026-09-16T10:00:01",
                price=20000.0,
                volume=1.0,
            )
        )

        assert cache.snapshot("NIFTY24SEPFUT").depth is None


class TestTickHandlerHotpath:
    """Test hotpath tracing."""
    
    def test_hotpath_callback_invoked_when_enabled(self):
        """Ensure hotpath callback is invoked when provided."""
        hotpath = MagicMock()
        
        handler = TickHandler(
            symbol="NIFTY24SEPFUT",
            macro_aggregator=MagicMock(),
            micro_aggregator=None,
            amt_engine=MagicMock(),
            state_getter=lambda: MagicMock(position=None),
            manage_tick_exit_callback=MagicMock(),
            decide_callback=MagicMock(),
            on_bar_closed_callback=MagicMock(),
            manage_exit_callback=MagicMock(),
            hotpath_callback=hotpath,
        )
        
        tick = Mock()
        tick.price = 20000.0
        tick.time = "2026-09-16T10:00:00"
        tick.depth = None
        
        handler.process_tick(tick)
        
        # Verify hotpath callback was called
        hotpath.assert_called_once_with(
            "NIFTY24SEPFUT", "tick",
            "2026-09-16T10:00:00", 20000.0, "option",
        )
