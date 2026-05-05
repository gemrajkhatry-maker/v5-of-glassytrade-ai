"""Pydantic-like settings model with environment variable support."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

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

    # Pydantic compatibility shim for environments where only legacy BaseModel exists
    class Config:
        arbitrary_types_allowed = True

    if hasattr(BaseSettings, "model_config"):
        model_config = {"env_prefix": "GLASSYTRADE_", "extra": "ignore"}

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "AppSettings":
        if hasattr(cls, "model_validate"):
            return cls.model_validate(values)  # type: ignore[attr-defined]
        return cls(**values)  # pragma: no cover

