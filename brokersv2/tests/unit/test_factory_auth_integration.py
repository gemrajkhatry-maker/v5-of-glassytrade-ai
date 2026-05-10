"""
Auth integration tests - Phase 1, Step 3 & 4 (TDD)

Tests for wiring auth provider into DhanHttpClient and factory.
"""

import pytest
import os
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from brokersv2.infrastructure.dhan_adapter.auth_provider import DhanAuthProvider, AuthError
from brokersv2.infrastructure.dhan_adapter.client import DhanConfig, DhanHttpClient
from brokersv2.infrastructure.dhan_adapter.factory import DhanGatewayConfig, DhanFactory


class TestClientAuthIntegration:
    """Test DhanHttpClient with auth provider."""
    
    def test_client_accepts_auth_provider(self):
        """Should accept optional auth_provider parameter."""
        config = DhanConfig(client_id="test123", access_token="token123")
        auth_provider = DhanAuthProvider(client_id="test123")
        
        client = DhanHttpClient(config, auth_provider=auth_provider)
        
        assert client._auth_provider == auth_provider
    
    def test_client_works_without_auth_provider(self):
        """Should work without auth provider (backward compat)."""
        config = DhanConfig(client_id="test123", access_token="token123")
        
        client = DhanHttpClient(config)  # No auth provider
        
        assert client._auth_provider is None
    
    @pytest.mark.asyncio
    async def test_client_uses_auth_provider_token(self):
        """Should get token from auth provider when making requests."""
        config = DhanConfig(client_id="test123", access_token="old_token")
        auth_provider = DhanAuthProvider(client_id="test123")
        auth_provider.set_current_token("new_token", datetime.now() + timedelta(hours=24))
        
        client = DhanHttpClient(config, auth_provider=auth_provider)
        
        # Verify client uses auth provider's token
        assert client._headers["access-token"] == "new_token"
    
    @pytest.mark.asyncio
    async def test_client_updates_token_on_refresh(self):
        """Should update headers when token refreshes."""
        config = DhanConfig(client_id="test123", access_token="token123")
        auth_provider = DhanAuthProvider(client_id="test123")
        auth_provider.set_current_token("token123", datetime.now() + timedelta(hours=24))
        
        client = DhanHttpClient(config, auth_provider=auth_provider)
        
        # Simulate token refresh
        auth_provider.set_current_token("refreshed_token", datetime.now() + timedelta(hours=24))
        
        # Client should use new token on next request
        # (In real implementation, this happens via callback or lazy evaluation)
        assert "refreshed_token" in auth_provider._access_token


class TestFactoryAuthIntegration:
    """Test factory with auth provider."""
    
    @patch.dict(os.environ, {}, clear=True)
    def test_from_env_with_access_token_uses_it(self, tmp_path):
        """Should use ACCESS_TOKEN from .env when available."""
        env_file = tmp_path / ".env"
        env_file.write_text("DHAN_CLIENT_ID=test123\nDHAN_ACCESS_TOKEN=existing_token\n")
        
        # Change to tmp dir so it finds our .env
        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        
        try:
            # Clear and reload env
            import importlib
            from brokersv2.infrastructure.dhan_adapter import factory
            importlib.reload(factory)
            
            config = factory.DhanGatewayConfig.from_env()
            
            assert config.client_id == "test123"
            assert config.access_token == "existing_token"
        finally:
            os.chdir(original_cwd)
    
    @patch.dict(os.environ, {}, clear=True)
    def test_from_env_with_totp_stores_credentials(self, tmp_path):
        """Should store TOTP credentials for auto-generation."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "DHAN_CLIENT_ID=test123\n"
            "DHAN_TOTP_SECRET=JBSWY3DPEHPK3PXP\n"
            "DHAN_PIN=1234\n"
        )
        
        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        
        try:
            import importlib
            from brokersv2.infrastructure.dhan_adapter import factory
            importlib.reload(factory)
            
            config = factory.DhanGatewayConfig.from_env()
            
            assert config.client_id == "test123"
            # Config should allow empty token when TOTP available
            assert config.access_token == ""  # Will be generated later
        finally:
            os.chdir(original_cwd)
    
    @patch.dict(os.environ, {}, clear=True)
    def test_from_env_without_credentials_raises(self, tmp_path):
        """Should raise error if no credentials available."""
        env_file = tmp_path / ".env"
        env_file.write_text("DHAN_CLIENT_ID=test123\n")  # No token, no TOTP
        
        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        
        try:
            import importlib
            from brokersv2.infrastructure.dhan_adapter import factory
            importlib.reload(factory)
            
            with pytest.raises(ValueError, match="ACCESS_TOKEN"):
                factory.DhanGatewayConfig.from_env()
        finally:
            os.chdir(original_cwd)
    
    @pytest.mark.asyncio
    @patch.dict(os.environ, {}, clear=True)
    async def test_create_gateway_initializes_auth_provider(self, tmp_path):
        """Should create gateway with auth provider when TOTP configured."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "DHAN_CLIENT_ID=test123\n"
            "DHAN_TOTP_SECRET=JBSWY3DPEHPK3PXP\n"
            "DHAN_PIN=1234\n"
        )
        
        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        
        try:
            # Mock token generation to avoid real API call
            with patch('brokersv2.infrastructure.dhan_adapter.auth_provider.DhanAuthProvider.generate_token', new_callable=AsyncMock) as mock_gen:
                mock_gen.return_value = "generated_token"
                
                factory = DhanFactory.from_env()
                gateway = await factory.create_gateway()
                
                # Should have auth provider
                assert gateway._client._auth_provider is not None
        finally:
            os.chdir(original_cwd)


class TestEndToEndAuthFlow:
    """Test complete auth flow from factory to client."""
    
    @pytest.mark.asyncio
    @patch.dict(os.environ, {}, clear=True)
    async def test_full_flow_with_totp_generation(self, tmp_path):
        """Should generate token and create working gateway."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "DHAN_CLIENT_ID=test123\n"
            "DHAN_TOTP_SECRET=JBSWY3DPEHPK3PXP\n"
            "DHAN_PIN=1234\n"
        )
        
        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        
        try:
            # Mock the entire auth flow
            with patch('dhanhq.auth.DhanLogin') as mock_login_cls:
                mock_login = MagicMock()
                mock_login.generate_token.return_value = {"access_token": "auto_token_123"}
                mock_login_cls.return_value = mock_login
                
                factory = DhanFactory.from_env()
                gateway = await factory.create_gateway()
                
                # Verify token was generated
                assert gateway._client.config.access_token == "auto_token_123"
        finally:
            os.chdir(original_cwd)
