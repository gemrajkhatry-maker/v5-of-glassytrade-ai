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
from typing import Any, List

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
            str(Path(__file__).resolve().parent.parent.parent / "config")
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
        self.TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
    
    # =========================================================================
    # Property accessors that read from YAML config
    # =========================================================================
    
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
        underlyings = os.getenv(
            "SCANNER_UNDERLYINGS", "CRUDEOIL,NATURALGAS,GOLDM,SILVERM"
        )
        return [s.strip() for s in underlyings.split(",")]
    
    @property
    def SCANNER_UNDERLYING_PRIORITY(self) -> list[str] | None:
        """Explicit scanner root priority (first = primary, fills slots first).
        Falls back to None so the scanner keeps its score-ordered default when
        no priority is configured."""
        if self._mode_config:
            prio = self._mode_config.scanner_config.get("underlying_priority")
            if prio:
                return [str(s).strip() for s in prio]
            return None
        raw = os.getenv("SCANNER_UNDERLYING_PRIORITY", "")
        if raw:
            return [s.strip() for s in raw.split(",") if s.strip()]
        return None

    @property
    def SCANNER_TOP_N(self) -> int:
        """Get scanner top N from YAML config."""
        if self._mode_config:
            return int(self._mode_config.scanner_config.get("top_n", 4))
        return int(os.getenv("SCANNER_TOP_N", "4"))
    
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
    def CORS_ORIGINS(self) -> List[str]:
        """Get allowed CORS origins from env (comma-separated)."""
        raw = os.getenv(
            "CORS_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5190,http://127.0.0.1:5190,http://localhost:5191,http://127.0.0.1:5191,http://localhost:5173,http://127.0.0.1:5173",
        )
        return [o.strip() for o in raw.split(",") if o.strip()]

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
