"""Tests for YAML-based mode configuration system.

Tests verify:
1. MCX mode loads correctly
2. NSE mode loads correctly
3. Backward compatibility with old settings object
4. Configuration hierarchy (base → env → strategy)
"""

import os
import pytest
from pathlib import Path


class TestMCXModeConfig:
    """Test MCX mode configuration loading."""
    
    def test_mcx_mode_loads_correctly(self):
        """Test that MCX strategy loads with correct settings."""
        from config.mode_config import ModeConfigLoader
        
        config = ModeConfigLoader.load(
            environment="paper",
            strategy="mcx_options"
        )
        
        assert config.environment == "paper"
        assert config.strategy == "mcx_options"
        assert config.default_exchange == "MCX"
        assert "CRUDEOIL" in config.active_symbols
        assert "NATURALGAS" in config.active_symbols
        assert config.scanner_config.get("mode") == "mcx_options"
        assert config.scanner_config.get("top_n") == 4
    
    def test_mcx_amt_thresholds(self):
        """Test MCX-specific AMT thresholds."""
        from config.mode_config import ModeConfigLoader
        
        config = ModeConfigLoader.load(
            environment="paper",
            strategy="mcx_options"
        )
        
        crudeoil = config.system_config.exchanges["MCX"].symbols["CRUDEOIL"]

        # MCX should use the commodity thresholds from the active exchange config.
        assert crudeoil.aggression_sigma == 2.0
        assert crudeoil.displacement_multiplier == 1.2
        assert crudeoil.balance_ratio_threshold == 0.55


class TestNSEModeConfig:
    """Test NSE mode configuration loading."""
    
    def test_nse_mode_loads_correctly(self):
        """Test that NSE strategy loads with correct settings."""
        from config.mode_config import ModeConfigLoader
        
        config = ModeConfigLoader.load(
            environment="paper",
            strategy="nse_options"
        )
        
        assert config.environment == "paper"
        assert config.strategy == "nse_options"
        assert config.default_exchange == "NFO"
        assert "NIFTY" in config.active_symbols
        assert "BANKNIFTY" in config.active_symbols
        assert "FINNIFTY" in config.active_symbols
        assert config.scanner_config.get("mode") == "nse_options"
        assert config.scanner_config.get("top_n") == 3
    
    def test_nse_amt_thresholds(self):
        """Test NSE-specific AMT thresholds."""
        from config.mode_config import ModeConfigLoader
        
        config = ModeConfigLoader.load(
            environment="paper",
            strategy="nse_options"
        )
        
        nifty = config.system_config.exchanges["NSE"].symbols["NIFTY"]

        # NSE should use the index-option thresholds from the active exchange config.
        assert nifty.aggression_sigma == 2.5
        assert nifty.displacement_multiplier == 1.5
        assert nifty.balance_ratio_threshold == 0.70


class TestBackwardCompatibility:
    """Test backward compatibility with old settings object."""
    
    def test_settings_adapter_imports(self):
        """Test that old import pattern still works."""
        from app.config import settings
        
        # Should not raise ImportError
        assert settings is not None
    
    def test_settings_adapter_properties(self):
        """Test that settings adapter exposes expected properties."""
        # Set environment for test
        os.environ["GLASSYTRADE_ENV"] = "paper"
        os.environ["GLASSYTRADE_STRATEGY"] = "mcx_options"
        
        # Reload settings to pick up test env
        import importlib
        import app.config as app_config
        import app.config_models.settings_adapter as settings_adapter_module
        importlib.reload(settings_adapter_module)
        app_config.settings = settings_adapter_module.SettingsAdapter()
        
        from app.config import settings
        
        # Test critical properties
        assert settings.SCANNER_MODE is not None
        assert settings.DEFAULT_EXCHANGE is not None
        assert settings.DHAN_SYMBOLS is not None
        assert isinstance(settings.DHAN_SYMBOLS, list)
    
    def test_settings_adapter_secrets(self):
        """Test that secrets are loaded from .env."""
        from app.config import settings
        
        # Should have loaded secrets
        assert hasattr(settings, "DHAN_CLIENT_ID")
        assert hasattr(settings, "DHAN_ACCESS_TOKEN")


class TestConfigHierarchy:
    """Test configuration merge hierarchy."""
    
    def test_base_yaml_loads(self):
        """Test that base.yaml loads successfully."""
        from app.config_models.loader import load_config

        config = load_config(strategy="mcx_options")
        
        assert config is not None
        assert config.name == "GlassyTrade AI"
        assert config.capital > 0
        assert "CRUDEOIL" in config.active_symbols()

    def test_default_loader_path_points_to_backend_config(self):
        """Default loader path should resolve the real backend/config tree."""
        from app.config_models.loader import load_config

        config = load_config()

        assert config is not None
        assert config.active_symbols()
    
    def test_environment_override(self):
        """Test that environment files override base."""
        os.environ["GLASSYTRADE_ENV"] = "development"
        
        from app.config_models.loader import load_config
        
        config = load_config()
        
        # Development should have DEBUG log level
        assert config.log_level == "DEBUG"
    
    def test_strategy_override(self):
        """Test that strategy files override environment."""
        from config.mode_config import ModeConfigLoader
        
        # Load MCX config
        mcx_config = ModeConfigLoader.load(
            environment="paper",
            strategy="mcx_options"
        )
        
        # Load NSE config
        nse_config = ModeConfigLoader.load(
            environment="paper",
            strategy="nse_options"
        )
        
        # Strategies should have different settings
        assert mcx_config.default_exchange != nse_config.default_exchange
        assert mcx_config.active_symbols != nse_config.active_symbols


class TestEnvironmentConfigs:
    """Test different environment configurations."""
    
    def test_development_env(self):
        """Test development environment settings."""
        from config.mode_config import ModeConfigLoader
        
        config = ModeConfigLoader.load(
            environment="development",
            strategy="nse_options"
        )
        
        assert config.environment == "development"
        assert config.system_config.log_level == "DEBUG"
        # Development keeps NIFTY enabled and disables MCX.
        assert config.system_config.exchanges["NSE"].symbols["NIFTY"].enabled is True
        assert config.system_config.exchanges["MCX"].enabled is False
    
    def test_paper_env(self):
        """Test paper environment settings."""
        from config.mode_config import ModeConfigLoader
        
        config = ModeConfigLoader.load(
            environment="paper",
            strategy="mcx_options"
        )
        
        assert config.environment == "paper"
        assert config.system_config.log_level == "INFO"
        assert config.system_config.broker_mode == "paper"
    
    def test_live_env(self):
        """Test live environment settings."""
        from config.mode_config import ModeConfigLoader
        
        config = ModeConfigLoader.load(
            environment="live",
            strategy="mcx_options"
        )
        
        assert config.environment == "live"
        assert config.system_config.log_level == "WARNING"
        assert config.system_config.broker_mode == "live"
        # Live env should still preserve the live metadata even when strategy overrides other knobs.
        assert config.default_exchange == "MCX"


class TestRuntimeEnvPaths:
    """Test repo-root environment path resolution."""

    def test_mode_config_secrets_path_resolves_repo_env(self):
        from config.mode_config import ModeConfigLoader

        secrets = ModeConfigLoader._load_secrets()

        assert "DHAN_CLIENT_ID" in secrets


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
