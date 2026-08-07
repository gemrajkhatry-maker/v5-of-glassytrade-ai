"""Consolidated configuration management.

This module provides a single source of truth for all configuration,
eliminating scattered configuration across multiple files.

Architecture:
  - TradingConfig: Trading-specific settings
  - LLMConfig: LLM inference settings
  - RiskConfig: Risk management settings
  - ConsolidatedConfig: Main configuration container
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

import yaml
from pydantic import BaseModel, Field, field_validator


class TradingConfig(BaseModel):
    """Trading-specific configuration."""

    default_symbol: str = Field(
        default="CRUDEOIL 20 MAR 6500 CALL", description="Default trading symbol"
    )
    stream_interval: str = Field(
        default="5m", description="Candle interval for streaming"
    )
    tick_poll_seconds: float = Field(
        default=5.0, ge=1.0, le=60.0, description="Tick polling interval in seconds"
    )
    allow_short: bool = Field(
        default=False, description="Whether to allow short positions"
    )
    max_risk_per_trade: float = Field(
        default=0.02,
        ge=0.001,
        le=0.10,
        description="Maximum risk per trade as percentage of equity",
    )
    scanner_mode: str = Field(
        default="mcx_options",
        description="Scanner mode (nse, nse_options, mcx_options)",
    )
    scanner_top_n: int = Field(
        default=3, ge=1, le=20, description="Number of top contracts to scan"
    )
    scanner_top_per_underlying: int = Field(
        default=2, ge=1, le=10, description="Number of top contracts per underlying"
    )
    strikes_around_atm: int = Field(
        default=2, ge=1, le=10, description="Number of strikes around ATM to consider"
    )


class LLMConfig(BaseModel):
    """LLM inference configuration."""

    backend: str = Field(
        default="mlx", description="LLM backend (mlx, llama_cpp, etc.)"
    )
    temperature: float = Field(
        default=0.3, ge=0.0, le=2.0, description="Default LLM temperature"
    )
    entry_temperature: float = Field(
        default=0.4, ge=0.0, le=2.0, description="LLM temperature for entry decisions"
    )
    overseer_temperature: float = Field(
        default=0.3,
        ge=0.0,
        le=2.0,
        description="LLM temperature for overseer decisions",
    )
    max_new_tokens: int = Field(
        default=120, ge=50, le=2048, description="Maximum new tokens for LLM generation"
    )
    timeout_seconds: float = Field(
        default=15.0, ge=5.0, le=120.0, description="LLM inference timeout in seconds"
    )
    model_path: str = Field(default="", description="Path to LLM model")
    adapter_path: str = Field(default="", description="Path to LLM adapter")
    reasoning_model_path: str = Field(default="", description="Path to reasoning model")


class RiskConfig(BaseModel):
    """Risk management configuration."""

    max_daily_drawdown: float = Field(
        default=0.05,
        ge=0.01,
        le=0.20,
        description="Maximum daily drawdown as percentage",
    )
    max_consecutive_losses: int = Field(
        default=3, ge=1, le=10, description="Maximum consecutive losses before halt"
    )
    cooldown_seconds: int = Field(
        default=300,
        ge=60,
        le=3600,
        description="Cooldown period after stop-out in seconds",
    )
    slippage_pct: float = Field(
        default=0.0005, ge=0.0001, le=0.01, description="Expected slippage percentage"
    )
    playbook_guard_max_rejections: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum playbook guard rejections before tripping",
    )
    explainability_alert_min_trades: int = Field(
        default=3,
        ge=1,
        le=20,
        description="Minimum trades before explainability alerts",
    )
    explainability_min_driver_coverage_pct: float = Field(
        default=90.0,
        ge=50.0,
        le=100.0,
        description="Minimum feature driver coverage percentage",
    )
    explainability_min_aggression_driver_pct: float = Field(
        default=75.0,
        ge=50.0,
        le=100.0,
        description="Minimum aggression driver percentage",
    )


class AMTConfig(BaseModel):
    """AMT threshold configuration."""

    aggression_sigma: float = Field(
        default=2.5, ge=0.5, le=5.0, description="Aggression sigma threshold"
    )
    displacement_multiplier: float = Field(
        default=1.5, ge=0.5, le=3.0, description="Displacement multiplier"
    )
    balance_ratio_threshold: float = Field(
        default=0.55, ge=0.0, le=1.0, description="Balance ratio threshold"
    )
    composite_session_window: int = Field(
        default=5, ge=1, le=10, description="Composite session window size"
    )
    alert_proximity_ticks: int = Field(
        default=3, ge=1, le=10, description="Alert proximity in ticks"
    )


class NotificationConfig(BaseModel):
    """Notification configuration."""

    telegram_bot_token: str = Field(default="", description="Telegram bot token")
    telegram_chat_id: str = Field(default="", description="Telegram chat ID")


class ScannerConfig(BaseModel):
    """Scanner configuration."""

    mode: str = Field(default="nse_options", description="Scanner mode")
    top_n: int = Field(default=10, ge=1, le=50, description="Top N contracts to scan")
    strikes_around_atm: int = Field(
        default=2, ge=1, le=10, description="Strikes around ATM"
    )
    expiry_index: int = Field(default=0, ge=0, le=4, description="Expiry index")


class FeatureFlags(BaseModel):
    """Feature flag configuration."""

    allow_short: bool = Field(default=True, description="Allow short positions")
    short_signals_enabled: bool = Field(default=True, description="Enable short signals")
    scalp_engine_enabled: bool = Field(default=False, description="Enable scalping engine")
    scalp_ib_breakout: bool = Field(default=False, description="Enable IB breakout scalping")
    risk_tier_engine: bool = Field(default=True, description="Use risk tier engine")
    llm_execution_enabled: bool = Field(default=True, description="Enable LLM execution")
    llm_pre_candle_advisory: bool = Field(default=True, description="Enable LLM pre-candle advisory")
    llm_post_trade: bool = Field(default=True, description="Enable LLM post-trade analysis")
    llm_overseer: bool = Field(default=True, description="Enable LLM overseer")
    realistic_cost_model: bool = Field(default=True, description="Use realistic cost model")


class ConsolidatedConfig(BaseModel):
    """Consolidated application configuration.

    This is the single source of truth for all configuration.
    All modules should import from this module instead of
    implementing their own configuration logic.
    """

    # Core settings
    trading: TradingConfig = Field(default_factory=TradingConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    amt: AMTConfig = Field(default_factory=AMTConfig)
    notifications: NotificationConfig = Field(default_factory=NotificationConfig)
    scanner: ScannerConfig = Field(default_factory=ScannerConfig)
    feature_flags: FeatureFlags = Field(default_factory=FeatureFlags)

    # CORS settings
    cors_origins: List[str] = Field(
        default=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3030",
            "http://127.0.0.1:3030",
            "http://localhost:3090",
            "http://127.0.0.1:3090",
            "http://localhost:5190",
            "http://127.0.0.1:5190",
        ],
        description="Allowed CORS origins",
    )

    # Exchange settings
    default_exchange: str = Field(default="MCX", description="Default exchange")
    dhan_symbols: List[str] = Field(
        default=["CRUDEOIL", "NATURALGAS"], description="Dhan symbols to trade"
    )
    scanner_underlyings: List[str] = Field(
        default=["CRUDEOIL", "NATURALGAS"], description="Scanner underlyings"
    )

    # Dhan API credentials
    dhan_client_id: str = Field(default="", description="Dhan client ID")
    dhan_access_token: str = Field(default="", description="Dhan access token")

    # Server settings
    port: int = Field(default=9090, ge=1000, le=65535, description="Server port")

    @field_validator(
        "cors_origins", "dhan_symbols", "scanner_underlyings", mode="before"
    )
    @classmethod
    def assemble_list_from_str(cls, v: Any) -> List[str]:
        """Assemble list from string (comma-separated)."""
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, list):
            return v
        return v

    @classmethod
    def from_env(cls) -> ConsolidatedConfig:
        """Load configuration from environment variables.

        Environment variables:
          - DEFAULT_SYMBOL: Default trading symbol
          - STREAM_INTERVAL: Candle interval
          - ALLOW_SHORT: Allow short positions (true/false)
          - SCANNER_MODE: Scanner mode
          - SCANNER_TOP_N: Number of top contracts
          - LLM_BACKEND: LLM backend
          - LLM_TEMPERATURE: LLM temperature
          - LLM_TIMEOUT_SECONDS: LLM timeout
          - DHAN_CLIENT_ID: Dhan client ID
          - DHAN_ACCESS_TOKEN: Dhan access token
          - DEFAULT_EXCHANGE: Default exchange
          - TELEGRAM_BOT_TOKEN: Telegram bot token
          - TELEGRAM_CHAT_ID: Telegram chat ID
        """
        return cls(
            trading=TradingConfig(
                default_symbol=os.getenv("DEFAULT_SYMBOL", "CRUDEOIL 20 MAR 6500 CALL"),
                stream_interval=os.getenv("STREAM_INTERVAL", "5m"),
                tick_poll_seconds=float(os.getenv("TICK_POLL_SECONDS", "5.0")),
                allow_short=os.getenv("ALLOW_SHORT", "false").lower() == "true",
                scanner_mode=os.getenv("SCANNER_MODE", "mcx_options"),
                scanner_top_n=int(os.getenv("SCANNER_TOP_N", "3")),
                scanner_top_per_underlying=int(
                    os.getenv("SCANNER_TOP_PER_UNDERLYING", "2")
                ),
                strikes_around_atm=int(os.getenv("STRIKES_AROUND_ATM", "2")),
            ),
            llm=LLMConfig(
                backend=os.getenv("LLM_BACKEND", "mlx"),
                temperature=float(os.getenv("LLM_TEMPERATURE", "0.3")),
                entry_temperature=float(os.getenv("LLM_ENTRY_TEMPERATURE", "0.4")),
                overseer_temperature=float(
                    os.getenv("LLM_OVERSEER_TEMPERATURE", "0.3")
                ),
                max_new_tokens=int(os.getenv("LLM_MAX_NEW_TOKENS", "120")),
                timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "15.0")),
                model_path=os.getenv("MLX_MODEL_PATH", ""),
                adapter_path=os.getenv("MLX_ADAPTER_PATH", ""),
                reasoning_model_path=os.getenv("REASONING_MODEL_PATH", ""),
            ),
            risk=RiskConfig(
                max_daily_drawdown=float(os.getenv("MAX_DAILY_DRAWDOWN", "0.05")),
                max_consecutive_losses=int(os.getenv("MAX_CONSECUTIVE_LOSSES", "3")),
                cooldown_seconds=int(os.getenv("COOLDOWN_SECONDS", "300")),
                slippage_pct=float(os.getenv("SLIPPAGE_PCT", "0.0005")),
                playbook_guard_max_rejections=int(
                    os.getenv("PLAYBOOK_GUARD_MAX_REJECTIONS", "3")
                ),
            ),
            amt=AMTConfig(
                aggression_sigma=float(os.getenv("AGGRESSION_SIGMA", "2.5")),
                displacement_multiplier=float(
                    os.getenv("DISPLACEMENT_MULTIPLIER", "1.5")
                ),
                balance_ratio_threshold=float(
                    os.getenv("BALANCE_RATIO_THRESHOLD", "0.55")
                ),
                composite_session_window=int(
                    os.getenv("COMPOSITE_SESSION_WINDOW", "5")
                ),
                alert_proximity_ticks=int(os.getenv("ALERT_PROXIMITY_TICKS", "3")),
            ),
            notifications=NotificationConfig(
                telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
                telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
            ),
            cors_origins=os.getenv(
                "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
            ).split(","),
            default_exchange=os.getenv("DEFAULT_EXCHANGE", "MCX"),
            dhan_symbols=os.getenv("DHAN_SYMBOLS", "CRUDEOIL,NATURALGAS").split(","),
            scanner_underlyings=os.getenv(
                "SCANNER_UNDERLYINGS", "CRUDEOIL,NATURALGAS,GOLDM,SILVERM"
            ).split(","),
            dhan_client_id=os.getenv("DHAN_CLIENT_ID", ""),
            dhan_access_token=os.getenv("DHAN_ACCESS_TOKEN", ""),
            port=int(os.getenv("PORT", "9090")),
        )

    @classmethod
    def from_unified(cls) -> ConsolidatedConfig:
        """Load env + secrets (``from_env``), then overlay YAML strategy via ``ModeConfigLoader``.

        Keeps API keys, MLX paths, PORT, and other env-only fields from ``from_env`` while
        aligning scanner, exchange, LLM timeouts/temperatures, risk, and AMT with
        ``strategies/{GLASSYTRADE_STRATEGY}.yaml`` — the same source as ``app.config.settings``.
        """
        import logging

        log = logging.getLogger(__name__)
        base = cls.from_env()
        try:
            from config.mode_config import ModeConfigLoader

            mode = ModeConfigLoader.load_from_env()
        except Exception as exc:
            log.warning(
                "Unified config unavailable, using env-only: %s", exc, exc_info=True
            )
            return base

        sc = mode.scanner_config
        feat = dict(sc.get("feature_flags") or {})
        amt_src = dict(sc.get("amt_thresholds") or {})

        trading = base.trading.model_copy(
            update={
                "scanner_mode": sc.get("mode", base.trading.scanner_mode),
                "scanner_top_n": int(sc.get("top_n", base.trading.scanner_top_n)),
                "scanner_top_per_underlying": int(
                    sc.get("top_per_underlying", base.trading.scanner_top_per_underlying)
                ),
                "strikes_around_atm": int(
                    sc.get("strikes_around_atm", base.trading.strikes_around_atm)
                ),
                "allow_short": bool(feat.get("allow_short", base.trading.allow_short)),
                "stream_interval": f"{mode.system_config.candle_timeframe_minutes}m",
                "max_risk_per_trade": float(mode.system_config.risk.risk_per_trade_pct),
            }
        )

        sys_llm = mode.system_config.llm
        llm_temp_raw = os.getenv("LLM_TEMPERATURE")
        default_mid = (
            float(sys_llm.temperature_entry) + float(sys_llm.temperature_overseer)
        ) / 2.0
        llm = base.llm.model_copy(
            update={
                "temperature": float(llm_temp_raw)
                if llm_temp_raw is not None and llm_temp_raw.strip() != ""
                else default_mid,
                "entry_temperature": float(sys_llm.temperature_entry),
                "overseer_temperature": float(sys_llm.temperature_overseer),
                "max_new_tokens": int(sys_llm.max_tokens),
                "timeout_seconds": float(sys_llm.timeout_seconds),
            }
        )

        sr = mode.system_config.risk
        risk = base.risk.model_copy(
            update={
                "max_daily_drawdown": float(sr.max_daily_loss_pct),
                "max_consecutive_losses": int(sr.max_consecutive_losses),
            }
        )

        amt = base.amt.model_copy(
            update={
                "aggression_sigma": float(
                    amt_src.get("aggression_sigma", base.amt.aggression_sigma)
                ),
                "displacement_multiplier": float(
                    amt_src.get("displacement_multiplier", base.amt.displacement_multiplier)
                ),
                "balance_ratio_threshold": float(
                    amt_src.get("balance_ratio_threshold", base.amt.balance_ratio_threshold)
                ),
            }
        )

        scanner = base.scanner.model_copy(
            update={
                "mode": sc.get("mode", base.scanner.mode),
                "top_n": int(sc.get("top_n", base.scanner.top_n)),
                "strikes_around_atm": int(
                    sc.get("strikes_around_atm", base.scanner.strikes_around_atm)
                ),
                "expiry_index": int(sc.get("expiry_index", base.scanner.expiry_index)),
            }
        )

        sym = list(mode.active_symbols) if mode.active_symbols else base.dhan_symbols
        und = (
            list(mode.scanner_underlyings)
            if mode.scanner_underlyings
            else base.scanner_underlyings
        )

        # Update feature flags from scanner config
        feature_flags = base.feature_flags.model_copy(
            update={
                "allow_short": bool(feat.get("allow_short", base.feature_flags.allow_short)),
                "short_signals_enabled": bool(feat.get("short_signals_enabled", base.feature_flags.short_signals_enabled)),
                "scalp_engine_enabled": bool(feat.get("scalp_engine_enabled", base.feature_flags.scalp_engine_enabled)),
                "scalp_ib_breakout": bool(feat.get("scalp_ib_breakout", base.feature_flags.scalp_ib_breakout)),
                "risk_tier_engine": bool(feat.get("risk_tier_engine", base.feature_flags.risk_tier_engine)),
                "llm_pre_candle_advisory": bool(feat.get("llm_pre_candle_advisory", base.feature_flags.llm_pre_candle_advisory)),
                "llm_post_trade": bool(feat.get("llm_post_trade", base.feature_flags.llm_post_trade)),
                "llm_overseer": bool(feat.get("llm_overseer", base.feature_flags.llm_overseer)),
                "realistic_cost_model": bool(feat.get("realistic_cost_model", base.feature_flags.realistic_cost_model)),
            }
        )

        return base.model_copy(
            update={
                "trading": trading,
                "llm": llm,
                "risk": risk,
                "amt": amt,
                "scanner": scanner,
                "feature_flags": feature_flags,
                "default_exchange": mode.default_exchange,
                "dhan_symbols": sym,
                "scanner_underlyings": und,
            }
        )

    @classmethod
    def from_yaml(
        cls,
        path: str = "market_config.yaml",
        env_override: bool = True,
    ) -> ConsolidatedConfig:
        """Load configuration from YAML file, merged with env vars.

        Args:
            path: Path to YAML configuration file (relative to app/ dir).
            env_override: If True, env vars override YAML values.

        Returns:
            ConsolidatedConfig instance with exchange-specific configs parsed.
        """
        # Resolve YAML path — try relative to app/ then relative to config/
        candidates = [
            Path(__file__).resolve().parent.parent / "app" / path,
            Path(__file__).resolve().parent / path,
            Path(path),
        ]

        market_config: Dict[str, Any] = {}
        for candidate in candidates:
            if candidate.exists():
                with open(candidate, "r") as f:
                    raw = yaml.safe_load(f) or {}
                    market_config = raw.get("markets", {})
                break

        # Build base config from env
        base = cls.from_env() if env_override else cls()

        # Parse exchange-specific overrides from YAML
        exchange_configs: Dict[str, Any] = {}
        for exchange_key, raw_cfg in market_config.items():
            exchange_name = exchange_key.upper()
            # Map NFO → NSE for consistency
            if exchange_name == "NFO":
                exchange_name = "NSE"
            exchange_configs[exchange_name] = dict(raw_cfg) if raw_cfg else {}

        base._exchange_configs = exchange_configs
        return base

    def get_exchange_config_dict(self, exchange: str) -> Dict[str, Any]:
        """Get raw YAML dict for a specific exchange.

        Returns empty dict if no YAML config exists for this exchange.
        """
        if not hasattr(self, "_exchange_configs"):
            return {}
        return self._exchange_configs.get(exchange.upper(), {})


# Singleton instance
_config: ConsolidatedConfig | None = None


def get_config() -> ConsolidatedConfig:
    """Get the consolidated configuration.

    Loads from YAML first, then env overrides.

    Returns:
        ConsolidatedConfig instance (singleton)
    """
    global _config
    if _config is None:
        _config = ConsolidatedConfig.from_yaml()
    return _config


def set_config(config: ConsolidatedConfig) -> None:
    """Set the consolidated configuration.

    Args:
        config: ConsolidatedConfig instance
    """
    global _config
    _config = config


def get_exchange_config(exchange: str) -> "ExchangeConfig":
    """Get domain ExchangeConfig for a given exchange.

    Bridges consolidated config → domain ExchangeConfig value object.
    Uses YAML overrides when available, falls back to defaults.

    Args:
        exchange: "NSE" or "MCX"

    Returns:
        ExchangeConfig value object
    """
    from quant.contracts.exchange_config import ExchangeConfig as _EC

    cfg = get_config()
    yaml_data = cfg.get_exchange_config_dict(exchange)
    if yaml_data:
        return _EC.from_dict(exchange, yaml_data)
    return _EC.for_exchange(exchange)
