# Phase 3: Chart Component Decomposition & Testing Plan

## 📋 Phase 3 Overview

**Duration:** ~15-20 hours  
**Goal:** Decompose ChartScene God component (1937 lines) into testable subcomponents + comprehensive unit tests  
**Target:** 50-70 tests with 95%+ pass rate

---

## 🎯 Current State

### ChartScene.tsx (1937 lines)

**Single Responsibility Violations:**
1. Chart initialization & configuration (lines 130-250)
2. Candlestick series management (lines 250-400)
3. Volume series rendering (lines 400-500)
4. Prediction series overlay (lines 500-600)
5. AMT level drawing - POC/VAH/VAL (lines 600-900)
6. Profile histogram rendering (lines 900-1200)
7. VWAP overlay (lines 1200-1300)
8. Execution markers - entries/SL/TP (lines 1300-1500)
9. Footprint chart rendering (lines 1500-1700)
10. Aggressive print annotations (lines 1700-1800)
11. Crosshair & tooltip management (lines 1800-1900)

**Testing Challenges:**
- Canvas-based rendering (hard to test DOM)
- TradingView Lightweight Charts API (external library)
- Complex state management (15+ refs)
- Tightly coupled drawing logic
- No separation of concerns

---

## 🏗️ Proposed Architecture

### Decomposition Strategy

```
ChartScene.tsx (1937 lines → ~150 lines coordinator)
├── ChartInitialization.tsx (100 lines)
│   └── Chart lifecycle, configuration, theme
│
├── CandleSeriesManager.ts (150 lines)
│   └── Candlestick series CRUD, updates
│
├── VolumeSeriesManager.ts (100 lines)
│   └── Volume histogram, color coding
│
├── PredictionSeriesManager.ts (100 lines)
│   └── AI prediction overlay
│
├── ChartOverlayEngine.ts (400 lines) ← EXTRACT & TEST
│   ├── AMTLevelsOverlay.ts (150 lines)
│   │   └── POC, VAH, VAL, LEG levels
│   ├── ProfileHistogram.ts (150 lines)
│   │   └── Session/daily/leg profiles
│   └── VWAPOverlay.ts (100 lines)
│       └── VWAP line, sigma bands
│
├── ExecutionMarkersManager.ts (300 lines) ← EXTRACT & TEST
│   ├── EntryMarkers.ts (100 lines)
│   │   └── Long/short entry indicators
│   ├── SLTPMarkers.ts (100 lines)
│   │   └── Stop loss, take profit lines
│   └── PnLAnnotations.ts (100 lines)
│       └── PnL labels, R-multiples
│
├── FootprintChartManager.ts (400 lines)
│   └── Footprint-specific rendering
│
└── CrosshairManager.ts (100 lines)
    └── Custom tooltips, crosshair logic
```

---

## 📊 Test Plan by Component

### 1. ChartInitialization.tsx (15 tests)

**Test Categories:**
- Chart creation with default config (3 tests)
- Theme application (light/dark) (3 tests)
- Responsive resize handling (3 tests)
- Cleanup on unmount (2 tests)
- Error handling (invalid config) (2 tests)
- Grid configuration (2 tests)

**Estimated Time:** 1.5 hours

---

### 2. CandleSeriesManager.ts (20 tests)

**Test Categories:**
- Series creation with OHLC data (3 tests)
- Data update (incremental) (3 tests)
- Data replacement (full refresh) (2 tests)
- Bull/bear color configuration (2 tests)
- Empty data handling (2 tests)
- Large dataset performance (3 tests)
- Time sequence validation (3 tests)
- Gap handling (2 tests)

**Estimated Time:** 2 hours

---

### 3. VolumeSeriesManager.ts (15 tests)

**Test Categories:**
- Volume histogram creation (2 tests)
- Bull/bear volume coloring (3 tests)
- Price scale margins (2 tests)
- Volume spike detection (2 tests)
- Zero volume handling (2 tests)
- Volume profile overlay (2 tests)
- Data synchronization with candles (2 tests)

**Estimated Time:** 1.5 hours

---

### 4. AMTLevelsOverlay.ts (25 tests) ← HIGH PRIORITY

**Test Categories:**
- POC line rendering (3 tests)
  * Color, style, label
  * Position accuracy
  * Multiple POC types (session/daily/leg)
  
- VAH/VAL lines (4 tests)
  * Value area high/low rendering
  * Fill between VAH-VAL
  * Label positioning
  * Breach indicators

- LEG levels (4 tests)
  * Leg POC/VAH/VAL rendering
  * Conditional display (only in PROBING/IMBALANCED)
  * Color differentiation
  * Overlap handling

- Level interaction (3 tests)
  * Click/hover on levels
  * Level visibility toggle
  * Z-order management

- Edge cases (11 tests)
  * Missing levels
  * Invalid price ranges
  * Extreme values
  * Overlapping levels
  * Empty profile data
  * Profile updates
  * Time-based expiry
  * Price scale bounds
  * Canvas clipping
  * Label overlap prevention
  * Responsive adjustment

**Estimated Time:** 3 hours

---

### 5. ExecutionMarkersManager.ts (30 tests) ← HIGH PRIORITY

**Test Categories:**
- Entry markers (6 tests)
  * LONG entry (green triangle up)
  * SHORT entry (red triangle down)
  * Entry price label
  * Entry time marker
  * Multiple entries
  * Entry with rationale

- Stop Loss markers (5 tests)
  * SL line rendering
  * SL price label
  * SL color (orange/red)
  * SL distance calculation
  * SL adjustment tracking

- Take Profit markers (5 tests)
  * TP line rendering
  * TP1/TP2/TP3 levels
  * TP color (green)
  * TP hit detection
  * Partial TP tracking

- PnL annotations (6 tests)
  * Realized PnL display
  * Unrealized PnL display
  * PnL color coding (green/red)
  * R-multiple calculation
  * PnL percentage
  * PnL tooltip

- Position management (5 tests)
  * Active positions display
  * Closed positions history
  * Partial close indicators
  * Position stacking
  * Position grouping

- Edge cases (3 tests)
  * No positions
  * Invalid position data
  * Overlapping markers

**Estimated Time:** 3.5 hours

---

### 6. ProfileHistogram.ts (20 tests)

**Test Categories:**
- Session profile rendering (4 tests)
  * Volume bars
  * POC highlight
  * VAH/VAL markers
  * Color gradient

- Daily profile (3 tests)
  * Profile overlay
  * DPOC marker
  * Color differentiation

- Leg profile (3 tests)
  * Dynamic profile
  * Leg POC tracking
  * Update frequency

- Profile metrics (4 tests)
  * Value area calculation
  * POC calculation
  * Volume distribution
  * Profile shape detection (D/P/b/B)

- Edge cases (6 tests)
  * Empty profile
  * Insufficient data
  * Profile expiry
  * Canvas bounds
  * Label overlap
  * Performance with large profiles

**Estimated Time:** 2 hours

---

### 7. VWAPOverlay.ts (15 tests)

**Test Categories:**
- VWAP line rendering (3 tests)
  * Line style, color
  * Price accuracy
  * Time synchronization

- Sigma bands (4 tests)
  * ±1σ band
  * ±2σ band
  * Band coloring
  * Band fill

- VWAP interaction (3 tests)
  * Crosshair tooltip
  * VWAP bounce detection
  * VWAP trend direction

- Edge cases (5 tests)
  * Missing VWAP data
  * VWAP reset (new session)
  * Extreme deviations
  * Label positioning
  * Performance calculation

**Estimated Time:** 1.5 hours

---

### 8. CrosshairManager.ts (10 tests)

**Test Categories:**
- Custom tooltip rendering (3 tests)
- OHLC data display (2 tests)
- AMT level tooltip (2 tests)
- Crosshair visibility (2 tests)
- Edge cases (1 test)

**Estimated Time:** 1 hour

---

## 📅 Phase 3 Execution Plan

### Week 1: Component Decomposition (8-10 hours)

**Day 1-2: Architecture Setup (4 hours)**
- Create directory structure
- Set up component interfaces
- Extract ChartInitialization
- Extract CandleSeriesManager
- Write 35 tests

**Day 3-4: Overlay Components (4 hours)**
- Extract AMTLevelsOverlay
- Extract ProfileHistogram
- Write 45 tests

**Day 5: VWAP & Crosshair (2 hours)**
- Extract VWAPOverlay
- Extract CrosshairManager
- Write 25 tests

### Week 2: Execution Markers & Integration (7-10 hours)

**Day 6-7: Execution Markers (4-5 hours)**
- Extract ExecutionMarkersManager
- Extract EntryMarkers
- Extract SLTPMarkers
- Extract PnLAnnotations
- Write 30 tests

**Day 8: Integration Testing (2 hours)**
- ChartScene coordinator tests
- Component interaction tests
- Data flow validation

**Day 9-10: Bug Fixes & Polish (1-3 hours)**
- Fix test failures
- Optimize performance
- Documentation

---

## 🎯 Success Criteria

### Must Have:
- ✅ ChartScene reduced from 1937 → <300 lines
- ✅ 8-10 extracted components
- ✅ 120+ unit tests created
- ✅ 95%+ test pass rate
- ✅ Zero regression in chart functionality
- ✅ All AMT levels rendering correctly
- ✅ All execution markers displaying properly

### Nice to Have:
- Canvas rendering tests (if feasible)
- Performance benchmarks
- Visual regression tests
- Integration test suite

---

## 🔧 Technical Approach

### Testing Canvas Components

**Challenge:** Canvas rendering doesn't produce DOM elements

**Solutions:**
1. **Mock Canvas API:** Mock getContext('2d') and spy on drawing methods
2. **Data Layer Testing:** Test the data transformation logic (90% of bugs)
3. **Wrapper Component Testing:** Test React wrapper props/state
4. **Visual Snapshots:** Use jest-canvas-mock + snapshot testing
5. **Integration Tests:** End-to-end chart rendering with real data

### Recommended Strategy:
```typescript
// Test data transformations (most valuable)
describe('AMTLevelsOverlay', () => {
  it('calculates correct Y positions for price levels', () => {
    const positions = calculateYPositions({
      poc: 50000,
      vah: 50500,
      val: 49500,
      priceRange: { min: 49000, max: 51000 },
      canvasHeight: 600,
    });
    expect(positions.poc).toBeCloseTo(300); // Middle
    expect(positions.vah).toBeCloseTo(150); // Upper
    expect(positions.val).toBeCloseTo(450); // Lower
  });
});

// Mock canvas drawing for critical paths
describe('ProfileHistogram.draw()', () => {
  it('calls fillRect for each volume bar', () => {
    const mockCtx = createMockCanvasContext();
    const histogram = new ProfileHistogram(mockCtx);
    histogram.draw(profileData);
    expect(mockCtx.fillRect).toHaveBeenCalledTimes(profileData.length);
  });
});
```

---

## 📊 Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Canvas testing too complex | High | Medium | Focus on data layer, mock canvas |
| Chart API coupling | Medium | High | Create adapter layer |
| Performance regression | Low | High | Benchmark before/after |
| Visual bugs after refactor | Medium | Medium | Manual QA checklist |
| Time estimate overrun | Medium | Medium | Phase delivery, cut scope |

---

## 🚀 Quick Wins (First 2 Hours)

1. **Extract AMTLevelsOverlay** (150 lines)
   - Clear boundaries
   - Testable data logic
   - High value

2. **Write 25 AMT level tests**
   - Position calculations
   - Color/style validation
   - Edge cases

3. **Extract ExecutionMarkersManager** (200 lines)
   - Well-defined interface
   - Business logic heavy
   - Production critical

---

## 📝 Deliverables

1. **8-10 Extracted Components**
   - Each <200 lines
   - Single responsibility
   - Well-documented interfaces

2. **120+ Unit Tests**
   - Data transformation tests
   - Canvas mock tests
   - Edge case coverage

3. **Updated ChartScene.tsx**
   - Reduced to ~300 lines
   - Coordinator pattern
   - Clean composition

4. **Test Infrastructure**
   - Canvas mock utilities
   - Test data generators
   - Helper functions

5. **Documentation**
   - Component API docs
   - Testing guide
   - Migration notes

---

## 🎓 Learning Opportunities

- Canvas testing strategies
- TradingView Lightweight Charts API
- Complex state management
- Performance optimization
- Visual regression testing
- Component decomposition patterns

---

## ✅ Phase 3 Checklist

- [ ] Architecture approved
- [ ] Directory structure created
- [ ] ChartInitialization extracted + tested
- [ ] CandleSeriesManager extracted + tested
- [ ] VolumeSeriesManager extracted + tested
- [ ] AMTLevelsOverlay extracted + tested
- [ ] ProfileHistogram extracted + tested
- [ ] VWAPOverlay extracted + tested
- [ ] ExecutionMarkersManager extracted + tested
- [ ] CrosshairManager extracted + tested
- [ ] ChartScene coordinator updated
- [ ] Integration tests passing
- [ ] Manual QA completed
- [ ] Performance benchmarks verified
- [ ] Documentation written
- [ ] Code review completed
- [ ] Merged to stable_3

---

**Estimated Total:** 120-150 tests, 15-20 hours  
**Priority:** HIGH - Critical for production reliability  
**Dependencies:** Phase 1-2 complete ✅
