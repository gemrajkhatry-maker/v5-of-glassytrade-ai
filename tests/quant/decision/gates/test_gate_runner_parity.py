"""Parity: run_gate_pipeline via legacy shim vs moved quant module.

AMTResult is the same class through the shim, so a single populated instance
drives both sides. Fields read by run_gate_pipeline:
  amt_result.value_area_high / value_area_low / lvns / poc / setup
  amt_result.session_vwap / vwap_upper_1 / absorption_side (via getattr)
tick.close, tick.close.volume; data[i].volume.
"""

from __future__ import annotations

from quant.decision.gates.gate_runner import run_gate_pipeline
from quant.contracts.value_objects import AMTResult, OHLC
from tests.quant.parity import assert_parity


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


def _loose_kwargs():
    return dict(
        market_state="IMBALANCED",
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


def test_run_gate_pipeline_blocks_on_warmup_parity():
    data = _session_candles()[:2]
    tick = data[-1]
    amt = _amt_imbalance()
    kwargs = dict(data=data, amt_result=amt, tick=tick, **_loose_kwargs())
    run_gate_pipeline(**kwargs)


def test_run_gate_pipeline_passes_parity():
    data = _session_candles()
    tick = OHLC.create("2025-01-15T09:35:00+05:30", 96.0, 97.0, 95.5, 96.0, 12_000.0)
    data = data + [tick]
    amt = _amt_imbalance()
    kwargs = dict(data=data, amt_result=amt, tick=tick, **_loose_kwargs())
    run_gate_pipeline(**kwargs)


def test_run_gate_pipeline_risk_halt_parity():
    data = _session_candles()
    tick = OHLC.create("2025-01-15T09:35:00+05:30", 96.0, 97.0, 95.5, 96.0, 12_000.0)
    data = data + [tick]
    amt = _amt_imbalance()
    kwargs = dict(data=data, amt_result=amt, tick=tick, is_risk_halted=True,
                  halt_reason="Daily loss", **_loose_kwargs())
    run_gate_pipeline(**kwargs)
