from __future__ import annotations

import asyncio

import os
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request

from app.infrastructure.serialization import RuntimeControlRequest
from app.infrastructure.adapters.paper_broker import PaperBrokerAdapter
from app.runtime.contracts import RuntimeMode
from app.runtime.feeds import DhanFeedSource
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
    runtime_mode = (request.mode or getattr(settings, "broker_mode", None) or RuntimeMode.PAPER.value).lower()
    symbols = list(request.symbols or getattr(http_request.app.state, "active_symbols", []))
    if not symbols:
        raise HTTPException(status_code=400, detail="Runtime start requires at least one symbol")

    if runtime_mode == RuntimeMode.LIVE.value and os.getenv("LIVE_TRADING_ENABLED", "").lower() not in {"1", "true", "yes"}:
        raise HTTPException(
            status_code=403,
            detail="Live execution requires LIVE_TRADING_ENABLED=true",
        )

    feed = _resolve_feed(http_request, runtime_mode, symbols)
    broker = _resolve_broker(http_request, runtime_mode)
    create_session = getattr(orchestrator, "start_session", None)
    if callable(create_session):
        session = create_session(
            session_id=request.session_id,
            feed=feed,
            symbols=symbols,
        )
    else:
        session = orchestrator.create_live_session(
            session_id=request.session_id,
            feed=feed,
            symbols=symbols,
        )
    try:
        orchestrator.bind_broker(request.session_id, broker)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    orchestrator.start(request.session_id)
    session_state = orchestrator.get_session_state(request.session_id)
    if hasattr(session_state, "value"):
        session_state = session_state.value
    readiness = session.ready_readiness() if hasattr(session, "ready_readiness") else None
    start_snapshot = session.snapshot() if hasattr(session, "snapshot") else {}
    return {
        "status": "started",
        "session_id": request.session_id,
        "mode": runtime_mode,
        "symbols": symbols,
        "feed": feed.name(),
        "broker_bound": True,
        "session_state": session_state,
        "state_digest": start_snapshot.get("state_digest"),
        "readiness": asdict(readiness) if readiness is not None else None,
        "safety_block": [check.reason for check in getattr(readiness, "checks", ()) if check.reason],
    }


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
    readiness = session.ready_readiness() if hasattr(session, "ready_readiness") else None
    snapshot = session.snapshot()
    portfolio = snapshot.get("portfolio", {})
    open_order_count = 0
    if isinstance(portfolio, dict):
        open_order_count = sum(
            len(item.get("open_positions", []))
            for item in portfolio.values()
            if isinstance(item, dict)
        )
    session_state = getattr(session, "session_state", None)
    if hasattr(session_state, "value"):
        session_state = session_state.value
    return {
        "session_id": session_id,
        "running": session.is_running,
        "session_state": session_state,
        "state_digest": snapshot.get("state_digest"),
        "readiness": asdict(readiness) if readiness is not None else None,
        "open_order_count": open_order_count,
    }


@router.post("/runtime/{session_id}/run_once")
async def runtime_run_once(session_id: str, request: Request, max_ticks: int = 100):
    orchestrator = _get_orchestrator(request)
    if orchestrator.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}")
    loop = asyncio.get_running_loop()
    try:
        events = await loop.run_in_executor(
            None,
            orchestrator.run_once,
            session_id,
            max_ticks,
        )
    except RuntimeError as exc:
        detail = str(exc)
        if "run_in_progress" in detail:
            raise HTTPException(status_code=409, detail="run_in_progress")
        if detail.startswith("session_not_running"):
            raise HTTPException(status_code=409, detail=detail)
        raise HTTPException(status_code=500, detail=detail)
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


def _resolve_feed(
    request: Request,
    runtime_mode: str,
    symbols: list[str],
):
    if runtime_mode in {RuntimeMode.LIVE.value, RuntimeMode.PAPER.value}:
        adapter = getattr(request.app.state, "market_data_adapter", None)
        if adapter is None:
            raise HTTPException(status_code=503, detail="market_data_adapter not initialized")
        return DhanFeedSource(adapter, symbols=symbols)
    raise HTTPException(status_code=400, detail=f"Unsupported runtime mode: {runtime_mode}")

def _resolve_broker(request: Request, runtime_mode: str):
    if runtime_mode == RuntimeMode.LIVE.value:
        broker = getattr(request.app.state, "market_data_adapter", None)
        if broker is None:
            raise HTTPException(status_code=503, detail="live broker adapter not initialized")
        return broker
    if runtime_mode == RuntimeMode.PAPER.value:
        return PaperBrokerAdapter()
    raise HTTPException(status_code=400, detail=f"Unsupported runtime mode: {runtime_mode}")
