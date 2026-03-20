"""Unit tests for LLMEntryProcessor and OverseerProcessor.

All LLM inference and overseer handler dependencies are mocked — no real model
inference takes place in these tests.

Tests:
  LLMEntryProcessor
  -----------------
  - test_llm_entry_skips_gate_fail          gate_pass=False → no LLM call, FLAT emitted
  - test_llm_entry_calls_llm_on_gate_pass   gate_pass=True  → LLM called, decision emitted
  - test_llm_entry_timeout_emits_flat       LLM times out   → FLAT decision, no exception
  - test_llm_entry_flat_response_emitted    LLM returns FLAT → direction="FLAT" in payload
  - test_llm_entry_long_response_emitted    LLM returns LONG → direction="LONG" in payload

  OverseerProcessor
  -----------------
  - test_overseer_skips_flat_decision       FLAT direction → no overseer call, HOLD emitted
  - test_overseer_processes_long_decision   LONG direction → overseer called, decision emitted
  - test_overseer_processes_short_decision  SHORT direction → overseer called, decision emitted
  - test_overseer_cooldown_suppresses_call  rapid messages → second message within cooldown → HOLD
  - test_overseer_no_handler_emits_hold     no handler set → HOLD emitted without error
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.pipeline.channel import Channel
from app.pipeline.message import (
    LLMDecisionPayload,
    Message,
    OverseerDecisionPayload,
    SignalGatePayload,
)
from app.pipeline.processor import ProcessorConfig
from app.pipeline.processors.llm_entry import LLMEntryProcessor
from app.pipeline.processors.overseer import OverseerProcessor

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

IST = timezone(timedelta(hours=5, minutes=30))
_BASE_TS = datetime(2026, 3, 14, 9, 15, 0, tzinfo=IST)
_SYMBOL = "NIFTY"


# ---------------------------------------------------------------------------
# Message factories
# ---------------------------------------------------------------------------


def _make_gate_msg(
    passed: bool,
    symbol: str = _SYMBOL,
    setup_grade: str = "A",
    confidence: float = 0.8,
    reason: str = "Three-Align PASSED",
) -> Message:
    """Build a SignalGateMessage for testing."""
    payload = SignalGatePayload(
        passed=passed,
        reason=reason if passed else f"Gate BLOCKED: {reason}",
        setup_grade=setup_grade if passed else "",
        confidence=confidence if passed else 0.0,
    )
    return Message(
        payload=payload,
        symbol=symbol,
        timestamp=_BASE_TS,
        source_processor="test_gate",
        pipeline_id="test",
    )


def _make_llm_decision_msg(
    direction: str,
    symbol: str = _SYMBOL,
    logic: str = "test logic",
    trigger: str = "test",
    probability: float = 0.7,
    latency_ms: float = 50.0,
) -> Message:
    """Build an LLMDecisionMessage for testing."""
    payload = LLMDecisionPayload(
        direction=direction,
        logic=logic,
        trigger=trigger,
        probability=probability,
        latency_ms=latency_ms,
    )
    return Message(
        payload=payload,
        symbol=symbol,
        timestamp=_BASE_TS,
        source_processor="test_llm",
        pipeline_id="test",
    )


# ---------------------------------------------------------------------------
# Helper: run LLMEntryProcessor with given messages and return output
# ---------------------------------------------------------------------------


async def _run_llm_entry(
    gate_msgs: list[Message],
    llm_port: object | None = None,
    timeout_seconds: float = 15.0,
    patch_build_entry_prompt: bool = True,
) -> list[Message]:
    """Wire LLMEntryProcessor, feed messages, drain output channel."""
    processor = LLMEntryProcessor()
    config = ProcessorConfig(
        name="test_llm_entry",
        processor_class="app.pipeline.processors.llm_entry.LLMEntryProcessor",
        inbox={"signal_gates": "signal_gates"},
        outbox={"llm_decisions": "llm_decisions"},
        settings={
            "llm_port": llm_port,
            "timeout_seconds": timeout_seconds,
        },
    )
    await processor.setup(config)

    in_ch: Channel = Channel("signal_gates", capacity=500)
    out_ch: Channel = Channel("llm_decisions", capacity=500)

    for msg in gate_msgs:
        await in_ch.send(msg)
    await in_ch.close()

    if patch_build_entry_prompt:
        with patch(
            "app.pipeline.processors.llm_entry.LLMEntryProcessor._build_prompt_data",
            return_value={},
        ):
            await processor.process({"signal_gates": in_ch}, {"llm_decisions": out_ch})
    else:
        await processor.process({"signal_gates": in_ch}, {"llm_decisions": out_ch})

    await processor.teardown()

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
# Helper: run OverseerProcessor with given messages and return output
# ---------------------------------------------------------------------------


async def _run_overseer(
    decision_msgs: list[Message],
    overseer_handler: object | None = None,
    check_interval_seconds: float = 0.0,  # 0 disables cooldown in tests
) -> list[Message]:
    """Wire OverseerProcessor, feed messages, drain output channel."""
    processor = OverseerProcessor()
    config = ProcessorConfig(
        name="test_overseer",
        processor_class="app.pipeline.processors.overseer.OverseerProcessor",
        inbox={"llm_decisions": "llm_decisions"},
        outbox={"overseer_decisions": "overseer_decisions"},
        settings={
            "overseer_handler": overseer_handler,
            "check_interval_seconds": check_interval_seconds,
        },
    )
    await processor.setup(config)

    in_ch: Channel = Channel("llm_decisions", capacity=500)
    out_ch: Channel = Channel("overseer_decisions", capacity=500)

    for msg in decision_msgs:
        await in_ch.send(msg)
    await in_ch.close()

    await processor.process({"llm_decisions": in_ch}, {"overseer_decisions": out_ch})
    await processor.teardown()

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


# ===========================================================================
# LLMEntryProcessor tests
# ===========================================================================


@pytest.mark.asyncio
async def test_llm_entry_skips_gate_fail():
    """gate_pass=False must emit FLAT without calling the LLM port."""
    mock_port = MagicMock()
    mock_port.is_ready.return_value = True

    msgs = [_make_gate_msg(passed=False)]
    results = await _run_llm_entry(msgs, llm_port=mock_port)

    assert len(results) == 1, f"Expected 1 result, got {len(results)}"
    payload: LLMDecisionPayload = results[0].payload
    assert isinstance(payload, LLMDecisionPayload)
    assert payload.direction == "FLAT"

    # LLM must not be called when gate is blocked
    mock_port.predict.assert_not_called()


@pytest.mark.asyncio
async def test_llm_entry_calls_llm_on_gate_pass():
    """gate_pass=True must trigger an LLM call and emit the parsed decision."""
    mock_port = MagicMock()
    mock_port.is_ready.return_value = True
    # Return a minimal JSON that parse_entry_response can handle
    mock_port.predict.return_value = '{"direction": "LONG", "logic": "bullish", "trigger": "test"}'

    msgs = [_make_gate_msg(passed=True)]

    with patch(
        "app.pipeline.processors.llm_entry.LLMEntryProcessor._build_prompt_data",
        return_value={"ltp": 0.0, "vah": 0.0, "val": 0.0, "poc": 0.0, "delta": 0.0,
                      "volume": 0.0, "market_state": "BALANCED", "profile_shape": "D",
                      "cvd": 0.0, "cvd_divergence": "", "is_second_drive": False,
                      "market_structure": "", "aggressive_prints": [], "bubble_retests": [],
                      "lvn_play": None},
    ), patch(
        "app.pipeline.processors.llm_entry.build_entry_prompt",
        return_value="mocked prompt",
    ), patch(
        "app.pipeline.processors.llm_entry.parse_entry_response",
        return_value={"direction": "LONG", "logic": "bullish", "trigger": "test", "probability": 0.8},
    ):
        processor = LLMEntryProcessor()
        config = ProcessorConfig(
            name="test_llm_entry",
            processor_class="app.pipeline.processors.llm_entry.LLMEntryProcessor",
            inbox={"signal_gates": "signal_gates"},
            outbox={"llm_decisions": "llm_decisions"},
            settings={"llm_port": mock_port, "timeout_seconds": 15.0},
        )
        await processor.setup(config)

        in_ch: Channel = Channel("signal_gates", capacity=500)
        out_ch: Channel = Channel("llm_decisions", capacity=500)

        for msg in msgs:
            await in_ch.send(msg)
        await in_ch.close()

        await processor.process({"signal_gates": in_ch}, {"llm_decisions": out_ch})
        await processor.teardown()

    results: list[Message] = []
    while True:
        try:
            m = out_ch._queue.get_nowait()
            if m is None:
                break
            results.append(m)
        except Exception:
            break

    assert len(results) == 1, f"Expected 1 result, got {len(results)}"
    payload: LLMDecisionPayload = results[0].payload
    assert payload.direction == "LONG"
    assert results[0].symbol == _SYMBOL


@pytest.mark.asyncio
async def test_llm_entry_timeout_emits_flat():
    """When the LLM times out, the processor must emit FLAT and not raise.

    We simulate a timeout by patching ``asyncio.wait_for`` to raise
    ``asyncio.TimeoutError`` directly — this is the cleanest way to verify
    the timeout-handling path without making the test sleep.
    """
    mock_port = MagicMock()
    mock_port.is_ready.return_value = True

    msgs = [_make_gate_msg(passed=True)]

    async def _raise_timeout(*args, **kwargs):
        raise asyncio.TimeoutError("simulated timeout")

    with patch(
        "app.pipeline.processors.llm_entry.LLMEntryProcessor._build_prompt_data",
        return_value={},
    ), patch(
        "app.pipeline.processors.llm_entry.build_entry_prompt",
        return_value="mocked prompt",
    ), patch(
        "app.pipeline.processors.llm_entry.asyncio.wait_for",
        side_effect=_raise_timeout,
    ):
        processor = LLMEntryProcessor()
        config = ProcessorConfig(
            name="test_timeout",
            processor_class="app.pipeline.processors.llm_entry.LLMEntryProcessor",
            inbox={"signal_gates": "signal_gates"},
            outbox={"llm_decisions": "llm_decisions"},
            settings={"llm_port": mock_port, "timeout_seconds": 15.0},
        )
        await processor.setup(config)

        in_ch: Channel = Channel("signal_gates", capacity=500)
        out_ch: Channel = Channel("llm_decisions", capacity=500)

        for msg in msgs:
            await in_ch.send(msg)
        await in_ch.close()

        await processor.process({"signal_gates": in_ch}, {"llm_decisions": out_ch})
        await processor.teardown()

    results: list[Message] = []
    while True:
        try:
            m = out_ch._queue.get_nowait()
            if m is None:
                break
            results.append(m)
        except Exception:
            break

    assert len(results) == 1, f"Expected 1 result (FLAT on timeout), got {len(results)}"
    payload: LLMDecisionPayload = results[0].payload
    assert payload.direction == "FLAT", f"Expected FLAT on timeout, got {payload.direction}"
    assert "timeout" in payload.trigger.lower() or "timeout" in payload.logic.lower(), (
        f"Expected timeout-related trigger/logic, got trigger={payload.trigger!r}, logic={payload.logic!r}"
    )


@pytest.mark.asyncio
async def test_llm_entry_flat_response_emitted():
    """When the LLM returns FLAT, LLMDecisionPayload.direction must be 'FLAT'."""
    mock_port = MagicMock()
    mock_port.is_ready.return_value = True

    msgs = [_make_gate_msg(passed=True)]

    with patch(
        "app.pipeline.processors.llm_entry.LLMEntryProcessor._build_prompt_data",
        return_value={},
    ), patch(
        "app.pipeline.processors.llm_entry.build_entry_prompt",
        return_value="mocked prompt",
    ), patch(
        "app.pipeline.processors.llm_entry.parse_entry_response",
        return_value={"direction": "FLAT", "logic": "no setup", "trigger": "flat", "probability": 0.0},
    ):
        processor = LLMEntryProcessor()
        config = ProcessorConfig(
            name="test_flat",
            processor_class="app.pipeline.processors.llm_entry.LLMEntryProcessor",
            inbox={"signal_gates": "signal_gates"},
            outbox={"llm_decisions": "llm_decisions"},
            settings={"llm_port": mock_port, "timeout_seconds": 15.0},
        )
        await processor.setup(config)

        in_ch: Channel = Channel("signal_gates", capacity=500)
        out_ch: Channel = Channel("llm_decisions", capacity=500)

        for msg in msgs:
            await in_ch.send(msg)
        await in_ch.close()

        await processor.process({"signal_gates": in_ch}, {"llm_decisions": out_ch})
        await processor.teardown()

    results: list[Message] = []
    while True:
        try:
            m = out_ch._queue.get_nowait()
            if m is None:
                break
            results.append(m)
        except Exception:
            break

    assert len(results) == 1
    payload: LLMDecisionPayload = results[0].payload
    assert payload.direction == "FLAT", f"Expected FLAT, got {payload.direction}"


@pytest.mark.asyncio
async def test_llm_entry_long_response_emitted():
    """When the LLM returns LONG, LLMDecisionPayload.direction must be 'LONG'."""
    mock_port = MagicMock()
    mock_port.is_ready.return_value = True

    msgs = [_make_gate_msg(passed=True)]

    with patch(
        "app.pipeline.processors.llm_entry.LLMEntryProcessor._build_prompt_data",
        return_value={},
    ), patch(
        "app.pipeline.processors.llm_entry.build_entry_prompt",
        return_value="mocked prompt",
    ), patch(
        "app.pipeline.processors.llm_entry.parse_entry_response",
        return_value={"direction": "LONG", "logic": "strong buy", "trigger": "vp_reversal", "probability": 0.85},
    ):
        processor = LLMEntryProcessor()
        config = ProcessorConfig(
            name="test_long",
            processor_class="app.pipeline.processors.llm_entry.LLMEntryProcessor",
            inbox={"signal_gates": "signal_gates"},
            outbox={"llm_decisions": "llm_decisions"},
            settings={"llm_port": mock_port, "timeout_seconds": 15.0},
        )
        await processor.setup(config)

        in_ch: Channel = Channel("signal_gates", capacity=500)
        out_ch: Channel = Channel("llm_decisions", capacity=500)

        for msg in msgs:
            await in_ch.send(msg)
        await in_ch.close()

        await processor.process({"signal_gates": in_ch}, {"llm_decisions": out_ch})
        await processor.teardown()

    results: list[Message] = []
    while True:
        try:
            m = out_ch._queue.get_nowait()
            if m is None:
                break
            results.append(m)
        except Exception:
            break

    assert len(results) == 1
    payload: LLMDecisionPayload = results[0].payload
    assert payload.direction == "LONG"


# ===========================================================================
# OverseerProcessor tests
# ===========================================================================


@pytest.mark.asyncio
async def test_overseer_skips_flat_decision():
    """FLAT direction must emit HOLD without calling the overseer handler."""
    mock_handler = MagicMock()
    mock_handler.execute = MagicMock(return_value=None)

    msgs = [_make_llm_decision_msg(direction="FLAT")]
    results = await _run_overseer(msgs, overseer_handler=mock_handler)

    assert len(results) == 1, f"Expected 1 result, got {len(results)}"
    payload: OverseerDecisionPayload = results[0].payload
    assert isinstance(payload, OverseerDecisionPayload)
    assert payload.action == "HOLD"

    # execute must NOT be called for FLAT decisions
    mock_handler.execute.assert_not_called()


@pytest.mark.asyncio
async def test_overseer_processes_long_decision():
    """LONG direction must invoke overseer handler and emit the returned action."""
    from types import SimpleNamespace

    mock_handler = MagicMock()
    mock_handler.execute = MagicMock(
        return_value=SimpleNamespace(
            action="HOLD",
            reason="Position holding steady",
            position_id="pos_001",
        )
    )

    msgs = [_make_llm_decision_msg(direction="LONG")]
    results = await _run_overseer(msgs, overseer_handler=mock_handler, check_interval_seconds=0.0)

    assert len(results) == 1, f"Expected 1 result, got {len(results)}"
    payload: OverseerDecisionPayload = results[0].payload
    assert payload.action == "HOLD"
    assert results[0].symbol == _SYMBOL

    # execute must be called once
    mock_handler.execute.assert_called_once()
    call_args = mock_handler.execute.call_args
    assert "LONG" in call_args[0] or "LONG" in str(call_args)


@pytest.mark.asyncio
async def test_overseer_processes_short_decision():
    """SHORT direction must invoke overseer handler and emit the returned action."""
    from types import SimpleNamespace

    mock_handler = MagicMock()
    mock_handler.execute = MagicMock(
        return_value=SimpleNamespace(
            action="TIGHTEN_SL",
            reason="Short near resistance",
            position_id="pos_002",
        )
    )

    msgs = [_make_llm_decision_msg(direction="SHORT")]
    results = await _run_overseer(msgs, overseer_handler=mock_handler, check_interval_seconds=0.0)

    assert len(results) == 1
    payload: OverseerDecisionPayload = results[0].payload
    assert payload.action == "TIGHTEN_SL"
    assert payload.position_id == "pos_002"


@pytest.mark.asyncio
async def test_overseer_cooldown_suppresses_call():
    """A second message within the cooldown window must emit HOLD without calling handler."""
    from types import SimpleNamespace

    mock_handler = MagicMock()
    mock_handler.execute = MagicMock(
        return_value=SimpleNamespace(action="HOLD", reason="ok", position_id="")
    )

    # First message: processed normally
    # Second message: within cooldown → suppressed
    msgs = [
        _make_llm_decision_msg(direction="LONG"),
        _make_llm_decision_msg(direction="LONG"),
    ]

    # Use a 10-second cooldown — both messages arrive almost simultaneously
    results = await _run_overseer(msgs, overseer_handler=mock_handler, check_interval_seconds=10.0)

    assert len(results) == 2, f"Expected 2 results, got {len(results)}"

    # First must have triggered handler; second must have been suppressed
    assert mock_handler.execute.call_count == 1, (
        f"Expected execute called once (cooldown should suppress 2nd), "
        f"called {mock_handler.execute.call_count} times"
    )

    # Both messages still produce output — the second is a HOLD
    assert results[1].payload.action == "HOLD"
    assert "cooldown" in results[1].payload.reason.lower()


@pytest.mark.asyncio
async def test_overseer_no_handler_emits_hold():
    """With no overseer_handler configured, LONG/SHORT decisions must emit HOLD."""
    msgs = [_make_llm_decision_msg(direction="LONG")]
    results = await _run_overseer(msgs, overseer_handler=None)

    assert len(results) == 1
    payload: OverseerDecisionPayload = results[0].payload
    assert payload.action == "HOLD"
