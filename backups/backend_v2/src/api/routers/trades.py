"""
Trades router — REST endpoints for trade management.
"""

from typing import Dict, List

from fastapi import APIRouter

router = APIRouter()


@router.get("/trades")
async def list_trades() -> List[Dict]:
    """
    List all trades.

    Returns:
        List of trades.
    """
    # TODO: Implement trade listing
    return []


@router.get("/trades/{trade_id}")
async def get_trade(trade_id: str) -> Dict:
    """
    Get trade by ID.

    Args:
        trade_id: Trade identifier

    Returns:
        Trade details.
    """
    # TODO: Implement trade retrieval
    return {
        "trade_id": trade_id,
        "message": "Trade endpoint - implementation pending",
    }


@router.post("/trades/entry")
async def manual_entry() -> Dict:
    """
    Manual trade entry override.

    Returns:
        Trade confirmation.
    """
    # TODO: Implement manual entry
    return {
        "status": "not_implemented",
        "message": "Manual entry endpoint - implementation pending",
    }


@router.post("/trades/exit")
async def manual_exit() -> Dict:
    """
    Manual trade exit override.

    Returns:
        Exit confirmation.
    """
    # TODO: Implement manual exit
    return {
        "status": "not_implemented",
        "message": "Manual exit endpoint - implementation pending",
    }