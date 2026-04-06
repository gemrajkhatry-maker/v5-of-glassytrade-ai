"""Tests for pipeline message schemas."""
import pytest
from datetime import datetime, timezone
from app.pipeline.message import (
    Message, RawTickPayload, CandlePayload, AMTResultPayload,
    LLMDecisionPayload, SignalGatePayload,
)


def test_message_envelope_defaults():
    msg = Message(
        payload=RawTickPayload(ltp=100.0),
        symbol="TEST",
        timestamp=datetime.now(timezone.utc),
    )
    assert msg.message_id != ""
    assert msg.correlation_id != ""
    assert msg.source_processor == ""
    assert msg.pipeline_id == "default"


def test_message_is_immutable():
    msg = Message(payload=RawTickPayload(ltp=50.0), symbol="TEST", timestamp=datetime.now(timezone.utc))
    with pytest.raises((AttributeError, TypeError)):
        msg.symbol = "OTHER"  # frozen dataclass


def test_raw_tick_payload_defaults():
    tick = RawTickPayload(ltp=123.45)
    assert tick.volume == 0
    assert tick.oi == 0
    assert tick.source == "ws"
    assert tick.depth_bids == ()


def test_candle_payload():
    candle = CandlePayload(
        time="2026-03-14T09:15:00+05:30",
        open=100.0, high=105.0, low=99.0, close=103.0,
        volume=5000.0, delta=200.0,
    )
    assert candle.closed is False
    assert candle.vwap == 0.0


def test_correlation_id_propagation():
    """correlation_id should be preserved when creating derived messages."""
    tick = Message(
        payload=RawTickPayload(ltp=100.0),
        symbol="NIFTY",
        timestamp=datetime.now(timezone.utc),
        correlation_id="my-correlation-id",
    )
    candle = Message(
        payload=CandlePayload(time="t", open=100, high=101, low=99, close=100, volume=100, delta=0),
        symbol=tick.symbol,
        timestamp=tick.timestamp,
        correlation_id=tick.correlation_id,  # preserved
    )
    assert candle.correlation_id == "my-correlation-id"


def test_llm_decision_payload():
    dec = LLMDecisionPayload(direction="LONG", logic="Strong imbalance", trigger="Break above VAH")
    assert dec.probability == 0.0
    assert dec.latency_ms == 0.0


def test_amt_result_payload():
    result = AMTResultPayload(
        market_state="IMBALANCED", leg_state="IMBALANCED",
        poc=100.0, vah=105.0, val=95.0,
    )
    assert result.near_level is False
    assert result.confirmation_score == 0
