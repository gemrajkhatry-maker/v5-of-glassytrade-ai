"""Live cache and engine event-tracking tests.

Migrated from StateProjector.on_event() tests: the engine now tracks
amt/decision/depth inline via _emit(), while LiveQuoteCache handles
only per-tick quote updates.
"""

from dataclasses import dataclass

from quant.brokers.gateway import Tick
from quant.event_store import EventStore
from quant.events import (
    AmtUpdated,
    BarClosed,
    DepthUpdated,
)
from quant.state import LiveQuoteCache, project_state


@dataclass(frozen=True)
class FakeBar:
    time: str
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    delta: float = 0.0
    oi: float = 0.0


def test_depth_updated_via_quote():
    """Depth is tracked via per-tick on_quote (the live path)."""
    cache = LiveQuoteCache()
    cache.on_quote("SYM", Tick(time="t1", price=100.0, volume=0, oi=0,
                               depth={"bids": [[1.0, 10.0]], "asks": [[1.1, 5.0]]}))
    assert cache.snapshot("SYM").depth == {"bids": [[1.0, 10.0]], "asks": [[1.1, 5.0]]}


def test_amt_tracked_by_event_store():
    """AmtUpdated events are stored and can be extracted from the trace."""
    store = EventStore()
    store.append(AmtUpdated(symbol="SYM", time="t1", amt={"poc": 1.0}))
    amt_events = [e for e in store.get_all() if isinstance(e, AmtUpdated)]
    assert len(amt_events) == 1
    assert amt_events[0].amt["poc"] == 1.0


def test_bar_close_sets_oi_via_quote():
    """OI is updated per-tick via on_quote (live path between bar closes)."""
    cache = LiveQuoteCache()
    cache.on_quote("SYM", Tick(time="t1", price=100.0, volume=0, oi=42.0))
    assert cache.snapshot("SYM").oi == 42.0


def test_oi_default_none_when_no_quote():
    """No quotes → OI is None (not zero)."""
    cache = LiveQuoteCache()
    assert cache.snapshot("SYM").oi is None
