"""Pydantic-like settings model with environment variable support."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from enum import Enum
import os
from typing import Any

import yaml

try:
    from pydantic_settings import BaseSettings  # type: ignore
except ImportError:  # pragma: no cover - compatibility path
    from pydantic import BaseModel as BaseSettings  # type: ignore


class SettingsMode(str, Enum):
    DEVELOPMENT = "development"
    PAPER = "paper"
    LIVE = "live"


@dataclass
class BrokerSettings:
    mode: str = "paper"
    testnet: bool = True
    client_id: str | None = None
    access_token: str | None = None


@dataclass
class CostModelSettings:
    enabled: bool = True
    base_slippage_bps: float = 15.0
    stt_pct: float = 0.000625
    exchange_fee_pct: float = 0.000495
    brokerage_per_order: float = 20.0
    gst_pct: float = 0.18
    sebi_pct: float = 0.000001


@dataclass
class RiskSettings:
    risk_per_trade_pct: float = 0.005
    max_daily_loss_pct: float = 0.02
    max_consecutive_losses: int = 3
    max_drawdown_pct: float = 0.03
    max_concurrent_positions: int = 5


@dataclass
class ScannerSettings:
    mode: str = "mcx_options"
    top_n: int = 3
    top_per_underlying: int = 2
    strikes_around_atm: int = 2
    expiry_index: int = 0


class AppSettings(BaseSettings):
    """Application-wide settings loaded from YAML + environment variables."""

    environment: str = SettingsMode.DEVELOPMENT.value
    broker_mode: str = "paper"
    log_level: str = "INFO"
    db_path: str = "glassytrade.db"

    broker: BrokerSettings | None = None
    risk: RiskSettings | None = None
    cost_model: CostModelSettings | None = None
    scanner: ScannerSettings | None = None
    globals: dict[str, Any] | None = None

    # Pydantic compatibility shim for environments where only legacy BaseModel exists.
    # Pydantic v2 uses `model_config`; declaring both `Config` and `model_config`
    # raises a runtime error, so we choose one path only.
    if hasattr(BaseSettings, "model_config"):
        model_config = {"env_prefix": "GLASSYTRADE_", "extra": "ignore"}
    else:
        class Config:
            arbitrary_types_allowed = True

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "AppSettings":
        normalized = dict(values)
        if isinstance(normalized.get("broker"), dict):
            normalized["broker"] = BrokerSettings(**normalized["broker"])
        if isinstance(normalized.get("risk"), dict):
            normalized["risk"] = RiskSettings(**normalized["risk"])
        if isinstance(normalized.get("cost_model"), dict):
            normalized["cost_model"] = CostModelSettings(**normalized["cost_model"])
        if isinstance(normalized.get("scanner"), dict):
            normalized["scanner"] = ScannerSettings(**normalized["scanner"])
        if hasattr(cls, "model_validate"):
            return cls.model_validate(normalized)  # type: ignore[attr-defined]
        return cls(**normalized)  # pragma: no cover

    @classmethod
    def from_yaml_file(
        cls,
        profile: str | None = None,
        *,
        base_path: str | None = None,
    ) -> "AppSettings":
        """Load settings from base.yaml + environment override file.

        Supports profiles: development/dev, paper, live.
        """
        payload = load_app_settings(profile=profile, base_path=base_path)
        return cls.from_dict(payload)


logger = logging.getLogger(__name__)


_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"
_ENV_ALIAS: dict[str, str] = {
    "dev": "development",
    "development": "development",
    "paper": "paper",
    "live": "live",
}


def _resolve_profile(profile: str | None = None) -> str:
    env = (
        str(profile or os.getenv("GLASSYTRADE_ENV") or os.getenv("APP_PROFILE") or SettingsMode.DEVELOPMENT.value)
        .strip()
        .lower()
    )
    return _ENV_ALIAS.get(env, SettingsMode.DEVELOPMENT.value)


def _read_yaml_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        logger.debug("YAML config not found: %s", path)
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        logger.debug("YAML config was not a mapping: %s", path)
        return {}
    return data


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_app_settings(
    profile: str | None = None,
    *,
    base_path: str | None = None,
) -> dict[str, Any]:
    """Load a plain settings dict from base.yaml + selected environment yaml."""
    base_dir = Path(base_path) if base_path else _CONFIG_DIR
    normalized = _resolve_profile(profile)
    base = _read_yaml_file(base_dir / "base.yaml")
    override = _read_yaml_file(base_dir / "environments" / f"{normalized}.yaml")
    merged = _deep_merge(base, override)
    merged["environment"] = merged.get("environment", normalized)
    merged["broker_mode"] = (
        merged.get("broker_mode")
        or merged.get("broker", {}).get("mode")
        or os.getenv("BROKER_MODE", "paper")
    )
    merged["log_level"] = (
        merged.get("log_level")
        or os.getenv("LOG_LEVEL", merged.get("system", {}).get("log_level", "INFO"))
    )
    merged["db_path"] = (
        os.getenv("GLASSYTRADE_DB_PATH", os.getenv("DB_PATH", merged.get("db_path", "glassytrade.db")))
    )
    return merged


def resolve_app_profile() -> str:
    return _resolve_profile(None)

