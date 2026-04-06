"""
Config router — REST endpoints for configuration.
"""

from typing import Dict

from fastapi import APIRouter

router = APIRouter()


@router.get("/config/{symbol}")
async def get_config(symbol: str) -> Dict:
    """
    Get instrument configuration.

    Args:
        symbol: Trading symbol

    Returns:
        Instrument configuration.
    """
    from src.config.instruments import get_instrument

    try:
        config = get_instrument(symbol)
        return {
            "symbol": config.symbol,
            "exchange": config.exchange,
            "tick_size": config.tick_size,
            "lot_size": config.lot_size,
            "point_value": config.point_value,
            "profile_bucket_size": config.profile_bucket_size,
            "security_id": config.security_id,
        }
    except ValueError:
        return {
            "error": f"Unknown symbol: {symbol}",
        }


@router.get("/config/engine")
async def get_engine_config() -> Dict:
    """
    Get engine configuration.

    Returns:
        Engine configuration thresholds.
    """
    from src.config.engine_config import CFG

    return {
        "value_area_pct": CFG.value_area_pct,
        "lvn_threshold_pct": CFG.lvn_threshold_pct,
        "hvn_threshold_pct": CFG.hvn_threshold_pct,
        "min_aggression_score": CFG.min_aggression_score,
        "pyramid_aggression_score": CFG.pyramid_aggression_score,
        "min_rr_ratio": CFG.min_rr_ratio,
        "max_cushion_ticks": CFG.max_cushion_ticks,
        "risk_per_trade_pct": CFG.risk_per_trade_pct,
        "max_daily_loss_pct": CFG.max_daily_loss_pct,
        "max_consecutive_losses": CFG.max_consecutive_losses,
        "max_drawdown_pct": CFG.max_drawdown_pct,
    }