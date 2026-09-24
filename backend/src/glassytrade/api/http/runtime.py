"""Versioned runtime read endpoint."""

from fastapi import APIRouter

router = APIRouter(prefix="/v1/runtime", tags=["v1"])


@router.get("")
async def get_runtime() -> dict:
    return {"schemaVersion": "1.0", "status": "unknown"}
