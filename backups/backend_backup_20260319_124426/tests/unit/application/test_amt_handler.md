# AMTHandler Unit Test Cases

## Test File

`tests/unit/application/test_amt_handler.py`

## Test Purpose

Test the `AMTHandler` class, which wraps AMT analysis and footprint generation
for every tick. The handler manages incremental volume profiles with a sliding
window, detects day boundaries, and caches profile arrays for sub-candle updates.
All dependencies (AMTAnalyzer, FootprintAnalyzer, IncrementalVolumeProfile,
and the serialization helpers) are mocked so tests run without any real
market data or GPU access.

## Test Cases Overview

| Case ID | Feature Description                                           | Test Type     |
| ------- | ------------------------------------------------------------- | ------------- |
| AH-01   | AMTHandler initialises with default state                     | Positive Test |
| AH-02   | AMTHandler initialises with session_only_vp=False             | Positive Test |
| AH-03   | analyze() calls AMTAnalyzer with correct arguments            | Positive Test |
| AH-04   | analyze() calls FootprintAnalyzer.generate with last 50 bars  | Positive Test |
| AH-05   | analyze() returns (AMTResult, amt_dto, footprint_dto) tuple   | Positive Test |
| AH-06   | First call triggers full VP rebuild (prev_data_len == 0)      | Positive Test |
| AH-07   | Incremental update when data grows by exactly 1 candle        | Positive Test |
| AH-08   | Sub-candle update (data_grew_by == 0) skips VP rebuild        | Positive Test |
| AH-09   | Bulk data growth (grew_by > 1) triggers full VP rebuild       | Positive Test |
| AH-10   | Data shrink (grew_by < 0) triggers full VP rebuild            | Positive Test |
| AH-11   | Day boundary resets VP profiles and prev_data_len             | Positive Test |
| AH-12   | Cached profile arrays reused on sub-candle update             | Positive Test |
| AH-13   | Cached profile arrays refreshed on new candle                 | Positive Test |
| AH-14   | _filter_today_session returns only today's candles            | Positive Test |
| AH-15   | _filter_today_session falls back when no today candles        | Positive Test |
| AH-16   | _filter_today_session returns empty when data is empty        | Positive Test |
| AH-17   | Lookback is capped at _LOOKBACK (60)                          | Boundary Test |
| AH-18   | Developing profile uses _DEV_LOOKBACK (20)                    | Boundary Test |
| AH-19   | Error in AMTAnalyzer propagates (no silent swallowing)        | Error Test    |
| AH-20   | Error in FootprintAnalyzer propagates                         | Error Test    |

## Detailed Test Steps

### AH-01: AMTHandler initialises with default state

**Test Purpose**: Verify constructor sets up internal analyzers and counters.

**Test Data Preparation**: None

**Test Steps**:
1. Create AMTHandler()
2. Assert _prev_data_len == 0
3. Assert _session_only_vp is True
4. Assert _cached_profile is None

**Expected Results**:
- All defaults are correctly initialised

### AH-02: AMTHandler initialises with session_only_vp=False

**Test Purpose**: Verify non-default VP mode.

**Test Steps**:
1. Create AMTHandler(session_only_vp=False)
2. Assert _session_only_vp is False

**Expected Results**:
- Flag is set as specified

### AH-03: analyze() calls AMTAnalyzer with correct arguments

**Test Purpose**: Verify the handler passes data, order_book, and VP profiles
to the underlying AMTAnalyzer.

**Test Data Preparation**:
- Mock AMTAnalyzer.analyze
- Prepare a list of 30 OHLC candles with today's date

**Test Steps**:
1. Call handler.analyze(data, order_book, prior_poc, prior_vah, prior_val)
2. Assert AMTAnalyzer.analyze was called once with expected arguments

**Expected Results**:
- AMTAnalyzer.analyze receives data, order_book, incremental_profile, etc.

### AH-04: analyze() calls FootprintAnalyzer.generate with last 50 bars

**Test Purpose**: Footprint analysis uses the last 50 candles (or all if < 50).

**Test Steps**:
1. Call handler.analyze with 80 candles
2. Assert FootprintAnalyzer.generate received exactly 50 candles

**Expected Results**:
- fp_data has length 50

### AH-05: analyze() returns correct tuple

**Test Purpose**: The return is (AMTResult, amt_dto dict, footprint_dto dict).

**Test Steps**:
1. Call handler.analyze
2. Unpack return value into 3 variables
3. Assert types

**Expected Results**:
- First element is AMTResult
- Second and third are dicts

### AH-06 to AH-10: VP rebuild strategies

Tests verify which code path is taken based on `data_grew_by`:
- 0: skip rebuild (sub-candle)
- 1: incremental update
- >1: full rebuild
- <0: full rebuild
- First call: full rebuild

### AH-11: Day boundary

**Test Purpose**: When the IST date changes, profiles are reset.

**Test Steps**:
1. Call analyze with candles from yesterday
2. Patch datetime.now to return today
3. Call analyze again
4. Verify profiles were rebuilt

### AH-12 to AH-13: Profile caching

**Test Purpose**: On sub-candle updates, the cached profile/legProfile arrays
are reused in the DTO. On new candle, they are refreshed.

### AH-14 to AH-16: _filter_today_session

Tests for the module-level function that filters OHLC data to today's
trading session only.

### AH-17 to AH-18: Lookback boundaries

Verify the handler caps VP window at _LOOKBACK (60) and _DEV_LOOKBACK (20).

### AH-19 to AH-20: Error propagation

Verify that exceptions from AMTAnalyzer or FootprintAnalyzer propagate
up without being silently swallowed.

## Test Considerations

### Mock Strategy
- AMTAnalyzer.analyze: patched to return a controlled AMTResult
- FootprintAnalyzer.generate: patched to return a controlled dict
- IncrementalVolumeProfile.update: patched to count calls
- amt_result_to_dto: patched to return a controlled dict
- footprint_to_dto: patched to return a controlled dict
- datetime.now: patched for day-boundary tests

### Boundary Conditions
- Empty data list
- Data with exactly 1 candle
- Data with more candles than _LOOKBACK
- Sub-candle update (same data length)
- Cumulative bulk additions

### Asynchronous Operations
- AMTHandler.analyze() is synchronous; no async considerations needed
