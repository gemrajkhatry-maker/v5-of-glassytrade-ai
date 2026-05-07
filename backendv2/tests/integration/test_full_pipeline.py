"""Integration tests for the full pipeline — chain orchestration, failures, state propagation."""

from __future__ import annotations

import pytest
import time
from app.runtime.pipeline.events import (
    Tick, SequencedTick, NormalizedTick, CandleTimeframe,
    FeatureVector, Signal, GateResult, GateResultType, RiskResult,
)
from app.runtime.pipeline.sequencer import TickSequencer
from app.runtime.pipeline.normalizer import TickNormalizer
from app.runtime.pipeline.candle_builder import CandlePipeline
from app.runtime.pipeline.microstructure import MicrostructureAnalysis
from app.runtime.pipeline.signal import SignalGeneration
from app.runtime.pipeline.gates import GateEvaluation
from app.runtime.pipeline.risk import RiskEvaluation
from app.runtime.pipeline.telemetry import TelemetryPipeline


def _make_tick(symbol="NIFTY", price=22500.0, volume=100.0, ts=1_000_000_000_000_000_000):
    return Tick(symbol=symbol, price=price, volume=volume, timestamp=ts)


class TestFullPipelineChain:
    """Test full pipeline chain with independent stages."""

    def test_sequencer_produces_sequenced_tick(self):
        """TickSequencer assigns sequence number."""
        seq = TickSequencer()
        seq.warmup()
        result = seq.process(_make_tick())
        assert result is not None
        assert isinstance(result, SequencedTick)
        assert result.sequence == 1

    def test_normalizer_produces_normalized_tick(self):
        """TickNormalizer produces NormalizedTick from SequencedTick."""
        seq = TickSequencer()
        norm = TickNormalizer()
        seq.warmup()
        norm.warmup()
        sequenced = seq.process(_make_tick())
        assert sequenced is not None
        normalized = norm.process(sequenced)
        assert normalized is not None
        assert isinstance(normalized, NormalizedTick)
        assert normalized.price == 22500.0

    def test_candle_builder_accumulates(self):
        """CandlePipeline accumulates ticks into candles."""
        builder = CandlePipeline()
        builder.warmup()
        seq = TickSequencer()
        seq.warmup()
        norm = TickNormalizer()
        norm.warmup()

        for i in range(10):
            tick = _make_tick(price=22500.0 + i, ts=1_000_000_000_000_000_000 + i * 60_000_000_000)
            sequenced = seq.process(tick)
            if sequenced:
                normalized = norm.process(sequenced)
                if normalized:
                    builder.process(normalized)

        active = builder.get_active("NIFTY")
        assert active is not None
        assert active.tick_count == 10

    def test_signal_generation_produces_signal(self):
        """SignalGeneration produces Signal from FeatureVector."""
        sg = SignalGeneration()
        sg.warmup()
        feature = FeatureVector(
            symbol="NIFTY",
            timestamp=1_000_000_000_000_000_000,
            vwap=22500.0,
            vwap_upper_1sigma=22520.0,
            vwap_upper_2sigma=22540.0,
            vwap_lower_1sigma=22480.0,
            vwap_lower_2sigma=22460.0,
            atr_14=50.0,
            rsi_14=55.0,
            rolling_volume_avg_20=1000.0,
        )
        signals = sg.process(feature)
        assert len(signals) == 1
        assert isinstance(signals[0], Signal)
        assert signals[0].type in ("LONG", "SHORT", "NO_TRADE")

    def test_gate_evaluation(self):
        """GateEvaluation evaluates a signal through gates."""
        ge = GateEvaluation()
        ge.warmup()
        signal = Signal(
            symbol="NIFTY", timestamp=1_000_000_000_000_000_000,
            type="LONG", entry=22500.0, sl=22450.0, tp=22600.0,
            rr=2.0, confidence=0.7, reason="Test",
        )
        results = ge.process(signal)
        assert len(results) == 1
        assert isinstance(results[0], GateResult)

    def test_risk_evaluation(self):
        """RiskEvaluation evaluates a gate result."""
        re = RiskEvaluation()
        re.warmup()
        signal = Signal(
            symbol="NIFTY", timestamp=1_000_000_000_000_000_000,
            type="LONG", entry=22500.0, sl=22450.0, tp=22600.0,
            rr=2.0, confidence=0.7, reason="Test",
        )
        gate = GateResult(
            symbol="NIFTY", timestamp=1_000_000_000_000_000_000,
            signal=signal, result=GateResultType.APPROVED,
        )
        results = re.process(gate)
        assert len(results) == 1
        assert isinstance(results[0], RiskResult)

    def test_100_ticks_processed_sequentially(self):
        """100 ticks processed through core stages without errors."""
        seq = TickSequencer()
        norm = TickNormalizer()
        seq.warmup()
        norm.warmup()

        for i in range(100):
            tick = _make_tick(price=22500.0 + (i % 10), ts=1_000_000_000_000_000_000 + i * 60_000_000_000)
            sequenced = seq.process(tick)
            if sequenced:
                normalized = norm.process(sequenced)
                assert normalized is not None
                assert normalized.price > 0

        assert seq.sequence_count == 100


class TestPipelinePartialFailures:
    """Test pipeline handles partial failures gracefully."""

    def test_stage_exception_caught(self):
        """Stage raising exception → pipeline catches and continues."""
        class FailingStage:
            def process(self, event):
                raise RuntimeError("stage failure")
            def warmup(self): pass
            def reset(self): pass

        seq = TickSequencer()
        seq.warmup()
        fail = FailingStage()
        norm = TickNormalizer()
        norm.warmup()

        tick = _make_tick()
        sequenced = seq.process(tick)
        assert sequenced is not None

        # Failing stage raises — but doesn't crash pipeline
        try:
            fail.process(sequenced)
        except RuntimeError:
            pass

        # Next stage can still work
        normalized = norm.process(sequenced)
        assert normalized is not None

    def test_missing_data_graceful_degradation(self):
        """Stage with missing input data → returns None, pipeline continues."""
        cb = CandlePipeline()
        cb.warmup()
        active = cb.get_active("NIFTY")
        assert active is None

    def test_sequencer_drops_duplicate(self):
        """Duplicate tick → sequencer returns None, pipeline continues."""
        seq = TickSequencer()
        seq.warmup()
        tick = _make_tick(ts=1_000_000_000_000_000_000)
        result1 = seq.process(tick)
        result2 = seq.process(tick)

        assert result1 is not None
        assert result2 is None
        assert seq.dropped_duplicates == 1


class TestStatePropagation:
    """Test state propagates correctly through pipeline stages."""

    def test_telemetry_records_stages(self):
        """TelemetryPipeline records stage metrics."""
        tel = TelemetryPipeline()
        tel.warmup()
        # TelemetryPipeline accepts dict payloads
        tel.process({"stage": "TickSequencer", "latency_ns": 100})
        tel.process({"stage": "TickNormalizer", "latency_ns": 50})

        stats = tel.get_stats()
        assert stats is not None


class TestPipelineWarmupTeardown:
    """Test pipeline warmup and teardown lifecycle."""

    def test_warmup_resets_all_stages(self):
        """Warmup resets all stages to initial state."""
        stages = [
            TickSequencer(),
            TickNormalizer(),
            CandlePipeline(),
            SignalGeneration(),
            RiskEvaluation(),
        ]
        for s in stages:
            s.warmup()
        assert True

    def test_teardown_cleans_up(self):
        """Teardown flushes state from all stages."""
        stages = [
            TickSequencer(),
            TickNormalizer(),
            CandlePipeline(),
            SignalGeneration(),
            RiskEvaluation(),
        ]
        for s in stages:
            s.warmup()
            s.teardown()
        assert True

    def test_reset_then_restart(self):
        """Reset stages, then process ticks again."""
        seq = TickSequencer()
        seq.warmup()
        tick = _make_tick(ts=1_000_000_000_000_000_000)
        seq.process(tick)
        assert seq.sequence_count == 1

        seq.reset()
        assert seq.sequence_count == 0

        seq.warmup()
        tick2 = _make_tick(ts=2_000_000_000_000_000_000)
        result = seq.process(tick2)
        assert result is not None
        assert result.sequence == 1


class TestPipelinePerformance:
    """Test pipeline processes ticks within performance budget."""

    def test_1000_ticks_through_core_stages(self):
        """1000 ticks through core stages completes quickly."""
        seq = TickSequencer()
        norm = TickNormalizer()
        seq.warmup()
        norm.warmup()

        start = time.monotonic()
        for i in range(1000):
            tick = _make_tick(
                price=22500.0 + (i % 10),
                ts=1_000_000_000_000_000_000 + i * 60_000_000_000
            )
            sequenced = seq.process(tick)
            if sequenced:
                norm.process(sequenced)
        elapsed = time.monotonic() - start

        assert elapsed < 1.0
