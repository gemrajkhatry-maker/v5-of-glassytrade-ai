"""
Tests for DhanFactory and DhanGateway.

Tests verify:
1. Environment credential loading
2. Configuration validation
3. Gateway creation and lifecycle
4. Symbol translation
"""

import os
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

# Test the factory module
import sys
sys.path.insert(0, '/Users/apple/Downloads/v5-of-glassytrade-ai')

from brokersv2.infrastructure.dhan_adapter.factory import (
    DhanFactory,
    DhanGateway,
    DhanGatewayConfig,
    _load_dotenv,
)


class TestDhanGatewayConfig:
    """Test DhanGatewayConfig."""
    
    def test_from_env_with_valid_credentials(self):
        """Test config creation from environment."""
        env_vars = {
            'DHAN_CLIENT_ID': 'test_client',
            'DHAN_ACCESS_TOKEN': 'test_token',
            'DHAN_BASE_URL': 'https://custom.api',
            'DHAN_TIMEOUT': '60',
        }
        with patch.dict(os.environ, env_vars, clear=True):
            config = DhanGatewayConfig.from_env()
            
            assert config.client_id == 'test_client'
            assert config.access_token == 'test_token'
            assert config.base_url == 'https://custom.api'
            assert config.timeout == 60
    
    def test_from_env_missing_client_id(self):
        """Test error when client ID is missing."""
        # Save original env
        old_env = os.environ.copy()
        try:
            os.environ.clear()
            # Must also clear the dotenv loading effect
            with patch('brokersv2.infrastructure.dhan_adapter.factory._load_dotenv'):
                os.environ['DHAN_ACCESS_TOKEN'] = 'test_token'
                with pytest.raises(ValueError, match="DHAN_CLIENT_ID"):
                    DhanGatewayConfig.from_env()
        finally:
            os.environ.clear()
            os.environ.update(old_env)
    
    def test_from_env_missing_access_token_with_totp_pin(self):
        """Test token generation fallback with TOTP+PIN."""
        old_env = os.environ.copy()
        try:
            os.environ.clear()
            os.environ['DHAN_CLIENT_ID'] = 'test_client'
            os.environ['DHAN_TOTP_SECRET'] = 'secret'
            os.environ['DHAN_PIN'] = '123456'
            # Should not raise, uses TOTP+PIN fallback
            config = DhanGatewayConfig.from_env()
            assert config.client_id == 'test_client'
            # With TOTP+PIN, access_token can be empty or generated
        finally:
            os.environ.clear()
            os.environ.update(old_env)
    
    def test_from_env_missing_access_token_no_fallback(self):
        """Test error when access token and fallback missing."""
        old_env = os.environ.copy()
        try:
            os.environ.clear()
            # Must also clear the dotenv loading effect
            with patch('brokersv2.infrastructure.dhan_adapter.factory._load_dotenv'):
                os.environ['DHAN_CLIENT_ID'] = 'test_client'
                # access_token not set, no TOTP+PIN
                with pytest.raises(ValueError, match="DHAN_ACCESS_TOKEN"):
                    DhanGatewayConfig.from_env()
        finally:
            os.environ.clear()
            os.environ.update(old_env)


class TestDhanFactory:
    """Test DhanFactory."""
    
    def test_factory_from_env(self):
        """Test factory creation from environment."""
        with patch.dict(os.environ, {
            'DHAN_CLIENT_ID': 'test_client',
            'DHAN_ACCESS_TOKEN': 'test_token',
        }):
            factory = DhanFactory.from_env()
            assert factory._config.client_id == 'test_client'
            assert factory._config.access_token == 'test_token'
    
    def test_factory_with_config_override(self):
        """Test factory with config overrides."""
        config = DhanGatewayConfig(
            client_id='original',
            access_token='original_token',
        )
        factory = DhanFactory(config)
        
        # Override timeout
        new_factory = factory.with_config(timeout=60)
        
        # Original unchanged
        assert factory._config.timeout == 30
        # New has override
        assert new_factory._config.timeout == 60
    
    @pytest.mark.asyncio
    async def test_factory_create_gateway(self):
        """Test gateway creation."""
        config = DhanGatewayConfig(
            client_id='test',
            access_token='token',
        )
        factory = DhanFactory(config)
        
        gateway = await factory.create_gateway()
        
        assert isinstance(gateway, DhanGateway)
        assert gateway._config.client_id == 'test'


class TestDhanGateway:
    """Test DhanGateway."""
    
    @pytest.mark.asyncio
    async def test_gateway_context_manager(self):
        """Test gateway as async context manager."""
        with patch.dict(os.environ, {
            'DHAN_CLIENT_ID': 'test',
            'DHAN_ACCESS_TOKEN': 'token',
        }):
            async with await DhanGateway.from_env() as gw:
                assert gw._initialized
            
            # After context exit, should be closed
            assert not gw._initialized  # type: ignore
    
    @pytest.mark.asyncio
    async def test_get_quote_unknown_symbol(self):
        """Test quote for unknown symbol."""
        with patch.dict(os.environ, {
            'DHAN_CLIENT_ID': 'test',
            'DHAN_ACCESS_TOKEN': 'token',
        }):
            async with await DhanGateway.from_env() as gw:
                with pytest.raises(ValueError, match="'UNKNOWN' is not a valid Exchange|Unknown symbol"):
                    await gw.get_quote("UNKNOWN:SYMBOL")
    
    @pytest.mark.asyncio
    async def test_historical_returns_list(self):
        """Test historical returns empty list for unimplemented."""
        with patch.dict(os.environ, {
            'DHAN_CLIENT_ID': 'test',
            'DHAN_ACCESS_TOKEN': 'token',
        }):
            async with await DhanGateway.from_env() as gw:
                result = await gw.historical("NSE:TEST", "2024-01-01", "2024-01-31")
                assert isinstance(result, list)


class TestDotenvLoading:
    """Test dotenv loading functionality."""
    
    def test_load_dotenv_finds_project_env(self):
        """Test that _load_dotenv can be called without error."""
        # This should not raise
        _load_dotenv()


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])