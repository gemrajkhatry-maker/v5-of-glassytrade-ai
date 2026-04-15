"""Backward compatibility adapter - makes old settings object read from YAML.

This allows existing code (25+ files) to continue using:
    from app.config import settings
    
While the actual values come from YAML configuration loaded via GLASSYTRADE_ENV
and GLASSYTRADE_STRATEGY environment variables.

This is a CRITICAL component for zero-downtime migration. It ensures:
1. All existing imports continue to work without modification
2. Configuration values now come from YAML (not .env)
3. Secrets (API keys) still loaded from .env
4. Gradual migration path to dependency injection
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, List, Optional

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


class SettingsAdapter:
    """Adapter that exposes old Settings interface but reads from YAML config.
    
    This adapter maintains 100% backward compatibility with the old Settings class
    while loading configuration from the new YAML-based system.
    
    The configuration hierarchy is:
    1. base.yaml (defaults)
    2. environments/{GLASSYTRADE_ENV}.yaml
    3. strategies/{GLASSYTRADE_STRATEGY}.yaml
    4. .env (secrets only)
    
    Example usage (existing code - no changes needed):
        >>> from app.config import settings
        >>> print(settings.SCANNER_MODE)
        'mcx_options'
        >>> print(settings.DEFAULT_EXCHANGE)
        'MCX'
    """
    
    def __init__(self):
        """Load configuration from YAML based on environment/strategy."""
        # Load secrets from .env first
        self._load_secrets_from_env()
        
        # Load mode config (this loads YAML hierarchy)
        try:
            from config.mode_config import ModeConfigLoader
            # Set config_dir to backend/config/ (not app/config/)
            config_dir = str(Path(__file__).resolve().parent.parent.parent / "config")
            self._mode_config = ModeConfigLoader.load_from_env()
            self._system_config = self._mode_config.system_config
            self._initialized = True
            logger.info(
                "SettingsAdapter initialized: env=%s, strategy=%s",
                self._mode_config.environment,
                self._mode_config.strategy
            )
        except Exception as e:
            logger.error(
                "Failed to load YAML config, falling back to defaults: %s",
                e,
                exc_info=True
            )
            self._mode_config = None
            self._system_config = None
            self._initialized = False
    
    def _load_secrets_from_env(self):
        """Load sensitive data from .env (API keys, tokens)."""
        # Find .env file
        env_path = Path(__file__).resolve().parent.parent.parent.parent / ".env"
        
        if env_path.exists():
            load_dotenv(env_path)
            logger.debug("Loaded .env file: %s", env_path)
        else:
            logger.warning(".env file not found: %s", env_path)
        
        # Store secrets as instance attributes
        self.DHAN_CLIENT_ID = os.getenv("DHAN_CLIENT_ID", "")
        self.DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "")
        self.DHAN_API_KEY = os.getenv("DHAN_API_KEY", "")
        self.DHAN_API_SECRET = os.getenv("DHAN_API_SECRET", "")
        self.OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
        self.TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
        
        # LLM paths
        self.MLX_MODEL_PATH = os.getenv("MLX_MODEL_PATH", "")
        self.MLX_ADAPTER_PATH = os.getenv("MLX_ADAPTER_PATH", "")
        self.LFM25_MODEL_PATH = os.getenv("LFM25_MODEL_PATH", "")
        self.LFM25_ADAPTER_PATH = os.getenv("LFM25_ADAPTER_PATH", "")
        
        # LLM instruction (from env or default)
        self.LLM_INSTRUCTION = os.getenv(
            "LLM_INSTRUCTION",
            "You are an expert market analyst using Fabio Valentini's AMT methodology..."
        )

    def _merged_feature_flags(self) -> dict:
        """Strategy ``feature_flags`` live at YAML root; optional legacy nest under ``scanner``."""
        if not self._mode_config:
            return {}
        if self._mode_config.feature_flags:
            return dict(self._mode_config.feature_flags)
        return dict(self._mode_config.scanner_config.get("feature_flags") or {})

    # =========================================================================
    # Property accessors that read from YAML config
    # =========================================================================

    @property
    def SCANNER_MODE(self) -> str:
        """Get scanner mode from YAML config."""
        if self._mode_config:
            return self._mode_config.scanner_config.get("mode", "mcx_options")
        return os.getenv("SCANNER_MODE", "mcx_options")
    
    @property
    def DEFAULT_EXCHANGE(self) -> str:
        """Get default exchange from YAML config."""
        if self._mode_config:
            return self._mode_config.default_exchange
        return os.getenv("DEFAULT_EXCHANGE", "MCX")
    
    @property
    def DHAN_SYMBOLS(self) -> List[str]:
        """Get DHAN symbols from YAML config."""
        if self._mode_config:
            return self._mode_config.active_symbols
        symbols = os.getenv("DHAN_SYMBOLS", "CRUDEOIL,NATURALGAS")
        return [s.strip() for s in symbols.split(",")]
    
    @property
    def SCANNER_UNDERLYINGS(self) -> List[str]:
        """Get scanner underlyings from YAML config."""
        if self._mode_config:
            return self._mode_config.scanner_underlyings
        underlyings = os.getenv("SCANNER_UNDERLYINGS", "CRUDEOIL,NATURALGAS")
        return [s.strip() for s in underlyings.split(",")]
    
    @property
    def SCANNER_TOP_N(self) -> int:
        """Get scanner top N from YAML config."""
        if self._mode_config:
            return int(self._mode_config.scanner_config.get("top_n", 4))
        return int(os.getenv("SCANNER_TOP_N", "4"))
    
    @property
    def SCANNER_TOP_PER_UNDERLYING(self) -> int:
        """Get scanner top per underlying from YAML config."""
        if self._mode_config:
            return int(self._mode_config.scanner_config.get("top_per_underlying", 2))
        return int(os.getenv("SCANNER_TOP_PER_UNDERLYING", "2"))
    
    @property
    def STRIKES_AROUND_ATM(self) -> int:
        """Get strikes around ATM from YAML config."""
        if self._mode_config:
            return int(self._mode_config.scanner_config.get("strikes_around_atm", 2))
        return int(os.getenv("STRIKES_AROUND_ATM", "2"))
    
    @property
    def SCANNER_EXPIRY_INDEX(self) -> int:
        """Get scanner expiry index from YAML config."""
        if self._mode_config:
            return int(self._mode_config.scanner_config.get("expiry_index", 0))
        return int(os.getenv("SCANNER_EXPIRY_INDEX", "0"))
    
    @property
    def SCANNER_OPTION_TYPE(self) -> str:
        """Get scanner option type from YAML config."""
        if self._mode_config:
            return self._mode_config.scanner_config.get("option_type", "")
        return os.getenv("SCANNER_OPTION_TYPE", "")
    
    @property
    def AGGRESSION_SIGMA(self) -> float:
        """Get aggression sigma from YAML config."""
        if self._mode_config:
            amt = self._mode_config.amt_thresholds
            if amt.get("aggression_sigma") is not None:
                return float(amt["aggression_sigma"])
        return float(os.getenv("AGGRESSION_SIGMA", "2.0"))
    
    @property
    def DISPLACEMENT_MULTIPLIER(self) -> float:
        """Get displacement multiplier from YAML config."""
        if self._mode_config:
            amt = self._mode_config.amt_thresholds
            if amt.get("displacement_multiplier") is not None:
                return float(amt["displacement_multiplier"])
            return 1.2 if self._mode_config.strategy == "mcx_options" else 1.5
        return float(os.getenv("DISPLACEMENT_MULTIPLIER", "1.2"))
    
    @property
    def BALANCE_RATIO_THRESHOLD(self) -> float:
        """Get balance ratio threshold from YAML config."""
        if self._mode_config:
            amt = self._mode_config.amt_thresholds
            if amt.get("balance_ratio_threshold") is not None:
                return float(amt["balance_ratio_threshold"])
        return float(os.getenv("BALANCE_RATIO_THRESHOLD", "0.55"))
    
    @property
    def ALLOW_SHORT(self) -> bool:
        """Get allow short from YAML config."""
        if self._mode_config:
            flags = self._merged_feature_flags()
            return flags.get("allow_short", True)
        return os.getenv("ALLOW_SHORT", "true").lower() == "true"
    
    @property
    def RISK_TIER_ENGINE(self) -> bool:
        """Get risk tier engine flag from YAML config."""
        if self._mode_config:
            flags = self._merged_feature_flags()
            return flags.get("risk_tier_engine", True)
        return os.getenv("RISK_TIER_ENGINE", "true").lower() == "true"
    
    @property
    def SHORT_SIGNALS_ENABLED(self) -> bool:
        """Get short signals flag from YAML config."""
        if self._mode_config:
            flags = self._merged_feature_flags()
            return flags.get("short_signals_enabled", True)
        return os.getenv("SHORT_SIGNALS_ENABLED", "true").lower() == "true"
    
    @property
    def LLM_PRE_CANDLE_ADVISORY(self) -> bool:
        """Get LLM pre-candle advisory flag from YAML config."""
        if self._mode_config:
            flags = self._merged_feature_flags()
            return flags.get("llm_pre_candle_advisory", True)
        return os.getenv("LLM_PRE_CANDLE_ADVISORY", "true").lower() == "true"
    
    @property
    def SCALP_ENGINE_ENABLED(self) -> bool:
        """Get scalp engine flag from YAML config."""
        if self._mode_config:
            flags = self._merged_feature_flags()
            return flags.get("scalp_engine_enabled", False)
        return os.getenv("SCALP_ENGINE_ENABLED", "false").lower() == "true"
    
    @property
    def SCALP_IB_BREAKOUT(self) -> bool:
        """Get scalp IB breakout flag from YAML config."""
        if self._mode_config:
            flags = self._merged_feature_flags()
            return flags.get("scalp_ib_breakout", False)
        return os.getenv("SCALP_IB_BREAKOUT", "false").lower() == "true"
    
    @property
    def REALISTIC_COST_MODEL(self) -> bool:
        """Get realistic cost model flag from YAML config."""
        if self._mode_config:
            flags = self._merged_feature_flags()
            return flags.get("realistic_cost_model", True)
        return os.getenv("REALISTIC_COST_MODEL", "true").lower() == "true"
    
    @property
    def LLM_TIMEOUT_SECONDS(self) -> float:
        """Get LLM timeout from YAML config."""
        if self._mode_config:
            return float(self._mode_config.system_config.llm.timeout_seconds)
        return float(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
    
    @property
    def LLM_EXECUTION_ENABLED(self) -> bool:
        """Get LLM execution enabled from env (not in YAML for safety)."""
        return os.getenv("LLM_EXECUTION_ENABLED", "true").lower() == "true"
    
    @property
    def CAPITAL(self) -> float:
        """Get trading capital from YAML config."""
        if self._mode_config:
            return float(self._mode_config.system_config.capital)
        return float(os.getenv("CAPITAL", "5000000"))
    
    @property
    def STREAM_INTERVAL(self) -> str:
        """Get stream interval from YAML config."""
        if self._mode_config:
            return f"{self._mode_config.system_config.candle_timeframe_minutes}m"
        return os.getenv("STREAM_INTERVAL", "5m")
    
    @property
    def TICK_POLL_SECONDS(self) -> float:
        """Get tick poll seconds from env."""
        return float(os.getenv("TICK_POLL_SECONDS", "5.0"))
    
    # =========================================================================
    # Fallback mechanism for any attribute not explicitly defined
    # =========================================================================
    
    def __getattr__(self, name: str) -> Any:
        """Fallback to environment variables or defaults for unknown attributes.
        
        This ensures maximum backward compatibility - if code accesses an attribute
        we haven't explicitly mapped, it will try environment variables first,
        then return None.
        """
        # Try environment variable
        env_value = os.getenv(name)
        if env_value is not None:
            return env_value
        
        # Return None for missing attributes
        return None
    
    def get_mode_config(self):
        """Get the underlying ModeConfig object (for new code using DI)."""
        return self._mode_config
    
    def is_initialized(self) -> bool:
        """Check if YAML config was loaded successfully."""
        return self._initialized


# Singleton - replaces old settings object
# This is what existing code imports: from app.config import settings
settings = SettingsAdapter()
