"""Tests for TimesFMClient, TimesFMSnapshotBuffer, and TimesFMAdvisor."""

import time
from unittest.mock import MagicMock, patch

import pytest

from quant.bars import Bar
from quant.decision.context import DecisionContext
from quant.decision.timesfm_advisor import TimesFMAdvisor, build_decision_payload
from quant.decision.timesfm_client import (
    TimesFMClient,
    TimesFMSnapshotBuffer,
    context_to_snapshot,
)
from quant.events import AgentDecisionProduced


def test_context_to_snapshot_basic():
    bar = Bar("2026-09-08T15:30:00", 6450.0, 6465.0, 6445.0, 6460.0, 1500, 200, 500)
    ctx = DecisionContext(
        symbol="CRUDEOIL",
        bar=bar,
        poc=6455.0,
        vah=6470.0,
        val=6440.0,
        cvd_slope=0.75,
        session_phase="MIDDAY",
    )
    snap = context_to_snapshot(ctx)

    assert snap["symbol"] == "CRUDEOIL"
    assert snap["close"] == 6460.0
    assert snap["open"] == 6450.0
    assert snap["poc"] == 6455.0
    assert snap["vah"] == 6470.0
    assert snap["val"] == 6440.0
    assert snap["cvd_slope"] == 0.75
    assert snap["session_phase"] == "MIDDAY"


def test_snapshot_buffer_padding():
    buf = TimesFMSnapshotBuffer(target_size=32)
    snap = {"symbol": "GOLD", "close": 72000.0}

    # First snapshot: must be padded to 32
    window = buf.add_snapshot(snap)
    assert len(window) == 32
    assert all(s["symbol"] == "GOLD" for s in window)

    # Add 40 snapshots: maxlen remains 32
    for i in range(40):
        window = buf.add_snapshot({"symbol": "GOLD", "close": 72000.0 + i})
    assert len(window) == 32
    assert window[-1]["close"] == 72000.0 + 39


def test_build_decision_payload():
    ctx = DecisionContext(symbol="CRUDEOIL")
    service_res = {
        "direction": "LONG",
        "confidence": 0.85,
        "narrative": "Auction expanding upward beyond VAH.",
        "latency_ms": 215.4,
        "forecast_steps": ["LONG"] * 32,
        "quantile_spread": 0.35,
        "mean_forecast": 6485.0,
        "gate_results": [{"gate_no": 1, "gate_name": "SESSION", "passed": True, "message": ""}],
        "model_versions": {"timesfm": "3.0", "qwen": "3.8-27B"},
    }
    payload = build_decision_payload(ctx, service_res, {})
    assert payload["direction"] == "LONG"
    assert payload["action"] == "ENTER_LONG"
    assert payload["confidence"] == "High"
    assert payload["confidenceScore"] == 0.85
    assert payload["source"] == "TIMESFM_QWEN"
    assert payload["latencyMs"] == 215.4
    assert len(payload["forecastSteps"]) == 32
    assert payload["quantileSpread"] == 0.35
    assert payload["meanForecast"] == 6485.0
    assert len(payload["gateResults"]) == 1


def test_timesfm_advisor_offline_fallback():
    ctx = DecisionContext(symbol="COPPER")
    emitted = []

    # Point to an unreachable port to test offline fallback resilience
    advisor = TimesFMAdvisor(
        emit_fn=lambda e: emitted.append(e),
        service_url="http://127.0.0.1:59999",
        enable_llm_narrative=False,
    )
    advisor.on_context(ctx)
    time.sleep(0.3)
    advisor.shutdown()

    assert len(emitted) >= 1
    latest = emitted[0].decision
    assert latest["source"] == "AMT_LOCAL"
    assert "direction" in latest
    assert "forecastSteps" in latest
