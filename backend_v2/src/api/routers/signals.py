"""
Signals router — REST endpoints for signal data.
"""

from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/signals/{symbol}")
async def get_signal(symbol: str) -> Dict:
    """
    Get latest signal for a symbol.

    Args:
        symbol: Trading symbol

    Returns:
        Latest signal data.
    """
    # TODO: Implement signal retrieval from state
    return {
        "symbol": symbol,
        "direction": "FLAT",
        "message": "Signal endpoint - implementation pending",
    }


@router.get("/signals")
async def list_signals() -> List[Dict]:
    """
    List all recent signals.

    Returns:
        List of recent signals.
    """
    # TODO: Implement signal listing
    return []


@router.get("/symbols")
async def list_symbols() -> List[str]:
    """
    List all active symbols.

    Returns:
        List of active symbols.
    """
    from src.config.instruments import get_all_symbols
    return get_all_symbols()