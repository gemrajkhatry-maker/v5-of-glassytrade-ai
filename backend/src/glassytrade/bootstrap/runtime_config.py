"""Immutable runtime configuration for the target deployment boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Mapping


class StartupError(ValueError):
    """Raised when runtime configuration cannot safely start the process."""


def _enabled(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


@dataclass(frozen=True)
class RuntimeConfig:
    mode: Literal["shadow", "paper", "live"]
    account_id: str
    exchange: str
    database_path: Path
    evidence_policy: str
    risk_policy: Mapping[str, object]
    broker_capabilities: frozenset[str]
    config_fingerprint: str
    runtime_engine: Literal["legacy", "target"] = "legacy"

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> "RuntimeConfig":
        if not isinstance(values, Mapping):
            raise StartupError("runtime config must be a mapping")

        mode = str(values.get("mode", "")).strip().lower()
        if mode not in {"shadow", "paper", "live"}:
            raise StartupError("mode must be shadow, paper, or live")
        runtime_engine = str(values.get("runtime_engine", "legacy")).strip().lower()
        if runtime_engine not in {"legacy", "target"}:
            raise StartupError("runtime_engine must be legacy or target")

        if mode == "live":
            forbidden = {
                "clear_positions_on_restart": "clear_positions_on_restart",
                "reconcile_delete_stale": "reconcile_delete_stale",
                "allow_proxy_cvd": "allow_proxy_cvd",
            }
            enabled = [label for label in forbidden.values() if _enabled(values.get(label))]
            if enabled:
                raise StartupError(f"unsafe live settings enabled: {enabled}")

        required = (
            "account_id",
            "exchange",
            "database_path",
            "evidence_policy",
            "config_fingerprint",
        )
        missing = [key for key in required if not values.get(key)]
        if missing:
            raise StartupError(f"missing runtime config: {missing}")

        raw_risk_policy = values.get("risk_policy", {})
        if not isinstance(raw_risk_policy, Mapping):
            raise StartupError("risk_policy must be a mapping")
        raw_capabilities = values.get("broker_capabilities", ())
        if isinstance(raw_capabilities, (str, bytes)):
            raise StartupError("broker_capabilities must be a collection of names")

        return cls(
            mode=mode,  # type: ignore[arg-type]
            account_id=str(values["account_id"]),
            exchange=str(values["exchange"]).strip().upper(),
            database_path=Path(str(values["database_path"])),
            evidence_policy=str(values["evidence_policy"]).strip().upper(),
            risk_policy=MappingProxyType(dict(raw_risk_policy)),
            broker_capabilities=frozenset(str(item) for item in raw_capabilities),
            config_fingerprint=str(values["config_fingerprint"]),
            runtime_engine=runtime_engine,  # type: ignore[arg-type]
        )
