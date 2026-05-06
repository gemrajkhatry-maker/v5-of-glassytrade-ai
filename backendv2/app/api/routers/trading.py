"""Trading session lifecycle and trading-state endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.infrastructure.serialization import RuntimeControlRequest
from app.runtime.feeds import LiveFeed
from app.runtime.orchestrator import RuntimeOrchestrator

router = APIRouter()


def _get_orchestrator(request: Request) -> RuntimeOrchestrator:
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Runtime orchestrator unavailable")
    return orchestrator


@router.post("/runtime/start")
async def runtime_start(request: RuntimeControlRequest, http_request: Request):
    orchestrator = _get_orchestrator(http_request)
    settings = getattr(http_request.app.state, "app_settings", None)
    runtime_mode = (request.mode or getattr(settings, "broker_mode", None) or "paper").lower()
    if runtime_mode == "live":
        raise HTTPException(
            status_code=400,
            detail=(
                "Live runtime start requires a concrete tick_source/feed injection. "
                "Current API path creates LiveFeed without source."
            ),
        )
    orchestrator.create_live_session(
        session_id=request.session_id,
        feed=LiveFeed(symbols=request.symbols, strict_symbol_mode=True),
        symbols=request.symbols,
    )
    orchestrator.start(request.session_id)
    return {"status": "started", "session_id": request.session_id, "mode": request.mode or "live"}


@router.post("/runtime/stop/{session_id}")
async def runtime_stop(session_id: str, request: Request):
    orchestrator = _get_orchestrator(request)
    if not orchestrator.stop(session_id):
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}")
    return {"status": "stopped", "session_id": session_id}


@router.get("/runtime/{session_id}/state")
async def runtime_state(session_id: str, request: Request):
    orchestrator = _get_orchestrator(request)
    session = orchestrator.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}")
    return {"session_id": session_id, "running": session.is_running}


@router.post("/runtime/{session_id}/run_once")
async def runtime_run_once(session_id: str, request: Request, max_ticks: int = 100):
    orchestrator = _get_orchestrator(request)
    events = orchestrator.run_once(session_id=session_id, max_ticks=max_ticks)
    connected_clients = getattr(request.app.state, "connected_clients", [])
    for event in events:
        event_data = _serialize_event(event)
        for queue in connected_clients:
            await queue.put(event_data)
    return {"session_id": session_id, "event_count": len(events)}


@router.get("/positions")
async def get_positions(request: Request):
    orchestrator = _get_orchestrator(request)
    positions = []
    for session_id, session in getattr(orchestrator, "_sessions", {}).items():
        portfolios = session._position.snapshot() if hasattr(session._position, "snapshot") else {}
        if not portfolios:
            positions.append(
                {
                    "session": str(session_id),
                    "symbol": "",
                    "balance": 0.0,
                    "equity": 0.0,
                    "open_positions": [],
                },
            )
            continue
        for symbol, portfolio in portfolios.items():
            positions.append(
                {
                    "session": str(session_id),
                    "symbol": symbol,
                    "balance": float(portfolio.get("balance", 0.0)),
                    "equity": float(portfolio.get("equity", 0.0)),
                    "open_positions": portfolio.get("open_positions", []),
                }
            )
    return {"sessions": positions}


def _serialize_event(event: object) -> dict:
    if hasattr(event, "__dict__"):
        data = dict(getattr(event, "__dict__"))
    else:
        data = {"value": str(event)}
    data.setdefault("type", type(event).__name__)
    data.setdefault("event_type", data.get("type"))
    return data
