"""Gate 1 — Exchange session clock & spread filter.

Session entry windows come from the single SessionClock authority: the
boundary constants in ``quant/contracts/timezones.py`` evaluated by the
phase table in ``quant/amt/session/context.py`` (surfaced through
``session_allow_entry`` / ``get_session_info``). This module owns no
wall-clock constants of its own.

  NSE: entries 09:30–15:15 IST (close protection from NSE_LAST_ENTRY).
  MCX: entries 09:15–23:00 IST (close protection from MCX_EVENING_END;
       the exchange itself trades until MCX_SESSION_CLOSE 23:30 — Gate 1
       follows the phase table only, never an independent 23:15 clock).

Bid-Ask spread must satisfy Ask - Bid <= 2*tau (where tau is the minimum tick increment).
"""

from __future__ import annotations

from quant.amt.session.context import get_session_info
from quant.decision.context import DecisionContext
from quant.decision.result import GateResult
from quant.session_gates import session_allow_entry

_MOMENTUM_SETUPS = frozenset({"TRIPLE_A", "LVN_SNIPER"})
_REVERSION_SETUPS = frozenset({"VA_FADE", "SECOND_DRIVE"})


def gate_session_phase(ctx: DecisionContext) -> GateResult:
    """Gate 1: Session Phase, Clock and Spread Validation."""
    if not ctx.session_open:
        return GateResult(gate=1, passed=False, reason="Session closed")
    if not ctx.warmup_complete:
        return GateResult(gate=1, passed=False, reason="Warming up — insufficient bars")

    # Exchange clock — phase table is the only entry-window authority.
    market = str(getattr(ctx, "market", "NSE") or "NSE").upper()
    if ctx.time_str and not session_allow_entry(ctx.time_str, market):
        try:
            info = get_session_info(ctx.time_str, market=market)
            session_name, market_label = info.session, info.market
        except Exception:
            session_name, market_label = "unknown phase", market
        return GateResult(
            gate=1,
            passed=False,
            reason=(
                f"{market_label} clock blackout: no new entries in "
                f"{session_name} (t={ctx.time_str})"
            ),
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
    is_option = (
        is_option_contract(ctx.contract_symbol)
        if ctx.contract_symbol
        else (is_option_contract(ctx.symbol) or ctx.option_delta is not None)
    )
    if is_option:
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
