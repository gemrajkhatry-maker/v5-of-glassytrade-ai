"""Startup contract model and builder for runtime dependency checks."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any

from app.domain.services.startup_reconciliation import ReconciliationResult


def _callable(obj: object | None, attr: str) -> bool:
    """Return True when attribute exists and is callable."""
    target = getattr(obj, attr, None) if obj is not None else None
    return callable(target)


def _contract_id(checks: dict[str, str]) -> str:
    """Deterministic identifier over contract values for diff-friendly readiness output."""
    payload = json.dumps(checks, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"startup-contract:{digest}"


def _result(*parts: Any) -> str:
    """Compose a short stable contract status string."""
    if not parts:
        return "ok"
    return " ".join(str(part) for part in parts if part)


def _ok() -> str:
    return "ok"


def _error(message: str) -> str:
    return f"error: {message}"


@dataclass(frozen=True)
class StartupContracts:
    checks: dict[str, str]
    contract_id: str
    status: str

    def as_readiness_payload(self) -> dict[str, str]:
        payload = dict(self.checks)
        payload["contract_id"] = self.contract_id
        payload["status"] = self.status
        return payload


def build_startup_contracts(
    *,
    trading_session: Any,
    active_symbols: list[str] | None,
    reconciliation_result: ReconciliationResult | None = None,
    reconciliation_executed: bool | None = None,
) -> StartupContracts:
    """Evaluate startup runtime contracts for readiness observability.

    All checks are explicit and callable-based; `hasattr` alone is not treated
    as valid readiness without a real bound callable.
    """
    active_symbols = list(active_symbols or [])
    checks: dict[str, str] = {}

    checks["active_symbols"] = (
        _result(f"ok({len(active_symbols)})")
        if len(active_symbols) > 0
        else _error("no active symbols selected")
    )

    # Scanner settings are enforced at startup from config.
    from app.config import settings

    checks["scanner_settings"] = (
        _ok()
        if settings.SCANNER_TOP_N > 0 and settings.DEFAULT_EXCHANGE
        else _error("invalid scanner configuration")
    )

    # Strategy runtime contract (process_tick and routed event handling).
    event_router = getattr(trading_session, "_event_router", None)
    checks["strategy_runtime"] = (
        _ok()
        if callable(getattr(trading_session, "process_tick", None))
        and _callable(event_router, "execute_entry_path")
        and _callable(event_router, "trigger_llm_entry")
        and _callable(event_router, "should_trigger_llm")
        else _error("missing runtime contracts")
    )

    # Close-path contract: lifecycle close path resolution and callback.
    exit_coordinator = getattr(trading_session, "_exit_coordinator", None)
    checks["position_close_contract"] = (
        _ok()
        if _callable(exit_coordinator, "on_position_closed")
        and _callable(exit_coordinator, "_resolve_position")
        else _error("close path contract missing")
    )

    # Broker runtime contract.
    broker = getattr(trading_session, "_broker", None)
    checks["broker_runtime"] = (
        _ok()
        if _callable(broker, "execute_order")
        and _callable(broker, "cancel_order")
        else _error("broker runtime contract missing")
    )

    # Storage runtime contract for durable lifecycle operations and health checks.
    storage = getattr(trading_session, "_storage", None)
    checks["storage_runtime"] = (
        _ok()
        if _callable(storage, "save_open_position")
        and _callable(storage, "delete_open_position")
        and _callable(storage, "save_trade")
        and _callable(storage, "kv_set")
        else _error("storage runtime contract missing")
    )

    # Startup reconciliation contract: broker/storage lookup methods + optional result.
    broker_methods = _callable(broker, "get_positions") or _callable(
        broker, "get_account_positions"
    )
    if reconciliation_executed is None:
        reconciliation_executed = isinstance(reconciliation_result, ReconciliationResult)

    checks["reconciliation"] = (
        _ok()
        if reconciliation_executed
        and _callable(storage, "load_open_positions")
        and _callable(storage, "delete_open_position")
        and broker_methods
        else _error(
            "reconciliation contract missing"
            if not broker_methods
            or not _callable(storage, "load_open_positions")
            or not _callable(storage, "delete_open_position")
            else "reconciliation not executed"
        )
    )
    checks["reconciliation_summary"] = (
        _result(
            f"db={reconciliation_result.db_positions}",
            f"broker={reconciliation_result.broker_positions}",
            f"restored={reconciliation_result.restored}",
            f"stale={reconciliation_result.stale_removed}",
            f"orphaned={reconciliation_result.orphaned_registered}",
        )
        if isinstance(reconciliation_result, ReconciliationResult)
        else "not_run"
    )

    if active_symbols:
        checks["reconciliation_discrepancies"] = (
            str(len(reconciliation_result.discrepancies))
            if isinstance(reconciliation_result, ReconciliationResult)
            else "n/a"
        )
    else:
        checks["reconciliation_discrepancies"] = "n/a"

    critical_status_keys = {
        "active_symbols",
        "scanner_settings",
        "strategy_runtime",
        "position_close_contract",
        "broker_runtime",
        "storage_runtime",
        "reconciliation",
    }
    status = (
        "ok"
        if all(
            checks.get(key, "").startswith("ok")
            for key in critical_status_keys
        )
        else "degraded"
    )

    return StartupContracts(
        checks=checks,
        contract_id=_contract_id(checks),
        status=status,
    )
