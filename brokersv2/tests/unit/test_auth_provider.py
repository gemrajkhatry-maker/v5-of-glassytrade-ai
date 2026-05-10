"""
Dhan Auth Provider tests - Phase 1, Step 2 (TDD)

Tests for authentication provider using dhanhq.auth.DhanLogin.
Covers token generation, renewal, and lifecycle management.
"""

import pytest
import os
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from brokersv2.infrastructure.dhan_adapter.auth_provider import (
    DhanAuthProvider,
    AuthError,
    TokenExpiredError,
    TokenNearExpiryError,
)


class TestAuthProviderInitialization:
    """Test DhanAuthProvider initialization."""
    
    def test_create_with_client_id(self):
        """Should create auth provider with client ID."""
        provider = DhanAuthProvider(client_id="test123")
        
        assert provider.client_id == "test123"
    
    def test_create_with_custom_http_client(self):
        """Should accept custom HTTP client for testing."""
        mock_http = MagicMock()
        provider = DhanAuthProvider(client_id="test123", http_client=mock_http)
        
        assert provider._http_client == mock_http


class TestTokenGeneration:
    """Test TOTP-based token generation."""
    
    @pytest.mark.asyncio
    async def test_generate_token_success(self):
        """Should generate token using PIN + TOTP."""
        provider = DhanAuthProvider(client_id="test123")
        
        # Mock DhanLogin
        with patch('dhanhq.auth.DhanLogin') as mock_login_cls:
            mock_login = MagicMock()
            mock_login.generate_token.return_value = {
                "access_token": "new_token_123",
                "status": "success"
            }
            mock_login_cls.return_value = mock_login
            
            # Generate token
            token = await provider.generate_token(pin="1234", totp_secret="JBSWY3DPEHPK3PXP")
            
            assert token == "new_token_123"
            mock_login.generate_token.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_generate_token_stores_totp_secret(self):
        """Should store TOTP secret for future use."""
        provider = DhanAuthProvider(client_id="test123")
        
        with patch('dhanhq.auth.DhanLogin') as mock_login_cls:
            mock_login = MagicMock()
            mock_login.generate_token.return_value = {"access_token": "token123"}
            mock_login_cls.return_value = mock_login
            
            await provider.generate_token(pin="1234", totp_secret="JBSWY3DPEHPK3PXP")
            
            assert provider._totp_secret == "JBSWY3DPEHPK3PXP"
            assert provider._pin == "1234"
    
    @pytest.mark.asyncio
    async def test_generate_token_invalid_totp(self):
        """Should raise error for invalid TOTP."""
        provider = DhanAuthProvider(client_id="test123")
        
        with patch('dhanhq.auth.DhanLogin') as mock_login_cls:
            mock_login = MagicMock()
            mock_login.generate_token.side_effect = Exception("Invalid TOTP")
            mock_login_cls.return_value = mock_login
            
            with pytest.raises(AuthError, match="Invalid TOTP"):
                await provider.generate_token(pin="1234", totp_secret="INVALID")
    
    @pytest.mark.asyncio
    async def test_generate_token_enforces_cooldown(self):
        """Should enforce 2-minute cooldown between generations."""
        provider = DhanAuthProvider(client_id="test123")
        
        with patch('dhanhq.auth.DhanLogin') as mock_login_cls:
            mock_login = MagicMock()
            mock_login.generate_token.return_value = {"access_token": "token123"}
            mock_login_cls.return_value = mock_login
            
            # First generation
            await provider.generate_token(pin="1234", totp_secret="JBSWY3DPEHPK3PXP")
            
            # Immediate second generation should fail
            with pytest.raises(AuthError, match="cooldown"):
                await provider.generate_token(pin="1234", totp_secret="JBSWY3DPEHPK3PXP")


class TestTokenRenewal:
    """Test token renewal functionality."""
    
    @pytest.mark.asyncio
    async def test_renew_token_success(self):
        """Should renew active token."""
        provider = DhanAuthProvider(client_id="test123")
        
        with patch('dhanhq.auth.DhanLogin') as mock_login_cls:
            mock_login = MagicMock()
            mock_login.renew_token.return_value = {
                "access_token": "renewed_token_456",
                "status": "success"
            }
            mock_login_cls.return_value = mock_login
            
            new_token = await provider.renew_token("old_token_123")
            
            assert new_token == "renewed_token_456"
            mock_login.renew_token.assert_called_once_with("old_token_123")
    
    @pytest.mark.asyncio
    async def test_renew_expired_token_fails(self):
        """Should fail to renew already expired token."""
        provider = DhanAuthProvider(client_id="test123")
        
        with patch('dhanhq.auth.DhanLogin') as mock_login_cls:
            mock_login = MagicMock()
            mock_login.renew_token.side_effect = Exception("Token expired")
            mock_login_cls.return_value = mock_login
            
            with pytest.raises(AuthError, match="expired"):
                await provider.renew_token("expired_token")


class TestTokenLifecycle:
    """Test token expiry and refresh logic."""
    
    @pytest.mark.asyncio
    async def test_ensure_valid_token_renews_near_expiry(self):
        """Should renew token if near expiry (<1 hour)."""
        provider = DhanAuthProvider(client_id="test123")
        provider.set_current_token("token123")
        provider._token_expiry = datetime.now() + timedelta(minutes=30)  # Near expiry
        
        with patch.object(provider, 'renew_token', new_callable=AsyncMock) as mock_renew:
            mock_renew.return_value = "new_token_456"
            
            token = await provider.ensure_valid_token()
            
            assert token == "new_token_456"
            mock_renew.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_ensure_valid_token_regenerates_expired(self):
        """Should generate new token if expired and TOTP available."""
        provider = DhanAuthProvider(client_id="test123")
        provider.set_current_token("expired_token")
        provider._token_expiry = datetime.now() - timedelta(hours=1)  # Expired
        provider._totp_secret = "JBSWY3DPEHPK3PXP"
        provider._pin = "1234"
        provider._last_generation_time = datetime.now() - timedelta(hours=2)  # Past cooldown
        
        with patch.object(provider, 'generate_token', new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "new_token_789"
            
            token = await provider.ensure_valid_token()
            
            assert token == "new_token_789"
            mock_gen.assert_called_once_with("1234", "JBSWY3DPEHPK3PXP")
    
    @pytest.mark.asyncio
    async def test_ensure_valid_token_returns_current_if_valid(self):
        """Should return current token if still valid (>1hr)."""
        provider = DhanAuthProvider(client_id="test123")
        provider.set_current_token("valid_token")
        provider._token_expiry = datetime.now() + timedelta(hours=12)  # Far from expiry
        
        token = await provider.ensure_valid_token()
        
        assert token == "valid_token"
    
    def test_is_token_near_expiry(self):
        """Should detect token near expiry."""
        provider = DhanAuthProvider(client_id="test123")
        
        # Near expiry (30 min)
        provider._token_expiry = datetime.now() + timedelta(minutes=30)
        assert provider.is_token_near_expiry() is True
        
        # Far from expiry (12 hours)
        provider._token_expiry = datetime.now() + timedelta(hours=12)
        assert provider.is_token_near_expiry() is False
    
    def test_is_token_expired(self):
        """Should detect expired token."""
        provider = DhanAuthProvider(client_id="test123")
        
        # Expired
        provider._token_expiry = datetime.now() - timedelta(hours=1)
        assert provider.is_token_expired() is True
        
        # Valid
        provider._token_expiry = datetime.now() + timedelta(hours=1)
        assert provider.is_token_expired() is False


class TestTokenPersistence:
    """Test token persistence to .env file."""
    
    def test_persist_token_to_env(self, tmp_path):
        """Should save token to .env file."""
        env_file = tmp_path / ".env"
        provider = DhanAuthProvider(client_id="test123", env_file=str(env_file))
        
        expiry = datetime.now() + timedelta(hours=24)
        provider._persist_token("test_token_123", expiry)
        
        # Read file
        content = env_file.read_text()
        assert "DHAN_ACCESS_TOKEN=test_token_123" in content
    
    def test_load_token_from_env(self, tmp_path):
        """Should load token from .env file."""
        env_file = tmp_path / ".env"
        env_file.write_text("DHAN_ACCESS_TOKEN=existing_token_456\n")
        
        provider = DhanAuthProvider(client_id="test123", env_file=str(env_file))
        token = provider._load_saved_token()
        
        assert token == "existing_token_456"
    
    def test_load_token_from_env_not_found(self, tmp_path):
        """Should return None if .env doesn't exist."""
        env_file = tmp_path / ".env"
        
        provider = DhanAuthProvider(client_id="test123", env_file=str(env_file))
        token = provider._load_saved_token()
        
        assert token is None


class TestUserValidation:
    """Test user profile validation."""
    
    @pytest.mark.asyncio
    async def test_validate_token_valid(self):
        """Should validate active token."""
        provider = DhanAuthProvider(client_id="test123")
        
        with patch('dhanhq.auth.DhanLogin') as mock_login_cls:
            mock_login = MagicMock()
            mock_login.user_profile.return_value = {
                "status": "success",
                "client_id": "test123"
            }
            mock_login_cls.return_value = mock_login
            
            profile = await provider.validate_token("valid_token")
            
            assert profile["status"] == "success"
            mock_login.user_profile.assert_called_once_with("valid_token")
    
    @pytest.mark.asyncio
    async def test_validate_token_expired(self):
        """Should raise error for expired token."""
        provider = DhanAuthProvider(client_id="test123")
        
        with patch('dhanhq.auth.DhanLogin') as mock_login_cls:
            mock_login = MagicMock()
            mock_login.user_profile.side_effect = Exception("Token expired")
            mock_login_cls.return_value = mock_login
            
            with pytest.raises(AuthError, match="expired"):
                await provider.validate_token("expired_token")
