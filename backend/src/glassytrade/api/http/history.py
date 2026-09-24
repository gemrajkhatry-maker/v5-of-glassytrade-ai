"""Versioned history read endpoint."""

from fastapi import APIRouter

router = APIRouter(prefix="/v1/history", tags=["v1"])


@router.get("/{contract_id}")
async def get_history(contract_id: str) -> dict:
    return {"schemaVersion": "1.0", "contractId": contract_id, "bars": []}
