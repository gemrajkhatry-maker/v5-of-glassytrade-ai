# Responsibility Matrix
## GlassyTrade AI — AMT Order Flow Strategy Engine

**Document Version:** 1.0
**Date:** 2026-03-17
**Status:** Draft
**Source Documents:** srs.md, fulldoc.md, startergy.md

---

## 1. Component Responsibility Matrix (RACI)

### Legend
- **R** = Responsible (does the work)
- **A** = Accountable (owns the decision)
- **C** = Consulted (provides input)
- **I** = Informed (kept updated)

### 1.1 Data Ingestion Components

| Component | TickProcessor | CandleBuilder | SessionManager | DhanWSClient | DhanRESTClient | DuckDBStore |
|---|---|---|---|---|---|---|
| Tick normalization | R | I | I | I | - | - |
| Candle building | C | R | I | I | - | - |
| Session boundary detection | I | I | R | I | - | C |
| WebSocket connection | I | I | I | R | - | - |
| L2 DOM polling | - | - | - | - | R | - |
| Data persistence | I | I | I | - | - | R |

### 1.2 Profile Components

| Component | VolumeProfile | ProfileSelector | NodeDetector | LegAnchor |
|---|---|---|---|---|
| Session profile build | R | I | I | I |
| Leg profile build | R | I | I | C |
| POC/VAH/VAL calculation | R | I | - | - |
| LVN/HVN detection | I | - | R | - |
| LVN quality scoring | I | - | R | - |
| Profile selection logic | I | R | C | C |
| Leg anchor detection | I | C | - | R |
| Leg reset logic | I | C | - | R |

### 1.3 OrderFlow Components

| Component | CVDEngine | FootprintEngine | BubbleDetector | AbsorptionDetector | BigTradeDetector | OFICalculator | VWAPEngine | IBDetector | L2Monitor |
|---|---|---|---|---|---|---|---|---|---|
| CVD calculation | R | I | - | - | - | - | - | - | - |
| CVD slope | R | - | - | - | - | - | - | - | - |
| CVD divergence | R | - | - | - | - | - | - | - | - |
| Footprint build | I | R | I | - | - | - | - | - | - |
| Footprint imbalance | I | R | - | - | - | - | - | - | - |
| Volume bubble detection | - | C | R | - | - | - | - | - | - |
| Absorption detection | - | - | - | R | - | - | - | - | - |
| Big trade cluster | - | - | - | - | R | - | - | - | - |
| OFI calculation | - | - | - | - | - | R | - | - | - |
| VWAP calculation | - | - | - | - | - | - | R | - | - |
| Initial Balance | - | - | - | - | - | - | - | R | - |
| L2 DOM monitoring | - | - | - | - | - | - | - | - | R |

### 1.4 Strategy Components

| Component | MarketStateEngine | DriveTracker | AggressionScorer | TradeConstructor | RationaleGenerator |
|---|---|---|---|---|---|
| Market state classification | R | I | I | I | I |
| Drive tracking | I | R | I | I | I |
| Drive classification | C | R | I | I | I |
| Aggression scoring | I | I | R | I | I |
| Trade setup construction | I | I | C | R | I |
| Stop loss calculation | I | - | - | R | - |
| Target calculation | I | - | - | R | - |
| R:R validation | I | - | - | R | - |
| Cushion validation | I | - | - | R | - |
| Rationale generation | I | I | I | C | R |

### 1.5 Risk Components

| Component | SessionRiskManager | PositionSizer |
|---|---|---|
| Daily loss tracking | R | I |
| Drawdown tracking | R | I |
| Consecutive loss tracking | R | I |
| Session kill switch | R | I |
| Position sizing | I | R |
| Risk validation | R | C |

### 1.6 Trade Management Components

| Component | PartitionExitManager | PyramidManager |
|---|---|---|
| P1 exit logic | R | I |
| P2 exit logic | R | I |
| P3 exit logic | R | I |
| Pyramid eligibility | I | R |
| Pyramid level detection | I | R |
| Pyramid sizing | I | R |
| Stop management (pyramid) | I | R |
| Break-even trigger | R | I |
| Trailing stop logic | R | I |
| Counter-aggression detection | R | I |
| Hard exit execution | R | I |

### 1.7 Output Components

| Component | Output Package |
|---|---|
| Output schema construction | Placeholder |
| WebSocket push | Placeholder |
| Schema validation | Placeholder |

---

## 2. Dependency Matrix

### 2.1 Upstream Dependencies (What each component depends on)

| Component | Depends On |
|---|---|
| TickProcessor | None |
| CandleBuilder | TickProcessor |
| SessionManager | Config |
| SymbolState | None |
| VolumeProfile | SymbolState, TickProcessor |
| ProfileSelector | MarketStateEngine, VolumeProfile |
| NodeDetector | VolumeProfile |
| LegAnchor | VolumeProfile, MarketStateEngine |
| CVDEngine | SymbolState, TickProcessor |
| FootprintEngine | SymbolState, TickProcessor |
| BubbleDetector | FootprintEngine |
| AbsorptionDetector | SymbolState |
| BigTradeDetector | SymbolState |
| OFICalculator | SymbolState |
| VWAPEngine | SymbolState |
| IBDetector | SymbolState |
| MarketStateEngine | VolumeProfile |
| AggressionScorer | CVDEngine, FootprintEngine, BubbleDetector, AbsorptionDetector, BigTradeDetector, OFICalculator |
| TradeConstructor | AggressionScorer, SessionRiskManager |
| SessionRiskManager | Persistence |
| PositionSizer | SessionRiskManager |
| PartitionExitManager | CVDEngine |
| PyramidManager | VolumeProfile, AggressionScorer |
| ATRCalculator | CandleBuilder |
| Persistence | DuckDB |
| Output Package | None |

### 2.2 Downstream Consumers (What depends on each component)

| Component | Consumed By |
|---|---|
| TickProcessor | CandleBuilder, VolumeProfile, CVDEngine, FootprintEngine |
| CandleBuilder | AbsorptionDetector, OFICalculator, VWAPEngine, IBDetector |
| SessionManager | All session-scoped modules |
| SymbolState | All modules (central state) |
| VolumeProfile | ProfileSelector, NodeDetector, LegAnchor, MarketStateEngine, PyramidManager |
| ProfileSelector | TradeConstructor |
| NodeDetector | TradeConstructor, PyramidManager |
| LegAnchor | VolumeProfile |
| CVDEngine | AggressionScorer, PartitionExitManager |
| FootprintEngine | AggressionScorer, BubbleDetector |
| BubbleDetector | AggressionScorer |
| AbsorptionDetector | AggressionScorer |
| BigTradeDetector | AggressionScorer |
| OFICalculator | AggressionScorer |
| VWAPEngine | Strategy modules |
| IBDetector | Strategy modules |
| MarketStateEngine | ProfileSelector, TradeConstructor |
| AggressionScorer | TradeConstructor, PyramidManager |
| TradeConstructor | PartitionExitManager |
| SessionRiskManager | TradeConstructor, PositionSizer, PyramidManager |
| PositionSizer | TradeConstructor |
| PartitionExitManager | Strategy outputs |
| PyramidManager | Strategy outputs |
| ATRCalculator | TradeConstructor, PartitionExitManager |
| Persistence | SessionRiskManager, VolumeProfile |
| Output Package | Future adapters |

---

## 3. Data Ownership Matrix

| Data Element | Owner | Readers | Writers |
|---|---|---|---|
| Raw ticks | DhanWSClient | TickProcessor | DhanWSClient |
| Normalized ticks | TickProcessor | All OrderFlow modules | TickProcessor |
| Candles | CandleBuilder | All OrderFlow/Strategy modules | CandleBuilder |
| Session profile | VolumeProfile | ProfileSelector, MarketStateEngine, TradeConstructor | VolumeProfile |
| Leg profile | VolumeProfile | ProfileSelector, PyramidManager | VolumeProfile |
| POC/VAH/VAL | VolumeProfile | All strategy modules | VolumeProfile |
| LVNs/HVNs | NodeDetector | TradeConstructor, PyramidManager | NodeDetector |
| CVD series | CVDEngine | AggressionScorer, PartitionExitManager | CVDEngine |
| Footprint | FootprintEngine | AggressionScorer, BubbleDetector | FootprintEngine |
| Market state | MarketStateEngine | All strategy modules | MarketStateEngine |
| Aggression score | AggressionScorer | TradeConstructor, PyramidManager | AggressionScorer |
| Trade setup | TradeConstructor | PartitionExitManager | TradeConstructor |
| Risk state | SessionRiskManager | TradeConstructor, PositionSizer, PyramidManager | SessionRiskManager |
| Open entries | SymbolState | PartitionExitManager, PyramidManager | TradeConstructor, PyramidManager |
| Session PnL | SessionRiskManager | Strategy outputs | SessionRiskManager |
| Output schema | Output Package | Future adapters | Output Package |

---

## 4. Module Complexity & Criticality

| Module | Complexity | Criticality | Risk Level | Notes |
|---|---|---|---|---|
| TickProcessor | Low | Critical | Low | Simple normalization |
| CandleBuilder | Medium | Critical | Low | Time-boundary logic |
| VolumeProfile | High | Critical | Medium | O(1) update critical |
| CVDEngine | Medium | High | Low | Cumulative calculation |
| FootprintEngine | High | Critical | Medium | Per-level aggregation |
| MarketStateEngine | High | Critical | High | Core routing logic |
| AggressionScorer | High | Critical | High | Multi-signal aggregation |
| TradeConstructor | High | Critical | High | Entry/SL/Target logic |
| SessionRiskManager | Medium | Critical | High | Capital protection |
| PartitionExitManager | High | High | Medium | Complex exit logic |
| PyramidManager | High | High | Medium | Add-on logic |
| ATRCalculator | Low | High | Low | Volatility normalization |
| Persistence | Low | High | Medium | State durability |

---

## 5. Testing Responsibility Matrix

| Module | Unit Tests | Integration Tests | Owner |
|---|---|---|---|
| TickProcessor | R | C | TBD |
| CandleBuilder | R | C | TBD |
| VolumeProfile | R | C | TBD |
| CVDEngine | R | C | TBD |
| FootprintEngine | R | C | TBD |
| BubbleDetector | R | C | TBD |
| AbsorptionDetector | R | C | TBD |
| MarketStateEngine | R | C | TBD |
| DriveTracker | R | C | TBD |
| AggressionScorer | R | C | TBD |
| TradeConstructor | R | C | TBD |
| SessionRiskManager | R | C | TBD |
| PositionSizer | R | C | TBD |
| PartitionExitManager | R | C | TBD |
| PyramidManager | R | C | TBD |
| CounterAggression | R | C | TBD |
| DhanWSClient | C | R | TBD |
| DhanRESTClient | C | R | TBD |
| DuckDBStore | C | R | TBD |
| End-to-End Pipeline | - | R | TBD |

---

## 6. Change Impact Matrix

When modifying a component, these other components may be affected:

| Modified Component | Potentially Affected Components |
|---|---|
| TickProcessor | All OrderFlow modules, CandleBuilder |
| CandleBuilder | All modules using candle data |
| VolumeProfile | MarketStateEngine, ProfileSelector, NodeDetector, TradeConstructor, PyramidManager |
| CVDEngine | AggressionScorer, PartitionExitManager, CounterAggression |
| FootprintEngine | AggressionScorer, BubbleDetector, CounterAggression |
| MarketStateEngine | ProfileSelector, DriveTracker, TradeConstructor |
| DriveTracker | TradeConstructor |
| AggressionScorer | TradeConstructor, PyramidManager |
| TradeConstructor | SignalFormatter, PartitionExitManager, BreakevenManager |
| SessionRiskManager | TradeConstructor, PositionSizer, PyramidManager |
| Config (instruments) | All modules using tick_size, lot_size, thresholds |
| Config (engine) | All modules using thresholds |

---

**Document Control:**
- Created: 2026-03-17
- Last Modified: 2026-03-17
- Next Review: TBD
- Approved By: TBD
