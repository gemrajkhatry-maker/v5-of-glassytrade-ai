# Live Options Analytics Tests

## Overview

Comprehensive validation of **Options Analytics modules** using real DhanHQ broker data to ensure:
- ✅ Option chain contracts match expected format
- ✅ Greeks calculations work with real market prices
- ✅ IV surface construction from live option chains
- ✅ OI analytics and PCR validation
- ✅ Strike ladder and expiry verification
- ✅ Data quality (negative prices, OI, spacing)

---

## Test Suite Summary

| Category | Tests | Validates |
|----------|-------|-----------|
| **OptionChainContractValidation** | 3 | NIFTY, BANKNIFTY structure, expiry dates |
| **OptionChainEngineWithLiveData** | 2 | Chain construction, PCR calculation |
| **GreeksWithMarketData** | 2 | ATM Greeks, OTM vs ITM comparison |
| **IVSurfaceWithLiveData** | 1 | IV surface building from chain |
| **OIAnalyticsWithLiveData** | 2 | PCR validation, max OI strikes |
| **OptionsDataQuality** | 3 | Strike spacing, positive prices, non-negative OI |
| **TOTAL** | **13 tests** | Full options pipeline validation |

---

## Quick Start

### Option 1: Using Run Script

```bash
# Just verify tests load (will skip without credentials)
cd brokersv2/tests/integration
./run_options_live_tests.sh

# Run with credentials
export DHAN_CLIENT_ID="your_id"
export DHAN_ACCESS_TOKEN="your_token"
./run_options_live_tests.sh --run
```

### Option 2: Direct pytest

```bash
# Skip mode (verify tests load)
venv/bin/python -m pytest brokersv2/tests/integration/test_options_live_validation.py -v

# Run mode
export DHAN_CLIENT_ID="your_id"
export DHAN_ACCESS_TOKEN="your_token"
export RUN_OPTIONS_LIVE_TESTS=1
venv/bin/python -m pytest brokersv2/tests/integration/test_options_live_validation.py -v
```

---

## What Each Test Validates

### 1. TestOptionChainContractValidation

#### `test_nifty_option_chain_structure`
✅ **What it does**: Fetches NIFTY option chain from DhanHQ  
✅ **Validates**:
- Chain has underlying, expiry, strikes fields
- At least 10 strikes available
- Each strike has strike_price > 0
- Each strike has call and put contracts
- Call contract has ltp, oi, volume fields

**Expected outcome**: All assertions pass, chain structure matches contract

#### `test_banknifty_option_chain`
✅ **What it does**: Fetches BANKNIFTY option chain  
✅ **Validates**:
- Strikes are in 100 intervals (45000, 45100, 45200...)
- Structure same as NIFTY

**Expected outcome**: Strike prices divisible by 100

#### `test_option_expiry_dates`
✅ **What it does**: Fetches first 3 expiry dates  
✅ **Validates**:
- Expiry is in the future
- Expiry is on Thursday (weekly expiry)
- Dates are chronological

**Expected outcome**: All expiries valid, weekday = Thursday (3)

---

### 2. TestOptionChainEngineWithLiveData

#### `test_chain_engine_construction`
✅ **What it does**: 
1. Fetches live NIFTY option chain
2. Creates OptionChainEngine
3. Adds all call/put contracts
4. Builds chain with underlying price

✅ **Validates**:
- Options added successfully (>0)
- Strike count > 0
- ATM strike detected
- ATM strike within 1% of underlying price

**Expected outcome**: Engine fully populated, ATM strike accurate

#### `test_pcr_calculation`
✅ **What it does**: 
1. Fetches live chain
2. Loads OI data for all strikes
3. Calculates Put-Call Ratio

✅ **Validates**:
- PCR between 0.0 and 3.0 (reasonable range)
- Total call OI > 0 OR total put OI > 0

**Expected outcome**: PCR ~0.8-1.2 for NIFTY (varies by market sentiment)

---

### 3. TestGreeksWithMarketData

#### `test_atm_greeks`
✅ **What it does**: 
1. Fetches live chain
2. Finds ATM strike (closest to underlying price)
3. Calculates Greeks (delta, gamma, theta, vega)

✅ **Validates**:
- Delta between -1.0 and 1.0
- Gamma ≥ 0
- Theta < 0 (time decay)
- Vega > 0 (volatility sensitivity)
- ATM call delta between 0.3 and 0.7 (near 0.5)

**Expected outcome**: 
- Delta: ~0.5 for ATM call
- Gamma: highest for ATM
- Theta: -5 to -20 per day
- Vega: 10-30

#### `test_otm_vs_itm_greeks`
✅ **What it does**: 
1. Finds OTM and ITM strikes
2. Calculates Greeks for both
3. Compares delta values

✅ **Validates**:
- ITM delta > OTM delta
- Delta follows theoretical expectations

**Expected outcome**: ITM delta ~0.7-0.9, OTM delta ~0.1-0.3

---

### 4. TestIVSurfaceWithLiveData

#### `test_iv_surface_building`
✅ **What it does**: 
1. Fetches live option chain
2. Creates IVSurfaceEngine
3. Adds IV points for first 20 strikes

✅ **Validates**:
- IV points added (>0)
- Data point count > 0

**Expected outcome**: Surface populated with strike/IV pairs

---

### 5. TestOIAnalyticsWithLiveData

#### `test_oi_pcr_validation`
✅ **What it does**: 
1. Fetches live chain
2. Loads OI for all strikes
3. Calculates PCR at multiple strikes (low, ATM, high)

✅ **Validates**:
- PCR between 0.0 and 5.0 at each strike
- PCR varies across strikes (OTM vs ITM)

**Expected outcome**: 
- OTM puts: PCR > 1.0 (more put writing)
- ITM calls: PCR < 1.0 (more call writing)

#### `test_max_oi_strikes`
✅ **What it does**: 
1. Fetches live chain
2. Finds strike with max call OI (resistance)
3. Finds strike with max put OI (support)

✅ **Validates**:
- Max call strike found
- Max put strike found
- Different strikes (not same level)

**Expected outcome**: 
- Max call OI: Above current price (resistance)
- Max put OI: Below current price (support)

---

### 6. TestOptionsDataQuality

#### `test_strike_spacing`
✅ **What it does**: Validates strike price intervals  
✅ **Validates**:
- Strikes sorted ascending
- Spacing consistent: 50, 100, or 500

**Expected outcome**: NIFTY spacing = 50 or 100

#### `test_option_prices_positive`
✅ **What it does**: Checks all option LTP values  
✅ **Validates**:
- No negative prices
- All prices ≥ 0

**Expected outcome**: 0 negative prices found

#### `test_oi_non_negative`
✅ **What it does**: Checks all OI values  
✅ **Validates**:
- No negative OI
- All OI ≥ 0

**Expected outcome**: 0 negative OI values found

---

## Prerequisites

### 1. DhanHQ Account
- Active account with API access enabled
- Valid credentials (client_id + access_token)

### 2. Environment Setup

```bash
# Required
export DHAN_CLIENT_ID="your_client_id"
export DHAN_ACCESS_TOKEN="your_access_token"

# Enable live tests
export RUN_OPTIONS_LIVE_TESTS=1
```

### 3. Market Hours

**Options Analytics tests work ANYTIME** (even when market is closed):
- ✅ Option chain data available 24/7
- ✅ Historical data accessible
- ✅ OI data updated end-of-day

**Unlike order book tests, no live market needed!**

---

## Running Tests

### Run All 13 Tests

```bash
# Set credentials
export DHAN_CLIENT_ID="your_id"
export DHAN_ACCESS_TOKEN="your_token"
export RUN_OPTIONS_LIVE_TESTS=1

# Run
cd /Users/apple/Downloads/v5-of-glassytrade-ai
venv/bin/python -m pytest brokersv2/tests/integration/test_options_live_validation.py -v
```

### Run Specific Category

```bash
# Test contract structure only
venv/bin/python -m pytest brokersv2/tests/integration/test_options_live_validation.py::TestOptionChainContractValidation -v

# Test Greeks only
venv/bin/python -m pytest brokersv2/tests/integration/test_options_live_validation.py::TestGreeksWithMarketData -v

# Test data quality only
venv/bin/python -m pytest brokersv2/tests/integration/test_options_live_validation.py::TestOptionsDataQuality -v
```

### Run Single Test

```bash
# Test NIFTY chain structure
venv/bin/python -m pytest brokersv2/tests/integration/test_options_live_validation.py::TestOptionChainContractValidation::test_nifty_option_chain_structure -v
```

---

## Expected Results

### When Tests Pass ✅

```
13 passed in 8.45s
```

**Interpretation**:
- ✅ All option chain formats correct
- ✅ Greeks calculations valid
- ✅ PCR calculations accurate
- ✅ Data quality checks pass
- ✅ Analytics modules ready for production

### When Tests Fail ❌

#### Scenario 1: Invalid Credentials
```
FAILED test_nifty_option_chain_structure - Authentication failed
```
**Fix**: Check `DHAN_CLIENT_ID` and `DHAN_ACCESS_TOKEN` are correct

#### Scenario 2: Rate Limiting
```
FAILED test_banknifty_option_chain - Rate limit exceeded
```
**Fix**: Wait 1-2 minutes, retry. DhanHQ has API limits.

#### Scenario 3: Invalid Strike Spacing
```
FAILED test_strike_spacing - Unexpected strike spacing: 75
```
**Fix**: Check symbol name (NIFTY=50/100, BANKNIFTY=100)

#### Scenario 4: Negative Prices
```
FAILED test_option_prices_positive - Found 2 negative option prices
```
**Fix**: Data quality issue - investigate broker data source

---

## Troubleshooting

### Issue: All Tests Skip

**Check**:
```bash
echo $RUN_OPTIONS_LIVE_TESTS
# Should output: 1

echo $DHAN_CLIENT_ID
# Should output: your_client_id
```

**Fix**:
```bash
export RUN_OPTIONS_LIVE_TESTS=1
export DHAN_CLIENT_ID="your_id"
export DHAN_ACCESS_TOKEN="your_token"
```

### Issue: Connection Timeout

**Symptom**:
```
Failed to connect to DhanHQ API
```

**Fix**:
```bash
# Test connectivity
curl -X GET "https://api.dhan.co/v2/optionchain?symbol=NIFTY" \
  -H "access-token: $DHAN_ACCESS_TOKEN"
```

### Issue: Incomplete Option Chain

**Symptom**:
```
Expected >10 strikes, got 5
```

**Fix**: 
- Market may be closed (limited data)
- Try different expiry_index (0, 1, 2)
- Check DhanHQ API status

---

## Integration with Analytics Modules

These tests validate the following production modules:

| Test | Module | File |
|------|--------|------|
| Chain construction | OptionChainEngine | `analytics/options/chain.py` |
| PCR calculation | OptionChainEngine | `analytics/options/chain.py` |
| ATM Greeks | GreeksCalculator | `analytics/options/greeks.py` |
| IV surface | IVSurfaceEngine | `analytics/options/iv_surface.py` |
| OI analytics | OIAnalyzer | `analytics/options/oi_analytics.py` |
| Data quality | All modules | - |

---

## Safety Notes

⚠️ **Important**:
- ✅ **READ-ONLY** - No orders placed
- ✅ **No market impact** - Only data retrieval
- ✅ **Safe anytime** - Works 24/7
- ✅ **No trading limits** - Does not consume order limits
- ⚠️ **API quota** - May consume daily API limits (check DhanHQ dashboard)

---

## Test Data Flow

```
DhanHQ API
    ↓
Option Chain (strikes, calls, puts, OI)
    ↓
OptionChainEngine.build_chain()
    ↓
Analytics:
    - PCR calculation
    - ATM strike detection
    - Greeks (delta, gamma, theta, vega)
    - IV surface
    - OI analysis (support/resistance)
    ↓
Validation:
    - Format checks
    - Price ranges
    - Data quality
    - Mathematical validity
```

---

## Adding New Tests

When adding new options tests, follow this pattern:

```python
@pytest.mark.asyncio
async def test_your_options_feature(self, live_options_adapter):
    """Test your options analytics with live data."""
    
    # 1. Fetch live option chain
    chain = await live_options_adapter.get_option_chain(
        symbol="NIFTY",
        exchange="NSE",
        expiry_index=0,
    )
    
    # 2. Validate data structure
    assert chain is not None
    assert len(chain.strikes) > 0
    
    # 3. Feed into analytics module
    engine = YourOptionsEngine("NIFTY")
    engine.process(chain)
    
    # 4. Validate output
    assert engine.result > 0
    assert engine.metric == expected_value
```

---

## Production Readiness Checklist

After all 13 tests pass:

- [x] Option chain parsing works with real broker data
- [x] Greeks calculations mathematically valid
- [x] PCR calculations accurate
- [x] IV surface construction functional
- [x] OI analytics identify support/resistance
- [x] Data quality checks catch anomalies
- [x] Edge cases handled (negative prices, zero OI)
- [x] Strike spacing validation works
- [x] Expiry date validation correct
- [x] ATM/ITM/OTM classification accurate

**✅ Ready for production deployment!**

---

## Support

- **DhanHQ API Docs**: https://dhanhq.co/docs/v2/
- **API Status**: https://dhanhq.co/
- **Test Logs**: `pytest -v --log-cli-level=INFO`
- **Issues**: Check credentials, network, API limits
