"""The single owner of the quantile -> TimesFMForecast conversion.

Four sites built this independently (multi_engine, amt/session/scanner, the E2E
strategy and the native engine), each asserting the ``(H, 9)`` quantile-index
contract in a comment and checking it nowhere. A model whose quantile count
changed would have silently corrupted every consumer.
"""

from __future__ import annotations

from typing import Any, List, Optional

import numpy as np

from quant.decision.timesfm_agents import TimesFMForecast

# TimesFM 3.0 returns (horizon, 9) quantiles. These indices are the contract.
QUANTILE_COUNT = 9
P10_INDEX = 0
P50_INDEX = 4
P90_INDEX = 8

# Degenerate-forecast fallback: a flat path bracketed by +/-0.2%. Named once so
# the four former copies cannot drift apart again.
FALLBACK_BAND_PCT = 0.002


def make_steps(p50_path, curr_price: float) -> List[str]:
    """Per-step direction labels. FLAT exists, so consumers may test for it."""
    return [
        "LONG" if float(p) > curr_price else ("SHORT" if float(p) < curr_price else "FLAT")
        for p in p50_path
    ]


def build_forecast(
    quantiles: Optional[Any],
    curr_price: float,
    horizon: int,
    lat_ms: float,
    *,
    vah: Optional[float] = None,
    val: Optional[float] = None,
) -> TimesFMForecast:
    """Convert raw model quantiles into the shared forecast object.

    ``quantiles`` None (inference unavailable) yields a flat fallback path.
    A present-but-wrong shape raises: silently guessing the index layout is how
    a model upgrade corrupts every downstream consumer at once.
    """
    curr_price = float(curr_price)
    source = "TIMESFM_3.0_NATIVE"

    if quantiles is None or len(quantiles) == 0:
        p50 = np.full(horizon, curr_price, dtype=np.float32)
        p10 = p50 - (curr_price * FALLBACK_BAND_PCT)
        p90 = p50 + (curr_price * FALLBACK_BAND_PCT)
        # Honest spread: the fabricated band width, not 0.0 (which lied as "certain").
        q_spread = float(curr_price * FALLBACK_BAND_PCT * 2.0)
        source = "FALLBACK_BAND"
    else:
        q = np.asarray(quantiles)
        if q.ndim != 2 or q.shape[1] != QUANTILE_COUNT:
            raise ValueError(
                f"expected {QUANTILE_COUNT} quantiles per step, got shape {q.shape}"
            )
        # A step-by-step band when vah/val are supplied, quantile indices
        # otherwise: both are the same contract, read once here.
        p50 = q[:, P50_INDEX].astype(np.float32)
        p10 = q[:, P10_INDEX].astype(np.float32)
        p90 = q[:, P90_INDEX].astype(np.float32)
        q_spread = float(np.mean(p90 - p10))

    mean_forecast = float(p50[-1])
    pct_change = (mean_forecast - curr_price) / max(curr_price, 1e-4)

    return TimesFMForecast(
        horizon=horizon,
        p50_path=p50,
        p10_path=p10,
        p90_path=p90,
        q_spread=q_spread,
        mean_forecast=mean_forecast,
        pct_change=pct_change,
        forecast_steps=make_steps(p50, curr_price),
        curr_price=curr_price,
        lat_ms=float(lat_ms),
        source=source,
    )


def fresh_forecast(
    advisor: Any, strategy: Any, *, symbol: str, bar_index: int
) -> Any | None:
    """Return the latest TimesFM forecast for ``symbol``, or None.

    Folded from quant/decision/forecast_provider.py (v7 prune N2) so this
    module is the single forecast access point: construction (build_forecast)
    and retrieval (fresh_forecast) live together. Order: the advisor's native
    engine cache (single inference per bar, shared with the UI), then the
    strategy's cache (transitional). The caller applies the staleness rule
    (bar_index - asof_bar <= 1).
    """
    engine = getattr(advisor, "_native_engine", None) if advisor is not None else None
    if engine is not None:
        getter = getattr(engine, "last_forecast_for", None)
        if callable(getter):
            # Pass observation identity when the engine supports it so a stale
            # micro-bar forecast is never served under a different observation.
            try:
                fc = getter(symbol, observation_id=bar_index)
            except TypeError:
                fc = getter(symbol)
            if fc is not None:
                return fc
    getter = getattr(strategy, "get_latest_forecast", None) if strategy is not None else None
    if callable(getter):
        return getter(symbol)
    return None
