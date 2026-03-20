"""Application configuration loaded from environment variables."""

import os
from pathlib import Path
from typing import Any, List
import yaml

from pydantic import BaseModel, Field, field_validator
from shared.config import SharedSettings

# Load market config
market_config_path = Path(__file__).resolve().parent / "market_config.yaml"
market_config = {}
if market_config_path.exists():
    with open(market_config_path, "r") as f:
        market_config = yaml.safe_load(f).get("markets", {})


class AMTThresholds(BaseModel):
    """AMT threshold configuration with validation."""
    aggression_sigma: float = Field(default=2.5, ge=0.5, le=5.0)
    displacement_multiplier: float = Field(default=1.5, ge=0.5, le=3.0)
    balance_ratio_threshold: float = Field(default=0.70, ge=0.0, le=1.0)


class LLMConfig(BaseModel):
    """LLM inference configuration with validation."""
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    entry_temperature: float = Field(default=0.4, ge=0.0, le=2.0)
    overseer_temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    max_new_tokens: int = Field(default=120, ge=50, le=2048)
    timeout_seconds: float = Field(default=15.0, ge=5.0, le=120.0)


class ScannerConfig(BaseModel):
    """Scanner configuration with validation."""
    mode: str = Field(default="nse_options")
    top_n: int = Field(default=10, ge=1, le=50)
    strikes_around_atm: int = Field(default=2, ge=1, le=10)
    expiry_index: int = Field(default=0, ge=0, le=4)


class Settings(SharedSettings):
    """
    Main application settings.
    Inherits shared settings (Dhans, Environment) from the shared layer.
    """
    
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3030",
        "http://127.0.0.1:3030",
        "http://localhost:3090",
        "http://127.0.0.1:3090",
        "http://localhost:5190",
        "http://127.0.0.1:5190",
    ]

    # Computed scanner settings
    SCANNER_MODE: str = Field(default="mcx_options")
    DEFAULT_SYMBOL: str = Field(default="CRUDEOIL 20 MAR 6500 CALL")
    DHAN_SYMBOLS: Any = Field(default=["CRUDEOIL", "NATURALGAS"])
    SCANNER_UNDERLYING: str = Field(default="CRUDEOIL")
    SCANNER_UNDERLYINGS: Any = Field(default=["CRUDEOIL", "NATURALGAS"])
    SCANNER_OPTION_TYPE: str = Field(default="")
    SCANNER_EXPIRY_INDEX: int = Field(default=0)
    SCANNER_TOP_N: int = Field(default=3)  # Top 3 contracts only (scalping-optimized)
    STRIKES_AROUND_ATM: int = Field(default=2)

    # AMT thresholds
    AGGRESSION_SIGMA: float = Field(default=2.5)
    DISPLACEMENT_MULTIPLIER: float = Field(default=1.5)
    BALANCE_RATIO_THRESHOLD: float = Field(default=0.70)

    # Risk & Execution
    SLIPPAGE_PCT: float = Field(default=0.0005)

    # Trading settings
    PORT: int = Field(default=9090)
    STREAM_INTERVAL: str = Field(default="5m")
    TICK_POLL_SECONDS: float = Field(default=5.0)
    ALLOW_SHORT: bool = Field(default=False)
    LLM_EXECUTION_ENABLED: bool = Field(default=False)
    PLAYBOOK_GUARD_MAX_REJECTIONS: int = Field(default=3)
    EXPLAINABILITY_ALERT_MIN_TRADES: int = Field(default=3)
    EXPLAINABILITY_MIN_DRIVER_COVERAGE_PCT: float = Field(default=90.0)
    EXPLAINABILITY_MIN_AGGRESSION_DRIVER_PCT: float = Field(default=75.0)
    
    # Fabio Gap #13: Place SL 1-2 ticks INSIDE the aggressive print cluster
    SL_INSIDE_CLUSTER: bool = Field(default=True)

    # LLM Inference Paths
    LLM_BASE_MODEL_PATH: str = Field(default="")
    LLM_ADAPTER_PATH: str = Field(default="")

    # LLM Backend Selection
    LLM_BACKEND: str = Field(default="mlx")
    MLX_MODEL_PATH: str = Field(default=str(Path(__file__).resolve().parent.parent / "models" / "glassytrade-qwen-mlx-fused"))
    MLX_ADAPTER_PATH: str = Field(default="")
    REASONING_MODEL_PATH: str = Field(default=str(Path(__file__).resolve().parent.parent / "models" / "reasoning-model"))
    REASONING_MODEL_ID: str = Field(default="Jackrong/Qwen3.5-4B-Claude-4.6-Opus-Reasoning-Distilled")
    REASONING_ADAPTER_PATH: str = Field(default="")

    # LLM Inference Settings
    LLM_INSTRUCTION: str = Field(
        default="You are READING the auction using Fabio Valentini's AMT methodology..."
    )
    LLM_TEMPERATURE: float = Field(default=0.3)
    LLM_ENTRY_TEMPERATURE: float = Field(default=0.4)
    LLM_OVERSEER_TEMPERATURE: float = Field(default=0.3)
    LLM_MAX_NEW_TOKENS: int = Field(default=120)
    LLM_TIMEOUT_SECONDS: float = Field(default=15.0)

    # Notifications
    TELEGRAM_BOT_TOKEN: str = Field(default="")
    TELEGRAM_CHAT_ID: str = Field(default="")

    @field_validator("CORS_ORIGINS", "DHAN_SYMBOLS", "SCANNER_UNDERLYINGS", mode="before")
    @classmethod
    def assemble_list_from_str(cls, v: Any) -> List[str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, list):
            return v
        return v

    def validate_all(self) -> List[str]:
        errors: List[str] = []
        if not self.DHAN_CLIENT_ID:
            errors.append("DHAN_CLIENT_ID is empty")
        if not self.DHAN_ACCESS_TOKEN:
            errors.append("DHAN_ACCESS_TOKEN is empty")
        return errors


settings = Settings()
