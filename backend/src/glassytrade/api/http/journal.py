"""Versioned journal read endpoint."""

from fastapi import APIRouter, Query

router = APIRouter(prefix="/v1/journal", tags=["v1"])


@router.get("")
async def get_journal(after_sequence: int = Query(default=0, ge=0)) -> dict:
    return {"schemaVersion": "1.0", "afterSequence": after_sequence, "events": []}
