"""The ONE place that maps auction state -> playbook model.

Decision 2026-09-17 (D2): IMBALANCED -> TREND, BALANCED -> MEAN_REVERSION.
A *complete* evidence snapshot or a certified initiative break may override a
lagging VA label, because the session-scale VA classification lags the
displacement that actually starts a trend (or the failed auction that starts a
reversion). This module is the single enforcement point; gates only report
which setup fired via GateResult.setup_key.
"""
from __future__ import annotations

from typing import Literal

from quant.contracts.enums import MarketState
from quant.decision.context import DecisionContext

Model = Literal["TREND", "MEAN_REVERSION"]

TREND = "TREND"
MEAN_REVERSION = "MEAN_REVERSION"

_TREND_SETUPS = frozenset(
    {"TRIPLE_A", "SECOND_DRIVE", "LVN_SNIPER", "INITIATIVE", "SQUEEZE"}
)
_REVERSION_SETUPS = frozenset({"VA_FADE"})


def setup_model(setup_key: str) -> Model | None:
    """Map a setup key to its playbook model, or None if unknown."""
    key = str(setup_key or "").upper()
    if key in _TREND_SETUPS:
        return TREND
    if key in _REVERSION_SETUPS:
        return MEAN_REVERSION
    return None


def _evidence_override(ctx: DecisionContext) -> Model | None:
    """Model forced by certified evidence, or None when the state label rules."""
    ev = getattr(ctx, "setup_evidence", None)
    if ev is not None:
        is_complete = getattr(ev, "is_complete", None)
        if callable(is_complete) and is_complete():
            m = setup_model(str(getattr(ev, "setup_type", "")))
            if m is not None:
                return m
    # A certified initiative break is displacement evidence the VA label may not
    # have caught up to yet — ponytail: Fabio Model 1 initiation.
    if str(getattr(ctx, "break_type", "") or "").upper() == "INITIATIVE":
        if str(getattr(ctx, "break_direction", "") or ""):
            return TREND
    return None


def select_model(ctx: DecisionContext) -> Model:
    """Return the active playbook model for this bar (evidence > state)."""
    override = _evidence_override(ctx)
    if override is not None:
        return override
    state = getattr(ctx, "market_state", MarketState.BALANCED)
    value = state.value if hasattr(state, "value") else str(state)
    if value == MarketState.IMBALANCED.value:
        return TREND
    return MEAN_REVERSION


def allows(setup_key: str, model: Model) -> bool:
    """True when ``setup_key`` belongs to ``model``."""
    return setup_model(setup_key) == model


__all__ = [
    "Model", "TREND", "MEAN_REVERSION", "setup_model", "select_model", "allows",
]
