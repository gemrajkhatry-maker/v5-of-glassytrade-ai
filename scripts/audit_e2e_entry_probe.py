"""Audit probe: does the E2E TimesFM entry path honour session/warmup gates?

Read-only. Builds a TimesFMTradingStrategy with a stubbed TimesFM model that
returns a strong upward trajectory, then calls should_enter() with a context
that a deterministic path would hard-reject (session closed, warmup incomplete,
opening-noise phase). Prints what actually happens.
"""
import os
import sys
from unittest.mock import Mock

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant.bars import Bar
from quant.decision.context import DecisionContext
from quant.decision.timesfm_engine import TimesFMEngine
from quant.strategies.timesfm_strategy import TimesFMTradingStrategy

import quant.decision.timesfm_engine as eng_mod


def make_forecast_engine():
    """Engine whose stubbed model returns a strongly bullish p50 path."""
    engine = TimesFMEngine(target_horizon=8)
    horizon = 8
    # p50 rises steadily; p10/p90 bracket it.
    p50 = np.linspace(100.0, 104.0, horizon, dtype=np.float32)
    quantiles = np.zeros((horizon, 9), dtype=np.float32)
    quantiles[:, 0] = p50 - 1.0   # p10
    quantiles[:, 4] = p50         # p50
    quantiles[:, 8] = p50 + 1.0   # p90
    fake = Mock()
    fake.predict.return_value = Mock(quantiles=quantiles)
    return engine, fake


def build_ctx(**overrides):
    bar = Bar("2026-09-10T09:20:00+05:30", 100.0, 101.0, 99.0, 100.5, 1000, 100)
    base = dict(
        symbol="NIFTY", bar=bar, bar_index=3,
        session_open=True, warmup_complete=True, session_phase="PRIMARY",
        poc=100.0, vah=101.0, val=99.0, cvd_slope=2.0,
        absorption_side="SELL_ABSORBED", allow_trend=True, allow_reversion=True,
    )
    base.update(overrides)
    return DecisionContext(**base)


def run_case(label, engine, fake, ctx):
    original = eng_mod.get_timesfm_model
    eng_mod.get_timesfm_model = lambda *a, **k: fake
    try:
        strategy = TimesFMTradingStrategy(target_horizon=8, engine=engine)
        decision = strategy.should_enter(ctx)
    finally:
        eng_mod.get_timesfm_model = original
    verdict = "APPROVED -> WOULD SUBMIT ORDER" if decision.approved else "blocked"
    print(f"  {label:<48} {verdict:<32} reason={decision.reason}")
    return decision


def main():
    print("\n=== E2E entry gate probe (should_enter, model returns bullish path) ===\n")

    cases = [
        ("baseline: session open, warm, PRIMARY", {}),
        ("session_open=False", dict(session_open=False)),
        ("warmup_complete=False (bar 3 of 15)", dict(warmup_complete=False)),
        ("session_phase=OPENING", dict(session_phase="OPENING")),
        ("session_phase=PRE_OPEN", dict(session_phase="PRE_OPEN")),
        ("session_phase=CLOSE", dict(session_phase="CLOSE")),
        ("session_phase=POST_MARKET", dict(session_phase="POST_MARKET")),
        ("all blocked at once", dict(
            session_open=False, warmup_complete=False,
            session_phase="OPENING",
        )),
        ("allow_trend=False", dict(allow_trend=False)),
        ("allow_reversion=False, VA_FADE geometry", dict(
            allow_reversion=False, cvd_slope=-2.0,
            absorption_side="BUY_ABSORBED",
        )),
    ]

    for label, overrides in cases:
        engine, fake = make_forecast_engine()
        ctx = build_ctx(**overrides)
        run_case(label, engine, fake, ctx)

    print("\n=== For comparison: the deterministic path (AmtScalpingStrategy) ===\n")
    from quant.strategies.amt_scalping import AmtScalpingStrategy
    for label, overrides in [
        ("session_open=False", dict(session_open=False)),
        ("warmup_complete=False", dict(warmup_complete=False)),
        ("baseline: session open, warm, PRIMARY", {}),
    ]:
        ctx = build_ctx(**overrides)
        decision = AmtScalpingStrategy().should_enter(ctx)
        verdict = "APPROVED -> WOULD SUBMIT ORDER" if decision.approved else "blocked"
        print(f"  {label:<48} {verdict:<32} reason={decision.reason}")

    print()


if __name__ == "__main__":
    main()
