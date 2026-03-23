"""
Risk router — REST endpoints for risk management data.
"""

from typing import Dict

from fastapi import APIRouter

router = APIRouter()


@router.get("/risk/session")
async def get_session_risk() -> Dict:
    """
    Get session risk metrics.

    Returns:
        Session risk state.
    """
    # TODO: Implement risk state retrieval
    return {
        "session_start_equity": 0,
        "current_equity": 0,
        "daily_pnl": 0,
        "daily_pnl_pct": 0,
        "consecutive_losses": 0,
        "is_halted": False,
        "message": "Risk endpoint - implementation pending",
    }