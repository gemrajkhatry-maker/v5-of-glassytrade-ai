"""Certification battery over recorded journals.

S13: 2-engine payload-exact replay per journal (hard fail).
S11: StopMoved coverage stats (informational until Task 3 ages into data).
S9: sizing sanity — actual size <= equity*pct/risk-distance per trade.

Usage: PYTHONPATH=backend:. python -m tests.quant.certification.run_battery \
           [--journals-dir backend/journals] [--limit 5]

# ponytail: S2 market-state accuracy waits for a labeled ground-truth corpus;
# S12 OMS matrix lives in brokers/tests. This runner certifies what journals
# can actually prove today.
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
from datetime import datetime

from tests.quant.certification.journal_replay import load_ticks, replay_twice
from tests.quant.certification.trace_compare import first_divergence


def s13_determinism(paths: list[str]) -> tuple[list[tuple[str, bool, str]], list[str]]:
    """Return (determinism_rows, skipped_hygiene).

    Journals with fewer than 2 BarClosed rows are harness artifacts / empty
    captures — not determinism findings. They are reported separately so the
    PASS/FAIL verdict reflects genuine replay divergence only.
    """
    out = []
    skipped = []
    for p in paths:
        try:
            ticks, iv = load_ticks(p)
        except ValueError as exc:  # fewer than 2 BarClosed rows -> corpus hygiene
            skipped.append((os.path.basename(p), str(exc)))
            continue
        try:
            t1, t2 = replay_twice(ticks, "CERT", iv)
            div = first_divergence(t1, t2)
            out.append((os.path.basename(p), div is None, div or f"{len(t1)} events exact"))
        except Exception as exc:  # noqa: BLE001 - battery reports, not crashes
            out.append((os.path.basename(p), False, f"harness error: {exc}"))
    return out, skipped


def s11_stop_moves(trace) -> dict:
    moves = [e for e in trace if type(e).__name__ == "StopMoved"]
    return {
        "count": len(moves),
        "reasons": sorted({e.reason for e in moves}),
        "unexplained": sum(1 for e in moves if not e.reason),
    }


def s9_sizing_sanity(trace) -> dict:
    """For every PositionOpened, find the last RiskUpdated before it and check
    quantity <= equity * pct / risk_distance (+lot slack)."""
    checked = violations = 0
    last_equity, last_pct = 0.0, 0.005
    for e in trace:
        name = type(e).__name__
        if name == "RiskUpdated":
            last_equity = float(getattr(e.risk, "equity", 0.0) or 0.0)
            last_pct = float(getattr(e.risk, "risk_per_trade_pct", 0.005) or 0.005)
        elif name == "PositionOpened":
            sig = e.position.order.signal
            risk_dist = abs(float(sig.entry) - float(sig.sl))
            qty = abs(float(e.position.size))
            if risk_dist <= 0 or qty <= 0:
                continue
            checked += 1
            ceiling = last_equity * last_pct / risk_dist * 1.001 + 1.0  # +1 lot snap slack
            if qty > ceiling:
                violations += 1
    return {"checked": checked, "violations": violations}


def write_report(results_dir: str, rows, stats, skipped) -> str:
    os.makedirs(results_dir, exist_ok=True)
    path = os.path.join(
        results_dir, f"certification-results-{datetime.now():%Y%m%d}.md")
    lines = ["# Certification Results", "",
             f"_Generated {datetime.now():%Y-%m-%d %H:%M} by run_battery_", "",
             "## S13 Replay Determinism", "",
             "| Journal | Deterministic | Detail |", "|---|---|---|"]
    lines += [f"| {n} | {'PASS' if ok else 'FAIL'} | {d} |" for n, ok, d in rows]
    if skipped:
        lines.append("")
        lines.append("## Corpus Hygiene (skipped — fewer than 2 BarClosed rows)")
        lines += [f"- {n}: {d}" for n, d in skipped]
    lines += ["", "## S11 Stop-Move Audit", "",
              f"- moves: {stats['s11']['count']}, unexplained: "
              f"{stats['s11']['unexplained']}, reasons: {stats['s11']['reasons']}"]
    lines += ["", "## S9 Sizing Sanity", "",
              f"- trades checked: {stats['s9']['checked']}, "
              f"over-sized: {stats['s9']['violations']}"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--journals-dir", default="backend/journals")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--results-dir", default="docs/reviews")
    args = ap.parse_args(argv)
    paths = sorted(glob.glob(os.path.join(args.journals_dir, "*.jsonl")))
    if not paths:
        print("no journals found")
        return 2
    rows, skipped = s13_determinism(paths[-args.limit:])
    stats = {}
    if rows:
        ticks, iv = load_ticks(os.path.join(args.journals_dir, rows[0][0]))
        t1, _ = replay_twice(ticks, "CERT", iv)
        stats["s11"] = s11_stop_moves(t1)
        stats["s9"] = s9_sizing_sanity(t1)
    path = write_report(args.results_dir, rows, stats, skipped)
    ok = all(ok for _, ok, _ in rows)
    print(f"{'PASS' if ok else 'FAIL'} — report: {path}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
