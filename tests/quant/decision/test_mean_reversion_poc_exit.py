# tests/quant/decision/test_mean_reversion_poc_exit.py
"""A MEAN_REVERSION signal's TP must equal the POC, not an R-multiple."""
from quant.decision.signal_builder import SignalBuilder
from quant.decision.context import DecisionContext
from quant.decision.result import GateResult
from quant.decision.setup_state import SetupEvidence
from quant.bars import Bar


def test_va_fade_signal_tp_is_poc():
    bar = Bar(time=1, open=100, high=101, low=99, close=100.2, volume=1000,
              buy_volume=500, sell_volume=500, delta=0, oi=50000, vwap=100)
    ev = SetupEvidence(setup_type="VA_FADE", direction="SHORT", level=101.5,
                       rejection=True, acceptance=False, cvd_agrees=True)
    ctx = DecisionContext(symbol="NIFTY", bar=bar, agent_direction="SHORT",
                          poc=100.0, vah=101.0, val=99.0, tick_size=0.05,
                          setup_evidence=ev, cvd_slope=-0.5)
    gates = [GateResult(1, True), GateResult(2, True),
             GateResult(3, True, "va fade"), GateResult(4, True)]
    sig, _ = SignalBuilder().build_or_reason(ctx, gates, model_label="MEAN_REVERSION")
    assert sig is not None and sig.tp == 100.0
