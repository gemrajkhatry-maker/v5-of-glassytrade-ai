"""Unit tests for AMTAnalysisProcessor and SignalGateProcessor.

All external domain dependencies (AMTHandler, three_align_check) are mocked so
these tests exercise only the pipeline plumbing — message routing, payload
translation, candle-history management, and gate pass/fail propagation.

Tests:
  - test_amt_processor_produces_result_on_closed_candle
  - test_amt_processor_skips_open_candle_for_history
  - test_amt_processor_accumulates_candle_history
  - test_gate_processor_emits_gate_pass_true
  - test_gate_processor_emits_gate_pass_false
  - test_gate_processor_passes_through_all_messages
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.pipeline.channel import Channel
from app.pipeline.message import (
    AMTResultPayload,
    CandlePayload,
    Message,
    SignalGatePayload,
)
from app.pipeline.processor import ProcessorConfig
from app.pipeline.processors.analysis import AMTAnalysisProcessor
from app.pipeline.processors.gate import SignalGateProcessor


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

IST = timezone(timedelta(hours=5, minutes=30))
# Use 10:00 IST = NSE_PRIMARY session (allows all models)
# Previously used 09:15 which is NSE_OPENING (no entry allowed per Fabio rule)
_BASE_TS = datetime(2026, 3, 14, 10, 0, 0, tzinfo=IST)

_SYMBOL = "NIFTY"


# ---------------------------------------------------------------------------
# Fake / stub helpers
# ---------------------------------------------------------------------------


def _fake_amt_result(
    market_state: str = "BALANCED",
    poc: float = 100.0,
    vah: float = 105.0,
    val: float = 95.0,
    cvd_slope: float = 0.0,
    aggression: float = 0.0,
    market_structure: str = "BALANCE",
    profile_shape: str = "D",
    balance_ratio: float = 0.5,
) -> SimpleNamespace:
    """Build a minimal AMTResult-like namespace for use in mocks.
    
    Includes all fields required by the enriched AMTResultPayload.
    """
    return SimpleNamespace(
        market_state=market_state,
        poc=poc,
        value_area_high=vah,
        value_area_low=val,
        cvd_slope=cvd_slope,
        cvd_divergence="",
        profile_shape=profile_shape,
        aggression=aggression,
        market_structure=market_structure,
        balance_ratio=balance_ratio,
        # Enriched fields
        session_vwap=0.0,
        vwap_upper_2=0.0,
        vwap_lower_2=0.0,
        dev_poc=0.0,
        dev_vah=0.0,
        dev_val=0.0,
        leg_poc=0.0,
        leg_vah=0.0,
        leg_val=0.0,
        leg_lvns=(),
        lvns=(),
        hvns=(),
        lvn_play=None,
        aggressive_prints=(),
        bubble_retests=[],
    )


def _make_candle_msg(
    symbol: str = _SYMBOL,
    close: float = 100.0,
    ts: datetime | None = None,
    closed: bool = True,
    volume: float = 1000.0,
    delta: float = 50.0,
) -> Message:
    """Factory for CandleMessage."""
    ts = ts or _BASE_TS
    payload = CandlePayload(
        time=ts.isoformat(),
        open=close - 1.0,
        high=close + 2.0,
        low=close - 2.0,
        close=close,
        volume=volume,
        delta=delta,
        vwap=close,
        closed=closed,
    )
    return Message(
        payload=payload,
        symbol=symbol,
        timestamp=ts,
        source_processor="test",
        pipeline_id="test",
    )


def _make_amt_result_msg(
    symbol: str = _SYMBOL,
    market_state: str = "BALANCED",
    poc: float = 100.0,
    vah: float = 105.0,
    val: float = 95.0,
    ts: datetime | None = None,
) -> Message:
    """Factory for AMTResultMessage with enriched fields."""
    ts = ts or _BASE_TS
    payload = AMTResultPayload(
        market_state=market_state,
        leg_state="BALANCE",
        poc=poc,
        vah=vah,
        val=val,
        cvd_slope=0.0,
        cvd_divergence=False,
        profile_shape="D",
        delta_score=0.0,
        aggression="NEUTRAL",
        balance_pct=50.0,
        near_level=False,
        confirmation_score=0,
        # Enriched fields
        dev_poc=0.0,
        dev_vah=0.0,
        dev_val=0.0,
        leg_poc=0.0,
        leg_vah=0.0,
        leg_val=0.0,
        leg_lvns=(),
        session_vwap=0.0,
        vwap_upper_2=0.0,
        vwap_lower_2=0.0,
        lvns=(),
        hvns=(),
        lvn_play=None,
        aggressive_prints=(),
        bubble_retests=(),
    )
    return Message(
        payload=payload,
        symbol=symbol,
        timestamp=ts,
        source_processor="amt_analysis",
        pipeline_id="test",
    )


# ---------------------------------------------------------------------------
# Helpers to wire up processor and drain the output channel
# ---------------------------------------------------------------------------


async def _run_amt_processor(
    candle_msgs: list[Message],
    mock_handler_factory=None,
    lookback: int = 50,
) -> list[Message]:
    """Feed *candle_msgs* through a (mocked) AMTAnalysisProcessor.

    If *mock_handler_factory* is provided it is called with the symbol each
    time a new handler would be created (replaces the real AMTHandler import).
    """
    processor = AMTAnalysisProcessor()
    config = ProcessorConfig(
        name="test_amt",
        processor_class="app.pipeline.processors.analysis.AMTAnalysisProcessor",
        inbox={"candles": "candles"},
        outbox={"amt_results": "amt_results"},
        settings={"lookback": lookback},
    )
    await processor.setup(config)

    # Replace the real AMTHandler with a lightweight fake
    if mock_handler_factory is not None:
        processor._handlers = {}

        original_get_handler = processor._get_handler

        def patched_get_handler(symbol: str):
            if symbol not in processor._handlers:
                processor._handlers[symbol] = mock_handler_factory(symbol)
            return processor._handlers[symbol]

        processor._get_handler = patched_get_handler

    in_ch: Channel = Channel("candles", capacity=500)
    out_ch: Channel = Channel("amt_results", capacity=500)

    for msg in candle_msgs:
        await in_ch.send(msg)
    await in_ch.close()

    await processor.process({"candles": in_ch}, {"amt_results": out_ch})

    results: list[Message] = []
    while True:
        try:
            m = out_ch._queue.get_nowait()
            if m is None:
                break
            results.append(m)
        except Exception:
            break
    return results


async def _run_gate_processor(
    amt_msgs: list[Message],
    three_align_return_value=None,
    min_candles: int = 6,
) -> list[Message]:
    """Feed *amt_msgs* through a SignalGateProcessor with a mocked gate call."""
    if three_align_return_value is None:
        # Default: gate passes, confirmation weak, no second drive
        three_align_return_value = (True, False, False)

    processor = SignalGateProcessor()
    config = ProcessorConfig(
        name="test_gate",
        processor_class="app.pipeline.processors.gate.SignalGateProcessor",
        inbox={"amt_results": "amt_results"},
        outbox={"signal_gates": "signal_gates"},
        settings={"min_candles": min_candles},
    )
    await processor.setup(config)

    in_ch: Channel = Channel("amt_results", capacity=500)
    out_ch: Channel = Channel("signal_gates", capacity=500)

    for msg in amt_msgs:
        await in_ch.send(msg)
    await in_ch.close()

    patch_target = "app.pipeline.processors.gate.three_align_check"
    with patch(patch_target, return_value=three_align_return_value):
        await processor.process({"amt_results": in_ch}, {"signal_gates": out_ch})

    results: list[Message] = []
    while True:
        try:
            m = out_ch._queue.get_nowait()
            if m is None:
                break
            results.append(m)
        except Exception:
            break
    return results


# ---------------------------------------------------------------------------
# Tests — AMTAnalysisProcessor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_amt_processor_produces_result_on_closed_candle():
    """A single closed candle must trigger AMT analysis and emit one result."""
    fake_result = _fake_amt_result()

    def make_handler(_symbol):
        handler = MagicMock()
        handler.analyze.return_value = (fake_result, {}, {})
        return handler

    msgs = [_make_candle_msg(closed=True)]
    results = await _run_amt_processor(msgs, mock_handler_factory=make_handler)

    assert len(results) == 1, f"Expected 1 result, got {len(results)}"
    payload = results[0].payload
    assert isinstance(payload, AMTResultPayload)
    assert payload.market_state == "BALANCED"
    assert payload.poc == pytest.approx(100.0)
    assert payload.vah == pytest.approx(105.0)
    assert payload.val == pytest.approx(95.0)
    assert results[0].symbol == _SYMBOL


@pytest.mark.asyncio
async def test_amt_processor_skips_open_candle_for_history():
    """An open (live) candle must NOT be appended to the closed-candle history.

    Scenario:
      1. One closed candle -> handler.analyze called with 1 OHLC (just the history)
      2. One live candle  -> handler.analyze called with 2 OHLC (history + live bar)
         BUT history should still have length 1 (only the closed candle).
    """
    fake_result = _fake_amt_result()
    captured_calls: list[list] = []

    def make_handler(_symbol):
        handler = MagicMock()

        def side_effect(data, *args, **kwargs):
            captured_calls.append(list(data))
            return fake_result, {}, {}

        handler.analyze.side_effect = side_effect
        return handler

    # Send one closed candle, then one open candle
    msgs = [
        _make_candle_msg(closed=True, close=100.0, ts=_BASE_TS),
        _make_candle_msg(
            closed=False,
            close=101.0,
            ts=_BASE_TS.replace(second=30),
        ),
    ]
    results = await _run_amt_processor(msgs, mock_handler_factory=make_handler)

    # Both messages must produce an output (live candle still triggers analysis
    # using existing history + the live bar)
    assert len(results) == 2

    # First call: history=[closed candle] only
    assert len(captured_calls[0]) == 1, (
        f"First call should have 1 OHLC element (closed candle only), "
        f"got {len(captured_calls[0])}"
    )

    # Second call: history=[closed candle] + live bar appended
    assert len(captured_calls[1]) == 2, (
        f"Second call should have 2 OHLC elements (history + live bar), "
        f"got {len(captured_calls[1])}"
    )


@pytest.mark.asyncio
async def test_amt_processor_accumulates_candle_history():
    """Ten closed candles must build a history of exactly 10 entries."""
    fake_result = _fake_amt_result()
    captured_lengths: list[int] = []

    def make_handler(_symbol):
        handler = MagicMock()

        def side_effect(data, *args, **kwargs):
            captured_lengths.append(len(data))
            return fake_result, {}, {}

        handler.analyze.side_effect = side_effect
        return handler

    n = 10
    msgs = [
        _make_candle_msg(
            closed=True,
            close=100.0 + i,
            ts=_BASE_TS.replace(minute=15 + i),
        )
        for i in range(n)
    ]
    results = await _run_amt_processor(msgs, mock_handler_factory=make_handler)

    assert len(results) == n, f"Expected {n} results, got {len(results)}"

    # History should grow by 1 on each closed candle
    expected_lengths = list(range(1, n + 1))
    assert captured_lengths == expected_lengths, (
        f"History lengths across calls: {captured_lengths}, expected {expected_lengths}"
    )


@pytest.mark.asyncio
async def test_amt_processor_respects_lookback_limit():
    """After exceeding lookback, history must be capped at the lookback value."""
    fake_result = _fake_amt_result()
    captured_lengths: list[int] = []

    def make_handler(_symbol):
        handler = MagicMock()

        def side_effect(data, *args, **kwargs):
            captured_lengths.append(len(data))
            return fake_result, {}, {}

        handler.analyze.side_effect = side_effect
        return handler

    lookback = 5
    n = 8  # more than lookback
    msgs = [
        _make_candle_msg(closed=True, close=100.0 + i, ts=_BASE_TS.replace(minute=15 + i))
        for i in range(n)
    ]
    results = await _run_amt_processor(
        msgs, mock_handler_factory=make_handler, lookback=lookback
    )

    assert len(results) == n
    # After the lookback is exceeded, history length must stay <= lookback
    assert max(captured_lengths) <= lookback, (
        f"History exceeded lookback={lookback}: lengths={captured_lengths}"
    )


# ---------------------------------------------------------------------------
# Tests — SignalGateProcessor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_processor_emits_gate_pass_true():
    """When three_align_check returns (True, ...), SignalGatePayload.passed must be True."""
    msgs = [_make_amt_result_msg()]
    # Gate passes, confirmation strong
    results = await _run_gate_processor(
        msgs, three_align_return_value=(True, True, False)
    )

    assert len(results) == 1
    payload: SignalGatePayload = results[0].payload
    assert isinstance(payload, SignalGatePayload)
    assert payload.passed is True
    assert results[0].symbol == _SYMBOL


@pytest.mark.asyncio
async def test_gate_processor_emits_gate_pass_false():
    """When three_align_check returns (False, ...), SignalGatePayload.passed must be False."""
    msgs = [_make_amt_result_msg()]
    results = await _run_gate_processor(
        msgs, three_align_return_value=(False, False, False)
    )

    assert len(results) == 1
    payload: SignalGatePayload = results[0].payload
    assert payload.passed is False
    assert payload.confidence == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_gate_processor_passes_through_all_messages():
    """Every AMTResultMessage must produce exactly one SignalGateMessage.

    The gate must never silently swallow messages — downstream must always
    receive a gate verdict, even if the gate blocks.
    """
    n = 5
    msgs = [
        _make_amt_result_msg(ts=_BASE_TS.replace(minute=15 + i))
        for i in range(n)
    ]
    # Alternate pass/fail to ensure both paths produce output
    call_count = [0]

    def alternating_gate(*args, **kwargs):
        result = call_count[0] % 2 == 0
        call_count[0] += 1
        return (result, result, False)

    processor = SignalGateProcessor()
    config = ProcessorConfig(
        name="test_gate_passthrough",
        processor_class="app.pipeline.processors.gate.SignalGateProcessor",
        inbox={"amt_results": "amt_results"},
        outbox={"signal_gates": "signal_gates"},
        settings={"min_candles": 6},
    )
    await processor.setup(config)

    in_ch: Channel = Channel("amt_results", capacity=500)
    out_ch: Channel = Channel("signal_gates", capacity=500)

    for msg in msgs:
        await in_ch.send(msg)
    await in_ch.close()

    with patch(
        "app.pipeline.processors.gate.three_align_check",
        side_effect=alternating_gate,
    ):
        await processor.process({"amt_results": in_ch}, {"signal_gates": out_ch})

    results: list[Message] = []
    while True:
        try:
            m = out_ch._queue.get_nowait()
            if m is None:
                break
            results.append(m)
        except Exception:
            break

    # All messages flow through — no filtering
    assert len(results) == n, (
        f"Expected {n} gate messages (one per AMT result), got {len(results)}"
    )

    # First message gate passes (call 0: 0%2==0 → True), second fails, etc.
    assert results[0].payload.passed is True
    assert results[1].payload.passed is False


@pytest.mark.asyncio
async def test_gate_processor_confidence_levels():
    """Confidence must reflect gate outcome + confirmation strength.

    - gate=True, confirmation=True  -> confidence=1.0, grade="A"
    - gate=True, confirmation=False -> confidence=0.5, grade="B"
    - gate=False, any               -> confidence=0.0, grade=""
    """
    base_msg = _make_amt_result_msg()

    # Strong pass
    results_a = await _run_gate_processor([base_msg], (True, True, False))
    # New grading: 0.4 (confirmation) + 0.2 (CVD neutral) + 0.15 (no div) + 0.1 (D-shape) = 0.85
    assert results_a[0].payload.confidence == pytest.approx(0.85)
    assert results_a[0].payload.setup_grade == "A"

    # Weak pass
    results_b = await _run_gate_processor([base_msg], (True, False, False))
    # New grading: 0.15 (weak confirm) + 0.2 (CVD neutral) + 0.15 (no div) + 0.1 (D-shape) = 0.6
    assert results_b[0].payload.confidence == pytest.approx(0.6)
    assert results_b[0].payload.setup_grade == "B"

    # Fail
    results_c = await _run_gate_processor([base_msg], (False, False, False))
    assert results_c[0].payload.confidence == pytest.approx(0.0)
    assert results_c[0].payload.setup_grade == ""
