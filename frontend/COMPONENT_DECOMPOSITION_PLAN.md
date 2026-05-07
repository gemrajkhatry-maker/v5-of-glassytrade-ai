# Component Decomposition Strategy

**Date:** May 7, 2026  
**Status:** Planning Phase  
**Components to Decompose:** ChartScene (1,989 lines), AIAnalysisPanel (1,813 lines)

---

## Executive Summary

The current god components are too large for safe automated refactoring. Manual decomposition is required to avoid breaking complex canvas rendering and state management logic. This document provides a detailed extraction plan that can be executed incrementally with testing at each step.

---

## ChartScene Decomposition (1,989 lines → 8 files)

### Current Structure Analysis

**Line Distribution:**
- Lines 1-110: Imports, props, memoization (110 lines)
- Lines 113-280: Chart initialization (167 lines)
- Lines 282-365: Realtime subscription (83 lines)
- Lines 367-462: Canvas overlay setup (95 lines)
- Lines 464-1360: **Drawing functions (896 lines)** ← EXTRACT
- Lines 1361-1403: Prediction updates (42 lines)
- Lines 1405-1455: Range bar updates (50 lines)
- Lines 1457-1872: Markers & price lines (415 lines) ← EXTRACT
- Lines 1874-1903: Render (29 lines)
- Lines 1905-1970: DecisionCard component (65 lines) ← EXTRACT
- Lines 1972-1986: Memoization comparator (14 lines)

### Target Architecture

```
components/chart/
├── ChartScene.tsx (250 lines) - Orchestrator
├── ChartEngine.tsx (200 lines) - TradingView lifecycle
├── OverlayEngine.tsx (900 lines) - Canvas drawing functions
├── ExecutionMarkers.tsx (250 lines) - Trade markers & price lines
├── DecisionCard.tsx (80 lines) - Decision display component
├── PredictionLayer.tsx (60 lines) - AI prediction updates
├── RangeBarHandler.tsx (70 lines) - Range bar data management
└── index.ts - Barrel exports
```

### Extraction Plan

#### Step 1: Extract DecisionCard (LOW RISK - 2 hours)
**Lines:** 1905-1970 (65 lines)  
**File:** `components/chart/DecisionCard.tsx`

**Reason:**
- Self-contained React component
- No canvas dependencies
- Clear props interface
- Easy to test

**Action:**
```bash
# 1. Create new file
# 2. Copy DecisionCard component
# 3. Export from chart/index.ts
# 4. Import in ChartScene
# 5. Test visually
```

---

#### Step 2: Extract Overlay Drawing Functions (MEDIUM RISK - 6 hours)
**Lines:** 464-1360 (896 lines)  
**File:** `components/chart/OverlayEngine.tsx`

**Functions to Extract:**
1. `drawAggressiveBubbles` (66 lines)
2. `drawVAShadedBox` (38 lines)
3. `drawTimeMarkers` (99 lines)
4. `drawIBRetestZone` (84 lines)
5. `drawProfileBars` (125 lines)
6. `drawVerticalLabel` (13 lines)
7. `drawVolumeProfile` (28 lines)
8. `drawRangeVolumeProfile` (32 lines)
9. `drawFootprint` (298 lines) ← Most complex
10. `drawRangeBars` (111 lines)

**Dependencies:**
- Canvas API (CanvasRenderingContext2D)
- TradingView types (IChartApi, ISeriesApi, UTCTimestamp)
- ChartConfig
- AMTAnalysis
- FootprintCandle, AggressivePrint, RangeBarData

**Interface:**
```typescript
export interface OverlayDrawParams {
    ctx: CanvasRenderingContext2D;
    canvas: HTMLCanvasElement;
    chart: IChartApi;
    series: ISeriesApi<"Candlestick">;
    data: OHLCData[];
    amtAnalysis?: AMTAnalysis | null;
    footprintData?: Record<string, FootprintCandle> | null;
    cumulativeDeltas?: number[];
    rangeBarData?: RangeBarData | null;
    config: ChartConfig;
    mode: ChartMode;
}

export class OverlayEngine {
    static drawVAShadedBox(params: OverlayDrawParams): void;
    static drawVolumeProfile(params: OverlayDrawParams): void;
    static drawFootprint(params: OverlayDrawParams): void;
    // ... etc
}
```

**Testing Strategy:**
1. Visual comparison before/after
2. Test each mode separately (STANDARD, FOOTPRINT, RANGE)
3. Verify all overlays render correctly
4. Check performance (no regression)

---

#### Step 3: Extract Execution Markers (MEDIUM RISK - 3 hours)
**Lines:** 1457-1872 (415 lines)  
**File:** `components/chart/ExecutionMarkers.tsx`

**Responsibilities:**
- Create/remove price lines for trades
- Add chart markers for entries/exits
- Manage AMT level lines (POC, VAH, VAL)
- Handle legend updates

**Interface:**
```typescript
export interface ExecutionMarkersProps {
    chartRef: RefObject<IChartApi | null>;
    candleSeriesRef: RefObject<ISeriesApi<"Candlestick"> | null>;
    positions: TradePosition[];
    closedTrades: TradePosition[];
    amtAnalysis?: AMTAnalysis | null;
    config: ChartConfig;
    mode: ChartMode;
}

export function ExecutionMarkers(props: ExecutionMarkersProps): null;
```

**Note:** This is a non-rendering component (returns null) that manages side effects via useEffect.

---

#### Step 4: Extract ChartEngine (LOW RISK - 3 hours)
**Lines:** 113-280 (167 lines)  
**File:** `components/chart/ChartEngine.tsx`

**Responsibilities:**
- TradingView chart initialization
- Series creation (candlestick, volume, prediction)
- ResizeObserver setup
- Chart lifecycle management

**Interface:**
```typescript
export interface ChartEngineProps {
    containerRef: RefObject<HTMLDivElement | null>;
    overlayRef: RefObject<HTMLCanvasElement | null>;
    config: ChartConfig;
    mode: ChartMode;
    onInit: (refs: ChartRefs) => void;
    onDestroy: () => void;
}

export function ChartEngine(props: ChartEngineProps): JSX.Element;
```

---

#### Step 5: Refactor ChartScene as Orchestrator (LOW RISK - 2 hours)
**Target:** ~250 lines

**New ChartScene Structure:**
```typescript
function ChartScene(props: ChartSceneProps) {
    // Refs
    const chartContainerRef = useRef<HTMLDivElement>(null);
    const overlayRef = useRef<HTMLCanvasElement>(null);
    const chartRefs = useRef<ChartRefs>({ ... });
    
    // Data memoization
    const stableAmtAnalysis = useStableAMT(amtAnalysis);
    const stableData = useStableData(data);
    
    // Chart lifecycle
    ChartEngine({ containerRef, overlayRef, config, mode, ... });
    
    // Realtime subscription
    useRealtimeSubscription({ tickBus, symbol, mode, chartRefs });
    
    // Overlay drawing
    useOverlayDrawing({ chartRefs, stableAmtAnalysis, stableData, ... });
    
    // Execution markers
    ExecutionMarkers({ chartRefs, positions, closedTrades, ... });
    
    // Prediction layer
    PredictionLayer({ chartRefs, data, predictions, mode });
    
    // Range bar handler
    RangeBarHandler({ chartRefs, mode, rangeBarData });
    
    // Render
    return (
        <div className="...">
            <div ref={chartContainerRef} />
            <canvas ref={overlayRef} />
            <DecisionCard {...} />
        </div>
    );
}
```

---

## AIAnalysisPanel Decomposition (1,813 lines → 7 files)

### Current Structure Analysis

**Major Sections:**
1. Lines 1-100: Props, memoization, LTP calculation (100 lines)
2. Lines 100-250: Market State section (150 lines)
3. Lines 250-500: Location section (AMT levels) (250 lines)
4. Lines 500-750: Aggression section (250 lines)
5. Lines 750-1000: Market Metrics section (250 lines)
6. Lines 1000-1400: Order Book / Depth (400 lines)
7. Lines 1400-1600: Portfolio / Equity (200 lines)
8. Lines 1600-1813: Risk State, LLM History (213 lines)

### Target Architecture

```
components/intelligence/
├── AIAnalysisPanel.tsx (150 lines) - Tabbed orchestrator
├── tabs/
│   ├── StateTab.tsx (200 lines) - Market state, regime
│   ├── LocationTab.tsx (250 lines) - AMT levels, POC, VAH/VAL
│   ├── AggressionTab.tsx (200 lines) - Orderflow aggression
│   ├── MetricsTab.tsx (250 lines) - OFI, CVD, delta
│   └── DecisionTab.tsx (200 lines) - Agent decision, history
├── shared/
│   ├── AnalysisHeader.tsx (50 lines)
│   └── MetricCard.tsx (80 lines)
└── index.ts - Barrel exports
```

### Extraction Plan

#### Step 1: Create Tabbed Interface (LOW RISK - 3 hours)
**File:** `components/intelligence/AIAnalysisPanel.tsx`

**Structure:**
```typescript
function AIAnalysisPanel(props: AIAnalysisPanelProps) {
    const [activeTab, setActiveTab] = useState<'state' | 'location' | 'aggression' | 'metrics' | 'decision'>('state');
    
    return (
        <div>
            {/* Tab Bar */}
            <div className="flex gap-1 border-b border-glassy-border-default">
                <button onClick={() => setActiveTab('state')}>State</button>
                <button onClick={() => setActiveTab('location')}>Location</button>
                <button onClick={() => setActiveTab('aggression')}>Aggression</button>
                <button onClick={() => setActiveTab('metrics')}>Metrics</button>
                <button onClick={() => setActiveTab('decision')}>Decision</button>
            </div>
            
            {/* Tab Content */}
            {activeTab === 'state' && <StateTab {...props} />}
            {activeTab === 'location' && <LocationTab {...props} />}
            {activeTab === 'aggression' && <AggressionTab {...props} />}
            {activeTab === 'metrics' && <MetricsTab {...props} />}
            {activeTab === 'decision' && <DecisionTab {...props} />}
        </div>
    );
}
```

**Benefits:**
- Reduces visible content by 80% (only 1 tab shown at a time)
- Improves readability
- Easier to navigate
- Each tab can be developed/tested independently

---

#### Step 2: Extract Each Tab (LOW-MEDIUM RISK - 8 hours total)

**StateTab (200 lines):**
- Market state display
- Regime indicator
- Aggression score
- Status badges

**LocationTab (250 lines):**
- POC, VAH, VAL levels
- Session/Leg profile toggle
- Distance calculations
- Level markers

**AggressionTab (200 lines):**
- Delta score visualization
- CVD slope
- OFI metrics
- Progress bars

**MetricsTab (250 lines):**
- Volume metrics
- Volatility indicators
- Momentum signals
- Statistical summaries

**DecisionTab (200 lines):**
- Agent decision display
- Probability breakdown
- Rationale text
- History timeline

---

## Risk Assessment

### LOW RISK (Can be done immediately)
- DecisionCard extraction
- Tabbed interface creation
- Individual tab extraction
- ChartEngine extraction

### MEDIUM RISK (Requires testing)
- Overlay drawing functions extraction
- Execution markers extraction
- Shared utility extraction

### HIGH RISK (Avoid or proceed with caution)
- Realtime subscription logic
- State memoization logic
- Canvas coordinate calculations

---

## Testing Strategy

### Visual Regression Testing
1. Screenshot current UI for all modes
2. After each extraction, compare screenshots
3. Verify pixel-perfect match

### Functional Testing
1. Test each chart mode (STANDARD, FOOTPRINT, RANGE)
2. Test all overlays (VA box, volume profile, bubbles, footprint)
3. Test execution markers (entries, exits, SL/TP lines)
4. Test decision card expand/collapse

### Performance Testing
1. Measure FPS before/after each extraction
2. Check memory usage
3. Verify no new re-renders introduced

---

## Implementation Order (Recommended)

### Week 1: Low-Hanging Fruit
- Day 1-2: Extract DecisionCard ✅ (2 hours)
- Day 2-3: Create tabbed interface for AIAnalysisPanel ✅ (3 hours)
- Day 4-5: Extract 5 tabs from AIAnalysisPanel ✅ (8 hours)

**Result:** AIAnalysisPanel reduced from 1,813 → 150 lines

### Week 2: Chart Engine
- Day 1-2: Extract ChartEngine ✅ (3 hours)
- Day 3-5: Extract overlay drawing functions ✅ (6 hours)

**Result:** ChartScene reduced from 1,989 → 600 lines

### Week 3: Final Cleanup
- Day 1-2: Extract ExecutionMarkers ✅ (3 hours)
- Day 3: Extract PredictionLayer & RangeBarHandler ✅ (2 hours)
- Day 4-5: Testing & refinement ✅ (8 hours)

**Result:** ChartScene reduced from 1,989 → 250 lines

---

## Success Metrics

| Component | Before | After | Reduction |
|-----------|--------|-------|-----------|
| ChartScene | 1,989 lines | 250 lines | 87% |
| AIAnalysisPanel | 1,813 lines | 150 lines | 92% |
| Total files | 2 files | 15 files | Modular |
| Testability | Low | High | Significant |
| Maintainability | Poor | Excellent | Significant |

---

## Automated Refactoring Limitations

**Why this requires manual work:**

1. **Canvas Drawing Complexity:**
   - Coordinate calculations depend on TradingView API
   - Context passing requires careful refactoring
   - Visual testing is essential

2. **State Dependencies:**
   - Multiple useEffect hooks with complex dependency arrays
   - Ref sharing between components
   - Memoization logic is tightly coupled

3. **Performance Sensitivity:**
   - Chart rendering is performance-critical
   - Any regression will be immediately visible
   - Requires careful profiling

**Safe Automation Opportunities:**
- File creation (boilerplate)
- Import/export statements
- Type definitions
- Barrel exports (index.ts)

**Manual Work Required:**
- Function extraction
- Dependency management
- Testing
- Visual verification

---

## Next Steps

1. **Get approval on this strategy**
2. **Start with LOW RISK extractions:**
   - DecisionCard (2 hours)
   - Tabbed interface (3 hours)
3. **Test thoroughly after each extraction**
4. **Proceed to MEDIUM RISK extractions**
5. **Complete all extractions in 3 weeks**

---

**Recommendation:** Execute this plan incrementally with manual testing at each step. Do NOT attempt automated extraction of canvas drawing functions or complex state logic.
