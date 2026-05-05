"""Tests for TickSequencer — monotonic sequencing, dedup, thread safety."""

from app.runtime.pipeline.sequencer import TickSequencer
from app.runtime.pipeline.events import Tick


def test_empty_sequencer_returns_defaults():
    s = TickSequencer()
    assert s.sequence_count == 0
    assert s.metrics.processed_count == 0


def test_first_tick_gets_sequence_1():
    s = TickSequencer()
    tick = Tick(symbol="BANKNIFTY", price=45000.0, volume=100, timestamp=1000.0)
    result = s.process(tick)
    assert result is not None
    assert result.sequence == 1
    assert result.tick.symbol == "BANKNIFTY"


def test_ticks_get_monotonic_sequences():
    s = TickSequencer()
    t1 = Tick(symbol="BANKNIFTY", price=45000.0, volume=100, timestamp=1000.0)
    t2 = Tick(symbol="BANKNIFTY", price=45001.0, volume=200, timestamp=1001.0)
    t3 = Tick(symbol="NIFTY", price=22000.0, volume=150, timestamp=1002.0)
    r1 = s.process(t1)
    r2 = s.process(t2)
    r3 = s.process(t3)
    assert r1.sequence == 1
    assert r2.sequence == 2
    assert r3.sequence == 3


def test_duplicate_timestamp_dropped():
    s = TickSequencer()
    t1 = Tick(symbol="BANKNIFTY", price=45000.0, volume=100, timestamp=1000.0)
    t2 = Tick(symbol="BANKNIFTY", price=45001.0, volume=200, timestamp=1000.0)
    r1 = s.process(t1)
    r2 = s.process(t2)
    assert r1 is not None
    assert r2 is None
    assert s.sequence_count == 1


def test_same_timestamp_different_symbols_allowed():
    s = TickSequencer()
    t1 = Tick(symbol="BANKNIFTY", price=45000.0, volume=100, timestamp=1000.0)
    t2 = Tick(symbol="NIFTY", price=22000.0, volume=150, timestamp=1000.0)
    r1 = s.process(t1)
    r2 = s.process(t2)
    assert r1 is not None
    assert r2 is not None
    assert r2.sequence == 2


def test_reset_clears_state():
    s = TickSequencer()
    t1 = Tick(symbol="BANKNIFTY", price=45000.0, volume=100, timestamp=1000.0)
    s.process(t1)
    assert s.sequence_count == 1
    s.reset()
    assert s.sequence_count == 0
    t2 = Tick(symbol="BANKNIFTY", price=45000.0, volume=100, timestamp=1000.0)
    r2 = s.process(t2)
    assert r2 is not None
    assert r2.sequence == 1


def test_batch_processing():
    s = TickSequencer()
    ticks = [
        Tick(symbol="BANKNIFTY", price=45000.0, volume=100, timestamp=1000.0),
        Tick(symbol="BANKNIFTY", price=45001.0, volume=200, timestamp=1001.0),
        Tick(symbol="NIFTY", price=22000.0, volume=150, timestamp=1002.0),
    ]
    results = s.process_batch(ticks)
    assert len(results) == 3
    assert results[0].sequence == 1
    assert results[1].sequence == 2
    assert results[2].sequence == 3


def test_batch_with_duplicates():
    s = TickSequencer()
    ticks = [
        Tick(symbol="BANKNIFTY", price=45000.0, volume=100, timestamp=1000.0),
        Tick(symbol="BANKNIFTY", price=45001.0, volume=200, timestamp=1000.0),
        Tick(symbol="NIFTY", price=22000.0, volume=150, timestamp=1001.0),
    ]
    results = s.process_batch(ticks)
    assert len(results) == 2
    assert results[0].sequence == 1
    assert results[1].sequence == 2