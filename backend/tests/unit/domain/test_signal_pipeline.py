"""Tests for SignalPipeline."""

from __future__ import annotations

import pytest

from app.domain.fabio_ai.services.signal_pipeline import SignalPipeline, TradeContext
from app.domain.trading.models.enums import MarketState, SetupType, SignalType


def test_signal_pipeline_creates_signal_with_valid_context():
    """SignalPipeline creates Signal when context passes gates."""
    pipeline = SignalPipeline()
    ctx = TradeContext(
        symbol="CRUDEOIL",
        current_price=100.0,
        market_state="IMBALANCED",
        aggression_score=3.0,
        setup_type="MEAN_REVERSION",
        session_phase="MORNING",
        llm_decision={"type": "BUY", "reason": "test"},
        take_profit=110.0,
        stop_loss=90.0,
    )
    result = pipeline.evaluate(ctx)
    assert result is not None
    assert result.type == SignalType.BUY


def test_signal_pipeline_none_for_no_symbol():
    """SignalPipeline returns None when no symbol."""
    pipeline = SignalPipeline()
    ctx = TradeContext(symbol="")
    result = pipeline.evaluate(ctx)
    assert result is None


def test_signal_pipeline_determine_signal_type_from_llm():
    """_determine_signal_type extracts BUY from LLM decision."""
    pipeline = SignalPipeline()
    ctx = TradeContext(llm_decision={"type": "SELL"})
    result = pipeline._determine_signal_type(ctx)
    assert result == SignalType.SELL


def test_signal_pipeline_determine_signal_type_from_metadata():
    """_determine_signal_type extracts from metadata signal_type key."""
    pipeline = SignalPipeline()
    ctx = TradeContext(metadata={"signal_type": "SELL"})
    result = pipeline._determine_signal_type(ctx)
    assert result == SignalType.SELL


def test_signal_pipeline_determine_signal_type_from_direction():
    """_determine_signal_type extracts from metadata direction key."""
    pipeline = SignalPipeline()
    ctx = TradeContext(metadata={"direction": "LONG"})
    result = pipeline._determine_signal_type(ctx)
    assert result == SignalType.BUY


def test_signal_pipeline_determine_setup_type_trend():
    """_determine_setup_type returns TREND_MODEL for trend setup."""
    pipeline = SignalPipeline()
    ctx = TradeContext(setup_type="TREND_MODEL")
    result = pipeline._determine_setup_type(ctx)
    assert result == SetupType.TREND_MODEL


def test_signal_pipeline_determine_setup_type_mean_reversion():
    """_determine_setup_type returns MEAN_REVERSION."""
    pipeline = SignalPipeline()
    ctx = TradeContext(setup_type="MEAN_REVERSION")
    result = pipeline._determine_setup_type(ctx)
    assert result == SetupType.MEAN_REVERSION


def test_signal_pipeline_determine_setup_type_from_metadata():
    """_determine_setup_type reads from metadata."""
    pipeline = SignalPipeline()
    ctx = TradeContext(metadata={"setup_type": "PREDICTION_ENTRY"})
    result = pipeline._determine_setup_type(ctx)
    assert result == SetupType.PREDICTION_ENTRY


def test_signal_pipeline_determine_setup_type_default():
    """_determine_setup_type returns TREND_MODEL as default."""
    pipeline = SignalPipeline()
    ctx = TradeContext()
    result = pipeline._determine_setup_type(ctx)
    assert result == SetupType.TREND_MODEL


def test_signal_pipeline_with_custom_signal_builder():
    """SignalPipeline uses custom signal builder when provided."""
    from app.domain.trading.models.entities import Signal
    
    def custom_builder(ctx):
        return Signal.create(
            type=SignalType.BUY,
            price=ctx.current_price,
            reason="custom",
            stop_loss=ctx.stop_loss,
            take_profit=ctx.take_profit,
            timestamp="2024-01-01T00:00:00",
            setup=SetupType.MEAN_REVERSION,
            source="AMT",
        )
    
    pipeline = SignalPipeline(signal_builder_fn=custom_builder)
    ctx = TradeContext(
        symbol="TEST",
        current_price=100.0,
        take_profit=110.0,
        stop_loss=90.0,
    )
    result = pipeline.evaluate(ctx)
    assert result is not None
    assert "custom" in result.reason