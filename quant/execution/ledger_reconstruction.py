"""Durable paper-book reconciliation from the append-only fill ledger."""
from __future__ import annotations

import math
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


def _side(fill: dict[str, Any]) -> str:
    return str(fill.get("side") or "").strip().upper()


def _is_entry(fill: dict[str, Any]) -> bool:
    order_id = str(fill.get("order_id") or "").strip().lower()
    return order_id.startswith("entry:") or _side(fill) == "ENTRY"


def _is_exit(fill: dict[str, Any]) -> bool:
    order_id = str(fill.get("order_id") or "").strip().lower()
    return order_id.startswith(("close:", "partial:")) or _side(fill) in {"EXIT", "BUY", "SELL"}


def reconstruct_fill_ledger(fills: list[dict[str, Any]] | None) -> LedgerReconstruction:
    """Fold durable fills into open positions without guessing ambiguous data.

    Canonical direction is BUY for long entries and SELL for short entries;
    LONG/SHORT are accepted as legacy entry aliases. Exit direction is the
    opposite side. Duplicate IDs are idempotent only when their accounting
    payload agrees; conflicting duplicates quarantine the position.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    seen: dict[str, tuple[Any, ...]] = {}
    duplicate_positions: set[str] = set()
    result = LedgerReconstruction()
    for fill in fills or []:
        if not isinstance(fill, dict):
            result.issues.add("invalid-fill")
            continue
        fid = str(fill.get("fill_id") or "").strip()
        pid = str(fill.get("position_id") or "").strip()
        if not fid or not pid:
            result.issues.add(fid or "missing-fill-id")
            continue
        try:
            qty = float(fill.get("quantity"))
            price = float(fill.get("fill_price"))
            if not math.isfinite(qty) or not math.isfinite(price) or qty <= 0 or price <= 0:
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            result.issues.add(fid)
            continue
        side = _side(fill)
        if side not in {"BUY", "SELL", "ENTRY", "EXIT", "LONG", "SHORT"}:
            result.issues.add(fid)
            continue
        identity = (pid, str(fill.get("symbol") or "").strip(), side, qty, price)
        if fid in seen:
            if seen[fid] != identity:
                result.issues.add(f"conflicting-fill:{fid}")
                duplicate_positions.add(pid)
            continue
        seen[fid] = identity
        grouped.setdefault(pid, []).append(fill)

    for pid, records in grouped.items():
        if pid in duplicate_positions:
            result.issues.add(pid)
            continue
        entries = [r for r in records if _is_entry(r)]
        if not entries:
            entries = [r for r in records if _side(r) in {"BUY", "SELL", "LONG", "SHORT"}]
        if not entries:
            result.issues.add(pid)
            continue
        entry_directions = {
            "SELL" if _side(r) in {"SELL", "SHORT"} else "BUY"
            for r in entries
        }
        if len(entry_directions) != 1:
            result.issues.add(pid)
            continue
        entry_direction = next(iter(entry_directions))
        exits = [r for r in records if r not in entries and _is_exit(r)]
        expected_exit = "SELL" if entry_direction == "BUY" else "BUY"
        normalized_exits: list[dict[str, Any]] = []
        for record in exits:
            side = _side(record)
            if side in {"EXIT", "BUY", "SELL"} and side not in {expected_exit, "EXIT"}:
                result.issues.add(pid)
                normalized_exits = []
                break
            normalized_exits.append(record)
        if pid in result.issues:
            continue
        entry_qty = sum(float(r["quantity"]) for r in entries)
        exit_qty = sum(float(r["quantity"]) for r in normalized_exits)
        remaining = entry_qty - exit_qty
        if remaining < -1e-9:
            result.issues.add(pid)
            continue
        if remaining > 1e-9:
            first = entries[0]
            result.positions[pid] = LedgerPosition(
                position_id=pid,
                symbol=str(first.get("symbol") or ""),
                signed_quantity=remaining if entry_direction == "BUY" else -remaining,
                entry_price=float(first["fill_price"]),
                entry_fill_ids=tuple(str(r["fill_id"]) for r in entries),
                exit_fill_ids=tuple(str(r["fill_id"]) for r in normalized_exits),
            )
    return result
