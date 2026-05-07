"""Live data ingestion checks for the real Dhan feed contract."""

from __future__ import annotations

import os
import threading
import time

import pytest

from app.infrastructure.adapters.dhan_adapter import DhanAdapter
from app.runtime.feeds.dhan_feed import DhanFeedSource
from app.runtime.pipeline.sequencer import TickSequencer


def _live_feed() -> tuple[DhanFeedSource, DhanAdapter]:
    if os.getenv("RUN_LIVE_DATA_TESTS", "").lower() not in {"1", "true", "yes"}:
        pytest.skip("RUN_LIVE_DATA_TESTS=true is required for live broker ingestion tests")
    client_id = os.getenv("DHAN_CLIENT_ID")
    access_token = os.getenv("DHAN_ACCESS_TOKEN")
    if not client_id or not access_token:
        pytest.skip("DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN are required for live ingestion tests")
    symbol = os.getenv("DHAN_LIVE_TEST_SYMBOL", "CRUDEOIL")
    adapter = DhanAdapter(symbols=[symbol], exchange=os.getenv("DHAN_LIVE_TEST_EXCHANGE", "MCX"), client_id=client_id, access_token=access_token)
    return DhanFeedSource(adapter, symbols=[symbol]), adapter


def _collect_ticks(feed: DhanFeedSource, limit: int, timeout_sec: float = 15.0):
    ticks = []
    feed.start()

    def _consume() -> None:
        for tick in feed.stream():
            ticks.append(tick)
            if len(ticks) >= limit:
                feed.stop()
                break

    thread = threading.Thread(target=_consume, daemon=True)
    thread.start()
    thread.join(timeout=timeout_sec)
    feed.stop()
    thread.join(timeout=2.0)
    return ticks


class TestLiveDataIngestion:
    """End-to-end ingestion checks for market feed intake and sequencing."""

    def test_tick_shape_is_valid(self) -> None:
        """Validate minimum tick schema before feeding into RuntimeOrchestrator."""
        feed, adapter = _live_feed()
        try:
            ticks = _collect_ticks(feed, limit=1)
            assert ticks, "live feed did not emit a tick before timeout"
            tick = ticks[0]
            assert tick.symbol
            assert tick.price > 0
            assert tick.timestamp > 0
        finally:
            adapter.close_sync()

    def test_sequence_integrity_is_monotonic(self) -> None:
        """Validate monotonic sequence + dedupe behavior from LiveFeed input."""
        feed, adapter = _live_feed()
        try:
            ticks = _collect_ticks(feed, limit=2)
            assert ticks, "live feed did not emit ticks before timeout"
            sequencer = TickSequencer()
            sequences = []
            for tick in ticks:
                seq = sequencer.process(tick)
                if seq is not None:
                    sequences.append(seq.sequence)
            assert sequences == sorted(sequences)
            assert len(sequences) == len(set(sequences))
        finally:
            adapter.close_sync()

    def test_gap_detection_is_reported(self) -> None:
        """Validate feed exposes stale/drop telemetry for operator readiness."""
        feed, adapter = _live_feed()
        try:
            feed.start()
            time.sleep(0.2)
            snapshot = feed.snapshot()
            assert "dropped_ticks" in snapshot
            assert "last_tick_age_sec" in snapshot
            assert snapshot["uses_stream_full"] is True
        finally:
            feed.stop()
            adapter.close_sync()

