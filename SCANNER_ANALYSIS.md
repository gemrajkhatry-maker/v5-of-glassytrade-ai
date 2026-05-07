# Backend Scanner Analysis - How It Works

**Date**: 2026-05-06  
**Component**: OptionScannerService + DhanAdapter  
**Status**: Understanding complete

---

## Scanner Flow Overview

```
Backend Startup
    ↓
main.py lifespan()
    ↓
Create DhanAdapter (broker connection)
    ↓
Create OptionScannerService
    ↓
Call scanner.scan_top_n()  ← THIS IS BLOCKING
    ↓
For each underlying (CRUDEOIL, NATURALGAS, etc.):
    ↓
    Call broker.get_option_chain()
    ↓
    DhanAdapter makes HTTP request to Dhan API
    ↓
    Parse option chain data
    ↓
    Score each contract (OI, volume, momentum)
    ↓
Return top N scored symbols
    ↓
Set app.state.active_symbols
```

---

## Detailed Component Analysis

### 1. OptionScannerService

**Location**: `backendv2/app/domain/fabio_ai/services/option_scanner.py`

**Purpose**: Scans underlying assets and scores option contracts based on momentum, OI, and volume.

**Key Methods**:

#### `scan_top_n(n=3, underlyings, exchange, ...)`
- Entry point called during startup
- Iterates through each underlying (CRUDEOIL, NATURALGAS, NIFTY, etc.)
- Calls `_scan_underlying_for_contracts()` for each
- Ranks results by score
- Returns top N contracts

**Supported Underlyings**:
```python
# NSE
_SCAN_NSE_UNDERLYINGS = {"NIFTY", "BANKNIFTY", "FINNIFTY"}

# MCX
_SCAN_MCX_UNDERLYINGS = {
    "CRUDEOIL", "NATURALGAS", "GOLD", "SILVER",
    "GOLDM", "SILVERM", "CRUDEOILM"
}
```

#### `_scan_underlying_for_contracts(underlying, exchange, expiry_index, ...)`
- For each underlying:
  1. Determines exchange (NFO for NSE, MCX for MCX)
  2. **Calls `broker.get_option_chain()`** ← THIS IS THE BLOCKING CALL
  3. Finds valid expiry (skips expired contracts)
  4. Gets ATM strike and nearby strikes (±2 strikes)
  5. Detects momentum bias (bullish/bearish)
  6. Scores each contract (CE and PE)
  7. Returns list of ScanResult

**Scoring Factors**:
- Open Interest (OI) - higher is better
- Volume - liquidity indicator
- Distance from ATM - prefers near-ATM
- Momentum bias - trend direction
- Bid/ask spread - tightness indicates liquidity

---

### 2. DhanAdapter.get_option_chain()

**Location**: `backendv2/app/infrastructure/adapters/dhan_adapter.py`

**Purpose**: Fetches option chain from Dhan broker API.

**Flow**:
```python
def get_option_chain(underlying, exchange="NFO", expiry_index=0):
    1. Check cache (TTL: 30 seconds)
    2. If cache miss:
       a. Make HTTP GET to /api/options/chain
       b. Params: {underlying, exchange, expiry_index}
       c. Wait for response
    3. Parse response into OptionChain object
    4. Cache result
    5. Return chain
```

**HTTP Request**:
```python
response = self._client.get(
    "/api/options/chain",
    params={
        "underlying": underlying,  # e.g., "CRUDEOIL"
        "exchange": exchange,       # e.g., "MCX"
        "expiry_index": expiry_index  # 0 = nearest expiry
    }
)
```

**Blocking Behavior**:
- Uses `_run_sync()` to convert async HTTP to sync
- Creates ThreadPoolExecutor for each call
- **NO TIMEOUT** on HTTP request ← POTENTIAL ISSUE
- Will hang indefinitely if Dhan API doesn't respond

---

### 3. Startup Sequence in main.py

**Location**: `backendv2/app/api/main.py` (lines 147-160)

```python
try:
    # Create scanner service
    scanner_service = OptionScannerService(
        market_data,  # DhanAdapter instance
        default_underlyings=list(configured_symbols)
    )
    
    # Run scanner synchronously during startup
    async_scan_result = await asyncio.get_running_loop().run_in_executor(
        None,
        scanner_service.scan_top_n,
        top_n,                      # 3
        configured_symbols,          # ["CRUDEOIL", "NATURALGAS"]
        None,                        # preferred_option_type
        top_per_underlying,          # 2
        "MCX",                       # exchange (if MCX mode)
        expiry_index,                # 0
        strikes_around_atm,          # 2
    )
    
    # Extract symbols from results
    symbols = [r.symbol for r in async_scan_result[:top_n]]
    
    # Update app state
    if symbols:
        application.state.active_symbols = symbols
```

**Problem**: This runs **during startup** in the lifespan context manager. If the scanner hangs, the entire backend startup hangs.

---

## Why Backend Might Hang on Startup

### Root Cause Analysis

**Scenario 1: Dhan API Timeout**
- Dhan API doesn't respond to `/api/options/chain`
- HTTP client waits indefinitely (no timeout configured)
- Scanner blocks forever
- Backend never finishes startup

**Scenario 2: Invalid Access Token**
- `DHAN_ACCESS_TOKEN` is expired or invalid
- Dhan API returns 401/403 error
- `get_option_chain()` returns None
- Scanner continues but returns empty results
- Falls back to configured symbols

**Scenario 3: Network Issue**
- Can't reach `api.dhan.co`
- DNS resolution fails
- TCP connection hangs
- No timeout → infinite wait

**Scenario 4: MCX Market Closed**
- MCX session: 09:00 - 23:15 IST
- If scanner runs outside session, API might return empty data
- Scanner handles gracefully but returns no symbols

---

## Current Configuration

### Environment Variables
```bash
GLASSYTRADE_STRATEGY=mcx_options
DHAN_CLIENT_ID=1106251237
DHAN_ACCESS_TOKEN=eyJ0eXAiOiJKV1Qi...
DEFAULT_EXCHANGE=NSE  # ← This is being overridden
```

### Config (base.yaml)
```yaml
scanner:
  mode: "mcx_options"
  top_n: 3
  top_per_underlying: 2
  strikes_around_atm: 2
  expiry_index: 0

exchanges:
  MCX:
    enabled: true
    symbols:
      CRUDEOIL:
        enabled: true
        lot_size: 100
      NATURALGAS:
        enabled: true
        lot_size: 1250
```

---

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    BACKEND STARTUP                        │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  1. Create DhanAdapter                                   │
│     - HTTP client initialized                            │
│     - Access token set                                   │
│     - Symbols: [CRUDEOIL, NATURALGAS]                    │
│                                                          │
│  2. Create OptionScannerService                          │
│     - Broker: DhanAdapter                                │
│     - Underlyings: [CRUDEOIL, NATURALGAS]                │
│                                                          │
│  3. Call scanner.scan_top_n()                            │
│     ↓                                                     │
│     For CRUDEOIL:                                        │
│       ↓                                                   │
│       get_option_chain("CRUDEOIL", "MCX", 0)            │
│         ↓                                                 │
│         HTTP GET /api/options/chain                     │
│           ?underlying=CRUDEOIL                          │
│           &exchange=MCX                                 │
│           &expiry_index=0                               │
│         ↓                                                 │
│         [WAITING FOR RESPONSE...] ← POTENTIAL HANG      │
│         ↓                                                 │
│         Parse response → OptionChain                     │
│           - ATM strike: 6200                             │
│           - Calls: {6100, 6150, 6200, 6250, 6300}       │
│           - Puts: {6100, 6150, 6200, 6250, 6300}        │
│         ↓                                                 │
│         Score each contract                              │
│           - CRUDEOIL 06 JUN 6200 CE: score=92           │
│           - CRUDEOIL 06 JUN 6200 PE: score=85           │
│           - CRUDEOIL 06 JUN 6250 CE: score=78           │
│                                                          │
│     For NATURALGAS:                                      │
│       [Same flow...]                                     │
│                                                          │
│  4. Rank all results by score                            │
│     - CRUDEOIL 06 JUN 6200 CE: 92                        │
│     - NATURALGAS 06 JUN 285 CE: 88                       │
│     - CRUDEOIL 06 JUN 6200 PE: 85                        │
│                                                          │
│  5. Take top 3                                           │
│     active_symbols = [                                   │
│       "CRUDEOIL 06 JUN 6200 CE",                         │
│       "NATURALGAS 06 JUN 285 CE",                        │
│       "CRUDEOIL 06 JUN 6200 PE"                          │
│     ]                                                     │
│                                                          │
│  6. Update app.state                                     │
│     - active_symbols set                                 │
│     - scanner_status updated                             │
│     - ContractGuard records first contract               │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

---

## Key Issues Identified

### ❌ Issue 1: No HTTP Timeout
**Location**: `dhan_adapter.py` line 326-335

**Problem**: HTTP request to Dhan API has no timeout. If API hangs, scanner hangs forever.

**Fix**: Add timeout to HTTP client
```python
self._client = httpx.AsyncClient(
    base_url=self._base_url,
    timeout=httpx.Timeout(30.0, connect=10.0),  # 30s total, 10s connect
    ...
)
```

### ❌ Issue 2: Scanner Runs During Startup
**Location**: `main.py` line 150-160

**Problem**: Scanner blocks startup. If it hangs, backend never starts.

**Fix Options**:
1. Run scanner asynchronously after startup
2. Add timeout to scanner execution
3. Start with configured symbols, update when scanner completes

### ⚠️ Issue 3: Exchange Selection Logic
**Location**: `main.py` line 83-109

**Problem**: Iterates exchanges dict and picks first enabled (NSE comes before MCX).

**Fix Applied**: Added GLASSYTRADE_STRATEGY check to force correct exchange.

### ⚠️ Issue 4: Access Token Expiry
**Location**: `.env` file

**Problem**: `DHAN_ACCESS_TOKEN` expires periodically. When expired, scanner returns None.

**Current Token**: Saved at `1777882507` (check if still valid)

**Fix**: Implement token refresh logic or detect expiry and warn.

---

## Scanner API Endpoints

### GET `/api/scanner/status`
Returns current scanner state:
```json
{
  "active_symbols": ["CRUDEOIL 06 JUN 6200 CE", ...],
  "contract_guard": {
    "current_contract": "CRUDEOIL 06 JUN 6200 CE"
  },
  "scanner": {
    "last_scan_time": "2026-05-06T18:00:00",
    "result_count": 3,
    "parameters": {
      "n": 3,
      "exchange": "MCX",
      "underlyings": ["CRUDEOIL", "NATURALGAS"]
    }
  }
}
```

### POST `/api/scanner/rescan?n=3`
Triggers manual rescan:
- Runs scanner synchronously
- Updates `app.state.active_symbols`
- Returns new symbols

---

## Recommendations

### Immediate Fixes
1. **Add HTTP timeout** to DhanAdapter (30 seconds)
2. **Run scanner async** - don't block startup
3. **Add timeout to scanner** - fallback to configured symbols if it takes > 60s
4. **Log scanner progress** - see which underlying is being scanned

### Short Term
1. **Add circuit breaker** to scanner - if Dhan API fails, skip scanner
2. **Implement token refresh** - auto-refresh Dhan access token
3. **Add scanner health check** - monitor if scanner is working
4. **Cache option chains** - reduce API calls (already implemented, 30s TTL)

### Long Term
1. **WebSocket streaming** - stream scanner results instead of polling
2. **Parallel scanning** - scan all underlyings simultaneously (already supported via `OPTION_SCANNER_PARALLEL_UNDERLYINGS`)
3. **Scanner metrics** - track scan time, success rate, API latency

---

## Testing the Scanner

### Manual Test
```bash
# Start backend
cd backendv2
GLASSYTRADE_STRATEGY=mcx_options PYTHONPATH=. ../venv/bin/python -m uvicorn app.api.main:app --port 9090

# Check scanner status
curl http://localhost:9090/api/scanner/status | python3 -m json.tool

# Trigger manual rescan
curl -X POST "http://localhost:9090/api/scanner/rescan?n=3" | python3 -m json.tool
```

### Check Dhan API Connectivity
```python
# Test script
import httpx
client = httpx.AsyncClient(
    base_url="https://api.dhan.co",
    headers={"access-token": "YOUR_TOKEN", "x-client-id": "YOUR_CLIENT_ID"}
)
response = await client.get("/api/options/chain", params={
    "underlying": "CRUDEOIL",
    "exchange": "MCX",
    "expiry_index": 0
})
print(response.status_code, response.json())
```

---

## Summary

**How Scanner Works**:
1. Startup creates DhanAdapter with broker credentials
2. OptionScannerService scans configured underlyings
3. For each underlying, fetches option chain from Dhan API
4. Scores contracts based on OI, volume, momentum
5. Returns top N contracts as active_symbols
6. Frontend uses these symbols for trading

**Why It Might Hang**:
- Dhan API not responding (no timeout)
- Invalid/expired access token
- Network connectivity issues
- Market closed (no data available)

**Current Status**:
- Scanner code is solid and well-structured
- Has caching, parallel scanning support
- Missing: timeout, async execution, error recovery

**Next Steps**:
1. Add HTTP timeout to prevent hangs
2. Run scanner async after startup
3. Add better error handling and logging
4. Test with live Dhan credentials

---

**Analysis Complete**: Scanner architecture understood, issues identified, fixes proposed.
