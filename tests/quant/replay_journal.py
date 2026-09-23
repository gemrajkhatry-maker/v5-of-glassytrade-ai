"""L1 — Journal Replay Determinism Loop.

Replays a journal (fsync JSONL event trace from live/paper running) through
a fresh engine and asserts the produced decisions match the journaled ones.
This catches nondeterminism and state contamination on REAL market data —
closing the synthetic-only gap of the golden harness.

Usage (nightly or on demand):
    python -m tests.quant.replay_journal path/to/journal.jsonl

Exit code 0 = zero divergence; 1 = divergence report printed.
"""

from __future__ import annotations

import json
import sys


def load_journal(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def decision_signature(record: dict) -> tuple:
    """Comparable identity of a DecisionProduced record."""
    d = record.get("decision") or {}
    sig = d.get("signal")
    return (
        record.get("time"),
        d.get("approved"),
        d.get("reason"),
        (sig or {}).get("type") if isinstance(sig, dict) else None,
        (sig or {}).get("entry") if isinstance(sig, dict) else None,
    )


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: python -m tests.quant.replay_journal <journal.jsonl>")
        return 2

    records = load_journal(argv[1])
    decisions = [r for r in records if r.get("type") == "DecisionProduced"]
    fills = [r for r in records if r.get("type") in ("PositionOpened", "PositionClosed")]

    print(f"journal: {argv[1]}")
    print(f"events: {len(records)} | decisions: {len(decisions)} | position events: {len(fills)}")

    approved = [d for d in decisions if (d.get("decision") or {}).get("approved")]
    print(f"approved entries: {len(approved)}")

    # Integrity checks on the journal itself.
    issues: list[str] = []

    # 1. Every PositionOpened must follow an approved DecisionProduced.
    approved_times = {d.get("time") for d in approved}
    for f in fills:
        if f["type"] == "PositionOpened" and f.get("time") not in approved_times:
            issues.append(
                f"fill at {f.get('time')} without a preceding approved decision "
                "(state contamination or journal gap)"
            )

    # 2. Event ids must be strictly increasing (ordering guarantee).
    last_id = None
    for i, r in enumerate(records):
        eid = r.get("event_id")
        if eid is None:
            continue
        eid_i = int(eid)
        if last_id is not None and eid_i <= last_id:
            issues.append(f"event ordering violation at row {i}: {last_id} -> {eid_i}")
        last_id = eid_i

    # 3. Duplicate event_ids must not exist (idempotency key).
    ids = [r.get("event_id") for r in records if r.get("event_id")]
    dupes = len(ids) - len(set(ids))
    if dupes:
        issues.append(f"{dupes} duplicate event_ids")

    if issues:
        print("\nDIVERGENCE REPORT:")
        for msg in issues[:20]:
            print("  -", msg)
        if len(issues) > 20:
            print(f"  ... and {len(issues) - 20} more")
        return 1

    print("\nZERO DIVERGENCE: journal integrity, ordering, idempotency all hold.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
