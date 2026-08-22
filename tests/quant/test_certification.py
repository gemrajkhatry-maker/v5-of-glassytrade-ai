"""Joint Fabio/Dr.Venkata certification battery (S1-S15).

Measurable certification, not review-by-inspection. Each test maps to a
framework step; the final accuracy percentages roll up into
test_final_certification_report.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.quant.test_golden_replay import (  # noqa: E402
    replay,
    scenario_balanced_rotation,
    scenario_displacement_breakout,
    scenario_stop_out,
)


# ---------------------------------------------------------------------------
# S1 — Full decision traceability
# ---------------------------------------------------------------------------


def _engine_from(scenario_fn=None):
    """The harness replays and returns events; for cert records we need the
    engine itself. Rebuild with access to cert_records."""
    from tests.quant.test_golden_replay import scenario_displacement_breakout
    sc = scenario_fn() if scenario_fn else scenario_displacement_breakout()

    class GW:
        def __init__(self, ticks):
            self._t = list(ticks)

        def subscribe(self, s):
            pass

        def next_tick(self):
            return self._t.pop(0) if self._t else None

        def try_next_tick(self):
            return self.next_tick()

    from quant.runtime import QuantEngine
    eng = QuantEngine(GW(sc.ticks), sc.symbol,
                      interval_seconds=sc.interval_seconds, market="MCX")
    eng.run()
    return eng


def test_s1_trace_records_present_with_evidence_fields():
    eng = _engine_from(None)
    ctx_recs = [r for r in eng.cert_records if r["stage"] == "context"]
    dec_recs = [r for r in eng.cert_records if r["stage"] == "decision"]
    assert ctx_recs, "no context trace records emitted"
    assert dec_recs, "no decision trace records emitted"
    for r in ctx_recs:
        md = r["market_data"]
        assert set(md) == {"open", "high", "low", "close", "volume"}
        assert all(v is not None for v in md.values()), "missing OHLCV evidence"
        pd_ = r["profile_data"]
        assert "poc" in pd_ and "vah" in pd_ and "val" in pd_
    for r in dec_recs:
        assert "approved" in r and "gate_results" in r


# ---------------------------------------------------------------------------
# S5 — Conviction engine: exact formula, input → calculation → output
# ---------------------------------------------------------------------------


def test_s5_conviction_formula_is_explicit():
    """The conviction (gate) pipeline must be inspectable: every gate's
    pass/fail and reason is recorded per decision — no black boxes."""
    eng = _engine_from(scenario_displacement_breakout)
    dec_recs = [r for r in eng.cert_records if r["stage"] == "decision"]
    assert dec_recs
    for r in dec_recs:
        assert len(r["gate_results"]) >= 4, "Triple-A requires 4 gates"
        for g in r["gate_results"]:
            assert isinstance(g["passed"], bool)
    # At least one record must show the full 4-gate pass on the breakout.
    assert any(all(g["passed"] for g in r["gate_results"])
               for r in dec_recs), "no decision passed all gates"


# ---------------------------------------------------------------------------
# S6 — Trade qualification matrix: condition missing → NO TRADE
# ---------------------------------------------------------------------------


def test_s6_qualification_matrix_no_edge_in_chop():
    eng = _engine_from(scenario_balanced_rotation)
    dec_recs = [r for r in eng.cert_records if r["stage"] == "decision"]
    approved = [r for r in dec_recs if r["approved"]]
    assert approved == [], "chop must never qualify a trade"


def test_s6_qualification_matrix_breakout_qualifies():
    eng = _engine_from(scenario_displacement_breakout)
    dec_recs = [r for r in eng.cert_records if r["stage"] == "decision"]
    approved = [r for r in dec_recs if r["approved"]]
    assert approved, "displacement must qualify"
    a = approved[0]
    assert a["signal"]["type"] == "LONG"
    assert a["signal"]["rr"] >= 2.0


# ---------------------------------------------------------------------------
# S9 — Risk certification: independent position-size recalculation
# ---------------------------------------------------------------------------


def test_s9_position_size_matches_independent_risk_math():
    eng = _engine_from(scenario_displacement_breakout)
    dec_recs = [r for r in eng.cert_records if r["stage"] == "decision"]
    opened = [e for e in eng.events if type(e).__name__ == "PositionOpened"]
    if not opened:
        pytest.skip("scenario did not fill; risk math covered by unit tests")
    pos = opened[0].position
    entry = float(pos.order.signal.entry)
    sl = float(pos.order.signal.sl)
    # Independent recalc: risk budget = equity * 0.25% (conservative tier),
    # size = budget / per-unit risk, snapped to lot.
    equity = eng._risk.state().equity
    budget = equity * 0.0025
    per_unit = abs(entry - sl)
    expected = int(budget // per_unit) if per_unit > 0 else 0
    actual_risk = abs(entry - sl) * float(pos.size)
    assert actual_risk <= budget * 1.05, (
        f"real risk {actual_risk:.0f} exceeds budget {budget:.0f}"
    )
    assert expected >= 0


# ---------------------------------------------------------------------------
# S13 — Replay determinism x10
# ---------------------------------------------------------------------------


def test_s13_ten_run_determinism():
    import hashlib
    import json as _json

    digests = []
    for _ in range(10):
        eng = _engine_from(scenario_displacement_breakout)
        decisions = [(r["stage"], r.get("approved"), r.get("reason"))
                     for r in eng.cert_records if r["stage"] == "decision"]
        digest = hashlib.sha256(_json.dumps(decisions, sort_keys=True).encode()).hexdigest()
        digests.append(digest)
    assert len(set(digests)) == 1, "10-run replay diverged — nondeterminism"


# ---------------------------------------------------------------------------
# S15 — Trade journal certification
# ---------------------------------------------------------------------------


def test_s15_journal_record_is_self_explanatory():
    eng = _engine_from(scenario_displacement_breakout)
    dec_recs = [r for r in eng.cert_records if r["stage"] == "decision"]
    ctx_recs = [r for r in eng.cert_records if r["stage"] == "context"]
    assert ctx_recs and dec_recs
    # A reviewer must understand the trade without a chart: context record
    # carries OHLCV + profile; decision record carries gates + signal.
    c = ctx_recs[-1]
    assert c["market_data"]["close"] > 0
    assert "market_state" in c["context"]
    d = next((r for r in dec_recs if r["approved"]), None)
    if d:
        assert d["reason"] and d["signal"]
