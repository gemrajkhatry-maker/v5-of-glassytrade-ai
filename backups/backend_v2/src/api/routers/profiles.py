"""
Profiles router — REST endpoints for volume profile data.
"""

from typing import Dict, List, Optional

from fastapi import APIRouter

router = APIRouter()


@router.get("/profile/{symbol}")
async def get_profile(symbol: str) -> Dict:
    """
    Get volume profile for a symbol.

    Args:
        symbol: Trading symbol

    Returns:
        Volume profile data with POC/VAH/VAL/LVNs.
    """
    # TODO: Implement profile retrieval from state
    return {
        "symbol": symbol,
        "poc": None,
        "vah": None,
        "val": None,
        "lvns": [],
        "hvns": [],
        "message": "Profile endpoint - implementation pending",
    }