"""Testing router — dev-only tick injection for cross-process E2E.

DANGEROUS IF EXPOSED: this routes synthetic packets into the LIVE feed
producer path. Guarded three ways:
  1. GLASSYTRADE_ENV must be "development" (checked per-request)
  2. Binds only when explicitly included (see main.py registration)
  3. Packets go through the SAME _route() path as real Dhan WS packets —
     no bypass, no mock — so E2E results are trustworthy.

Payload: a single Dhan-shaped packet or a list of them:
    {"symbol": "GOLDM SEP FUT", "ltp": 101.0, "volume": 10, ...}
    [{"symbol": ..., ...}, ...]
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["testing"])
logger = logging.getLogger(__name__)


_ALLOWED_ENVS = {"development", "paper"}


def _env_allows() -> tuple[bool, str]:
    """Injection is for validating the paper loop; live mode stays blocked."""
    env = os.environ.get("GLASSYTRADE_ENV", "").strip().lower()
    if env not in _ALLOWED_ENVS:
        return False, (
            f"tick injection requires GLASSYTRADE_ENV in {sorted(_ALLOWED_ENVS)} "
            f"(current: {env or 'unset'})"
        )
    return True, ""


@router.post("/inject-tick")
async def inject_tick(request: Request):
    """Inject one or many Dhan-shaped packets through the real feed path."""
    ok, why = _env_allows()
    if not ok:
        raise HTTPException(status_code=403, detail=why)

    coordinator = getattr(getattr(request.app, "state", None), "coordinator", None)
    if coordinator is None or not getattr(coordinator, "started", False):
        raise HTTPException(status_code=503, detail="coordinator not started")

    feed = getattr(coordinator, "_feed", None)
    if feed is None:
        raise HTTPException(status_code=503, detail="feed not available")

    payload = await request.json()
    packets = payload if isinstance(payload, list) else [payload]
    if not packets:
        raise HTTPException(status_code=422, detail="empty payload")

    injected, skipped = 0, 0
    subscribed = set(feed.symbols()) if hasattr(feed, "symbols") else set()
    for pkt in packets:
        if not isinstance(pkt, dict) or not pkt.get("symbol"):
            skipped += 1
            continue
        # Route through the EXACT production path (same method real WS uses).
        feed._route(pkt)
        injected += 1

    return {
        "injected": injected,
        "skipped": skipped,
        "subscribedSymbols": sorted(subscribed),
    }
