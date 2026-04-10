"""AMT Live Trading System — Pydantic settings loaded from environment variables.

All required vars validated at startup. Missing required var → clear error.
"""

from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Dhan Broker ───────────────────────────────────────────────
    DHAN_ACCESS_TOKEN: str = Field(..., description="Dhan API access token")
    DHAN_CLIENT_ID: str = Field(..., description="Dhan client ID")

    # ── Trading Configuration ─────────────────────────────────────
    CAPITAL: float = Field(
        default=5_000_000.0, ge=100_000, description="Trading capital in INR"
    )
    EXCHANGE: str = Field(
        default="NSE",
        pattern="^(NSE|MCX)$",
        description="Exchange: NSE or MCX",
    )
    SYMBOLS: str = Field(
        default="NIFTY,BANKNIFTY",
        description="Comma-separated underlying symbols to trade",
    )
    UNDERLYINGS: str = Field(
        default="",
        description="Comma-separated underlying futures for AMT analysis "
        "(empty = auto-detect from SYMBOLS)",
    )

    # ── Risk Parameters ───────────────────────────────────────────
    RISK_PER_TRADE_PCT: float = Field(
        default=1.0, gt=0, le=5, description="Max risk per trade (% of capital)"
    )
    MAX_DAILY_LOSS_PCT: float = Field(
        default=3.0, gt=0, le=10, description="Max daily loss (% of capital)"
    )
    MAX_CONSECUTIVE_LOSSES: int = Field(
        default=5, ge=1, le=10, description="Max consecutive losses before halt"
    )
    CIRCUIT_BREAKER_COOLDOWN_MINUTES: int = Field(
        default=30, ge=5, description="Cooldown after circuit breaker triggers (min)"
    )
    MAX_POSITIONS_PER_SYMBOL: int = Field(
        default=3, ge=1, le=10, description="Max simultaneous positions per symbol"
    )

    # ── Execution Mode ────────────────────────────────────────────
    LIVE_TRADING: bool = Field(
        default=False,
        description="If false, all orders go to paper broker",
    )
    PAPER_SLIPPAGE_BPS: int = Field(
        default=10, ge=0, le=100, description="Paper broker slippage (basis points)"
    )
    PAPER_COMMISSION_PER_TRADE: float = Field(
        default=50.0, ge=0, description="Paper broker commission per trade (INR)"
    )

    # ── AMT Thresholds (overridable; defaults in constants.py) ────
    AGGRESSION_SIGMA_THRESHOLD: float = Field(
        default=2.5, gt=0, description="Aggression score threshold (sigma)"
    )
    LVN_THRESHOLD: float = Field(
        default=0.15, gt=0, lt=1, description="LVN = < X% of mean volume"
    )
    HVN_THRESHOLD: float = Field(
        default=2.0, gt=0, description="HVN = > X× mean volume"
    )
    VALUE_AREA_PCT: float = Field(
        default=0.70, gt=0, lt=1, description="Value area percentage"
    )
    DISPLACEMENT_MULTIPLIER: float = Field(
        default=1.5, gt=0, description="Displacement = range > X× ATR"
    )

    # ── Options Parameters ────────────────────────────────────────
    OPTION_STRIKE_PREF: str = Field(
        default="ATM",
        pattern="^(ATM|ITM)$",
        description="Strike preference for options selection",
    )
    MIN_OPTION_OI: int = Field(
        default=10_000, ge=0, description="Minimum OI for option liquidity filter"
    )
    MAX_OPTION_SPREAD_BPS: int = Field(
        default=50, ge=0, description="Max bid-ask spread for options (basis points)"
    )
    THETA_COST_MAX_PCT: float = Field(
        default=20.0, gt=0, le=100,
        description="Max theta cost as % of expected profit",
    )

    # ── Logging ───────────────────────────────────────────────────
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")
    LOG_DIR: str = Field(default="logs", description="Log directory")

    # ── Server ────────────────────────────────────────────────────
    HOST: str = Field(default="0.0.0.0", description="Bind address")
    PORT: int = Field(default=8001, ge=1, le=65535, description="Port to bind")
    FRONTEND_URL: str = Field(
        default="http://localhost:5174", description="Frontend URL for CORS"
    )

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @property
    def symbols_list(self) -> list[str]:
        return [s.strip() for s in self.SYMBOLS.split(",") if s.strip()]

    @property
    def underlyings_list(self) -> list[str]:
        return [s.strip() for s in self.UNDERLYINGS.split(",") if s.strip()]


# Singleton
settings = Settings()
