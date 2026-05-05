"""Startup telemetry and operator-facing crash/runbook mapping."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass

from app.core.metrics import metrics


@dataclass
class PhaseResult:
    status: str
    duration_ms: float
    detail: str | None = None


RUNBOOK = {
    "syntax": {
        "message": "Syntax/import failure in backend code",
        "action": "Fix syntax/import in indicated file, restart startup.",
    },
    "config": {
        "message": "Mode/configuration could not be resolved",
        "action": "Verify GLASSYTRADE_ENV, GLASSYTRADE_STRATEGY, and strategy YAML files.",
    },
    "mlx": {
        "message": "MLX/LLM bootstrap unavailable at startup",
        "action": "Keep deferred loading enabled; verify MLX_MODEL_PATH, adapter path, and OpenRouter fallback.",
    },
    "symbol_resolution": {
        "message": "Symbol mapping missing for option->underlying",
        "action": "Verify instruments.json and broker symbol format for listed symbols.",
    },
    "engine": {
        "message": "Trading engine startup failure",
        "action": "Check startup logs and storage connectivity; restart after correcting root cause.",
    },
    "runtime": {
        "message": "Unexpected runtime exception during startup",
        "action": "Inspect logs with full stack trace; validate dependent service health.",
    },
}


_lock = threading.Lock()
_phase_starts: dict[str, float] = {}
_phase_results: dict[str, PhaseResult] = {}
_symbol_resolution: dict[str, int] = defaultdict(int)
_unresolved_symbols: set[str] = set()
_crash_categories: dict[str, int] = defaultdict(int)
_startup_started_at: float = 0.0
_startup_finished_at: float = 0.0

_startup_phase_counter = metrics.counter("startup_phase_count_total", "Startup lifecycle phase transitions")
_startup_crash_counter = metrics.counter("startup_crash_count_total", "Startup failures by category")
_startup_latency_hist = metrics.histogram(
    "startup_phase_duration_seconds",
    "Startup phase latency in seconds",
)
_startup_unresolved_symbol_gauge = metrics.gauge(
    "startup_unresolved_symbols_total",
    "Symbols missing required mapping or seed data",
)
_backend_startup_ready_gauge = metrics.gauge(
    "backend_startup_ready",
    "Backend readiness lifecycle state (1=ready,0=starting, -1=failed)",
)


def mark_startup_started() -> None:
    global _startup_started_at, _startup_finished_at
    with _lock:
        _startup_started_at = time.time()
        _startup_finished_at = 0.0
        _phase_starts.clear()
        _phase_results.clear()
        _crash_categories.clear()
        _unresolved_symbols.clear()
        _symbol_resolution.clear()
        _backend_startup_ready_gauge.set(0)


def mark_startup_finished() -> None:
    global _startup_finished_at
    with _lock:
        if _startup_started_at:
            _startup_finished_at = time.time()
        _backend_startup_ready_gauge.set(1)


def mark_startup_failed(category: str, detail: str | None = None) -> None:
    with _lock:
        _crash_categories[category] += 1
    metrics.counter(
        "startup_crash_count_total",
        "Startup failures by category",
        labels={"category": category},
    ).inc(1)
    if detail:
        end_phase("startup", status="failed", detail=detail)
    _backend_startup_ready_gauge.set(-1)


def begin_phase(phase: str) -> None:
    with _lock:
        _phase_starts[phase] = time.time()


def end_phase(phase: str, status: str = "ok", detail: str | None = None) -> float:
    with _lock:
        start = _phase_starts.pop(phase, None)
        if start is None:
            duration_ms = 0.0
        else:
            duration_ms = (time.time() - start) * 1000.0
        _phase_results[phase] = PhaseResult(status=status, duration_ms=duration_ms, detail=detail)

    _startup_phase_counter.inc(1)
    _startup_latency_hist.observe(duration_ms / 1000.0)
    metrics.gauge(
        "startup_phase_status",
        "Startup phase status (1=ok, 0=warn, -1=failed)",
        labels={"phase": phase, "status": status},
    ).set(1 if status == "ok" else 0)
    return duration_ms


def record_symbol_resolution(symbol: str, stage: str, found: bool) -> None:
    status = "found" if found else "missing"
    _symbol_resolution[f"{stage}:{status}"] += 1
    if not found:
        with _lock:
            _unresolved_symbols.add(symbol)
        metrics.counter(
            "startup_symbol_resolution_total",
            "Symbol resolution outcomes during startup",
            labels={"stage": stage, "status": status},
        ).inc(1)
        mark_startup_failed("symbol_resolution", f"unresolved symbol={symbol} stage={stage}")
    else:
        metrics.counter(
            "startup_symbol_resolution_total",
            "Symbol resolution outcomes during startup",
            labels={"stage": stage, "status": status},
        ).inc(1)


def unresolved_symbols() -> list[str]:
    with _lock:
        return sorted(_unresolved_symbols)


def unresolved_count() -> int:
    unresolved = unresolved_symbols()
    _startup_unresolved_symbol_gauge.set(float(len(unresolved)))
    return len(unresolved)


def crash_summary() -> list[dict[str, object]]:
    with _lock:
        return [
            {
                "category": k,
                "count": v,
                "runbook": RUNBOOK.get(k, {}),
            }
            for k, v in sorted(_crash_categories.items(), key=lambda item: item[0])
        ]


def startup_snapshot() -> dict[str, object]:
    with _lock:
        total_ms = (
            (time.time() - _startup_started_at) * 1000.0
            if _startup_started_at
            else 0.0
        )
        phases = {
            name: {
                "status": result.status,
                "duration_ms": round(result.duration_ms, 2),
                "detail": result.detail,
            }
            for name, result in _phase_results.items()
        }
    return {
        "started_at": _startup_started_at,
        "elapsed_ms": round(total_ms, 2),
        "phase_count": len(phases),
        "phases": phases,
        "symbol_resolution": {
            "missing_count": unresolved_count(),
            "missing_symbols": unresolved_symbols(),
            "breakdown": dict(_symbol_resolution),
        },
        "crash_summary": crash_summary(),
    }
