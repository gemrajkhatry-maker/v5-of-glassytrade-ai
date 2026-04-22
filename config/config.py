from pydantic import BaseModel, Field, validator
from typing import List, Dict, Any, Optional
import os
from datetime import timedelta


class TradingConfig(BaseModel):
    """Trading configuration."""

    default_symbol: str = "CRUDEOIL 20 MAR 6500 CALL"
    stream_interval: str = "5m"
    tick_poll_seconds: float = 5.0
    allow_short: bool = False
    scanner_top_n: int = 3
    scanner_top_per_underlying: int = 2
    strikes_around_atm: int = 2
    max_daily_losses: int = 3
    cooldown_seconds: float = 30.0
    partial_tp_pct: float = 0.50
    partial_size_pct: float = 0.50
    trail_activation_r: float = 1.0
    trail_step_pct: float = 0.20
    stop_loss_pct: float = 0.005
    take_profit_pct: float = 0.015
    max_hold_seconds: float = 1800.0

    @validator("stream_interval")
    def validate_interval(cls, v):
        if v not in ["1m", "5m", "15m", "1h"]:
            raise ValueError("Invalid interval")
        return v


class ScannerConfig(BaseModel):
    """Scanner configuration."""

    mode: str = "nse_options"
    top_n: int = 10
    strikes_around_atm: int = 2
    expiry_index: int = 0
    min_premium: float = 20.0
    max_premium: float = 800.0
    min_oi: int = 100
    max_spread_pct: float = 2.5

    @validator("mode")
    def validate_mode(cls, v):
        if v not in ["nse_options", "mcx_options"]:
            raise ValueError("Invalid scanner mode")
        return v


class LLMConfig(BaseModel):
    """LLM configuration."""

    backend: str = "mlx"
    temperature: float = 0.3
    max_new_tokens: int = 120
    max_total_tokens: int = 4000
    top_p: float = 0.9
    frequency_penalty: float = 0.5

    @validator("backend")
    def validate_backend(cls, v):
        if v not in ["mlx", "openai", "anthropic"]:
            raise ValueError("Invalid LLM backend")
        return v


class RLConfig(BaseModel):
    """Reinforcement learning configuration."""

    enabled: bool = False
    model_path: Optional[str] = None
    training: bool = False


class Configuration(BaseModel):
    """Main application configuration."""

    env: str = "production"
    trading: TradingConfig = TradingConfig()
    scanner: ScannerConfig = ScannerConfig()
    llm: LLMConfig = LLMConfig()
    rl: RLConfig = RLConfig()
    debug: bool = False

    @validator("env")
    def validate_env(cls, v):
        if v not in ["production", "staging", "development", "testing"]:
            raise ValueError("Invalid environment")
        return v

    @classmethod
    def from_env(cls) -> "Configuration":
        """Load configuration from environment variables."""
        env = os.getenv("APP_ENV", "production")
        config_path = os.getenv("CONFIG_PATH", "config/config.yaml")

        # For now, load defaults and override with env vars
        config = cls(env=env)

        # Override with environment variables
        for field in config.schema()["properties"]:
            env_var = f"APP_{field.upper()}"
            if env_var in os.environ:
                setattr(config, field, os.environ[env_var])

        return config
