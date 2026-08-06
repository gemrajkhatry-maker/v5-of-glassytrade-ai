"""Split-brain unification comparison: ``quant.coordinator.AuctionCoordinator``
(quant.core, real-time ``auction``-WS producer) vs ``quant.amt.analyzer.AMTAnalyzer``
(full AMT decision engine).

Feeds the EXACT 60-bar synthetic session from ``tests/quant/test_golden_file.py``
through BOTH engines on a FRESH instance per side (both are stateful), then measures
the per-bar deltas on the overlapping outputs:

  * volume-profile POC / VAH / VAL
  * VWAP value
  * CVD / delta
  * IB high / low

This is a MEASUREMENT test, not a parity test: the two engines are different
products (a byte-compatible realtime WS producer vs a full decision engine) and
are EXPECTED to diverge.  The tests pin the divergence budget recorded in
``docs/AMT_UNIFICATION.md`` so any future drift past the budget fails loudly.

A key measurement caveat is exercised here and documented in that file: the
``_session_bars()`` shape labels bars ``t0..t59`` (non-ISO).  ``AMTAnalyzer``
detects a new session when ``current.time[:10] != last_time[:10]`` and its IB
engine requires ISO ``datetime.fromisoformat`` timestamps — so the ``t{i}``
labels reset the AMT session-VWAP/IB accumulators on EVERY bar.  To separate
that harness artifact from genuine engine divergence we also run an
ISO-timestamped variant (identical OHLCV) and budget the genuine VWAP/IB deltas
against it.  ``quant.core`` uses a bar-count IB model and a close-weighted VWAP;
``quant.amt`` uses a wall-clock (30-min) IB model and a typical-price-weighted
VWAP.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from quant.amt.analyzer import AMTAnalyzer
from quant.bars import Bar
from quant.coordinator import AuctionCoordinator
from quant.contracts.value_objects import OHLC
from tests.quant.test_golden_file import _session_bars

# Divergence budgets (relative %, against the quant.core reference value).
# Recorded in docs/AMT_UNIFICATION.md.
POC_BUDGET_PCT = 5.0
VAH_BUDGET_PCT = 5.0
VAL_BUDGET_PCT = 5.0
VWAP_BUDGET_PCT = 1.0  # ISO-timestamped run (genuine divergence; close- vs typical-price VWAP)
IB_BUDGET_PCT = 0.1  # ISO-timestamped run

_BARS_START = 4  # AMTAnalyzer.analyze() returns empty until it has >= 5 bars


def _bar_to_ohlc(bar: Bar) -> OHLC:
    """Bar -> OHLC with plain floats.

    ``AMTAnalyzer`` (e.g. AcceptanceRejectionEngine) compares ``candle.volume``
    against floats, so ``OHLC.create``'s Decimal coercion raises TypeError.
    """
    return OHLC(
        time=bar.time,
        open=float(bar.open),
        high=float(bar.high),
        low=float(bar.low),
        close=float(bar.close),
        volume=float(bar.volume),
        taker_buy_volume=float(bar.buy_volume),
        delta=float(bar.delta),
    )


def _with_iso_times(bars: list[Bar]) -> list[Bar]:
    """Same session, realistic ISO timestamps (5-min bars from 09:15)."""
    t0 = datetime(2026, 1, 5, 9, 15, 0)
    out = []
    for i, b in enumerate(bars):
        iso = (t0 + timedelta(minutes=5 * i)).isoformat()
        out.append(
            Bar(time=iso, open=b.open, high=b.high, low=b.low, close=b.close,
                volume=b.volume, buy_volume=b.buy_volume,
                sell_volume=b.sell_volume, delta=b.delta)
        )
    return out


def _with_delta_enriched(bars: list[Bar]) -> list[Bar]:
    """Same session, delta = buy_volume - sell_volume to exercise the CVD paths."""
    out = []
    for b in bars:
        delta = (b.buy_volume - b.sell_volume) if (b.buy_volume or b.sell_volume) else 0.0
        out.append(
            Bar(time=b.time, open=b.open, high=b.high, low=b.low, close=b.close,
                volume=b.volume, buy_volume=b.buy_volume,
                sell_volume=b.sell_volume, delta=delta)
        )
    return out


def _silence_amt_logging() -> None:
    for name in ("quant.amt", "quant.amt.analyzer", "quant.amt.session.ib_engine"):
        logging.getLogger(name).setLevel(logging.ERROR)


def _run_core(bars: list[Bar]) -> list[dict]:
    """Feed one bar at a time through a FRESH AuctionCoordinator."""
    core = AuctionCoordinator()
    rows = []
    for b in bars:
        st = core.on_bar_close(b)
        vp = st.volume_profile
        rows.append(
            {
                "time": b.time,
                "poc": vp.poc,
                "vah": vp.vah,
                "val": vp.val,
                "vwap": st.vwap.value,
                "cvd": st.order_flow.cvd,
                "delta": st.order_flow.delta,
                "cvd_slope": st.order_flow.cvd_slope,
                "ib_high": st.location.ib_high,
                "ib_low": st.location.ib_low,
                "ib_complete": st.location.ib_complete,
            }
        )
    return rows


def _run_amt(bars: list[Bar]) -> tuple[list[dict], AMTAnalyzer]:
    """Feed the session through a FRESH AMTAnalyzer, one analyze() per bar."""
    amt = AMTAnalyzer()
    rows = []
    for i, b in enumerate(bars):
        r = amt.analyze([_bar_to_ohlc(x) for x in bars[: i + 1]], symbol="TEST")
        rows.append(
            {
                "time": b.time,
                "poc": float(r.poc),
                "vah": float(r.value_area_high),
                "val": float(r.value_area_low),
                "vwap": float(r.session_vwap),
                "cvd": float(amt._cvd_tracker.state().value),
                "delta": float(r.delta_normalized_option),
                "cvd_slope": float(r.cvd_slope),
                "ib_high": float(r.ib_high),
                "ib_low": float(r.ib_low),
                "ib_complete": bool(r.ib_complete),
            }
        )
    return rows, amt


def _measure(bars: list[Bar]) -> tuple[list[dict], list[dict]]:
    """Run both engines on fresh instances; return (core_rows, amt_rows)."""
    _silence_amt_logging()
    return _run_core(bars), _run_amt(bars)[0]


def _delta_stats(core_rows: list[dict], amt_rows: list[dict], field: str):
    """max abs, max %, mean % of |core - amt| over bars 4..end (core as ref)."""
    pairs = [
        (c[field], a[field])
        for c, a in zip(core_rows, amt_rows)
        if c["time"] == a["time"]
    ][_BARS_START:]
    abs_deltas, pct_deltas = [], []
    for c, a in pairs:
        d = abs(c - a)
        abs_deltas.append(d)
        if c:
            pct_deltas.append(d / abs(c) * 100)
    return (
        max(abs_deltas) if abs_deltas else 0.0,
        max(pct_deltas) if pct_deltas else 0.0,
        sum(pct_deltas) / len(pct_deltas) if pct_deltas else 0.0,
    )


def _leg_clamp_bars(amt_rows: list[dict], bars: list[Bar], amt: AMTAnalyzer) -> set[int]:
    """Bars where AMTAnalyzer applied the Task-2.3 session-VA-vs-leg-VA clamp:
    reported VAL equals the displacement-leg VAL, i.e. session VAL was pulled down
    to the leg VAL.  These are documented, intentional AMT overrides and are
    excluded from the VAL budget assertion."""
    clamped = set()
    for i in range(_BARS_START, len(bars)):
        leg = amt.detect_displacement_leg([_bar_to_ohlc(x) for x in bars[: i + 1]])
        leg_val = float(leg.get("val", 0.0) or 0.0)
        if leg_val > 0 and abs(amt_rows[i]["val"] - leg_val) < 1e-9:
            clamped.add(i)
    return clamped


def test_both_engines_are_deterministic_on_fresh_instances():
    bars = _session_bars()
    core1, amt1 = _measure(bars)
    core2, amt2 = _measure(bars)
    assert core1 == core2
    assert amt1 == amt2


def test_overlapping_outputs_measured_per_bar():
    """Both engines consume the full fixed session; every bar >= 5 has a row on
    both sides (no dropped/wrong bars) — the harness feeds identical input."""
    bars = _session_bars()
    core_rows, amt_rows = _measure(bars)
    assert len(core_rows) == len(amt_rows) == len(bars)
    assert [r["time"] for r in core_rows] == [r["time"] for r in amt_rows]


def test_poc_and_vah_within_divergence_budget():
    bars = _session_bars()
    core_rows, amt_rows = _measure(bars)
    for field, budget in (("poc", POC_BUDGET_PCT), ("vah", VAH_BUDGET_PCT)):
        _, max_pct, _ = _delta_stats(core_rows, amt_rows, field)
        assert max_pct <= budget, f"{field} max% {max_pct:.2f} > budget {budget}"


def test_val_within_budget_except_documented_leg_clamp_bars():
    """VAL matches within budget on all bars EXCEPT the Task-2.3 leg-VA clamp bars,
    where AMT intentionally replaces session VAL with the displacement-leg VAL."""
    bars = _session_bars()
    _silence_amt_logging()
    core_rows, _ = _measure(bars)
    amt_rows, amt_inst = _run_amt(bars)
    clamped = _leg_clamp_bars(amt_rows, bars, amt_inst)
    assert clamped, "expected Task-2.3 leg-VA clamp to be exercised by the session"
    for i in range(_BARS_START, len(bars)):
        c, a = core_rows[i]["val"], amt_rows[i]["val"]
        if i in clamped:
            continue
        if c:
            assert abs(c - a) / abs(c) * 100 <= VAL_BUDGET_PCT, (
                f"bar {i} VAL {c:.4f} vs {a:.4f} > budget"
            )


def test_vwap_and_ib_genuine_divergence_small_with_iso_times():
    """The apparent VWAP/IB divergence on the t{i}-labelled session is a harness
    artifact (AMT's per-bar session reset).  With realistic ISO timestamps —
    identical OHLCV — genuine divergence is tiny: VWAP differs only because
    quant.core is close-weighted while quant.amt is typical-price-weighted; IB
    high/low agree exactly (both take the first 6 5-min bars)."""
    bars = _with_iso_times(_session_bars())
    core_rows, amt_rows = _measure(bars)
    for field, budget in (
        ("vwap", VWAP_BUDGET_PCT),
        ("ib_high", IB_BUDGET_PCT),
        ("ib_low", IB_BUDGET_PCT),
    ):
        _, max_pct, _ = _delta_stats(core_rows, amt_rows, field)
        assert max_pct <= budget, f"{field} max% {max_pct:.2f} > budget {budget}"


def test_cvd_value_matches_on_delta_enriched_session():
    """The synthetic session carries no delta (Bar.delta == 0), so raw CVD is 0 on
    both sides.  With delta=buy_volume-sell_volume both engines accumulate the
    running sum of bar delta, so CVD *value* matches exactly; only the slope
    diverges (window 20 vs 40 + AMT sign-persistence filter), which is a config
    difference, not a math difference.  (quant.core exposes last-bar delta as
    ``OrderFlowState.delta``; AMT exposes no comparable per-bar delta in
    ``AMTResult`` — its ``delta_normalized_option`` is option-tick-only — so the
    raw-delta fields are not a valid cross-engine overlap.)"""
    bars = _with_delta_enriched(_with_iso_times(_session_bars()))
    core_rows, amt_rows = _measure(bars)
    for c, a in zip(core_rows[_BARS_START:], amt_rows[_BARS_START:]):
        assert abs(c["cvd"] - a["cvd"]) < 1e-6


def test_delta_summary_table_printed_for_reporting():
    """Prints the per-field delta summary consumed by docs/AMT_UNIFICATION.md."""
    asis = _session_bars()
    iso = _with_iso_times(asis)
    enriched = _with_delta_enriched(iso)
    core_asis, amt_asis = _measure(asis)
    core_iso, amt_iso = _measure(iso)
    core_enr, amt_enr = _measure(enriched)

    def line(field, c1, a1, c2, a2):
        d1, p1, m1 = _delta_stats(c1, a1, field)
        d2, p2, m2 = _delta_stats(c2, a2, field)
        return f"{field:<8} {d1:>9.4f} {p1:>9.3f}% {m1:>9.3f}%   " \
               f"{d2:>9.4f} {p2:>9.3f}% {m2:>9.3f}%"

    print("\nAMT vs quant.core split-brain delta table (bars 4-59)")
    print("field      max|d|      max%     mean%    max|d|      max%     mean%")
    for f in ("poc", "vah", "val", "vwap", "ib_high", "ib_low"):
        print(line(f, core_asis, amt_asis, core_iso, amt_iso))
    print("-- order-flow (delta-enriched ISO session; as-is carries no delta) --")
    for f in ("cvd", "cvd_slope"):
        print(line(f, core_asis, amt_asis, core_enr, amt_enr))
