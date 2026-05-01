"""AMT analysis coordination - extracted from trading_session.py.

Handles AMT analysis execution and data source selection.
"""

from __future__ import annotations

import logging
from typing import Any

from app.domain.constants import RECENT_DATA_WINDOW

log = logging.getLogger(__name__)


def run_amt_analysis(
    event,
    amt_handler,
    risk_coordinator,
    cache,
    prior: dict | None = None,
) -> Any | None:
    """Run AMT analysis with data source selection and prior profile injection."""
    # Dual feed: use underlying futures data for AMT analysis (only if we have enough data)
    # Lowered threshold from 20 to 5 candles — CVD on option data produces sign-flipping noise
    # because option delta is driven by MM hedging, not actual market direction.
    _underlying_min_candles = 5
    amt_data = list(event.data)
    cvd_source = "option"  # default: option premium data
    
    if cache.has_underlying_data(_underlying_min_candles):
        amt_data = cache.get_underlying_data()
        cvd_source = "underlying"
    elif amt_data:
        log.warning(
            "AMT: using option premium data for %s (no underlying futures available) "
            "— CVD/OFI will be from option ticks, not NIFTY FUT. Interpret with caution.",
            event.symbol,
        )

    srm = risk_coordinator.get_session_risk_manager(event.symbol)
    
    # Compute prior session average volume from prior profile
    prior_avg_volume = 0.0
    if prior:
        prior_total_vol = prior.get("total_volume", 0.0)
        prior_elapsed_min = prior.get("elapsed_minutes", 0.0)
        if prior_total_vol > 0 and prior_elapsed_min > 0:
            # Average volume per minute from prior session
            prior_avg_volume = prior_total_vol / prior_elapsed_min
    
    try:
        amt_result, amt_dto, fp_dto = amt_handler.analyze(
            amt_data,
            event.order_book,
            prior_poc=prior.get("poc", 0.0) if prior else 0.0,
            prior_vah=prior.get("vah", 0.0) if prior else 0.0,
            prior_val=prior.get("val", 0.0) if prior else 0.0,
            cushion_tier=srm.risk_tier.name if srm else "NORMAL",
            session_pnl=srm.session_pnl if srm else 0.0,
            option_tick=event.tick,
            cvd_source=cvd_source,
            prior_avg_volume=prior_avg_volume,
        )
    except Exception:
        log.error(
            "AMT analysis failed for %s — skipping tick",
            event.symbol,
            exc_info=True,
        )
        return None

    # Update cache with AMT results
    cache.update_amt(amt_result, amt_dto, fp_dto)
    return amt_result, amt_dto, fp_dto


def select_amt_data_source(cache, min_candles: int = 5) -> tuple[list, str]:
    """Select appropriate data source for AMT analysis."""
    if cache.has_underlying_data(min_candles):
        return cache.get_underlying_data(), "underlying"
    return cache.get_option_data(), "option"