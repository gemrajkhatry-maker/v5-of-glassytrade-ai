"""Gate 1 — Exchange session clock & spread filter.

NSE: Trading active between 09:30:00 and 15:15:00 IST (09:15–09:30 opening blackout).
MCX: Trading active between 09:15:00 and 23:15:00 IST (09:00–09:15 opening blackout).
Bid-Ask spread must satisfy Ask - Bid <= 2*tau (where tau is the minimum tick increment).
"""

from __future__ import annotations

from datetime import time
from typing import Optional

from quant.decision.context import DecisionContext
from quant.decision.result import GateResult

_MOMENTUM_SETUPS = frozenset({"TRIPLE_A", "LVN_SNIPER"})
_REVERSION_SETUPS = frozenset({"VA_FADE", "SECOND_DRIVE"})

# Session clock boundaries (IST)
_NSE_START = time(9, 30, 0)
_NSE_END = time(15, 15, 0)

_MCX_START = time(9, 15, 0)
_MCX_END = time(23, 15, 0)


def _parse_time(time_str: str) -> Optional[time]:
    """Parse wall-clock time from ISO-8601, epoch-adjacent or bare "HH:MM[:SS]" strings.

    The context builder feeds ``time_str`` straight from ``bar.time`` (ISO-8601
    with offset, e.g. ``2026-08-19T09:20:00+05:30``), so the ISO "T" separator
    must be handled or the exchange-clock blackout would never fire.
    """
    if not time_str:
        return None
    clean = time_str.strip()
    if "T" in clean:
        clean = clean.split("T", 1)[1]
    elif " " in clean:
        clean = clean.split(" ")[-1]
    clean = clean.split("+")[0].split("Z")[0].split(".")[0]
    parts = clean.split(":")
    if len(parts) >= 2:
        try:
            h = int(parts[0])
            m = int(parts[1])
            s = int(parts[2]) if len(parts) > 2 else 0
            return time(h, m, s)
        except (ValueError, TypeError):
            return None
    return None


def gate_session_phase(ctx: DecisionContext) -> GateResult:
    """Gate 1: Session Phase, Clock and Spread Validation."""
    if not ctx.session_open:
        return GateResult(gate=1, passed=False, reason="Session closed")
    if not ctx.warmup_complete:
        return GateResult(gate=1, passed=False, reason="Warming up — insufficient bars")

    # Exchange clock & opening blackout check
    market = str(getattr(ctx, "market", "NSE") or "NSE").upper()
    t = _parse_time(ctx.time_str)
    if t is not None:
        if market == "MCX":
            if t < _MCX_START or t > _MCX_END:
                return GateResult(
                    gate=1,
                    passed=False,
                    reason=f"MCX clock blackout: current {t.strftime('%H:%M:%S')} outside 09:15:00–23:15:00 IST",
                )
        else:
            # NSE default
            if t < _NSE_START or t > _NSE_END:
                return GateResult(
                    gate=1,
                    passed=False,
                    reason=f"NSE clock blackout: current {t.strftime('%H:%M:%S')} outside 09:30:00–15:15:00 IST",
                )

    # Session-phase setup permissions (Fabio)
    evidence = ctx.setup_evidence
    if evidence is not None and evidence.setup_type and evidence.setup_type != "NONE":
        phase_label = ctx.session_phase or "current phase"
        if evidence.setup_type in _MOMENTUM_SETUPS and not ctx.allow_trend:
            return GateResult(
                gate=1,
                passed=False,
                reason=(
                    f"SESSION_PHASE: {evidence.setup_type} blocked — "
                    f"trend continuation not permitted in {phase_label}"
                ),
            )
        if evidence.setup_type in _REVERSION_SETUPS and not ctx.allow_reversion:
            return GateResult(
                gate=1,
                passed=False,
                reason=(
                    f"SESSION_PHASE: {evidence.setup_type} blocked — "
                    f"mean reversion not permitted in {phase_label}"
                ),
            )

    # Bid-Ask spread filter (playbook): spread ≤ max(2×tick, 0.1% of price, ₹0.40).
    # Fail CLOSED when no book — admitting a wide/unknown book is the only
    # slippage gate in the pipeline.
    tick = ctx.tick_size if ctx.tick_size and ctx.tick_size > 0 else 0.05
    if not (ctx.ask > 0 and ctx.bid > 0 and ctx.ask >= ctx.bid):
        return GateResult(
            gate=1,
            passed=False,
            reason="No bid/ask book — cannot verify spread",
        )
    from quant.contracts.instrument_registry import is_option_contract

    spread = ctx.ask - ctx.bid
    # Instrument price basis: mid of the book (option premium or futures LTP),
    # not an underlying bar that may be attached on translated engines.
    mid = (ctx.ask + ctx.bid) / 2.0
    close_px = float(getattr(ctx.bar, "close", 0) or 0) if ctx.bar is not None else 0.0
    px = mid if mid > 0 else close_px
    if is_option_contract(ctx.symbol):
        # Options: wider spread allowance for normal market liquidity (up to 1.5% of premium or 10 ticks, min ₹2.00)
        max_spread = max(10.0 * tick, px * 0.015, 2.00)
    else:
        # Futures / Underlying: tight spread filter (2x tick, 0.1% of price, min ₹0.50)
        max_spread = max(2.0 * tick, px * 0.001, 0.50)
    if spread > max_spread:
        pct = (spread / px * 100.0) if px > 0 else 0.0
        return GateResult(
            gate=1,
            passed=False,
            reason=f"Wide spread ({spread:.2f} > {max_spread:.2f}, {pct:.2f}%) — slippage risk",
        )

    return GateResult(gate=1, passed=True)


__all__ = [
    "gate_session_phase",
]
