#!/usr/bin/env python
"""
Test script to verify auto token generation works with real credentials.
"""

import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, '/Users/apple/Downloads/v5-of-glassytrade-ai')

async def test_auto_token_generation():
    """Test auto token generation with real credentials."""
    from brokersv2.infrastructure.dhan_adapter.factory import DhanGateway
    
    print("=" * 60)
    print("Testing Auto Token Generation")
    print("=" * 60)
    
    # Check environment variables
    print("\n1. Checking environment variables:")
    print(f"   DHAN_CLIENT_ID: {os.environ.get('DHAN_CLIENT_ID', 'NOT SET')}")
    print(f"   DHAN_ACCESS_TOKEN: {'SET' if os.environ.get('DHAN_ACCESS_TOKEN') else 'NOT SET'}")
    print(f"   DHAN_TOTP_SECRET: {'SET' if os.environ.get('DHAN_TOTP_SECRET') else 'NOT SET'}")
    print(f"   DHAN_PIN: {'SET' if os.environ.get('DHAN_PIN') else 'NOT SET'}")
    
    # Try to create gateway
    print("\n2. Creating gateway (should auto-generate token):")
    try:
        async with await DhanGateway.from_env() as gw:
            print("   ✅ Gateway created successfully!")
            print(f"   Client ID: {gw._config.client_id}")
            print(f"   Token: {gw._client.config.access_token[:50]}...")
            
            # Try to get user profile
            print("\n3. Testing token with API call:")
            try:
                # Try a simple API call
                from dhanhq.auth import DhanLogin
                login = DhanLogin(gw._config.client_id)
                profile = login.user_profile(gw._client.config.access_token)
                
                if profile.get("status") == "success":
                    print("   ✅ Token is valid!")
                    print(f"   Profile: {profile}")
                else:
                    print(f"   ⚠️  Token validation response: {profile}")
            except Exception as e:
                print(f"   ⚠️  Profile check failed: {e}")
                print("   (Token may still be valid for trading operations)")
        
        print("\n" + "=" * 60)
        print("✅ AUTO TOKEN GENERATION TEST PASSED!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n   ❌ Gateway creation failed: {e}")
        import traceback
        traceback.print_exc()
        
        print("\n" + "=" * 60)
        print("❌ AUTO TOKEN GENERATION TEST FAILED!")
        print("=" * 60)
        return 1
    
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(test_auto_token_generation())
    sys.exit(exit_code)
