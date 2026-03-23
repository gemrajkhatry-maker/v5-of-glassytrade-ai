"""
Performance tests for latency and throughput.
"""

import pytest
import time
from datetime import datetime
from src.core.tick_processor import Tick
from src.profile.volume_profile import VolumeProfileEngine


class TestLatency:
    """Test latency and performance."""

    def test_profile_update_latency(self):
        """Test O(1) profile update per tick."""
        engine = VolumeProfileEngine(bucket_size=0.10)
        profile = {}

        # Create test tick
        tick = Tick(
            symbol="NATURALGAS",
            price=9.35,
            volume=100,
            bid_vol=40,
            ask_vol=60,
            delta=20,
            trade_size=100,
            timestamp=datetime.now(),
            exchange="MCX",
        )

        # Measure time for 10000 updates
        start = time.time()
        for i in range(10000):
            engine.update_bucket(profile, tick.price + (i * 0.01), tick.volume)
        end = time.time()

        elapsed_ms = (end - start) * 1000
        avg_ms = elapsed_ms / 10000

        # Should be < 1ms per update
        assert avg_ms < 0.1  # O(1) operation

    def test_tick_normalization_latency(self):
        """Test tick normalization is fast."""
        from src.core.tick_processor import normalize_tick

        raw = {
            "type": "ticker",
            "symbol": "NATURALGAS",
            "LTP": 9.35,
            "buy_qty": 125,
            "sell_qty": 75,
            "trade_size": 200,
            "timestamp": datetime.now().isoformat(),
            "exchange": "MCX",
        }

        # Measure time for 10000 normalizations
        start = time.time()
        for i in range(10000):
            tick = normalize_tick(raw)
        end = time.time()

        elapsed_ms = (end - start) * 1000
        avg_ms = elapsed_ms / 10000

        # Should be < 0.1ms per normalization
        assert avg_ms < 0.1

    def test_cvd_update_latency(self):
        """Test CVD update is fast."""
        from src.orderflow.cvd_engine import CVDEngine

        engine = CVDEngine()

        # Measure time for 10000 updates
        start = time.time()
        for i in range(10000):
            engine.update(10 if i % 2 == 0 else -5)
        end = time.time()

        elapsed_ms = (end - start) * 1000
        avg_ms = elapsed_ms / 10000

        # Should be < 0.1ms per update
        assert avg_ms < 0.1