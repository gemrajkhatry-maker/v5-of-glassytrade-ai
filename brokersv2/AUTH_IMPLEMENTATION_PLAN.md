# TDD Implementation Plan: Dhan Auto Token Generation

## Context
- **Package Available**: `dhanhq` (installed in project venv)
- **TOTP Package**: `pyotp` (installed)
- **Old Implementation**: `brokers/` has working code but uses custom HTTP, DO NOT PORT
- **New Approach**: Use `dhanhq.auth.DhanLogin` as the foundation

## DhanHQ Package Capabilities (from `dhanhq.auth.DhanLogin`)

### Available Methods:
```python
DhanLogin(client_id)
  ├── generate_token(pin, totp)           # TOTP-based auth
  ├── renew_token(access_token)            # Token renewal
  ├── user_profile(access_token)           # Token validation
  ├── generate_login_session(app_id, app_secret)  # OAuth flow (step 1-2)
  ├── consume_token_id(token_id, app_id, app_secret)  # OAuth flow (step 3)
  ├── set_ip(access_token, ip, ip_flag)   # Static IP management
  ├── modify_ip(access_token, ip, ip_flag) # IP modification
  └── get_ip(access_token)                 # Get current IPs
```

## Implementation Plan (TDD Approach)

### Phase 1: TOTP Token Generation (P0 CRITICAL)

#### Step 1: TOTP Code Generator
**File**: `brokersv2/infrastructure/dhan_adapter/totp_generator.py`

**Tests First** (`tests/unit/test_totp_generator.py`):
1. ✅ `test_generate_totp_from_secret` - Generate valid 6-digit TOTP
2. ✅ `test_totp_changes_over_time` - TOTP changes every 30s
3. ✅ `test_invalid_secret_raises_error` - Bad secret handling
4. ✅ `test_totp_format_is_6_digits` - Always 6 digits with leading zeros

**Implementation**:
```python
class TOTPGenerator:
    def __init__(self, secret: str)
    def generate_code(self) -> str  # Returns 6-digit code
    def get_current_window(self) -> int  # Current time window
```

#### Step 2: Auth Provider
**File**: `brokersv2/infrastructure/dhan_adapter/auth_provider.py`

**Tests First** (`tests/unit/test_auth_provider.py`):
1. ✅ `test_generate_token_with_totp` - Full TOTP flow using `dhanhq.auth.DhanLogin`
2. ✅ `test_generate_token_stores_credentials` - Persist totp_secret, pin
3. ✅ `test_renew_token_success` - Renew active token
4. ✅ `test_renew_expired_token_fails` - Cannot renew expired
5. ✅ `test_ensure_valid_token_renews_near_expiry` - Proactive refresh (<1hr)
6. ✅ `test_ensure_valid_token_regenerates_expired` - New token if expired
7. ✅ `test_token_generation_cooldown` - 2-min rate limit enforcement
8. ✅ `test_persist_token_to_env` - Save token to .env file
9. ✅ `test_load_token_from_env` - Load existing token on startup

**Implementation**:
```python
class DhanAuthProvider:
    def __init__(self, client_id: str, http_client=None)
    
    # Core methods
    async def generate_token(self, pin: str, totp_secret: str) -> str
    async def renew_token(self, access_token: str) -> str
    async def ensure_valid_token(self) -> str  # Smart refresh logic
    
    # State management
    def set_totp_secret(self, secret: str)
    def set_pin(self, pin: str)
    def is_token_near_expiry(self) -> bool
    def is_token_expired(self) -> bool
    
    # Persistence
    def _persist_token(self, token: str, expiry: datetime)
    def _load_saved_token(self) -> Optional[str]
    
    # Rate limiting
    def _check_generation_cooldown(self)
```

#### Step 3: Wire Auth into DhanHttpClient
**File**: `brokersv2/infrastructure/dhan_adapter/client.py` (modify)

**Tests First** (`tests/unit/test_client_auth_integration.py`):
1. ✅ `test_client_uses_auth_provider_token` - Token from auth provider
2. ✅ `test_client_updates_token_on_refresh` - Token refresh propagation
3. ✅ `test_client_handles_401_with_auto_refresh` - Auto-retry on 401

**Implementation**:
- Add `auth_provider` parameter to `DhanHttpClient.__init__`
- Add `_on_token_refreshed` callback
- Update `_headers` when token refreshes
- Auto-retry on 401 with fresh token

#### Step 4: Update Factory to Use Auth Provider
**File**: `brokersv2/infrastructure/dhan_adapter/factory.py` (modify)

**Tests First** (`tests/unit/test_factory_auth_integration.py`):
1. ✅ `test_from_env_with_access_token_uses_it` - Direct token
2. ✅ `test_from_env_with_totp_generates_token` - TOTP flow
3. ✅ `test_from_env_without_credentials_raises` - Validation
4. ✅ `test_gateway_initializes_auth_provider` - Wiring test

**Implementation**:
```python
@classmethod
def from_env(cls, prefix="DHAN_"):
    access_token = os.environ.get(f"{prefix}ACCESS_TOKEN")
    
    if not access_token:
        # Use auth provider to generate
        totp_secret = os.environ.get(f"{prefix}TOTP_SECRET")
        pin = os.environ.get(f"{prefix}PIN")
        
        if not (totp_secret and pin):
            raise ValueError("Missing ACCESS_TOKEN or TOTP_SECRET+PIN")
        
        # Generate token
        auth = DhanAuthProvider(client_id)
        access_token = await auth.generate_token(pin, totp_secret)
    
    return cls(client_id=client_id, access_token=access_token, ...)
```

### Phase 2: Token Lifecycle Management (P1)

#### Step 5: Background Token Refresh
**File**: `brokersv2/infrastructure/dhan_adapter/token_refresh_scheduler.py`

**Tests First** (`tests/unit/test_token_refresh.py`):
1. ✅ `test_schedules_refresh_at_near_expiry`
2. ✅ `test_refresh_succeeds_and_updates_client`
3. ✅ `test_refresh_failure_logs_error`
4. ✅ `test_scheduler_starts_on_gateway_init`

**Implementation**:
```python
class TokenRefreshScheduler:
    def __init__(self, auth_provider, http_client)
    async def start(self)  # Background task
    async def _refresh_loop(self)  # Check every 5 min
    async def _refresh_if_needed(self)  # Smart refresh
```

#### Step 6: User Profile Validation
**Tests First** (`tests/unit/test_user_profile.py`):
1. ✅ `test_validate_token_valid`
2. ✅ `test_validate_token_expired`
3. ✅ `test_validate_token_invalid`

**Implementation**: Use `dhanhq.auth.DhanLogin.user_profile()`

### Phase 3: Integration & End-to-End Tests (P1)

#### Step 7: Full Auth Flow Integration
**File**: `tests/integration/test_auth_flow.py`

**Tests**:
1. ✅ `test_full_totp_auth_flow` - Generate token with real Dhan API (skip if no credentials)
2. ✅ `test_token_renewal_flow` - Renew then use
3. ✅ `test_auto_refresh_on_401` - Integration test
4. ✅ `test_cli_works_with_totp` - End-to-end CLI test

### Test Execution Strategy

**Red-Green-Refactor Cycle**:
```bash
# 1. Write failing test
/Users/apple/Downloads/v5-of-glassytrade-ai/venv/bin/python -m pytest tests/unit/test_totp_generator.py -v

# 2. Implement minimal code to pass

# 3. Refactor with confidence (all tests pass)

# 4. Move to next test
```

**Test Markers**:
- `@pytest.mark.unit` - Fast unit tests (no network)
- `@pytest.mark.integration` - Real Dhan API (requires credentials)
- `@pytest.mark.slow` - Token lifecycle tests (time-based)

## Files to Create/Modify

### New Files (7):
1. `brokersv2/infrastructure/dhan_adapter/totp_generator.py`
2. `brokersv2/infrastructure/dhan_adapter/auth_provider.py`
3. `brokersv2/infrastructure/dhan_adapter/token_refresh_scheduler.py`
4. `tests/unit/test_totp_generator.py`
5. `tests/unit/test_auth_provider.py`
6. `tests/unit/test_client_auth_integration.py`
7. `tests/unit/test_factory_auth_integration.py`

### Modified Files (3):
1. `brokersv2/infrastructure/dhan_adapter/client.py` - Add auth_provider wiring
2. `brokersv2/infrastructure/dhan_adapter/factory.py` - Use auth provider
3. `brokersv2/app/bootstrap.py` - Initialize auth provider

## Dependencies
- ✅ `dhanhq` - Already installed
- ✅ `pyotp` - Already installed
- ✅ `python-dotenv` - Already installed (for token persistence)

## Success Criteria
- ✅ All unit tests pass (15+ tests)
- ✅ Integration tests pass with real credentials
- ✅ CLI works with TOTP_SECRET + PIN (no manual token generation)
- ✅ Auto token refresh works (<1hr before expiry)
- ✅ Token persists to .env across restarts
- ✅ 2-min cooldown enforced between token generations

## Estimated Timeline
- **Phase 1 (P0)**: 2-3 hours (TOTP generation + auth provider)
- **Phase 2 (P1)**: 1-2 hours (Background refresh + profile)
- **Phase 3 (P1)**: 1 hour (Integration tests)
- **Total**: 4-6 hours

## Risks & Mitigations
1. **Risk**: Dhan API rate limits (2-min cooldown)
   - **Mitigation**: Mock in unit tests, use real API only in integration tests
   
2. **Risk**: TOTP time drift
   - **Mitigation**: pyotp handles this, add retry with adjacent time windows
   
3. **Risk**: Token persistence security
   - **Mitigation**: Only write to .env file, never log tokens

## Next Steps
1. ✅ Start with Phase 1, Step 1 (TOTP Generator tests)
2. ✅ Implement TOTPGenerator class
3. ✅ Move to Auth Provider tests
4. ✅ Wire everything together
5. ✅ Run integration tests with real credentials
