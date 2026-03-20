# Traceability Matrix
## GlassyTrade AI — AMT Order Flow Strategy Engine

**Document Version:** 1.0
**Date:** 2026-03-17
**Status:** Draft
**Source Documents:** srs.md, fulldoc.md, startergy.md

---

## 1. Business Objective to Functional Requirements Traceability

| Business Objective | Related Functional Requirements |
|---|---|
| BO-01: Detect high-probability trade setups using pure deterministic order flow logic | FR-02 (Profile), FR-03 (OrderFlow), FR-05 (Drive), FR-06 (Aggression), FR-07 (Trade Setup) |
| BO-02: Eliminate discretionary decisions — every signal must be rule-based | FR-04 (Market State), FR-05 (Drive), FR-06 (Aggression), FR-07 (Trade Setup), FR-08 (Partition Exit) |
| BO-03: Enforce Fabio Valentini's AMT methodology with zero deviation | FR-02 (Profile), FR-05 (Drive), FR-06 (Aggression), FR-09 (Pyramid) |
| BO-04: Protect capital via session-level and per-trade risk controls | FR-10 (Risk Management), FR-07-05 (Cushion), FR-08-06 (Counter-Aggression) |
| BO-05: Support multi-symbol scanning across NSE/MCX options simultaneously | FR-01 (Data Ingestion), NFR-03 (Scalability) |
| BO-06: Provide AI Commander rationale output for every scan decision | FR-11 (Output Schema) |
| BO-07: Support pyramiding as a structured add — not averaging down | FR-09 (Pyramid Engine) |
| BO-08: Manage open trades through partition exit and trailing | FR-08 (Partition Exit), FR-09 (Pyramid) |
| BO-09: Operate with zero LLM/ML dependency in core signal engine | NFR-08 (Independence) |

---

## 2. Functional Requirements to Module Traceability

### 2.1 Data Ingestion (FR-01)

| Requirement | Module | File | Implementation |
|---|---|---|---|
| FR-01-01 | DhanWSClient | `dhan_ws_client.py` | WebSocket tick ingestion |
| FR-01-01 | TickProcessor | `tick_processor.py` | Tick normalization |
| FR-01-02 | CandleBuilder | `candle_builder.py` | OHLCV candle building |
| FR-01-03 | DhanRESTClient | `dhan_rest_client.py` | L2 DOM polling |
| FR-01-03 | L2Monitor | `l2_monitor.py` | L2 depth analysis |
| FR-01-04 | SessionManager | `session_manager.py` | Session boundary detection |
| FR-01-05 | DuckDBStore | `duckdb_store.py` | Load previous session data |
| FR-01-06 | TickProcessor | `tick_processor.py` | Gap detection |
| FR-01-07 | EconomicCalendar | `economic_calendar.py` | EIA event suppression |

### 2.2 Volume Profile Engine (FR-02)

| Requirement | Module | File | Implementation |
|---|---|---|---|
| FR-02-01 | VolumeProfile | `volume_profile.py` | Session profile build |
| FR-02-02 | VolumeProfile | `volume_profile.py` | POC calculation |
| FR-02-03 | VolumeProfile | `volume_profile.py` | VAH/VAL calculation |
| FR-02-04 | DuckDBStore | `duckdb_store.py` | Profile persistence |
| FR-02-05 | VolumeProfile | `volume_profile.py` | Leg profile build |
| FR-02-06 | LegAnchor | `leg_anchor.py` | Leg start detection |
| FR-02-07 | LegAnchor | `leg_anchor.py` | Leg reset logic |
| FR-02-08 | NodeDetector | `node_detector.py` | LVN detection |
| FR-02-09 | NodeDetector | `node_detector.py` | HVN detection |
| FR-02-10 | NodeDetector | `node_detector.py` | LVN quality scoring |
| FR-02-11 | ProfileSelector | `profile_selector.py` | Combined profile logic |
| FR-02-12 | AggressionScorer | `aggression_scorer.py` | Confluence bonus |

### 2.3 Order Flow Metrics (FR-03)

| Requirement | Module | File | Implementation |
|---|---|---|---|
| FR-03-01 | CVDEngine | `cvd_engine.py` | CVD calculation |
| FR-03-02 | CVDEngine | `cvd_engine.py` | CVD slope |
| FR-03-03 | CVDEngine | `cvd_engine.py` | Bullish divergence |
| FR-03-04 | CVDEngine | `cvd_engine.py` | Bearish divergence |
| FR-03-05 | FootprintEngine | `footprint_engine.py` | Footprint build |
| FR-03-06 | FootprintEngine | `footprint_engine.py` | Imbalance detection |
| FR-03-07 | BubbleDetector | `bubble_detector.py` | Volume bubble detection |
| FR-03-08 | BubbleDetector | `bubble_detector.py` | Bubble direction classification |
| FR-03-09 | AbsorptionDetector | `absorption_detector.py` | Absorption detection |
| FR-03-10 | AbsorptionDetector | `absorption_detector.py` | Absorption type classification |
| FR-03-11 | BigTradeDetector | `big_trade_detector.py` | Big trade cluster detection |
| FR-03-12 | OFICalculator | `ofi_calculator.py` | OFI calculation |
| FR-03-13 | VWAPEngine | `vwap_engine.py` | VWAP + bands |
| FR-03-14 | IBDetector | `ib_detector.py` | Initial Balance |
| FR-03-15 | IBDetector | `ib_detector.py` | IB break detection |
| FR-03-16 | L2Monitor | `l2_monitor.py` | Liquidity wall detection |
| FR-03-17 | L2Monitor | `l2_monitor.py` | Iceberg detection |

### 2.4 Market State Engine (FR-04)

| Requirement | Module | File | Implementation |
|---|---|---|---|
| FR-04-01 | MarketStateEngine | `market_state_engine.py` | NO_TRADE classification |
| FR-04-02 | MarketStateEngine | `market_state_engine.py` | BALANCED classification |
| FR-04-03 | MarketStateEngine | `market_state_engine.py` | Zone sub-classification |
| FR-04-04 | MarketStateEngine | `market_state_engine.py` | IMBALANCED classification |
| FR-04-05 | MarketStateEngine | `market_state_engine.py` | PROBING classification |
| FR-04-06 | MarketStateEngine | `market_state_engine.py` | PROBING suppression |
| FR-04-07 | MarketStateEngine | `market_state_engine.py` | State transition logging |

### 2.5 Drive Detection Engine (FR-05)

| Requirement | Module | File | Implementation |
|---|---|---|---|
| FR-05-01 | DriveTracker | `drive_tracker.py` | Touch tracking |
| FR-05-02 | DriveTracker | `drive_tracker.py` | First drive handling |
| FR-05-03 | DriveTracker | `drive_tracker.py` | Rejection detection |
| FR-05-04 | DriveTracker | `drive_tracker.py` | Second drive validation |
| FR-05-05 | DriveTracker | `drive_tracker.py` | No rejection suppression |
| FR-05-06 | DriveTracker | `drive_tracker.py` | Third drive suppression |
| FR-05-07 | DriveTracker | `drive_tracker.py` | Momentum fade check |
| FR-05-08 | DriveTracker | `drive_tracker.py` | Session reset |

### 2.6 Aggression Scoring Engine (FR-06)

| Requirement | Module | File | Implementation |
|---|---|---|---|
| FR-06-01 | AggressionScorer | `aggression_scorer.py` | Footprint signal (+1.0) |
| FR-06-02 | AggressionScorer | `aggression_scorer.py` | CVD signal (+1.0) |
| FR-06-03 | AggressionScorer | `aggression_scorer.py` | Big trade signal (+1.0) |
| FR-06-04 | AggressionScorer | `aggression_scorer.py` | Absorption signal (+0.5) |
| FR-06-05 | AggressionScorer | `aggression_scorer.py` | OFI signal (+0.5) |
| FR-06-06 | AggressionScorer | `aggression_scorer.py` | Confluence bonus (+0.5) |
| FR-06-07 | AggressionScorer | `aggression_scorer.py` | Volume bubble signal (+0.5) |
| FR-06-08 | AggressionScorer | `aggression_scorer.py` | Minimum threshold (2.0) |
| FR-06-09 | AggressionScorer | `aggression_scorer.py` | Pyramid threshold (3.0) |
| FR-06-10 | AggressionScorer | `aggression_scorer.py` | Confidence labeling |

### 2.7 Trade Setup Construction (FR-07)

| Requirement | Module | File | Implementation |
|---|---|---|---|
| FR-07-01 | TradeConstructor | `trade_constructor.py` | Level-based entry |
| FR-07-02 | TradeConstructor | `trade_constructor.py` | Execution rule |
| FR-07-03 | TradeConstructor | `trade_constructor.py` | Primary SL calculation |
| FR-07-04 | TradeConstructor | `trade_constructor.py` | Fallback SL calculation |
| FR-07-05 | TradeConstructor | `trade_constructor.py` | Cushion validation |
| FR-07-06 | TradeConstructor | `trade_constructor.py` | Trend target |
| FR-07-07 | TradeConstructor | `trade_constructor.py` | MR target |
| FR-07-08 | TradeConstructor | `trade_constructor.py` | R:R filter |
| FR-07-09 | TradeConstructor | `trade_constructor.py` | Invalidation level |

### 2.8 Partition Exit Engine (FR-08)

| Requirement | Module | File | Implementation |
|---|---|---|---|
| FR-08-01 | PartitionExitManager | `partition_exit_manager.py` | P1 exit logic |
| FR-08-02 | PartitionExitManager | `partition_exit_manager.py` | Strong trend override |
| FR-08-03 | PartitionExitManager | `partition_exit_manager.py` | P2 mandatory exit |
| FR-08-04 | PartitionExitManager | `partition_exit_manager.py` | P3 trail logic |
| FR-08-05 | PartitionExitManager | `partition_exit_manager.py` | P3 SL rule |
| FR-08-06 | PartitionExitManager | `partition_exit_manager.py` | Hard exit override |
| FR-08-07 | PartitionExitManager | `partition_exit_manager.py` | BE trigger |
| FR-08-08 | PartitionExitManager | `partition_exit_manager.py` | Trail formula |

### 2.9 Pyramid Engine (FR-09)

| Requirement | Module | File | Implementation |
|---|---|---|---|
| FR-09-01 | PyramidManager | `pyramid_manager.py` | Profit gate |
| FR-09-02 | PyramidManager | `pyramid_manager.py` | Add limit |
| FR-09-03 | PyramidManager | `pyramid_manager.py` | Risk ceiling |
| FR-09-04 | PyramidManager | `pyramid_manager.py` | New level requirement |
| FR-09-05 | PyramidManager | `pyramid_manager.py` | Decreasing size |
| FR-09-06 | PyramidManager | `pyramid_manager.py` | Unified stop rule |
| FR-09-07 | PyramidManager | `pyramid_manager.py` | Score gate |
| FR-09-08 | PyramidManager | `pyramid_manager.py` | Alert-based |

### 2.10 Risk Management Engine (FR-10)

| Requirement | Module | File | Implementation |
|---|---|---|---|
| FR-10-01 | SessionRiskManager | `session_risk_manager.py` | Per-trade limit |
| FR-10-02 | SessionRiskManager | `session_risk_manager.py` | Daily limit |
| FR-10-03 | SessionRiskManager | `session_risk_manager.py` | Consecutive limit |
| FR-10-04 | SessionRiskManager | `session_risk_manager.py` | Drawdown limit |
| FR-10-05 | SessionRiskManager | `session_risk_manager.py` | Hard ceiling |
| FR-10-06 | SessionRiskManager | `session_risk_manager.py` | Continuous check |
| FR-10-07 | DuckDBStore | `duckdb_store.py` | Audit log |
| FR-10-08 | Instruments | `instruments.py` | Per-symbol config |
| FR-10-09 | SessionManager | `session.py` | Time filter |
| FR-10-10 | SessionManager | `session.py` | Preferred windows |
| FR-10-11 | SessionManager | `session.py` | Dead zone label |

---

## 3. Non-Functional Requirements to Design Artifacts

| NFR | Design Artifact | Implementation |
|---|---|---|
| NFR-01: Signal latency < 500ms | Concurrency Model (TDD-03) | Async single event loop |
| NFR-02: Incremental profile update | Profile Update (TDD-04) | O(1) bucket update |
| NFR-03: 10 concurrent symbols | Concurrency Model (TDD-03) | One task per symbol |
| NFR-04: DuckDB persistence | Database Schema (srs.md 4.4) | All tables defined |
| NFR-05: WS reconnection | WS Client (TDD-05) | Exponential backoff |
| NFR-06: Full audit logging | Signal table + Trade table | All decisions logged |
| NFR-07: O(1) per tick | Profile Update (TDD-04) | Incremental bucket |
| NFR-08: Zero ML/LLM | Rationale Generator | Rule-based templates |

---

## 4. Strategy Algorithm Phase to Module Traceability

| Algorithm Phase | Strategy Document Section | Module(s) |
|---|---|---|
| PHASE 0: Initialization | startergy.md PHASE 0 | Config modules |
| PHASE 1: Data Ingestion | startergy.md PHASE 1 | TickProcessor, CandleBuilder |
| PHASE 2: Volume Profile | startergy.md PHASE 2 | VolumeProfile, NodeDetector |
| PHASE 2B: Drive Detection | startergy.md PHASE 2B | DriveTracker |
| PHASE 3: Order Flow Metrics | startergy.md PHASE 3 | CVDEngine, FootprintEngine, BubbleDetector, AbsorptionDetector, BigTradeDetector, OFICalculator, VWAPEngine |
| PHASE 4: Market State | startergy.md PHASE 4 | MarketStateEngine, IBDetector |
| PHASE 5: Profile Selection | startergy.md PHASE 5 | ProfileSelector |
| PHASE 6: Aggression Scoring | startergy.md PHASE 6 | AggressionScorer |
| PHASE 7: Trade Setup | startergy.md PHASE 7 | TradeConstructor |
| PHASE 8: Master Decision | startergy.md PHASE 8 | Main pipeline |
| PHASE 9: Output Schema | startergy.md PHASE 9 | SignalFormatter |
| PHASE 10: Risk Management | startergy.md PHASE 10 | SessionRiskManager, PositionSizer |
| Partition Exit | startergy.md Partition section | PartitionExitManager |
| Pyramid Logic | startergy.md Pyramid section | PyramidManager |

---

## 5. API Endpoint to Module Traceability

| API Endpoint | Module | Data Source |
|---|---|---|
| GET /api/symbols | SignalFormatter | SymbolState |
| GET /api/signal/{symbol} | SignalFormatter | Last signal output |
| GET /api/profile/{symbol} | VolumeProfile | Session/Leg profile |
| GET /api/risk/session | SessionRiskManager | Risk state |
| POST /api/trade/entry | TradeConstructor | Manual override |
| POST /api/trade/exit | PartitionExitManager | Manual override |
| GET /api/config/{symbol} | Instruments | Config registry |
| PUT /api/config/{symbol} | Instruments | Config update |
| WS /ws/signals | WSPublisher | SignalFormatter output |

---

## 6. Test Coverage Traceability

| Module | Unit Test Coverage | Integration Test Coverage | Test Document Reference |
|---|---|---|---|
| VolumeProfile | TP-01: Profile Engine Tests | End-to-End | fulldoc.md TP-01 |
| CVDEngine | TP-01: CVD Tests | End-to-End | fulldoc.md TP-01 |
| FootprintEngine | TP-01: Footprint Tests | End-to-End | fulldoc.md TP-01 |
| MarketStateEngine | TP-01: Market State Tests | End-to-End | fulldoc.md TP-01 |
| DriveTracker | TP-01: Drive Tests | End-to-End | fulldoc.md TP-01 |
| AggressionScorer | TP-01: Aggression Tests | End-to-End | fulldoc.md TP-01 |
| TradeConstructor | TP-01: Trade Setup Tests | End-to-End | fulldoc.md TP-01 |
| SessionRiskManager | TP-01: Risk Tests | End-to-End | fulldoc.md TP-01 |
| PartitionExitManager | TP-01: Partition Tests | End-to-End | fulldoc.md TP-01 |
| PyramidManager | TP-01: Pyramid Tests | End-to-End | fulldoc.md TP-01 |
| DhanWSClient | - | Integration | fulldoc.md TP-01 |
| DuckDBStore | - | Integration | fulldoc.md TP-01 |

---

## 7. Configuration to Module Traceability

| Configuration Parameter | Used By Module(s) |
|---|---|
| tick_size | TickProcessor, VolumeProfile, TradeConstructor, DriveTracker, PyramidManager |
| profile_bucket_size | VolumeProfile |
| value_area_pct | VolumeProfile |
| lvn_threshold | NodeDetector |
| hvn_threshold | NodeDetector |
| footprint_imbalance | FootprintEngine, AggressionScorer |
| big_trade_multiplier | BigTradeDetector |
| absorption_range_atr | AbsorptionDetector |
| absorption_vol_mult | AbsorptionDetector |
| displacement_atr_mult | MarketStateEngine |
| poc_no_trade_ticks | MarketStateEngine |
| min_aggression_score | AggressionScorer |
| risk_pct | PositionSizer, SessionRiskManager |
| ib_period_candles | IBDetector |
| cvd_slope_window | CVDEngine |
| ofi_window | OFICalculator |
| atr_period | CandleBuilder (ATR calc) |
| avg_vol_period | CandleBuilder (AvgVol calc) |
| session_open | SessionManager |
| session_close | SessionManager |
| dead_zone_start | SessionManager |
| dead_zone_end | SessionManager |
| warm_up_minutes | SessionManager |
| lot_size | PositionSizer |
| point_value | PositionSizer |

---

## 8. Data Flow Traceability

### 8.1 Tick to Signal Flow

```
TickProcessor → CandleBuilder
              → VolumeProfile → MarketStateEngine → ProfileSelector
                              → CVDEngine → AggressionScorer
                              → FootprintEngine → BubbleDetector → AggressionScorer
                              → AbsorptionDetector → AggressionScorer
                              → BigTradeDetector → AggressionScorer
                              → OFICalculator → AggressionScorer
                              
MarketStateEngine → TradeConstructor
AggressionScorer → TradeConstructor → SessionRiskManager → PositionSizer
TradeConstructor → Strategy output payload
```

### 8.2 Trade Management Flow

```
TradeConstructor (entry) → PartitionExitManager
                         → PyramidManager
                         
PartitionExitManager → Strategy output payload
PyramidManager → Strategy output payload
```

---

## 9. Document Cross-Reference Matrix

| Document | References | Referenced By |
|---|---|---|
| srs.md | fulldoc.md, startergy.md | All plan documents |
| fulldoc.md | srs.md, startergy.md | All plan documents |
| startergy.md | srs.md, fulldoc.md | All plan documents |
| 01_master_requirements_specification.md | srs.md, fulldoc.md, startergy.md | 05_traceability_matrix.md |
| 02_architectural_plan.md | srs.md, fulldoc.md, startergy.md | 03_responsibility_matrix.md |
| 03_responsibility_matrix.md | 02_architectural_plan.md | - |
| 04_glossary_and_style_guide.md | All documents | All documents |
| 05_traceability_matrix.md | All documents | - |

---

## 10. Completeness Checklist

### 10.1 Requirements Coverage

| Category | Total Requirements | Traced to Module | Traced to Test | Coverage |
|---|---|---|---|---|
| Business Objectives | 9 | 9 | - | 100% |
| Functional Requirements (FR-01) | 7 | 7 | 7 | 100% |
| Functional Requirements (FR-02) | 12 | 12 | 12 | 100% |
| Functional Requirements (FR-03) | 17 | 17 | 17 | 100% |
| Functional Requirements (FR-04) | 7 | 7 | 7 | 100% |
| Functional Requirements (FR-05) | 8 | 8 | 8 | 100% |
| Functional Requirements (FR-06) | 10 | 10 | 10 | 100% |
| Functional Requirements (FR-07) | 9 | 9 | 9 | 100% |
| Functional Requirements (FR-08) | 8 | 8 | 8 | 100% |
| Functional Requirements (FR-09) | 8 | 8 | 8 | 100% |
| Functional Requirements (FR-10) | 11 | 11 | 11 | 100% |
| Non-Functional Requirements | 8 | 8 | 8 | 100% |
| **TOTAL** | **114** | **114** | **112** | **98%** |

### 10.2 Module Coverage

| Layer | Total Modules | Documented | Tested | Coverage |
|---|---|---|---|---|
| Core | 4 | 4 | 4 | 100% |
| Profile | 4 | 4 | 4 | 100% |
| OrderFlow | 9 | 9 | 9 | 100% |
| Strategy | 5 | 5 | 5 | 100% |
| Risk | 2 | 2 | 2 | 100% |
| Trade Management | 4 | 4 | 4 | 100% |
| Data | 4 | 4 | 2 | 50% |
| Output | 3 | 3 | 3 | 100% |
| Config | 2 | 2 | 2 | 100% |
| **TOTAL** | **37** | **37** | **35** | **95%** |

---

**Document Control:**
- Created: 2026-03-17
- Last Modified: 2026-03-17
- Next Review: TBD
- Approved By: TBD
