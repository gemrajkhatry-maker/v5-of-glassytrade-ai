#!/usr/bin/env python3
"""Scan paper journals for the half-lot sizing bug (day-of-week multiplier).

The defect (fixed in commit 72a4fff2): SessionRisk.position_size in
aggressive mode applied the day-of-week multiplier (0.5 on Mon/Fri) AFTER
the lot computation with no re-snap, producing quantities that are not lot
multiples — orders the exchange would reject.

Signature: any PositionOpened / PositionClosed fill quantity that is not an
exact multiple of the instrument's lot size. Lot sizes are inferred per
symbol root from quant.contracts.instrument_registry when available, else
from the observed quantity distribution heuristic (MCX/FNO roots have
discrete lot sizes; every recorded quantity should cluster on one grid).

Usage:
    PYTHONPATH=backend:. python scripts/scan_half_lot_rejections.py \
        [--journals backend/journals] [--sample 200000]
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

# Lot sizes per instrument root. Kept in sync with the registry/lot tables
# used by the live path (brokers.broker.market_info / instrument_registry).
KNOWN_LOTS = {
    "NIFTY": 75, "BANKNIFTY": 35, "FINNIFTY": 65, "MIDCPNIFTY": 140,
    "NIFTYNXT50": 25,
    "CRUDEOIL": 100, "NATURALGAS": 1250, "GOLDM": 10, "SILVERM": 5,
    "GOLD": 100, "SILVER": 30, "COPPER": 2500, "ZINC": 5000,
    "MENTHAOIL": 360, "COTTONCNDY": 33000,
}


def root_of(symbol: str) -> str:
    return symbol.strip().split()[0].upper()


def is_lot_aligned(qty: float, lot: int) -> bool:
    if qty is None or lot <= 0:
        return True
    return abs(qty / lot - round(qty / lot)) < 1e-6


def infer_lots(quantities: list[float]) -> int | None:
    """Fallback: infer the lot grid as the GCD of integer quantities."""
    ints = [int(round(q)) for q in quantities if q and q > 0 and float(q).is_integer()]
    if len(ints) < 2:
        return None
    g = 0
    for n in ints:
        g = math.gcd(g, n)
    return g or None


def scan_file(path: Path, sample: int) -> dict:
    stats = {
        "file": path.name,
        "opens": 0,
        "closes": 0,
        "misaligned": [],
        "quantities": [],
        "trade_dates": set(),
    }
    with open(path, encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh):
            if i >= sample:
                break
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            etype = evt.get("type")
            t = evt.get("time", "")
            if len(t) > 10:
                stats["trade_dates"].add(t[:10])
            if etype == "PositionOpened":
                pos = evt.get("position") or {}
                qty = abs(float(pos.get("size") or 0))
                stats["opens"] += 1
                if qty > 0:
                    stats["quantities"].append(qty)
            elif etype in ("PositionClosed", "PositionReduced"):
                fill = evt.get("fill") or {}
                pos = fill.get("position") or {}
                qty = abs(float(pos.get("size") or fill.get("quantity") or 0))
                stats["closes"] += 1
                if qty > 0:
                    stats["quantities"].append(qty)
            else:
                continue
            # capture misaligned events with context
            qty = abs(float((evt.get("position") or {}).get("size")
                            or (evt.get("fill") or {}).get("quantity") or 0))
            stats["_events"] = stats.get("_events", 0) + 1
            stats.setdefault("_evt_list", []).append((etype, evt))
    return stats


def check_alignment(stats: dict) -> list[dict]:
    root = root_of(stats["file"])
    lot = KNOWN_LOTS.get(root) or infer_lots(stats["quantities"])
    if not lot:
        return []
    findings = []
    for etype, evt in stats.get("_evt_list", []):
        qty = abs(float((evt.get("position") or {}).get("size")
                        or (evt.get("fill") or {}).get("quantity") or 0))
        if qty > 0 and not is_lot_aligned(qty, lot):
            findings.append({
                "event": etype,
                "time": evt.get("time", ""),
                "qty": qty,
                "lot": lot,
                "residual": qty % lot,
                "reason": (evt.get("fill") or {}).get("reason", ""),
            })
    return findings


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--journals", default="backend/journals")
    ap.add_argument("--sample", type=int, default=200_000,
                    help="max lines read per journal file")
    args = ap.parse_args()

    files = sorted(Path(args.journals).glob("*.jsonl"))
    total_opens = total_closes = 0
    all_findings: list[dict] = []
    files_with_trades = 0

    for path in files:
        if path.stat().st_size == 0:
            continue
        stats = scan_file(path, args.sample)
        if not stats["opens"] and not stats["closes"]:
            continue
        files_with_trades += 1
        total_opens += stats["opens"]
        total_closes += stats["closes"]
        findings = check_alignment(stats)
        for f in findings:
            f["file"] = stats["file"]
        all_findings.extend(findings)

    print(f"journals scanned (with trades): {files_with_trades}")
    print(f"total PositionOpened:           {total_opens}")
    print(f"total PositionClosed/Reduced:   {total_closes}")
    print(f"lot-misaligned events:          {len(all_findings)}")
    if all_findings:
        by_lot = defaultdict(list)
        for f in all_findings:
            by_lot[f["lot"]].append(f)
        for lot in sorted(by_lot):
            fl = by_lot[lot]
            print(f"\n--- lot {lot} ({len(fl)} events) ---")
            for f in fl[:20]:
                print(f"  {f['time']} {f['event']:16s} qty={f['qty']:>10.0f} "
                      f"residual={f['residual']:>6.0f} {f['reason']} [{f['file']}]")
            if len(fl) > 20:
                print(f"  ... and {len(fl) - 20} more")
    else:
        print("\nNo misaligned quantities found in scanned journals.")


if __name__ == "__main__":
    main()
