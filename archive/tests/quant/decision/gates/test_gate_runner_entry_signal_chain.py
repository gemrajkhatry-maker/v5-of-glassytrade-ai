"""Synthetic OHLC + AMTResult through run_gate_pipeline and build_entry_signal.

Optional hardening from Fabio audit plan: assert pass/fail mechanics (not PnL).
Uses the same loose gate thresholds as SessionEventRouter.execute_entry_path.
"""

from __future__ import annotations

from quant.decision.gates.gate_runner import run_gate_pipeline
from quant.decision.gates.signal_builder import build_entry_signal
from quant.contracts.enums import SetupType
from quant.contracts.value_objects import AMTResult, OHLC


def _session_candles() -> list[OHLC]:
    times = [
        "2025-01-15T09:15:00+05:30",
        "2025-01-15T09:20:00+05:30",
        "2025-01-15T09:25:00+05:30",
        "2025-01-15T09:30:00+05:30",
    ]
    return [
        OHLC.create(t, 100.0, 101.0, 99.0, 100.0, 10_000.0 + i * 100)
        for i, t in enumerate(times)
    ]


def _amt_imbalance() -> AMTResult:
    return AMTResult(
        market_state="IMBALANCED",
        poc=100.0,
        value_area_high=105.0,
        value_area_low=95.0,
        setup="imbalance_continuation",
    )


def test_run_gate_pipeline_blocks_on_warmup_insufficient_candles():
    data = _session_candles()[:2]
    tick = data[-1]
    amt = _amt_imbalance()
    passed, reason, detail, _soft_gates_passed, _soft_gates_total = run_gate_pipeline(
        data=data,
        amt_result=amt,
        tick=tick,
        market_state=amt.market_state,
        drive_number=0,
        drive_entry_valid=False,
        aggression_score=3.0,
        tick_age_seconds=1.0,
        symbol="SYNTH_NIFTY_OPT",
        max_distance_to_level_ticks=50.0,
        probing_aggression_threshold=0.0,
        min_aggression_score=0.0,
        max_cushion_ticks=500.0,
        min_rr_ratio=0.1,
        tick_size=0.05,
    )
    assert passed is False
    assert "Warm-up" in detail or reason == "BLOCKED"


def test_run_gate_pipeline_passes_then_build_entry_signal_returns_signal():
    data = _session_candles()
    tick = OHLC.create("2025-01-15T09:35:00+05:30", 96.0, 97.0, 95.5, 96.0, 12_000.0)
    data = data + [tick]
    amt = _amt_imbalance()

    passed, reason, detail, _soft_gates_passed, _soft_gates_total = run_gate_pipeline(
        data=data,
        amt_result=amt,
        tick=tick,
        market_state=amt.market_state,
        drive_number=0,
        drive_entry_valid=False,
        aggression_score=3.0,
        tick_age_seconds=1.0,
        symbol="SYNTH_NIFTY_OPT",
        max_distance_to_level_ticks=50.0,
        probing_aggression_threshold=0.0,
        min_aggression_score=0.0,
        max_cushion_ticks=500.0,
        min_rr_ratio=0.1,
        tick_size=0.05,
    )
    assert passed is True, f"expected pass got reason={reason} detail={detail}"

    ai_stub = {
        "rationale": "Synthetic test — confluence aligned for integration check.",
        "market_state": "Trending",
        "raw_output": "SYNTH_OK",
    }
    sig = build_entry_signal(
        direction="LONG",
        tick=tick,
        amt_result=amt,
        ai_result=ai_stub,
        setup_type=SetupType.TREND_MODEL,
        data=data,
        tick_size=0.05,
    )
    assert sig is not None
    assert sig.stop_loss != sig.take_profit
    assert "grade_score" in (sig.metadata or {})
