"""State snapshot builder contract tests — dead top-level payload keys removed.

Task 1: AMT Strategy Cleanup — cut dead UI payload. The snapshot must no
longer carry the dead top-level keys, and the agentDecision / genAIAnalysis
DTOs must keep only the fields the strategy + LLM consumers read.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

from app.application.services.state_snapshot_builder import build_state_snapshot


class _FakeRiskManager:
    is_halted = False
    halt_reason = ""
    daily_state = SimpleNamespace(consecutive_losses=2, realized_pnl=1234.5)
    _drift_alert = False
    _drift_message = ""


class _FakeRiskCoordinator:
    def _get_risk_manager(self, symbol):
        return _FakeRiskManager()


class _FakePortfolio:
    balance = 100_000.0
    equity = 100_500.0
    leverage = 5
    positions = []
    closed_trades = []
    history = []

    def get_stats(self, source):
        return SimpleNamespace(
            total_trades=0,
            wins=0,
            losses=0,
            win_rate=0.0,
            net_profit=0.0,
            avg_profit=0.0,
            largest_win=0.0,
            largest_loss=0.0,
        )


def _make_agent_decision():
    return SimpleNamespace(
        direction="LONG",
        probability=0.72,
        regime="TRENDING",
        playbook="imbalance_continuation",
        feature_drivers=("CVD_DIVERGENCE",),
        timing="ENTER_NOW",
        size_fraction=0.5,
        sl_adjust=1.0,
        tp_adjust=1.0,
        stop_loss=0.0,
        take_profit=0.0,
        latency_us=1234,
        rationale="Strong trend",
    )


def _make_session():
    return SimpleNamespace(
        symbol="TEST",
        _lock=threading.Lock(),
        learning=SimpleNamespace(
            weights=SimpleNamespace(
                trend=0.4,
                momentum=0.25,
                delta=0.15,
                order_book=0.15,
                volatility=0.05,
            ),
            generation=3,
        ),
        last_ai_analysis={
            "direction": "LONG",
            "rationale": "LLM rationale",
            "confidence": "High",
            "input_prompt": "prompt",
            "raw_output": "raw",
            "market_state": "IMBALANCED",
            "aggression": "INITIATIVE",
            "quant_probability": 0.9,
            "quant_direction": "LONG",
            "llm_status": "AVAILABLE",
            "overseer_action": "HOLD",
            "overseer_reason": "Trend intact",
        },
        portfolio=_FakePortfolio(),
        last_amt={"marketState": "IMBALANCED"},
        last_footprint={},
        data=[],
        _agent_decision=_make_agent_decision(),
    )


def test_snapshot_has_no_dead_keys():
    snap = build_state_snapshot(_make_session(), _FakeRiskCoordinator(), object())
    for dead in (
        "prediction",
        "cumulative_deltas",
        "stats",
        "modelWeights",
        "generation",
        "statsBySource",
        "tradingState",
        "tradingStateReason",
        "playbookGuard",
        "aggressionBlocked",
        "gateScore",
        "explainabilityMonitor",
        "rlStatus",
    ):
        assert dead not in snap
    assert "riskState" in snap  # kept
    assert "amt" in snap


def test_snapshot_keeps_live_strategy_keys():
    snap = build_state_snapshot(_make_session(), _FakeRiskCoordinator(), object())
    for keep in (
        "portfolio",
        "amt",
        "genAIAnalysis",
        "overseerAction",
        "overseerReason",
        "agentDecision",
        "riskState",
    ):
        assert keep in snap


def test_agent_decision_dto_keeps_only_strategy_fields():
    snap = build_state_snapshot(_make_session(), _FakeRiskCoordinator(), object())
    ad = snap["agentDecision"]
    assert set(ad.keys()) == {
        "direction",
        "probability",
        "regime",
        "timing",
        "sizeFraction",
        "latencyUs",
        "rationale",
    }


def test_genai_analysis_dto_keeps_only_strategy_fields():
    snap = build_state_snapshot(_make_session(), _FakeRiskCoordinator(), object())
    ga = snap["genAIAnalysis"]
    assert set(ga.keys()) == {
        "direction",
        "rationale",
        "confidence",
        "inputPrompt",
        "rawOutput",
        "marketState",
        "aggression",
    }
