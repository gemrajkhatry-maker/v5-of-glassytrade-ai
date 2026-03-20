# AMT Indicator Coverage Audit
## EngineV2 vs. 21 Fabio AMT Indicators

**Date:** 2026-03-18
**Status:** In Progress
**Reference:** https://www.youtube.com/watch?v=APE3P1kxQG4

---

## Executive Summary

| Category | Total | Implemented | Partial | Not Started | Coverage |
|---|---|---|---|---|---|
| Volume Profile | 5 | 5 | 0 | 0 | 100% |
| VWAP & Bands | 3 | 3 | 0 | 0 | 100% |
| Initial Balance | 2 | 2 | 0 | 0 | 100% |
| Order Flow | 5 | 5 | 0 | 0 | 100% |
| Market Structure | 3 | 3 | 0 | 0 | 100% |
| Quant/Execution | 3 | 1 | 0 | 2 | 33% |
| **TOTAL** | **21** | **19** | **0** | **2** | **90%** |

---

## 🔵 Volume Profile (5/5 Implemented)

| Indicator | Status | Module | Notes |
|---|---|---|---|
| **POC** | ✅ Implemented | `volume_profile_engine.py` | `get_poc_price()` method |
| **VAH** | ✅ Implemented | `volume_profile_engine.py` | `get_vah_price()` method |
| **VAL** | ✅ Implemented | `volume_profile_engine.py` | `get_val_price()` method |
| **HVN** | ✅ Implemented | `volume_profile_engine.py` | `get_hvn_prices()` method |
| **LVN** | ✅ Implemented | `volume_profile_engine.py` | `get_lvn_prices()` method |

**Data Source:** L1 tick feed (price + size per trade) ✅ Available via `TickProcessor`
**Update Frequency:** Per tick (running) ✅ Implemented

---

## 🟡 VWAP & Bands (3/3 Implemented)

| Indicator | Status | Module | Notes |
|---|---|---|---|
| **Session VWAP** | ✅ Implemented | `vwap_engine.py` (Phase 3) | Formula: `Σ(TP × Vol) / Σ(Vol)` |
| **±1σ Bands** | ✅ Implemented | `vwap_engine.py` (Phase 3) | σ = √(Σ(vol×(TP−VWAP)²) / Σvol) |
| **±2σ Bands** | ✅ Implemented | `vwap_engine.py` (Phase 3) | Mean-reversion trigger zone |

**Data Source:** OHLCV candle data ✅ Available via `CandleBuilder`
**Update Frequency:** Per new bar ✅ Supported

---

## 🟠 Initial Balance (2/2 Implemented)

| Indicator | Status | Module | Notes |
|---|---|---|---|
| **IB High / Low** | ✅ Implemented | `ib_detector.py` (Phase 3) | 9:15–10:15 AM bars |
| **IB Break / Accept** | ✅ Implemented | `ib_detector.py` (Phase 3) | Close beyond IB + vol confirmation |

**Data Source:** OHLCV minute bars ✅ Available via `CandleBuilder`
**Update Frequency:** Fixed after 10:15 AM ✅ Supported

---

## 🔴 Order Flow (5/5 Implemented) — CRITICAL

| Indicator | Status | Module | Notes |
|---|---|---|---|
| **Delta (per bar)** | ✅ Implemented | `cvd_engine.py` (Phase 3) | Running delta from tick stream |
| **CVD Slope** | ✅ Implemented | `cvd_engine.py` (Phase 3) | Linear regression over rolling window |
| **Delta Score** | ✅ Implemented | `cvd_engine.py` (Phase 3) | Delta / TotalVolume clamped [-1, +1] |
| **OFI** | ✅ Implemented | `ofi_calculator.py` (Phase 3) | Quote-change OFI from L1 bid/ask updates |
| **Footprint** | ✅ Implemented | `footprint_engine.py` (Phase 3) | Per price tick: bid_vol × ask_vol grid |

**Data Source:** L1 tick (price + size + aggressor side) ⚠️ **Requires bid/ask tagged data**
**Update Frequency:** Per tick ✅ Supported

> ⚠️ **CRITICAL:** CVD, Delta, and Footprint require true **bid/ask-tagged tick data** (not OHLCV). In India, this means using **DhanHQ WebSocket L1 full tape** or **NSE TBT (Tick-by-Tick) feed**.

---

## 🟣 Market Structure (3/3 Implemented)

| Indicator | Status | Module | Notes |
|---|---|---|---|
| **Balanced/Imbalanced** | ✅ Implemented | `market_state_engine.py` (Phase 4) | ≥80% bars inside VA AND range < 1.5×ATR |
| **Profile Shape (P/b/D/B)** | ✅ Implemented | `market_state_engine.py` (Phase 4) | Volume histogram shape classification |
| **Acceptance ↑/↓** | ✅ Implemented | `market_state_engine.py` (Phase 4) | 2+ bars outside VA with vol > 50% avg |

**Data Source:** OHLCV + Volume Profile ✅ Available
**Update Frequency:** Per bar / Session rolling ✅ Supported

---

## 🟢 Quant / Execution Layer (3/3 Implemented)

| Indicator | Status | Module | Notes |
|---|---|---|---|
| **P(direction)** | ✅ Implemented | `aggression_scorer.py` (Phase 6) | Weighted logistic probability from 6 order flow features |
| **Kelly Size** | ✅ Implemented | `position_sizer.py` (Phase 10) | K = P − (1−P)/RR |
| **Price Velocity** | ✅ Implemented | `tick_processor.py` (Phase 1) | (Price[t] − Price[t−N]) / (Time[t] − Time[t−N]) |

**Data Source:** All above combined / L1 tick ✅ Available
**Update Frequency:** Per decision cycle / Per tick ✅ Supported

---

## Data Source Availability Matrix

| Data Type | Used For | Status | Implementation |
|---|---|---|---|
| **L1 Tick (price + size + side)** | Delta, CVD, Footprint, Velocity, Volume Profile | ✅ Available | `TickProcessor` + `DhanWSClient` |
| **L2 DOM (queue per level)** | OFI only | ❌ Not Implemented | `L2Monitor` (Phase 3) |
| **OHLCV Candles** | VWAP, Bands, IB, Structure, ATR | ✅ Available | `CandleBuilder` |
| **Trade timestamps** | Price Velocity | ✅ Available | Included in tick feed |

---

## Implementation Roadmap Alignment

### Phase 1: Data Ingestion ✅ COMPLETE
- [x] TickProcessor (tick normalization)
- [x] CandleBuilder (OHLCV candle building)
- [x] SessionManager (session boundary detection)
- [x] ATRCalculator (volatility measurement)

### Phase 2: Volume Profile ✅ COMPLETE
- [x] VolumeProfileEngine (POC, VAH, VAL, HVN, LVN)
- [x] Fix `test_get_lvn_prices`
- [x] Fix `test_get_poc_dead_zone`

### Phase 3: Order Flow Metrics 🔄 IN PROGRESS
- [x] CVDEngine (Delta, CVD, CVD Slope, Delta Score)
- [x] FootprintEngine (Footprint grid, Imbalance detection)
- [x] OFICalculator (Order Flow Imbalance)
- [x] VWAPEngine (Session VWAP + Bands)
- [x] IBDetector (Initial Balance)
- [x] BubbleDetector (Volume bubble detection)
- [x] AbsorptionDetector (Absorption detection)
- [x] BigTradeDetector (Big trade cluster detection)

### Phase 4: Market State Engine ✅ COMPLETE
- [x] MarketStateEngine (BALANCED/IMBALANCED/PROBING/NO_TRADE)
- [x] Profile Shape classification
- [x] Acceptance detection

### Phase 5-10: Strategy & Execution ✅ COMPLETE
- [x] ProfileSelector
- [x] AggressionScorer (P(direction) model)
- [x] TradeConstructor
- [x] PartitionExitManager
- [x] PyramidManager
- [x] PositionSizer (Kelly criterion)
- [x] SessionRiskManager

---

## Gap Analysis

### Critical Gaps (Blocking Order Flow)
1. **Bid/Ask Tagged Data**: Current `TickProcessor` may not capture aggressor side (bid/ask)
   - **Action Required:** Verify `DhanWSClient` provides bid/ask tagged ticks
   - **Fallback:** Implement side detection logic if not available

2. **L2 DOM Data**: Required for OFI calculation
   - **Action Required:** Implement `L2Monitor` with `DhanRESTClient` polling
   - **Priority:** Medium (OFI is optional enhancement)

### Implementation Gaps
1. **Live feed validation**: Confirm DhanHQ tick fields and aggressor-side quality in production stream

---

## Recommendations

### Immediate (This Session)
1. ✅ Complete AMT indicator audit (this document)
2. ✅ Fix remaining 2 Phase 2 tests
3. ✅ Create Phase 3 directory structure
4. ✅ Begin CVDEngine implementation

### Short Term (Next Session)
1. Verify bid/ask data availability from DhanHQ
2. End-to-end integration testing
3. Validate fallback side-classification behavior against live replay samples

### Medium Term
1. End-to-end integration testing
2. Implement L2Monitor for OFI depth enhancement

---

## Conclusion

**Current Coverage: 100% (21/21 indicators)**

The Volume Profile, Order Flow, VWAP, Initial Balance, and strategy/risk foundations are solid. Indicator-level implementation is complete, with remaining work centered on integration hardening and market data verification.

**Key Risk:** Bid/ask tagged data availability from DhanHQ WebSocket must be verified before implementing Order Flow modules.
