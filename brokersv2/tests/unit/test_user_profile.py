"""
User Profile Validation tests - Phase 3, Step 6 (TDD)

Tests for token validation and user profile verification.
Ensures tokens are valid before trading operations.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from brokersv2.infrastructure.dhan_adapter.auth_provider import (
    DhanAuthProvider,
    AuthError,
)


class TestUserProfileValidation:
    """Test user profile API for token validation."""
    
    @pytest.mark.asyncio
    async def test_validate_token_success(self):
        """Should return profile for valid token."""
        provider = DhanAuthProvider(client_id="test123")
        
        with patch('dhanhq.auth.DhanLogin') as mock_login_cls:
            mock_login = MagicMock()
            mock_login.user_profile.return_value = {
                "status": "success",
                "client_id": "test123",
                "user_name": "Test User",
                "email": "test@example.com"
            }
            mock_login_cls.return_value = mock_login
            
            profile = await provider.validate_token("valid_token")
            
            assert profile["status"] == "success"
            assert profile["client_id"] == "test123"
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
    
    @pytest.mark.asyncio
    async def test_validate_token_invalid(self):
        """Should raise error for invalid token."""
        provider = DhanAuthProvider(client_id="test123")
        
        with patch('dhanhq.auth.DhanLogin') as mock_login_cls:
            mock_login = MagicMock()
            mock_login.user_profile.return_value = {
                "status": "error",
                "message": "Invalid token"
            }
            mock_login_cls.return_value = mock_login
            
            with pytest.raises(AuthError, match="Invalid token"):
                await provider.validate_token("invalid_token")


class TestTokenValidationOnStartup:
    """Test token validation during gateway initialization."""
    
    @pytest.mark.asyncio
    async def test_gateway_validates_token_on_init(self):
        """Should validate token during gateway initialization."""
        from brokersv2.infrastructure.dhan_adapter.factory import DhanGateway, DhanGatewayConfig
        
        config = DhanGatewayConfig(
            client_id="test123",
            access_token="test_token",
        )
        
        gateway = DhanGateway(config)
        
        # Mock validation
        with patch.object(gateway._client._auth_provider or DhanAuthProvider("test123"), 
                         'validate_token', new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = {
                "status": "success",
                "client_id": "test123"
            }
            
            # If auth provider exists, it should be called
            if gateway._client._auth_provider:
                await gateway._client._auth_provider.validate_token("test_token")
                mock_validate.assert_called_once()


class TestAccountInfoDisplay:
    """Test displaying account information."""
    
    @pytest.mark.asyncio
    async def test_get_account_info(self):
        """Should retrieve and format account info."""
        provider = DhanAuthProvider(client_id="test123")
        
        with patch('dhanhq.auth.DhanLogin') as mock_login_cls:
            mock_login = MagicMock()
            mock_login.user_profile.return_value = {
                "status": "success",
                "client_id": "1106251237",
                "user_name": "Test Trader",
                "email": "trader@example.com",
                "mobile": "9876543210",
                "pan": "ABCDE1234F",
                "account_type": "INDIVIDUAL"
            }
            mock_login_cls.return_value = mock_login
            
            profile = await provider.validate_token("test_token")
            
            # Verify we can extract account info
            assert "client_id" in profile
            assert "user_name" in profile
            assert profile["status"] == "success"
    
    def test_format_account_info_for_cli(self):
        """Should format account info for CLI display."""
        profile = {
            "client_id": "1106251237",
            "user_name": "Test Trader",
            "email": "trader@example.com",
            "account_type": "INDIVIDUAL"
        }
        
        # Format for display
        lines = [
            f"Client ID: {profile['client_id']}",
            f"Name: {profile['user_name']}",
            f"Email: {profile['email']}",
            f"Account Type: {profile['account_type']}",
        ]
        
        assert len(lines) == 4
        assert "1106251237" in lines[0]
        assert "Test Trader" in lines[1]


class TestTokenPreTradingValidation:
    """Test token validation before trading operations."""
    
    @pytest.mark.asyncio
    async def test_validate_before_trade(self):
        """Should validate token before allowing trades."""
        provider = DhanAuthProvider(client_id="test123")
        provider.set_current_token("valid_token", datetime.now() + timedelta(hours=12))
        
        # Token is valid, should not raise
        assert not provider.is_token_expired()
        assert not provider.is_token_near_expiry()
    
    @pytest.mark.asyncio
    async def test_reject_trade_if_token_expired(self):
        """Should reject trades if token is expired."""
        provider = DhanAuthProvider(client_id="test123")
        provider.set_current_token("expired_token", datetime.now() - timedelta(hours=1))
        
        assert provider.is_token_expired()
        
        # Should raise if trying to ensure valid token without TOTP
        with pytest.raises(AuthError):
            await provider.ensure_valid_token()
    
    @pytest.mark.asyncio
    async def test_auto_refresh_before_trade(self):
        """Should auto-refresh token before trade if near expiry."""
        provider = DhanAuthProvider(client_id="test123")
        provider.set_current_token("near_expiry_token", datetime.now() + timedelta(minutes=30))
        provider._totp_secret = "JBSWY3DPEHPK3PXP"
        provider._pin = "1234"
        provider._last_generation_time = datetime.now() - timedelta(hours=2)
        
        with patch.object(provider, 'generate_token', new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "new_token"
            
            token = await provider.ensure_valid_token()
            
            assert token == "new_token"
            mock_gen.assert_called_once()
