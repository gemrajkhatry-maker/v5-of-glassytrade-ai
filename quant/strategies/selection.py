"""Single entry-authority factory — the deterministic Fabio AMT playbook.

Decision 2026-09-17: the gate pipeline is the only thing allowed to approve an
entry. TimesFM no longer selects an entry strategy; it provides forecasts to
exits/UI (see quant/decision/timesfm_forecast_factory.py).
"""
from __future__ import annotations

from quant.strategies.amt_scalping import AmtScalpingStrategy


def build_strategy(*, decision_service=None, exit_engine=None) -> AmtScalpingStrategy:
    """Return the one entry authority. Ignored env/strategy inputs cannot change it."""
    return AmtScalpingStrategy(
        decision_service=decision_service,
        exit_engine=exit_engine,
    )


__all__ = ["build_strategy"]
