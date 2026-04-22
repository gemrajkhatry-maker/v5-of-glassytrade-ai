"""Mode-based configuration loader with dependency injection.

This module provides a high-level interface for loading configuration
based on environment (development/paper/live) and strategy (mcx_options/nse_options).

Usage:
    # Load config for specific mode
    config = ModeConfigLoader.load(
        environment="paper",      # development/paper/live
        strategy="mcx_options",   # mcx_options/nse_options
        secrets_from_env=True     # Load DHAN tokens from .env
    )
    
    # Or use environment variables
    # GLASSYTRADE_ENV=paper GLASSYTRADE_STRATEGY=mcx_options
    config = ModeConfigLoader.load_from_env()
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from config.strategy_resolve import resolved_strategy_for_filesystem

from app.config_models import SystemConfig
from app.config_models.loader import load_config as load_system_config

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModeConfig:
    """Complete configuration for a specific mode.
    
    This is the top-level configuration object that contains:
    - SystemConfig: Core system configuration (from config_models)
    - Environment and strategy metadata
    - Scanner configuration
    - Exchange configuration
    - Secrets (API keys, tokens) loaded from .env
    """
    environment: str  # development/paper/live
    strategy: str     # mcx_options/nse_options
    system_config: SystemConfig
    scanner_config: Dict[str, Any] = field(default_factory=dict)
    exchange_config: Dict[str, Any] = field(default_factory=dict)
    secrets: Dict[str, str] = field(default_factory=dict)
    
    @property
    def default_exchange(self) -> str:
        """Get default exchange from config."""
        return self.exchange_config.get("default", "MCX")
    
    @property
    def active_symbols(self) -> list:
        """Get active symbols from config."""
        return self.exchange_config.get("symbols", [])
    
    @property
    def scanner_underlyings(self) -> list:
        """Get scanner underlyings from config."""
        return self.scanner_config.get("underlyings", [])


class ModeConfigLoader:
    """Loads configuration based on environment + strategy mode.
    
    This loader implements the professional configuration hierarchy:
    1. base.yaml (all defaults)
    2. environments/{environment}.yaml (environment overrides)
    3. strategies/{strategy}.yaml (strategy-specific overrides)
    4. .env file (secrets only: API keys, tokens)
    
    Example:
        >>> config = ModeConfigLoader.load(
        ...     environment="paper",
        ...     strategy="mcx_options"
        ... )
        >>> print(config.default_exchange)
        'MCX'
        >>> print(config.active_symbols)
        ['CRUDEOIL', 'NATURALGAS']
    """
    
    @staticmethod
    def load(
        environment: str = "paper",
        strategy: str = "mcx_options",
        config_dir: Optional[str] = None,
        secrets_from_env: bool = True
    ) -> ModeConfig:
        """Load unified configuration for specific mode.
        
        Args:
            environment: Environment name (development/paper/live)
            strategy: Strategy name (mcx_options/nse_options)
            config_dir: Path to config directory. Defaults to backend/config/
            secrets_from_env: Whether to load secrets from .env file
            
        Returns:
            ModeConfig object with all configuration loaded
        """
        if config_dir is None:
            config_dir = str(Path(__file__).resolve().parent.parent / "config")
        config_path = Path(config_dir)
        strategy = resolved_strategy_for_filesystem(config_path, strategy)

        # Set environment variables for downstream loaders
        os.environ["GLASSYTRADE_ENV"] = environment
        os.environ["GLASSYTRADE_STRATEGY"] = strategy

        # Load system config (this uses the enhanced loader with strategy support)
        system_config = load_system_config(
            config_dir=config_dir,
            strategy=strategy
        )
        
        # Load base config
        base_data = {}
        base_path = config_path / "base.yaml"
        if base_path.exists():
            with open(base_path) as f:
                base_data = yaml.safe_load(f) or {}
        
        # Load environment config
        env_data = {}
        env_path = config_path / "environments" / f"{environment}.yaml"
        if env_path.exists():
            with open(env_path) as f:
                env_data = yaml.safe_load(f) or {}
        
        # Load strategy config
        strat_data = {}
        strat_path = config_path / "strategies" / f"{strategy}.yaml"
        if strat_path.exists():
            with open(strat_path) as f:
                strat_data = yaml.safe_load(f) or {}
            logger.info("Loaded strategy file: %s", strat_path)
        else:
            logger.warning("Strategy file not found: %s", strat_path)
        
        # Extract scanner config (merge from all sources)
        scanner_config = {
            **base_data.get("scanner", {}),
            **env_data.get("scanner", {}),
            **strat_data.get("scanner", {}),
        }
        # Strategy file top-level keys consumed by ConsolidatedConfig.from_unified()
        for extra in ("feature_flags", "amt_thresholds"):
            if strat_data.get(extra):
                scanner_config[extra] = strat_data[extra]
        
        # Extract exchange config (merge from all sources)
        exchange_config = {
            **base_data.get("exchange", {}),
            **env_data.get("exchange", {}),
            **strat_data.get("exchange", {}),
        }
        
        # Load secrets from .env if requested
        secrets = {}
        if secrets_from_env:
            secrets = ModeConfigLoader._load_secrets()
        
        # Create mode config
        mode_config = ModeConfig(
            environment=environment,
            strategy=strategy,
            system_config=system_config,
            scanner_config=scanner_config,
            exchange_config=exchange_config,
            secrets=secrets,
        )
        
        # Log configuration summary
        ModeConfigLoader._log_mode_config(mode_config)
        
        return mode_config
    
    @staticmethod
    def load_from_env() -> ModeConfig:
        """Load from GLASSYTRADE_ENV and GLASSYTRADE_STRATEGY env vars.
        
        This is the recommended way to load config in production.
        Set these environment variables before starting the application:
            export GLASSYTRADE_ENV=paper
            export GLASSYTRADE_STRATEGY=mcx_options
        """
        env = os.getenv("GLASSYTRADE_ENV", "paper")
        raw = os.getenv("GLASSYTRADE_STRATEGY", "mcx_options")
        config_path = Path(__file__).resolve().parent.parent / "config"
        strategy = resolved_strategy_for_filesystem(config_path, raw)
        if strategy != (raw or "").strip():
            os.environ["GLASSYTRADE_STRATEGY"] = strategy

        logger.info(
            "Loading configuration from environment: env=%s, strategy=%s (resolved from %r)",
            env,
            strategy,
            raw,
        )

        return ModeConfigLoader.load(
            environment=env, strategy=strategy, config_dir=str(config_path)
        )
    
    @staticmethod
    def _load_secrets() -> Dict[str, str]:
        """Load sensitive data from .env file.
        
        Only loads secrets (API keys, tokens), not configuration values.
        This follows the 12-factor app principle of separating config from secrets.
        """
        from dotenv import load_dotenv
        
        # Find .env file (search from current module location)
        # Module is at: backend/config/mode_config.py → project_root = 3 parents up
        env_path = Path(__file__).resolve().parent.parent.parent / ".env"
        
        if env_path.exists():
            load_dotenv(env_path)
            logger.debug("Loaded .env file: %s", env_path)
        else:
            logger.warning(".env file not found: %s", env_path)
        
        # Extract only secrets (not config values)
        secrets = {}
        secret_keys = [
            "DHAN_CLIENT_ID",
            "DHAN_ACCESS_TOKEN",
            "DHAN_API_KEY",
            "DHAN_API_SECRET",
            "OPENROUTER_API_KEY",
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_CHAT_ID",
        ]
        
        for key in secret_keys:
            value = os.getenv(key)
            if value:
                secrets[key] = value
        
        return secrets
    
    @staticmethod
    def _log_mode_config(config: ModeConfig) -> None:
        """Log human-readable configuration summary at boot."""
        logger.info("=" * 70)
        logger.info("  GlassyTrade AI — Mode Configuration")
        logger.info("=" * 70)
        logger.info("  Environment: %s", config.environment)
        logger.info("  Strategy: %s", config.strategy)
        logger.info("  Default Exchange: %s", config.default_exchange)
        logger.info("  Active Symbols: %s", config.active_symbols)
        logger.info("  Scanner Underlyings: %s", config.scanner_underlyings)
        logger.info("  System Config:")
        logger.info("    - Capital: ₹%.0f", config.system_config.capital)
        logger.info("    - Log Level: %s", config.system_config.log_level)
        logger.info("    - Broker Mode: %s", config.system_config.broker_mode)
        logger.info("    - Active Exchanges: %s", 
                    [ex.name for ex in config.system_config.active_exchanges()])
        logger.info("  Risk Settings:")
        logger.info("    - Risk per Trade: %.2f%%", 
                    config.system_config.risk.risk_per_trade_pct * 100)
        logger.info("    - Max Daily Loss: %.2f%%", 
                    config.system_config.risk.max_daily_loss_pct * 100)
        logger.info("    - Max Positions: %d", 
                    config.system_config.risk.max_concurrent_positions)
        logger.info("=" * 70)
