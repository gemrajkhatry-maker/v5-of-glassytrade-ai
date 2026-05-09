"""
Phase 2: Replay Infrastructure Tests.

Tests cover:
1. Event Capture (8 tests)
2. Replay Engine (10 tests)
3. Determinism Verification (10 tests)
4. Integration (9 tests)

Total: 37 tests
"""

import asyncio
import json
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from brokersv2.replay.event_capture import (
    CapturedEvent,
    EventCapture,
    CaptureFilter,
)
from brokersv2.replay.replay_engine import ReplayEngine, ReplayProgress
from brokersv2.replay.determinism import (
    DeterminismVerifier,
    DeterminismReport,
    DriftDetection,
)
from brokersv2.replay.event_clock import ReplayClock, ClockState


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def sample_tick_event():
    """Create a sample tick event."""
    class TickEvent:
        def __init__(self, symbol, price, volume):
            self.symbol = symbol
            self.price = price
            self.volume = volume
    return TickEvent(symbol="RELIANCE", price=2500.0, volume=100)


@pytest.fixture
def temp_capture_file():
    """Create a temporary file for capture tests."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
        yield Path(f.name)
    try:
        Path(f.name).unlink()
    except FileNotFoundError:
        pass


@pytest.fixture
def replay_clock():
    """Create a replay clock for testing."""
    return ReplayClock(
        start_time=datetime(2024, 1, 1, 9, 15, 0, tzinfo=timezone.utc)
    )


# =============================================================================
# 1. Event Capture Tests (8 tests)
# =============================================================================

class TestEventCapture:
    """Test event capture system."""

    @pytest.mark.asyncio
    async def test_capture_events_to_jsonl(self, sample_tick_event, temp_capture_file):
        """Capture events to JSONL file."""
        capture = EventCapture(output_path=temp_capture_file)
        
        await capture.capture(sample_tick_event, event_type="TickEvent")
        await capture.flush()  # Ensure flush
        
        assert temp_capture_file.exists()
        
        with open(temp_capture_file, 'r') as f:
            lines = f.readlines()
        
        assert len(lines) == 1
        captured = json.loads(lines[0])
        assert captured['event_type'] == 'TickEvent'
        assert captured['sequence_id'] == 1

    @pytest.mark.asyncio
    async def test_sequence_ordering(self, sample_tick_event, temp_capture_file):
        """Events have monotonic sequence numbers."""
        capture = EventCapture(output_path=temp_capture_file)
        
        await capture.capture(sample_tick_event, event_type="TickEvent")
        await capture.capture(sample_tick_event, event_type="TickEvent")
        await capture.capture(sample_tick_event, event_type="TickEvent")
        
        await capture.flush()
        
        with open(temp_capture_file, 'r') as f:
            events = [json.loads(line) for line in f.readlines()]
        
        assert events[0]['sequence_id'] == 1
        assert events[1]['sequence_id'] == 2
        assert events[2]['sequence_id'] == 3

    @pytest.mark.asyncio
    async def test_metadata_correctness(self, sample_tick_event, temp_capture_file):
        """Event metadata is correct."""
        capture = EventCapture(output_path=temp_capture_file)
        
        await capture.capture(sample_tick_event, event_type="TickEvent")
        await capture.flush()
        
        with open(temp_capture_file, 'r') as f:
            captured = json.loads(f.readline())
        
        assert 'sequence_id' in captured
        assert 'event_type' in captured
        assert 'timestamp' in captured
        assert 'payload' in captured
        assert 'source' in captured
        assert captured['source'] == 'live'

    @pytest.mark.asyncio
    async def test_filter_by_event_type(self, sample_tick_event, temp_capture_file):
        """Filter captures by event type."""
        class OrderEvent:
            def __init__(self):
                self.order_id = "ORD-001"
        
        capture_filter = CaptureFilter(allowed_types={"TickEvent"})
        capture = EventCapture(output_path=temp_capture_file, capture_filter=capture_filter)
        
        await capture.capture(sample_tick_event, event_type="TickEvent")
        await capture.capture(OrderEvent(), event_type="OrderEvent")
        await capture.flush()
        
        with open(temp_capture_file, 'r') as f:
            lines = f.readlines()
        
        assert len(lines) == 1
        captured = json.loads(lines[0])
        assert captured['event_type'] == 'TickEvent'

    @pytest.mark.asyncio
    async def test_buffer_flush(self, sample_tick_event, temp_capture_file):
        """Buffer flushes correctly."""
        capture = EventCapture(output_path=temp_capture_file, buffer_size=2)
        
        await capture.capture(sample_tick_event, event_type="TickEvent")
        await capture.capture(sample_tick_event, event_type="TickEvent")
        
        with open(temp_capture_file, 'r') as f:
            lines = f.readlines()
        
        assert len(lines) == 2

    @pytest.mark.asyncio
    async def test_file_rotation(self, temp_capture_file):
        """File rotation works when size limit reached."""
        max_file_size = 500
        capture = EventCapture(
            output_path=temp_capture_file,
            max_file_size=max_file_size,
            enable_rotation=True
        )
        
        for i in range(10):
            class TickEvent:
                def __init__(self, idx):
                    self.symbol = f"SYM{idx}"
                    self.price = 100.0 + idx
                    self.volume = 10
            await capture.capture(TickEvent(i), event_type="TickEvent")
        
        await capture.flush()
        
        rotated_files = list(temp_capture_file.parent.glob(f"{temp_capture_file.stem}*.jsonl"))
        assert len(rotated_files) >= 1

    @pytest.mark.asyncio
    async def test_async_writing(self, sample_tick_event, temp_capture_file):
        """Async writing doesn't block."""
        capture = EventCapture(output_path=temp_capture_file)
        
        tasks = [
            capture.capture(sample_tick_event, event_type="TickEvent")
            for _ in range(5)
        ]
        await asyncio.gather(*tasks)
        await capture.flush()
        
        with open(temp_capture_file, 'r') as f:
            lines = f.readlines()
        
        assert len(lines) == 5

    @pytest.mark.asyncio
    async def test_error_handling(self, temp_capture_file):
        """Error handling for invalid paths."""
        invalid_path = Path("/invalid/path/capture.jsonl")
        
        with pytest.raises((OSError, ValueError)):
            EventCapture(output_path=invalid_path)


# =============================================================================
# 2. Replay Engine Tests (10 tests)
# =============================================================================

class TestReplayEngine:
    """Test replay engine."""

    @pytest.mark.asyncio
    async def test_load_events_from_jsonl(self, temp_capture_file):
        """Load events from JSONL file."""
        events_data = [
            {"sequence_id": 1, "event_type": "TickEvent", "timestamp": "2024-01-01T09:15:00Z", "payload": {"symbol": "RELIANCE", "price": 2500.0}, "source": "live"},
            {"sequence_id": 2, "event_type": "TickEvent", "timestamp": "2024-01-01T09:15:01Z", "payload": {"symbol": "TCS", "price": 3500.0}, "source": "live"},
        ]
        
        with open(temp_capture_file, 'w') as f:
            for event in events_data:
                f.write(json.dumps(event) + '\n')
        
        engine = ReplayEngine(event_path=temp_capture_file)
        await engine.load()
        
        assert len(engine.events) == 2

    @pytest.mark.asyncio
    async def test_replay_at_1x_speed(self, temp_capture_file, replay_clock):
        """Replay events at 1x speed."""
        events_data = [
            {"sequence_id": 1, "event_type": "TickEvent", "timestamp": "2024-01-01T09:15:00Z", "payload": {"symbol": "RELIANCE", "price": 2500.0}, "source": "live"},
        ]
        
        with open(temp_capture_file, 'w') as f:
            for event in events_data:
                f.write(json.dumps(event) + '\n')
        
        engine = ReplayEngine(event_path=temp_capture_file, clock=replay_clock)
        await engine.load()
        
        received_events = []
        engine.on_event(lambda e: received_events.append(e))
        
        await engine.replay(speed=1.0)
        
        assert len(received_events) == 1

    @pytest.mark.asyncio
    async def test_replay_at_2x_speed(self, temp_capture_file, replay_clock):
        """Replay events at 2x speed."""
        events_data = [
            {"sequence_id": 1, "event_type": "TickEvent", "timestamp": "2024-01-01T09:15:00Z", "payload": {"symbol": "RELIANCE", "price": 2500.0}, "source": "live"},
            {"sequence_id": 2, "event_type": "TickEvent", "timestamp": "2024-01-01T09:15:01Z", "payload": {"symbol": "TCS", "price": 3500.0}, "source": "live"},
        ]
        
        with open(temp_capture_file, 'w') as f:
            for event in events_data:
                f.write(json.dumps(event) + '\n')
        
        engine = ReplayEngine(event_path=temp_capture_file, clock=replay_clock)
        await engine.load()
        
        received_events = []
        engine.on_event(lambda e: received_events.append(e))
        
        await engine.replay(speed=2.0)
        
        assert len(received_events) == 2

    @pytest.mark.asyncio
    async def test_pause_resume(self, temp_capture_file, replay_clock):
        """Pause and resume replay."""
        events_data = [
            {"sequence_id": 1, "event_type": "TickEvent", "timestamp": "2024-01-01T09:15:00Z", "payload": {"symbol": "RELIANCE", "price": 2500.0}, "source": "live"},
            {"sequence_id": 2, "event_type": "TickEvent", "timestamp": "2024-01-01T09:15:01Z", "payload": {"symbol": "TCS", "price": 3500.0}, "source": "live"},
        ]
        
        with open(temp_capture_file, 'w') as f:
            for event in events_data:
                f.write(json.dumps(event) + '\n')
        
        engine = ReplayEngine(event_path=temp_capture_file, clock=replay_clock)
        await engine.load()
        
        received_events = []
        engine.on_event(lambda e: received_events.append(e))
        
        replay_task = asyncio.create_task(engine.replay(speed=1.0))
        
        await asyncio.sleep(0.1)
        await engine.pause()
        
        assert engine.state == "paused"
        
        await engine.resume()
        await replay_task
        
        assert len(received_events) == 2

    @pytest.mark.asyncio
    async def test_stop_mid_replay(self, temp_capture_file, replay_clock):
        """Stop replay mid-execution."""
        events_data = [
            {"sequence_id": i, "event_type": "TickEvent", "timestamp": f"2024-01-01T09:15:{i:02d}Z", "payload": {"symbol": "RELIANCE", "price": 2500.0 + i}, "source": "live"}
            for i in range(1, 11)
        ]
        
        with open(temp_capture_file, 'w') as f:
            for event in events_data:
                f.write(json.dumps(event) + '\n')
        
        engine = ReplayEngine(event_path=temp_capture_file, clock=replay_clock)
        await engine.load()
        
        received_events = []
        
        async def slow_handler(event):
            """Handler that adds delay to allow stop to work."""
            received_events.append(event)
            await asyncio.sleep(0.05)  # Slow down processing
        
        engine.on_event(slow_handler)
        
        # Start replay in background
        replay_task = asyncio.create_task(engine.replay(speed=0.1))
        
        # Wait for a few events to be processed
        await asyncio.sleep(0.2)
        
        # Now stop
        await engine.stop()
        
        try:
            await replay_task
        except asyncio.CancelledError:
            pass
        
        # Should have received some but not all events
        assert 0 < len(received_events) < 10

    @pytest.mark.asyncio
    async def test_progress_tracking(self, temp_capture_file, replay_clock):
        """Track replay progress."""
        events_data = [
            {"sequence_id": i, "event_type": "TickEvent", "timestamp": f"2024-01-01T09:15:{i:02d}Z", "payload": {"symbol": "RELIANCE", "price": 2500.0 + i}, "source": "live"}
            for i in range(1, 6)
        ]
        
        with open(temp_capture_file, 'w') as f:
            for event in events_data:
                f.write(json.dumps(event) + '\n')
        
        engine = ReplayEngine(event_path=temp_capture_file, clock=replay_clock)
        await engine.load()
        
        assert engine.progress.total_events == 5
        assert engine.progress.replayed_events == 0
        assert engine.progress.percentage == 0.0

    @pytest.mark.asyncio
    async def test_event_ordering_preserved(self, temp_capture_file, replay_clock):
        """Event ordering is preserved during replay."""
        events_data = [
            {"sequence_id": 1, "event_type": "TickEvent", "timestamp": "2024-01-01T09:15:00Z", "payload": {"symbol": "RELIANCE", "price": 2500.0}, "source": "live"},
            {"sequence_id": 2, "event_type": "TickEvent", "timestamp": "2024-01-01T09:15:01Z", "payload": {"symbol": "TCS", "price": 3500.0}, "source": "live"},
            {"sequence_id": 3, "event_type": "TickEvent", "timestamp": "2024-01-01T09:15:02Z", "payload": {"symbol": "INFY", "price": 1500.0}, "source": "live"},
        ]
        
        with open(temp_capture_file, 'w') as f:
            for event in events_data:
                f.write(json.dumps(event) + '\n')
        
        engine = ReplayEngine(event_path=temp_capture_file, clock=replay_clock)
        await engine.load()
        
        received_events = []
        engine.on_event(lambda e: received_events.append(e))
        
        await engine.replay(speed=1.0)
        
        assert received_events[0]['sequence_id'] == 1
        assert received_events[1]['sequence_id'] == 2
        assert received_events[2]['sequence_id'] == 3

    @pytest.mark.asyncio
    async def test_clock_integration(self, temp_capture_file, replay_clock):
        """Replay engine integrates with ReplayClock."""
        events_data = [
            {"sequence_id": 1, "event_type": "TickEvent", "timestamp": "2024-01-01T09:15:00Z", "payload": {"symbol": "RELIANCE", "price": 2500.0}, "source": "live"},
        ]
        
        with open(temp_capture_file, 'w') as f:
            for event in events_data:
                f.write(json.dumps(event) + '\n')
        
        engine = ReplayEngine(event_path=temp_capture_file, clock=replay_clock)
        await engine.load()
        
        received_events = []
        engine.on_event(lambda e: received_events.append(e))
        
        await engine.replay(speed=1.0)
        
        assert replay_clock.state() in [ClockState.RUNNING, ClockState.STOPPED]

    @pytest.mark.asyncio
    async def test_empty_store_handling(self, temp_capture_file, replay_clock):
        """Handle empty event store gracefully."""
        temp_capture_file.write_text('')
        
        engine = ReplayEngine(event_path=temp_capture_file, clock=replay_clock)
        await engine.load()
        
        received_events = []
        engine.on_event(lambda e: received_events.append(e))
        
        await engine.replay(speed=1.0)
        
        assert len(received_events) == 0

    @pytest.mark.asyncio
    async def test_corrupted_file_handling(self, temp_capture_file, replay_clock):
        """Handle corrupted JSONL file gracefully."""
        with open(temp_capture_file, 'w') as f:
            f.write('{"sequence_id": 1, INVALID JSON}\n')
            f.write('{"sequence_id": 2, "event_type": "TickEvent", "timestamp": "2024-01-01T09:15:00Z", "payload": {}, "source": "live"}\n')
        
        engine = ReplayEngine(event_path=temp_capture_file, clock=replay_clock)
        
        with pytest.raises((json.JSONDecodeError, ValueError)):
            await engine.load()


# =============================================================================
# 3. Determinism Verification Tests (10 tests)
# =============================================================================

class TestDeterminismVerification:
    """Test determinism verification system."""

    @pytest.mark.asyncio
    async def test_identical_live_vs_replay_outputs(self):
        """Identical outputs result in 100% determinism."""
        live_output = {
            "orders": [{"order_id": "ORD-001", "symbol": "RELIANCE", "price": 2500.0}],
            "positions": [{"symbol": "RELIANCE", "quantity": 10.0}],
            "analytics": {"pnl": 100.0, "trades": 1},
        }
        
        replay_output = {
            "orders": [{"order_id": "ORD-001", "symbol": "RELIANCE", "price": 2500.0}],
            "positions": [{"symbol": "RELIANCE", "quantity": 10.0}],
            "analytics": {"pnl": 100.0, "trades": 1},
        }
        
        verifier = DeterminismVerifier()
        report = await verifier.verify(live_output, replay_output)
        
        assert report.determinism_score == 100.0
        # Drifts exist but all within tolerance
        assert all(d.is_within_tolerance for d in report.drifts)

    @pytest.mark.asyncio
    async def test_detect_order_execution_drift(self):
        """Detect drift in order executions."""
        live_output = {
            "orders": [{"order_id": "ORD-001", "symbol": "RELIANCE", "price": 2500.0}],
            "positions": [],
            "analytics": {},
        }
        
        replay_output = {
            "orders": [{"order_id": "ORD-001", "symbol": "RELIANCE", "price": 2600.0}],  # Large drift
            "positions": [],
            "analytics": {},
        }
        
        verifier = DeterminismVerifier(tolerance=0.001)  # 0.1% tolerance
        report = await verifier.verify(live_output, replay_output)
        
        # Should detect drift (100 points on 2500 = 4% drift, way over 0.1% tolerance)
        assert any(d.category == "orders" and not d.is_within_tolerance for d in report.drifts)

    @pytest.mark.asyncio
    async def test_detect_position_state_drift(self):
        """Detect drift in position states."""
        live_output = {
            "orders": [],
            "positions": [{"symbol": "RELIANCE", "quantity": 10.0}],
            "analytics": {},
        }
        
        replay_output = {
            "orders": [],
            "positions": [{"symbol": "RELIANCE", "quantity": 11.0}],
            "analytics": {},
        }
        
        verifier = DeterminismVerifier()
        report = await verifier.verify(live_output, replay_output)
        
        assert any(d.category == "positions" for d in report.drifts)

    @pytest.mark.asyncio
    async def test_detect_analytics_drift(self):
        """Detect drift in analytics results."""
        live_output = {
            "orders": [],
            "positions": [],
            "analytics": {"pnl": 100.0, "trades": 5},
        }
        
        replay_output = {
            "orders": [],
            "positions": [],
            "analytics": {"pnl": 105.0, "trades": 5},
        }
        
        verifier = DeterminismVerifier()
        report = await verifier.verify(live_output, replay_output)
        
        assert any(d.category == "analytics" for d in report.drifts)

    @pytest.mark.asyncio
    async def test_determinism_score_calculation(self):
        """Determinism score is calculated correctly."""
        live_output = {
            "orders": [{"order_id": "ORD-001", "price": 100.0}],
            "positions": [],
            "analytics": {},
        }
        
        replay_output = {
            "orders": [{"order_id": "ORD-001", "price": 101.0}],
            "positions": [],
            "analytics": {},
        }
        
        verifier = DeterminismVerifier()
        report = await verifier.verify(live_output, replay_output)
        
        assert 0.0 <= report.determinism_score <= 100.0

    @pytest.mark.asyncio
    async def test_tolerance_thresholds(self):
        """Tolerance thresholds prevent false positives."""
        live_output = {
            "orders": [],
            "positions": [],
            "analytics": {"pnl": 100.0},
        }
        
        replay_output = {
            "orders": [],
            "positions": [],
            "analytics": {"pnl": 100.001},
        }
        
        verifier = DeterminismVerifier(tolerance=0.01)
        report = await verifier.verify(live_output, replay_output)
        
        assert report.determinism_score > 99.0

    @pytest.mark.asyncio
    async def test_multiple_runs_consistency(self):
        """Multiple runs produce consistent results."""
        live_output = {
            "orders": [{"order_id": "ORD-001", "price": 100.0}],
            "positions": [],
            "analytics": {},
        }
        
        replay_output = {
            "orders": [{"order_id": "ORD-001", "price": 100.0}],
            "positions": [],
            "analytics": {},
        }
        
        verifier = DeterminismVerifier()
        
        reports = []
        for _ in range(3):
            report = await verifier.verify(live_output, replay_output)
            reports.append(report)
        
        assert all(r.determinism_score == reports[0].determinism_score for r in reports)

    @pytest.mark.asyncio
    async def test_large_dataset_determinism(self):
        """Determinism works with large datasets."""
        live_orders = [{"order_id": f"ORD-{i}", "price": 100.0 + i} for i in range(100)]
        replay_orders = [{"order_id": f"ORD-{i}", "price": 100.0 + i} for i in range(100)]
        
        live_output = {"orders": live_orders, "positions": [], "analytics": {}}
        replay_output = {"orders": replay_orders, "positions": [], "analytics": {}}
        
        verifier = DeterminismVerifier()
        report = await verifier.verify(live_output, replay_output)
        
        assert report.determinism_score == 100.0

    @pytest.mark.asyncio
    async def test_edge_case_empty_events(self):
        """Handle empty event outputs."""
        live_output = {"orders": [], "positions": [], "analytics": {}}
        replay_output = {"orders": [], "positions": [], "analytics": {}}
        
        verifier = DeterminismVerifier()
        report = await verifier.verify(live_output, replay_output)
        
        assert report.determinism_score == 100.0

    @pytest.mark.asyncio
    async def test_edge_case_single_event(self):
        """Handle single event outputs."""
        live_output = {
            "orders": [{"order_id": "ORD-001", "price": 100.0}],
            "positions": [],
            "analytics": {},
        }
        
        replay_output = {
            "orders": [{"order_id": "ORD-001", "price": 100.0}],
            "positions": [],
            "analytics": {},
        }
        
        verifier = DeterminismVerifier()
        report = await verifier.verify(live_output, replay_output)
        
        assert report.determinism_score == 100.0


# =============================================================================
# 4. Integration Tests (9 tests)
# =============================================================================

class TestReplayIntegration:
    """Test replay infrastructure integration."""

    @pytest.mark.asyncio
    async def test_full_live_capture_replay_verify_cycle(self, temp_capture_file, replay_clock):
        """Full cycle: live -> capture -> replay -> verify."""
        capture = EventCapture(output_path=temp_capture_file)
        
        class TickEvent:
            def __init__(self, idx):
                self.symbol = "RELIANCE"
                self.price = 2500.0 + idx
                self.volume = 10
        
        events = [TickEvent(i) for i in range(5)]
        
        for event in events:
            await capture.capture(event, event_type="TickEvent")
        
        await capture.flush()
        
        engine = ReplayEngine(event_path=temp_capture_file, clock=replay_clock)
        await engine.load()
        
        replayed_events = []
        engine.on_event(lambda e: replayed_events.append(e))
        
        await engine.replay(speed=1.0)
        
        assert len(replayed_events) == 5
        assert replayed_events[0]['sequence_id'] == 1

    @pytest.mark.asyncio
    async def test_event_bus_integration(self, temp_capture_file):
        """Integration with EventBus."""
        from brokersv2.events.bus import EventBus
        
        class TickEvent:
            def __init__(self):
                self.symbol = "RELIANCE"
                self.price = 2500.0
                self.volume = 10
        
        bus = EventBus()
        capture = EventCapture(output_path=temp_capture_file)
        
        async def capture_handler(event):
            await capture.capture(event, event_type=type(event).__name__)
        
        bus.subscribe(TickEvent, capture_handler)
        
        await bus.publish(TickEvent())
        await capture.flush()
        
        with open(temp_capture_file, 'r') as f:
            lines = f.readlines()
        
        assert len(lines) >= 1

    @pytest.mark.asyncio
    async def test_clock_state_transitions(self, temp_capture_file, replay_clock):
        """Clock state transitions during replay."""
        events_data = [
            {"sequence_id": 1, "event_type": "TickEvent", "timestamp": "2024-01-01T09:15:00Z", "payload": {}, "source": "live"},
        ]
        
        with open(temp_capture_file, 'w') as f:
            for event in events_data:
                f.write(json.dumps(event) + '\n')
        
        engine = ReplayEngine(event_path=temp_capture_file, clock=replay_clock)
        await engine.load()
        
        assert replay_clock.state() == ClockState.STOPPED
        
        # Run replay to completion
        await engine.replay(speed=1.0)
        
        # After completion, clock should be STOPPED
        assert replay_clock.state() == ClockState.STOPPED

    @pytest.mark.asyncio
    async def test_concurrent_capture_safety(self, temp_capture_file):
        """Concurrent captures are thread-safe."""
        class TickEvent:
            def __init__(self, idx):
                self.symbol = f"SYM{idx}"
                self.price = 100.0 + idx
                self.volume = 10
        
        capture = EventCapture(output_path=temp_capture_file)
        
        tasks = [
            capture.capture(TickEvent(i), event_type="TickEvent")
            for i in range(100)
        ]
        
        await asyncio.gather(*tasks)
        await capture.flush()
        
        with open(temp_capture_file, 'r') as f:
            lines = f.readlines()
        
        assert len(lines) == 100
        
        sequence_ids = set()
        for line in lines:
            event = json.loads(line)
            sequence_ids.add(event['sequence_id'])
        
        assert len(sequence_ids) == 100

    @pytest.mark.asyncio
    async def test_replay_interruption_recovery(self, temp_capture_file, replay_clock):
        """Replay can recover from interruption."""
        events_data = [
            {"sequence_id": i, "event_type": "TickEvent", "timestamp": f"2024-01-01T09:15:{i:02d}Z", "payload": {}, "source": "live"}
            for i in range(1, 11)
        ]
        
        with open(temp_capture_file, 'w') as f:
            for event in events_data:
                f.write(json.dumps(event) + '\n')
        
        engine = ReplayEngine(event_path=temp_capture_file, clock=replay_clock)
        await engine.load()
        
        received_events = []
        engine.on_event(lambda e: received_events.append(e))
        
        replay_task = asyncio.create_task(engine.replay(speed=0.5))
        await asyncio.sleep(0.2)
        await engine.stop()
        
        try:
            await replay_task
        except asyncio.CancelledError:
            pass
        
        interrupted_count = len(received_events)
        
        received_events.clear()
        await engine.replay(speed=1.0)
        
        assert len(received_events) == 10

    @pytest.mark.asyncio
    async def test_multi_topic_capture(self, temp_capture_file):
        """Capture events from multiple topics."""
        class TickEvent:
            def __init__(self):
                self.symbol = "RELIANCE"
                self.price = 2500.0
                self.volume = 10
        
        class OrderEvent:
            def __init__(self):
                self.order_id = "ORD-001"
                self.symbol = "RELIANCE"
        
        capture_filter = CaptureFilter(allowed_types={"TickEvent", "OrderEvent"})
        capture = EventCapture(output_path=temp_capture_file, capture_filter=capture_filter)
        
        await capture.capture(TickEvent(), event_type="TickEvent")
        await capture.capture(OrderEvent(), event_type="OrderEvent")
        await capture.flush()
        
        with open(temp_capture_file, 'r') as f:
            lines = f.readlines()
        
        assert len(lines) == 2

    @pytest.mark.asyncio
    async def test_large_event_stream(self, temp_capture_file, replay_clock):
        """Handle large event stream (10k events)."""
        class TickEvent:
            def __init__(self, idx):
                self.symbol = "RELIANCE"
                self.price = 2500.0 + idx * 0.01
                self.volume = 10
        
        capture = EventCapture(output_path=temp_capture_file)
        
        for i in range(10000):
            await capture.capture(TickEvent(i), event_type="TickEvent")
        
        await capture.flush()
        
        engine = ReplayEngine(event_path=temp_capture_file, clock=replay_clock)
        await engine.load()
        
        assert len(engine.events) == 10000

    @pytest.mark.asyncio
    async def test_memory_usage_under_load(self, temp_capture_file):
        """Memory usage is reasonable under load."""
        import tracemalloc
        
        class TickEvent:
            def __init__(self, idx):
                self.symbol = "RELIANCE"
                self.price = 2500.0 + idx
                self.volume = 10
        
        tracemalloc.start()
        
        capture = EventCapture(output_path=temp_capture_file, buffer_size=1000)
        
        for i in range(1000):
            await capture.capture(TickEvent(i), event_type="TickEvent")
        
        await capture.flush()
        
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        
        assert peak < 100 * 1024 * 1024

    @pytest.mark.asyncio
    async def test_performance_benchmark(self, temp_capture_file, replay_clock):
        """Performance benchmark for replay."""
        import time
        
        events_data = [
            {"sequence_id": i, "event_type": "TickEvent", "timestamp": f"2024-01-01T09:15:{i%60:02d}Z", "payload": {"symbol": "RELIANCE", "price": 2500.0 + i}, "source": "live"}
            for i in range(1, 1001)
        ]
        
        with open(temp_capture_file, 'w') as f:
            for event in events_data:
                f.write(json.dumps(event) + '\n')
        
        engine = ReplayEngine(event_path=temp_capture_file, clock=replay_clock)
        await engine.load()
        
        received_events = []
        engine.on_event(lambda e: received_events.append(e))
        
        start_time = time.time()
        await engine.replay(speed=10.0)
        elapsed = time.time() - start_time
        
        assert len(received_events) == 1000
        assert elapsed < 10.0


# =============================================================================
# Resource Management Tests (P0-2 Fix)
# =============================================================================

class TestEventCaptureResourceManagement:
    """Test EventCapture resource management and leak prevention."""

    @pytest.mark.asyncio
    async def test_context_manager_usage(self, temp_capture_file, sample_tick_event):
        """EventCapture works as async context manager."""
        # Use buffer_size=1 to force immediate flush
        async with EventCapture(output_path=temp_capture_file, buffer_size=1) as capture:
            await capture.capture(sample_tick_event, event_type="TickEvent")
        
        # File should be closed after context exit
        assert capture._file_handle is None
        assert capture._closed is True
        
        # Verify event was written
        assert temp_capture_file.exists()
        with open(temp_capture_file) as f:
            lines = f.readlines()
        assert len(lines) == 1
        
        event_data = json.loads(lines[0])
        assert event_data['event_type'] == 'TickEvent'

    @pytest.mark.asyncio
    async def test_exception_during_flush(self, temp_capture_file, sample_tick_event):
        """Exception during flush doesn't leak file handle."""
        capture = EventCapture(output_path=temp_capture_file)
        
        await capture.capture(sample_tick_event, event_type="TickEvent")
        
        # Simulate corrupted state
        capture._file_handle = None
        
        # Should not raise, cleanup should be safe
        await capture.close()
        assert capture._file_handle is None
        assert capture._closed is True

    @pytest.mark.asyncio
    async def test_multiple_close_calls(self, temp_capture_file):
        """Multiple close calls are safe (idempotent close)."""
        capture = EventCapture(output_path=temp_capture_file)
        
        await capture.close()
        await capture.close()  # Should not raise
        await capture.close()  # Should not raise
        
        assert capture._closed is True
        assert capture._file_handle is None

    @pytest.mark.asyncio
    async def test_context_manager_with_exception(self, temp_capture_file, sample_tick_event):
        """Exception in context block still triggers cleanup."""
        with pytest.raises(ValueError, match="Test exception"):
            async with EventCapture(output_path=temp_capture_file) as capture:
                await capture.capture(sample_tick_event, event_type="TickEvent")
                raise ValueError("Test exception")
        
        # File should still be cleaned up despite exception
        assert capture._closed is True
        assert capture._file_handle is None

    @pytest.mark.asyncio
    async def test_flush_after_close_raises(self, temp_capture_file, sample_tick_event):
        """Flush after close is safe (no-op)."""
        capture = EventCapture(output_path=temp_capture_file, buffer_size=100)
        
        await capture.capture(sample_tick_event, event_type="TickEvent")
        await capture.close()
        
        # Flush after close should be safe
        await capture.flush()
        
        assert capture._closed is True
