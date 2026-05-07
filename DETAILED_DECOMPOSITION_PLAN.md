# Component Decomposition - Detailed Execution Plan

**Date:** May 7, 2026  
**Strategy:** Extract all components, test each, integrate tabbed interface, verify build  
**Timeline:** Single continuous execution session

---

## Current State Analysis

### AIAnalysisPanel Structure (1,813 lines)

| Section | Lines | Purpose | Complexity |
|---------|-------|---------|------------|
| **Header** | 127-212 | Equity, Risk, PnL, Engine Bar | LOW |
| **01. STATE** | 214-283 | Market regime, Session/Leg indicators | LOW |
| **02. LOCATION** | 285-394 | AMT levels (POC, VAH, VAL), Price map | MEDIUM |
| **03. AGGRESSION** | 396-1363 | Delta, CVD, OFI, Volume metrics | HIGH |
| **04. PROBABILITY ENGINE** | 1365-1636 | P(Long), P(Short), Kelly | MEDIUM |
| **05. RULE CHECKLIST** | 1638-1801 | Trading rules validation | LOW |
| **06. LLM DECISION HISTORY** | 1803-1813 | DecisionHistoryPanel | LOW (already extracted) |

### ChartScene Structure (1,937 lines)

| Section | Lines | Purpose | Complexity |
|---------|-------|---------|------------|
| **Chart Init** | 50-300 | TradingView setup, series creation | MEDIUM |
| **Real-time Updates** | 300-600 | tickBus, RAF batching | HIGH |
| **Canvas Overlays** | 600-1500 | 10 drawing functions | VERY HIGH |
| **Execution Markers** | 1500-1900 | Price lines, markers | MEDIUM |
| **DecisionCard** | 1900-1937 | Already extracted | DONE ✅ |

---

## Execution Plan

### Phase 1: Extract AIAnalysisPanel Tab Components (5 components)

#### Task 1: StateTab Component (~150 lines)
**Source:** Lines 214-283 of AIAnalysisPanel.tsx  
**Props Needed:**
- marketState: string
- hasDisplacement: boolean
- legPoc?: number
- legVah?: number
- legVal?: number
- sessionRegime: string
- legRegime: string

**Testing:**
- Build verification
- Visual rendering check
- Market state color coding

---

#### Task 2: LocationTab Component (~200 lines)
**Source:** Lines 285-394 of AIAnalysisPanel.tsx  
**Props Needed:**
- currentLtp: number
- poc: number
- vah: number
- val: number
- legPoc?: number
- legVah?: number
- legVal?: number
- dailyPoc?: number
- dailyVah?: number
- dailyVal?: number

**Testing:**
- Build verification
- Price calculation accuracy
- Visual price map rendering

---

#### Task 3: AggressionTab Component (~300 lines)
**Source:** Lines 396-700 of AIAnalysisPanel.tsx  
**Props Needed:**
- aggScore: number
- deltaScore: number
- cvdSlope: number
- ofi: number
- imbalance: boolean
- formatCVD: (cvd: number) => string

**Testing:**
- Build verification
- Delta/CVD calculations
- Progress bar rendering

---

#### Task 4: MetricsTab Component (~200 lines)
**Source:** Lines 700-900 of AIAnalysisPanel.tsx  
**Props Needed:**
- volumeMetrics: object
- volatility: object
- momentum: object

**Testing:**
- Build verification
- Metric calculations
- Formatting

---

#### Task 5: DecisionTab Component (~250 lines)
**Source:** Lines 1365-1800 of AIAnalysisPanel.tsx  
**Props Needed:**
- analysis: GenAIAnalysis
- amtResult: AMTAnalysis
- agentDecision?: AgentDecision
- llmHistory?: LLMHistoryEntry[]

**Testing:**
- Build verification
- Decision rendering
- History timeline

---

### Phase 2: Integrate Tabbed Interface

#### Task 6: Tab Integration
**Components:**
- AnalysisTabs (already created)
- StateTab, LocationTab, AggressionTab, MetricsTab, DecisionTab

**Integration Strategy:**
1. Add tab state to AIAnalysisPanel
2. Import AnalysisTabs
3. Wrap each section with conditional rendering
4. Test tab switching

---

### Phase 3: ChartScene Decomposition

#### Task 7: ChartEngine Extraction (~250 lines)
**Source:** Lines 50-300 of ChartScene.tsx  
**Props:**
- containerRef
- mode
- onReady callback

**Testing:**
- Chart creation in all 3 modes
- ResizeObserver functionality

---

#### Task 8: Overlay Utilities Extraction (~900 lines)
**Source:** Lines 600-1500 of ChartScene.tsx  
**Functions:**
1. drawVerticalLabel (13 lines) - Easiest
2. drawAggressiveBubbles (80 lines)
3. drawVAShadedBox (50 lines)
4. drawTimeMarkers (40 lines)
5. drawIBRetestZone (60 lines)
6. drawProfileBars (100 lines)
7. drawVolumeProfile (150 lines)
8. drawRangeVolumeProfile (120 lines)
9. drawRangeBars (90 lines)
10. drawFootprint (298 lines) - Most Complex

**Testing:**
- Visual verification after EACH extraction
- All overlays render correctly

---

### Phase 4: Final Testing

#### Task 9: Integration Testing
**Checklist:**
- [ ] Build successful (npm run build)
- [ ] No TypeScript errors
- [ ] No runtime errors
- [ ] All tabs switch correctly
- [ ] All data displays correctly
- [ ] Chart renders in all 3 modes
- [ ] All overlays display
- [ ] Real-time updates work
- [ ] FPS stable at 60
- [ ] Memory usage stable

---

## Success Criteria

1. **Build:** Successful, <2s
2. **Type Safety:** Zero TypeScript errors
3. **Functionality:** All features work as before
4. **Performance:** No degradation (60 FPS)
5. **Code Quality:** Avg file size <300 lines
6. **Maintainability:** Each component has single responsibility

---

## Risk Mitigations

1. **Breaking Changes:** Extract one component at a time, test after each
2. **Type Errors:** Create comprehensive prop interfaces
3. **Performance Issues:** Preserve all memoization patterns
4. **Visual Bugs:** Manual testing after each extraction
5. **Integration Complexity:** Use wrapper approach for tabs

---

**Prepared by:** AI Architecture Engineer  
**Date:** May 7, 2026  
**Status:** Ready for execution
