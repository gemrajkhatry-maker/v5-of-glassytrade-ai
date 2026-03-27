"""Application configuration loaded from environment variables.

This module now delegates to the consolidated configuration module
for a single source of truth. Backward compatibility is maintained
by exposing the same Settings class interface.
"""

import os
from pathlib import Path
from typing import Any, List

from pydantic import Field, field_validator
from shared.config import SharedSettings

# Import consolidated configuration
from config.consolidated import get_config, ConsolidatedConfig


class Settings(SharedSettings):
    """
    Main application settings.
    Inherits shared settings (Dhans, Environment) from the shared layer.

    This class now delegates to the consolidated configuration module
    for a single source of truth. Backward compatibility is maintained.
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
    SCANNER_TOP_N: int = Field(default=3)  # Total limit
    SCANNER_TOP_PER_UNDERLYING: int = Field(default=2)  # Per underlying limit
    STRIKES_AROUND_ATM: int = Field(default=2)

    # AMT thresholds
    AGGRESSION_SIGMA: float = Field(default=2.5)
    DISPLACEMENT_MULTIPLIER: float = Field(default=1.5)
    BALANCE_RATIO_THRESHOLD: float = Field(default=0.55)

    # Risk & Execution
    SLIPPAGE_PCT: float = Field(default=0.0005)

    # Feature flags
    RISK_TIER_ENGINE: bool = Field(default=False)
    SHORT_SIGNALS_ENABLED: bool = Field(default=True)
    LLM_PRE_CANDLE_ADVISORY: bool = Field(default=True)
    REALISTIC_COST_MODEL: bool = Field(default=False)
    SCALP_ENGINE_ENABLED: bool = Field(default=False)

    # Trading settings
    PORT: int = Field(default=9090)
    STREAM_INTERVAL: str = Field(default="5m")
    TICK_POLL_SECONDS: float = Field(default=5.0)
    ALLOW_SHORT: bool = Field(
        default=True, description="Short entries enabled — Direction-agnostic AMT mode"
    )
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
    MLX_MODEL_PATH: str = Field(
        default=str(
            Path(__file__).resolve().parent.parent
            / "models"
            / "glassytrade-qwen-mlx-fused"
        )
    )
    MLX_ADAPTER_PATH: str = Field(default="")
    REASONING_MODEL_PATH: str = Field(
        default=str(
            Path(__file__).resolve().parent.parent / "models" / "reasoning-model"
        )
    )
    REASONING_MODEL_ID: str = Field(
        default="Jackrong/Qwen3.5-4B-Claude-4.6-Opus-Reasoning-Distilled"
    )
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

    @field_validator(
        "CORS_ORIGINS", "DHAN_SYMBOLS", "SCANNER_UNDERLYINGS", mode="before"
    )
    @classmethod
    def assemble_list_from_str(cls, v: Any) -> List[str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, list):
            return v
        return v

    # Composite Profile (Gap #4)
    COMPOSITE_SESSION_WINDOW: int = Field(default=5, ge=1, le=10)

    # Pre-Alert System (Gap #6)
    ALERT_PROXIMITY_TICKS: int = Field(default=3, ge=1, le=10)

    def validate_all(self) -> List[str]:
        errors: List[str] = []
        if not self.DHAN_CLIENT_ID:
            errors.append("DHAN_CLIENT_ID is empty")
        if not self.DHAN_ACCESS_TOKEN:
            errors.append("DHAN_ACCESS_TOKEN is empty")
        return errors


settings = Settings()
