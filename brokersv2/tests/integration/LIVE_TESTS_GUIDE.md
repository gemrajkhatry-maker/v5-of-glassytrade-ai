# Live Integration Tests - Analytics Modules

## Overview

These tests validate analytics modules against **real market data** from DhanHQ broker to ensure:
- ✅ Data format matches expected contracts
- ✅ Analytics calculations work with real prices/volumes
- ✅ Edge cases in live data are handled correctly
- ✅ End-to-end pipeline works (Broker → Analytics → Results)

---

## Test Coverage

| Module | Tests | What's Validated |
|--------|-------|------------------|
| **LiveDataValidation** | 3 | Historical data, option chain, market quotes format |
| **OrderBookWithLiveData** | 1 | Order book reconstruction from real market depth |
| **OptionsAnalyticsWithLiveData** | 2 | Option chain engine, Greeks with real prices |
| **DeltaAnalyticsWithLiveData** | 1 | Delta calculations from intraday candles |
| **MarketProfileWithLiveData** | 1 | Volume profile from real 5-minute data |
| **LiveDataQuality** | 2 | Data completeness, expiry validation |
| **TOTAL** | **10 tests** | Full analytics pipeline validation |

---

## Prerequisites

### 1. DhanHQ Account
- Active DhanHQ account with API access
- Valid `client_id` and `access_token`

### 2. Environment Variables

```bash
# Required credentials
export DHAN_CLIENT_ID="your_client_id"
export DHAN_ACCESS_TOKEN="your_access_token"

# Enable live tests
export RUN_LIVE_ANALYTICS_TESTS=1

# Optional: Symbol configuration
export DHAN_LIVE_TEST_SYMBOL="NIFTY"
export DHAN_LIVE_TEST_EXCHANGE="NSE"
```

### 3. Market Hours

Some tests require market to be open:
- **Order Book tests**: Need live market depth (market hours only)
- **Historical data tests**: Work anytime (uses past data)
- **Option chain tests**: Work anytime (uses current chain)

---

## Running Tests

### Run All Live Tests

```bash
# Set environment
export DHAN_CLIENT_ID="your_id"
export DHAN_ACCESS_TOKEN="your_token"
export RUN_LIVE_ANALYTICS_TESTS=1

# Run all live tests
cd /Users/apple/Downloads/v5-of-glassytrade-ai
venv/bin/python -m pytest brokersv2/tests/integration/test_analytics_live.py -v
```

### Run Specific Test Categories

```bash
# Test data format validation only
venv/bin/python -m pytest brokersv2/tests/integration/test_analytics_live.py::TestLiveDataValidation -v

# Test options analytics
venv/bin/python -m pytest brokersv2/tests/integration/test_analytics_live.py::TestOptionsAnalyticsWithLiveData -v

# Test data quality
venv/bin/python -m pytest brokersv2/tests/integration/test_analytics_live.py::TestLiveDataQuality -v
```

### Run Without Credentials (Verify Skip)

```bash
# Should skip all tests gracefully
venv/bin/python -m pytest brokersv2/tests/integration/test_analytics_live.py -v
# Expected: 10 skipped
```

---

## What Each Test Validates

### 1. TestLiveDataValidation

#### `test_historical_data_format`
- ✅ Fetches 30 days of NIFTY daily candles
- ✅ Validates OHLCV structure
- ✅ Checks price ranges (15000-25000 for NIFTY)
- ✅ Ensures data is not empty

#### `test_option_chain_format`
- ✅ Fetches NIFTY option chain (nearest expiry)
- ✅ Validates strike structure (call + put)
- ✅ Ensures strikes list is populated

#### `test_market_quote_format`
- ✅ Fetches RELIANCE live quote
- ✅ Validates LTP, OHLC, volume fields
- ✅ Checks price range (2000-4000 for RELIANCE)

### 2. TestOrderBookWithLiveData

#### `test_order_book_reconstruction`
- ✅ Fetches real market depth for INFY
- ✅ Validates bid/ask ladder structure
- ✅ Builds OrderBookEngine from live data
- ✅ Checks spread > 0
- ✅ Ensures best_bid > best_ask (normal market)

### 3. TestOptionsAnalyticsWithLiveData

#### `test_option_chain_engine_with_live_data`
- ✅ Fetches real NIFTY option chain
- ✅ Populates OptionChainEngine with live contracts
- ✅ Builds chain with underlying price
- ✅ Validates ATM strike detection
- ✅ Checks PCR is reasonable (0.0 - 3.0)

#### `test_greeks_with_market_prices`
- ✅ Finds ATM strike from live chain
- ✅ Calculates Greeks (delta, gamma, theta, vega)
- ✅ Validates delta range (-1.0 to 1.0)
- ✅ Ensures gamma ≥ 0, theta < 0, vega > 0

### 4. TestDeltaAnalyticsWithLiveData

#### `test_delta_calculation_with_real_trades`
- ✅ Fetches 1-minute intraday candles
- ✅ Creates TradeEvent from each candle
- ✅ Classifies buy/sell based on price direction
- ✅ Validates delta = buy_volume - sell_volume
- ✅ Ensures volumes are non-negative

### 5. TestMarketProfileWithLiveData

#### `test_volume_profile_with_real_data`
- ✅ Fetches 5-minute RELIANCE intraday data
- ✅ Builds VolumeProfileEngine from real prices
- ✅ Validates total volume > 0
- ✅ Checks POC is valid price
- ✅ Ensures VAH > VAL

### 6. TestLiveDataQuality

#### `test_historical_data_completeness`
- ✅ Fetches 10 days of daily data
- ✅ Validates at least 7 trading days
- ✅ Checks chronological order
- ✅ Detects gaps in data

#### `test_option_expiry_dates_valid`
- ✅ Fetches option chain expiry
- ✅ Validates expiry is in the future
- ✅ Catches expired contracts

---

## Expected Outcomes

### When Tests Pass ✅
```
10 passed in 15.32s
```
- All analytics modules work correctly with real data
- Data formats match expected contracts
- Calculations are mathematically valid

### When Tests Fail ❌

#### Common Failure Modes:

1. **Invalid Credentials**
   ```
   FAILED test_historical_data_format - Authentication failed
   ```
   **Fix**: Check `DHAN_CLIENT_ID` and `DHAN_ACCESS_TOKEN`

2. **Market Closed (Order Book tests)**
   ```
   FAILED test_order_book_reconstruction - No market depth available
   ```
   **Fix**: Run during market hours (9:15 AM - 3:30 PM IST)

3. **Invalid Price Ranges**
   ```
   FAILED test_market_quote_format - Invalid RELIANCE price: 5000
   ```
   **Fix**: Check data source, price may be adjusted (splits/dividends)

4. **Empty Data**
   ```
   FAILED test_historical_data_format - No historical data returned
   ```
   **Fix**: Check symbol name, exchange, date range

---

## Troubleshooting

### Issue: Tests Skip Even With Credentials

**Solution**:
```bash
# Check environment variable
echo $RUN_LIVE_ANALYTICS_TESTS
# Should output: 1

# Re-export if needed
export RUN_LIVE_ANALYTICS_TESTS=1
```

### Issue: Rate Limiting

DhanHQ has API limits:
- Historical: 5/sec, 100,000/day
- Quotes: 1/sec
- Option Chain: Limited per minute

**Solution**: Add delays between tests if hitting limits:
```bash
venv/bin/python -m pytest test_analytics_live.py -v --forked --timeout=30
```

### Issue: Timezone Mismatch

**Symptom**:
```
TypeError: can't subtract offset-naive and offset-aware datetimes
```

**Solution**: All tests now use `datetime.now(timezone.utc)` for consistency.

---

## Integration with CI/CD

### GitHub Actions Example

```yaml
name: Live Analytics Tests

on:
  schedule:
    - cron: '0 10 * * 1-5'  # Run at 3:30 PM IST on weekdays

jobs:
  test-live-analytics:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.12'
      
      - name: Install dependencies
        run: pip install -r brokersv2/requirements.txt
      
      - name: Run live analytics tests
        env:
          DHAN_CLIENT_ID: ${{ secrets.DHAN_CLIENT_ID }}
          DHAN_ACCESS_TOKEN: ${{ secrets.DHAN_ACCESS_TOKEN }}
          RUN_LIVE_ANALYTICS_TESTS: "1"
        run: |
          pytest brokersv2/tests/integration/test_analytics_live.py -v \
            --junitxml=live-analytics-results.xml
      
      - name: Upload test results
        uses: actions/upload-artifact@v3
        if: always()
        with:
          name: live-analytics-results
          paths: live-analytics-results.xml
```

---

## Adding New Live Tests

When adding new tests, follow this pattern:

```python
@pytest.mark.asyncio
async def test_your_analytics_with_live_data(self, live_broker_adapter):
    """Test your analytics module with real broker data."""
    
    # 1. Fetch real data from broker
    data = await live_broker_adapter.get_something(...)
    
    # 2. Validate data structure
    assert data is not None
    assert hasattr(data, 'expected_field')
    
    # 3. Feed into analytics module
    engine = YourAnalyticsEngine("SYMBOL")
    engine.process(data)
    
    # 4. Validate analytics output
    assert engine.result > 0
    assert engine.metric == expected_value
```

---

## Safety Notes

⚠️ **Important**:
- These tests are **READ-ONLY** - they don't place orders
- No market impact - only data retrieval
- Safe to run during market hours
- Does not consume trading limits
- May consume API quota (check daily limits)

---

## Next Steps

After live tests pass, you can:
1. ✅ Deploy analytics to production with confidence
2. ✅ Use real data for backtesting
3. ✅ Validate model accuracy against live prices
4. ✅ Monitor data quality in production
5. ✅ Set up automated daily validation runs

---

## Support

For issues:
- Check DhanHQ API status: https://dhanhq.co/
- Review API docs: https://dhanhq.co/docs/v2/
- Check test logs: `pytest -v --log-cli-level=INFO`
