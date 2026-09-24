"""Versioned portfolio read endpoint."""

from fastapi import APIRouter

router = APIRouter(prefix="/v1/portfolio", tags=["v1"])


@router.get("")
async def get_portfolio() -> dict:
    return {"schemaVersion": "1.0", "accountId": "", "positions": []}
