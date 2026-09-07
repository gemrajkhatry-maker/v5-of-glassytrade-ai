"""Durable paper-book reconciliation from the append-only fill ledger."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LedgerPosition:
    position_id: str
    symbol: str
    signed_quantity: float
    entry_price: float
    entry_fill_ids: tuple[str, ...] = ()
    exit_fill_ids: tuple[str, ...] = ()


@dataclass
class LedgerReconstruction:
    positions: dict[str, LedgerPosition] = field(default_factory=dict)
    issues: set[str] = field(default_factory=set)


def reconstruct_fill_ledger(fills: list[dict[str, Any]] | None) -> LedgerReconstruction:
    """Fold durable entry/exit fills into open quantities.

    The ledger is intentionally the accounting authority: duplicate fill IDs
    are ignored, entries create quantity, and SELL/BUY exits reduce the signed
    quantity. Ambiguous records are quarantined rather than guessed.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    seen: set[str] = set()
    result = LedgerReconstruction()
    for fill in fills or []:
        fid = str(fill.get("fill_id") or "").strip()
        pid = str(fill.get("position_id") or "").strip()
        if not fid or not pid:
            result.issues.add(fid or "missing-fill-id")
            continue
        if fid in seen:
            continue
        seen.add(fid)
        try:
            qty = float(fill.get("quantity"))
            price = float(fill.get("fill_price"))
            if qty <= 0 or price <= 0:
                raise ValueError
        except (TypeError, ValueError):
            result.issues.add(fid)
            continue
        grouped.setdefault(pid, []).append(fill)

    for pid, records in grouped.items():
        entries = [r for r in records if str(r.get("side", "")).upper() in {"BUY", "ENTRY"}]
        exits = [r for r in records if str(r.get("side", "")).upper() in {"SELL", "EXIT"}]
        # Short positions use SELL entries and BUY exits; the explicit order_id
        # prefixes emitted by the OMS disambiguate those cases.
        if not entries:
            entries = [r for r in records if str(r.get("order_id", "")).startswith("entry:")]
        if not entries:
            result.issues.add(pid)
            continue
        entry_qty = sum(float(r["quantity"]) for r in entries)
        exit_qty = sum(float(r["quantity"]) for r in exits)
        remaining = entry_qty - exit_qty
        if remaining < -1e-9:
            result.issues.add(pid)
            continue
        first = entries[0]
        if remaining > 1e-9:
            result.positions[pid] = LedgerPosition(
                position_id=pid,
                symbol=str(first.get("symbol") or ""),
                signed_quantity=remaining if str(first.get("side", "")).upper() == "BUY" else -remaining,
                entry_price=float(first["fill_price"]),
                entry_fill_ids=tuple(str(r["fill_id"]) for r in entries),
                exit_fill_ids=tuple(str(r["fill_id"]) for r in exits),
            )
    return result
