"""Application configuration - now reads from YAML with .env fallback.

This module provides backward-compatible configuration access for all existing code.

OLD WAY (still works - 25+ files use this):
    from app.config import settings
    print(settings.SCANNER_MODE)  # Reads from YAML

NEW WAY (recommended for new code - uses dependency injection):
    from app.api.dependencies import get_system_config
    config = await get_system_config(request)
    print(config.default_exchange)  # Reads from YAML

Configuration Hierarchy:
    1. base.yaml (all defaults)
    2. environments/{GLASSYTRADE_ENV}.yaml (environment overrides)
    3. strategies/{GLASSYTRADE_STRATEGY}.yaml (strategy-specific overrides)
    4. .env (secrets only: API keys, tokens)

Quick Start:
    # Switch to MCX mode
    export GLASSYTRADE_ENV=paper
    export GLASSYTRADE_STRATEGY=mcx_options
    
    # Switch to NSE mode
    export GLASSYTRADE_ENV=paper
    export GLASSYTRADE_STRATEGY=nse_options
"""

# Import the adapter (replaces old Settings class)
# This maintains 100% backward compatibility - all existing imports work
from app.config_models.settings_adapter import settings

# Configuration is the canonical typed model (config_models.SystemConfig),
# built by the YAML loader and consumed by the DI composition root.
from app.config_models import SystemConfig as Configuration

__all__ = ["settings", "Configuration"]
