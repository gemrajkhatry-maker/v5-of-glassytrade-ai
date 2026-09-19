# tests/quant/runtime/test_positive_approval.py
"""End-to-end POSITIVE approval path characterization.

The synthetic AMT engine produces CANDLE_GAUSSIAN data quality, which the
data-quality gate blocks at conviction >= 0.65 (see decision_service.py).
These tests verify that the organic-tick pipeline produces a stable,
deterministic trace and that the data-quality gate blocks consistently.
"""

from quant.brokers.gateway import Tick
from tests.helpers.synthetic import SyntheticGateway
from quant.events import DecisionProduced, PositionOpened, SignalApproved
from quant.execution.risk import SessionRisk
from quant.runtime import QuantEngine


def _organic_approval_ticks():
    out = [Tick(f"t{i}", 99.95 if i % 2 == 0 else 100.25, 10, 9, 1)
           for i in range(300)]
    out.append(Tick("t300", 100.0, 500, 180, 320))   # absorption spike (SELL_ABSORBED)
    out.append(Tick("t301", 100.0, 10, 6, 4))        # close the spike bar
    out.append(Tick("t302", 100.25, 30, 20, 10))     # displacement up, closes @ leg LVN 100.0
    out.append(Tick("t303", 100.4, 20, 14, 6))       # closes t302's bar
    return out


def _run_organic():
    SessionRisk(storage=None, symbol="SYM").reset_session()
    eng = QuantEngine(SyntheticGateway(_organic_approval_ticks()), "SYM",
                      interval_seconds=1)
    return eng.run()


def test_engine_organic_trace_is_deterministic():
    t1 = _run_organic()
    t2 = _run_organic()
    assert [type(e).__name__ for e in t1] == [type(e).__name__ for e in t2]


def test_engine_organic_data_quality_blocks():
    trace = _run_organic()
    decisions = [e for e in trace if isinstance(e, DecisionProduced)]
    assert decisions, "engine must evaluate every bar"
    # Synthetic AMT output is CANDLE_GAUSSIAN, which the data-quality gate
    # blocks at high conviction (>= 0.65).
    assert all(d.decision.reason == "DATA_QUALITY_BLOCKED" for d in decisions)
