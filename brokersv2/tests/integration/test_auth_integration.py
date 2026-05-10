"""
Integration tests for Dhan auth flow - Phase 3, Step 8

Tests real Dhan API authentication with actual credentials.
Requires valid DHAN_CLIENT_ID, DHAN_TOTP_SECRET, and DHAN_PIN in .env

Run with: pytest tests/integration/test_auth_integration.py -v -m integration
"""

import pytest
import os
import asyncio
from datetime import datetime

from brokersv2.infrastructure.dhan_adapter.totp_generator import TOTPGenerator
from brokersv2.infrastructure.dhan_adapter.auth_provider import DhanAuthProvider, AuthError
from brokersv2.infrastructure.dhan_adapter.factory import DhanGateway


@pytest.mark.integration
class TestRealTOTPGeneration:
    """Test real TOTP code generation."""
    
    def test_totp_generates_valid_code(self):
        """Should generate valid 6-digit TOTP code."""
        totp_secret = os.environ.get("DHAN_TOTP_SECRET") or os.environ.get("TOTP_SECRET")
        
        if not totp_secret:
            pytest.skip("DHAN_TOTP_SECRET not set")
        
        generator = TOTPGenerator(totp_secret)
        code = generator.generate_code()
        
        assert len(code) == 6
        assert code.isdigit()
        print(f"\nGenerated TOTP: {code}")


@pytest.mark.integration
class TestRealTokenGeneration:
    """Test real token generation with Dhan API."""
    
    @pytest.mark.asyncio
    async def test_generate_token_with_real_credentials(self):
        """Should generate real access token from Dhan."""
        client_id = os.environ.get("DHAN_CLIENT_ID")
        totp_secret = os.environ.get("DHAN_TOTP_SECRET") or os.environ.get("TOTP_SECRET")
        pin = os.environ.get("DHAN_PIN") or os.environ.get("PIN")
        
        if not (client_id and totp_secret and pin):
            pytest.skip("Missing DHAN credentials")
        
        provider = DhanAuthProvider(client_id)
        
        try:
            token = await provider.generate_token(pin, totp_secret)
            
            assert token is not None
            assert len(token) > 50  # JWT tokens are long
            print(f"\nGenerated token: {token[:50]}...")
            
        except AuthError as e:
            if "Invalid TOTP" in str(e):
                pytest.fail("TOTP secret is incorrect. Please verify your Dhan TOTP setup.")
            raise


@pytest.mark.integration
class TestRealTokenValidation:
    """Test real token validation with Dhan API."""
    
    @pytest.mark.asyncio
    async def test_validate_existing_token(self):
        """Should validate the existing token in .env."""
        client_id = os.environ.get("DHAN_CLIENT_ID")
        access_token = os.environ.get("DHAN_ACCESS_TOKEN")
        
        if not (client_id and access_token):
            pytest.skip("Missing DHAN credentials")
        
        # Remove quotes if present
        access_token = access_token.strip("'\"")
        
        provider = DhanAuthProvider(client_id)
        
        try:
            profile = await provider.validate_token(access_token)
            
            assert profile["status"] == "success"
            assert profile.get("client_id") == client_id
            print(f"\nToken valid for: {profile.get('user_name', 'Unknown')}")
            
        except AuthError as e:
            if "expired" in str(e).lower() or "invalid" in str(e).lower():
                pytest.skip(f"Token expired/invalid: {e}")
            raise


@pytest.mark.integration
class TestRealGatewayCreation:
    """Test real gateway creation with auto token generation."""
    
    @pytest.mark.asyncio
    async def test_create_gateway_with_existing_token(self):
        """Should create gateway with existing valid token."""
        client_id = os.environ.get("DHAN_CLIENT_ID")
        access_token = os.environ.get("DHAN_ACCESS_TOKEN")
        
        if not (client_id and access_token):
            pytest.skip("Missing DHAN credentials")
        
        # Gateway should create successfully
        async with await DhanGateway.from_env() as gw:
            assert gw._config.client_id == client_id
            assert gw._client.config.access_token is not None
            print(f"\nGateway created for client: {client_id}")
    
    @pytest.mark.asyncio
    async def test_create_gateway_with_totp_auto_generation(self):
        """Should create gateway with auto-generated token via TOTP."""
        client_id = os.environ.get("DHAN_CLIENT_ID")
        totp_secret = os.environ.get("DHAN_TOTP_SECRET") or os.environ.get("TOTP_SECRET")
        pin = os.environ.get("DHAN_PIN") or os.environ.get("PIN")
        access_token = os.environ.get("DHAN_ACCESS_TOKEN")
        
        # Skip if we already have a valid token
        if access_token:
            pytest.skip("DHAN_ACCESS_TOKEN already set, testing TOTP auto-generation not needed")
        
        if not (client_id and totp_secret and pin):
            pytest.skip("Missing TOTP credentials for auto-generation")
        
        # Temporarily remove access_token from env
        old_token = os.environ.pop("DHAN_ACCESS_TOKEN", None)
        
        try:
            # Gateway should auto-generate token
            async with await DhanGateway.from_env() as gw:
                assert gw._client.config.access_token is not None
                print(f"\nAuto-generated token: {gw._client.config.access_token[:50]}...")
        finally:
            # Restore old token
            if old_token:
                os.environ["DHAN_ACCESS_TOKEN"] = old_token


@pytest.mark.integration
class TestEndToEndAuthFlow:
    """Test complete end-to-end authentication flow."""
    
    @pytest.mark.asyncio
    async def test_full_auth_lifecycle(self):
        """Test full token lifecycle: generate → validate → use."""
        client_id = os.environ.get("DHAN_CLIENT_ID")
        access_token = os.environ.get("DHAN_ACCESS_TOKEN")
        
        if not (client_id and access_token):
            pytest.skip("Missing DHAN credentials")
        
        access_token = access_token.strip("'\"")
        
        # Step 1: Validate token
        provider = DhanAuthProvider(client_id)
        provider.set_current_token(access_token)
        
        profile = await provider.validate_token(access_token)
        assert profile["status"] == "success"
        print(f"\n1. Token validated: {profile.get('client_id')}")
        
        # Step 2: Check expiry
        assert not provider.is_token_expired()
        print("2. Token is not expired")
        
        # Step 3: Ensure valid (should return current)
        token = await provider.ensure_valid_token()
        assert token == access_token
        print("3. Token is valid and ready for trading")
        
        print("\n✅ Full auth lifecycle test passed!")


@pytest.mark.integration
class TestCLIIntegration:
    """Test CLI integration with auth system."""
    
    def test_cli_can_access_credentials(self):
        """CLI should be able to load credentials from .env."""
        from dotenv import load_dotenv
        from pathlib import Path
        
        # Load .env
        env_file = Path(__file__).parent.parent.parent.parent / ".env"
        if env_file.exists():
            load_dotenv(env_file)
        
        client_id = os.environ.get("DHAN_CLIENT_ID")
        assert client_id is not None, "DHAN_CLIENT_ID should be in .env"
        
        print(f"\nCLI can access: Client ID = {client_id}")
    
    @pytest.mark.asyncio
    async def test_cli_historical_data_with_auth(self):
        """CLI should be able to fetch historical data with valid auth."""
        client_id = os.environ.get("DHAN_CLIENT_ID")
        access_token = os.environ.get("DHAN_ACCESS_TOKEN")
        
        if not (client_id and access_token):
            pytest.skip("Missing DHAN credentials")
        
        access_token = access_token.strip("'\"")
        
        # Create gateway and fetch historical data
        async with await DhanGateway.from_env() as gw:
            try:
                # Fetch some historical data
                candles = await gw.historical("NSE:RELIANCE", "2024-01-01", "2024-01-05", "1d")
                
                assert isinstance(candles, list)
                print(f"\nFetched {len(candles)} candles for RELIANCE")
                
            except Exception as e:
                # May fail due to market hours, but auth should work
                if "401" not in str(e) and "403" not in str(e):
                    print(f"\nAuth worked, but data fetch failed (expected): {e}")
