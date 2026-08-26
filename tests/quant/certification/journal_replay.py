"""Replay a recorded journal through TWO fresh engines; demand payload-exact
trace identity. Exit 0 = zero divergence.

Usage: PYTHONPATH=backend:. python -m tests.quant.certification.journal_replay \
           backend/journals/<file>.jsonl [--interval SEC]

# ponytail: proves ENGINE determinism over recorded bars. It does not yet
# prove live-parity (depth snapshots + tick-grade VWAP absent). See
# journal_ticks.py ceiling note.
"""
from __future__ import annotations

import argparse
import sys

from quant.execution.risk import SessionRisk
from quant.persistence import Journal
from quant.runtime import QuantEngine
from tests.helpers.synthetic import SyntheticGateway
from tests.quant.certification.journal_ticks import (
    bars_from_journal, ticks_from_bars,
)
from tests.quant.certification.trace_compare import first_divergence


def load_ticks(path: str, interval: int | None = None) -> tuple[list, int]:
    """Return (synthetic_ticks, interval_seconds) for a journal file."""
    rows = Journal(path).replay()
    inf, bars = bars_from_journal(rows)
    iv = int(interval or inf)
    return ticks_from_bars(bars, iv), iv


def replay_twice(ticks: list, symbol: str, interval: int):
    # Identical config for both engines (same symbol) — the golden-tape
    # pattern. Isolation is guaranteed without symbol suffixes: each engine
    # builds its own memory-only SessionLevelStore (path=None), and
    # SessionRisk.reset_session() clears any persisted daily-risk state.
    SessionRisk(storage=None, symbol=symbol).reset_session()
    eng1 = QuantEngine(SyntheticGateway(list(ticks)), symbol,
                       interval_seconds=interval)
    trace1 = eng1.run()
    SessionRisk(storage=None, symbol=symbol).reset_session()
    eng2 = QuantEngine(SyntheticGateway(list(ticks)), symbol,
                       interval_seconds=interval)
    trace2 = eng2.run()
    return trace1, trace2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("journal")
    ap.add_argument("--interval", type=int, default=None)
    args = ap.parse_args(argv)
    ticks, iv = load_ticks(args.journal, args.interval)
    print(f"{len(ticks)} synthetic ticks from {args.journal} (interval={iv}s)")
    t1, t2 = replay_twice(ticks, "CERT", iv)
    div = first_divergence(t1, t2)
    if div:
        print(f"DIVERGENCE: {div}")
        return 1
    print(f"OK: {len(t1)} events, payload-exact across 2 engines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
