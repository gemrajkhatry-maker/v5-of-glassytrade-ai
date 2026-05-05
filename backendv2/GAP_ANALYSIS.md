# BackendV2 vs Backend — Feature-Level Gap Analysis

> **Backend**: 273 source files, 2,061 tests, production trading system
> **BackendV2**: 53 source files, 209 tests, event-driven rewrite in progress
> **Parity**: ~20% by file count, ~10% by feature completeness

---

## 1. Event System & Domain Foundation

| Feature | Backend | BackendV2 | Gap |
|---------|---------|-----------|-----|
| Domain events | 14 event types in `events.py` | 13 event types in `shared/event/` | ✅ Parity |
| Event bus | `EventBus` in `event_store.py` | `EventBus` in `application/event_bus.py` | ✅ Better (error isolation, replay) |
| Event store | SQLite + abstract | Abstract only | ⚠️ Need SQLite impl |
| Domain ports | 8 ports in `domain/ports/` | 6 ports in `shared/port/` | ⚠️ Missing config_port |
| DI container | `composition_root.py` + `container.py` | `di/container.py` | ✅ Cleaner |
| Enums | Full set | Full set | ✅ Parity |
| Value objects | Full set | Full set | ✅ Parity |
| Entities (Position, Signal) | Full lifecycle | Full lifecycle | ✅ Parity |
| Portfolio aggregate | Full (slippage, commission, scale-in) | Full | ✅ Parity |

## 2. AMT Analysis Pipeline

| Feature | Backend | BackendV2 | Gap |
|---------|---------|-----------|-----|
| Volume profile | 488L (CME Two-Row) | 130L (basic) | ⚠️ Need CME Two-Row pairs |
| LVN/HVN detection | 392L (percentile + smoothing) | 173L (basic percentile) | ⚠️ Need smoothing + clustering |
| CVD tracking | 163L | 162L | ✅ Near parity |
| Aggression scorer | 281L (7-component) | 70L (σ outlier only) | ❌ Need 7-component model |
| Acceptance/Rejection | 182L | 130L | ⚠️ Basic, need time accumulation |
| Market state engine | 145L | 7L (stub) | ❌ Need full implementation |
| Profile classifier | 238L | 7L (stub) | ❌ Need shape + POC migration |
| Order flow detectors | 343L | 7L (stub) | ❌ Need BigTrade, Bubble, OFI, Absorption |
| Initial balance engine | 172L | 7L (stub) | ❌ Need full IB analysis |
| Break detector | 286L | 7L (stub) | ❌ Need IB break detection |
| Displacement detector | 236L | 7L (stub) | ❌ Need displacement detection |
| Drive tracker | 314L | 7L (stub) | ❌ Need momentum tracking |
| Session context | 596L | 7L (stub) | ❌ Need gap, OBI, session info |
| MTF analyzer | 118L | 7L (stub) | ❌ Need daily/hourly alignment |
| Signal pipeline | 323L | — | ❌ Missing |
| Gate pipeline | 427L | — | ❌ Missing |
| Entry gates (6 modules) | ~800L total | — | ❌ Missing entirely |
| AMT pipeline | 445L | — | ❌ Missing |
| AMT parameters | 147L | — | ❌ Missing |
| Composite profile | 235L | — | ❌ Missing |
| Profile factory/selector | 136L | — | ❌ Missing |
| Multi-timeframe AMT | 506L | — | ❌ Missing |
| NPOC tracker | 189L | — | ❌ Missing |
| OI analyzer | 181L | — | ❌ Missing |
| Opening classifier | 96L | — | ❌ Missing |
| Opening type classifier | 393L | — | ❌ Missing |
| Footprint analyzer | 341L | — | ❌ Missing |
| Order book analyzer | 217L | — | ❌ Missing |
| Order flow service | 265L | — | ❌ Missing |
| Level tracker | 107L | — | ❌ Missing |
| Narrative builder | 99L | — | ❌ Missing |
| Trade thesis | 200L | — | ❌ Missing |
| RR validator | 116L | — | ❌ Missing |
| Spread normalizer | 116L | — | ❌ Missing |
| LVN play engine | 135L | — | ❌ Missing |
| LVN quality scorer | 120L | — | ❌ Missing |
| Drive decay | 180L | — | ❌ Missing |
| EIA calendar | 180L | — | ❌ Missing |
| NSE event calendar | 120L | — | ❌ Missing |
| Regime detector | 575L | — | ❌ Missing |
| Prediction engine | 209L | — | ❌ Missing |
| VP contract selector | 653L | — | ❌ Missing |
| VWAP service | 230L | — | ❌ Missing |
| Loss tracker | 528L | — | ❌ Missing |
| Scale manager | 168L | — | ❌ Missing |
| Market structure classifier | 423L | — | ❌ Missing |

## 3. Trade Management (Exit Domain)

| Feature | Backend | BackendV2 | Gap |
|---------|---------|-----------|-----|
| Exit engine | 519L | — | ❌ Missing |
| Exit rules | 585L | 80L (basic) | ⚠️ Need session-aware time stops |
| Trail engine | 460L | — | ❌ Missing |
| Partition exit manager | 231L | — | ❌ Missing |
| Pyramid manager | 110L | — | ❌ Missing |
| Position sizer | 136L | — | ❌ Missing |
| Structural stop engine | 335L | — | ❌ Missing |
| Exit signal | 18L | — | ❌ Missing |
| Exit models | — | 79L | ✅ New |

## 4. Risk Management

| Feature | Backend | BackendV2 | Gap |
|---------|---------|-----------|-----|
| Risk manager | 257L | — | ❌ Missing |
| Risk sizing engine | 668L | 61L (basic) | ⚠️ Need full implementation |
| Risk tier engine | 285L | — | ❌ Missing |
| Circuit breakers | 147L | In core_components | ⚠️ Need domain-level |
| Flash crash protector | 123L | — | ❌ Missing |
| Self-healing | 216L | — | ❌ Missing |
| Position reconciliation | 163L | — | ❌ Missing |
| Startup reconciliation | 143L | — | ❌ Missing |
| Kill switch | In risk_manager | — | ❌ Missing |
| Walk forward validator | 64L | — | ❌ Missing |
| Watchdog | 148L | — | ❌ Missing |
| State bus | 247L | — | ❌ Missing |
| Latency tracker | 95L | — | ❌ Missing |
| Mobile alerts | 140L | — | ❌ Missing |
| OI wall detector | 136L | — | ❌ Missing |
| OI wall engine | 182L | — | ❌ Missing |
| Option selection engine | 221L | — | ❌ Missing |
| Underlying futures provider | 289L | — | ❌ Missing |
| Symbol registry | 93L | — | ❌ Missing |
| Capital ladder | 94L | — | ❌ Missing |
| Fifteen sec trigger | 49L | — | ❌ Missing |
| Short signal gates | 172L | — | ❌ Missing |
| Session phase gate | 329L | — | ❌ Missing |
| Gate rejection tracker | 119L | — | ❌ Missing |
| Scalp gate pipeline | 87L | — | ❌ Missing |
| IB breakout scalp | 461L | — | ❌ Missing |
| One min bar engine | 162L | — | ❌ Missing |
| Tick delta | 194L | — | ❌ Missing |
| Tick utils | 82L | — | ❌ Missing |
| Candle metrics | 84L | — | ❌ Missing |
| Volatility features | 182L | — | ❌ Missing |
| Aggressive prints | 173L | — | ❌ Missing |
| Decimal utils | 45L | — | ❌ Missing |

## 5. AI/ML Domain

| Feature | Backend | BackendV2 | Gap |
|---------|---------|-----------|-----|
| Generative AI service | 98L | — | ❌ Missing |
| Prompt builder | 807L | — | ❌ Missing |
| Prompt engineering service | 203L | — | ❌ Missing |
| Response parser | 167L | — | ❌ Missing |
| LLM rationale service | 117L | — | ❌ Missing |
| Rule-based rationale | 267L | — | ❌ Missing |
| LLM contract | 47L | — | ❌ Missing |
| MLX compute | 301L | — | ❌ Missing |
| Learning engine | 100L | — | ❌ Missing |
| Prediction engine | 209L | — | ❌ Missing |
| Regime detector | 575L | — | ❌ Missing |
| Agent pipeline | ~400L | — | ❌ Missing |
| RL system (env, trainer, etc.) | ~600L | — | ❌ Missing |
| Option scanner | 560L | — | ❌ Missing |
| Option selector | 335L | — | ❌ Missing |
| Profile factory | 66L | — | ❌ Missing |
| Profile selector | 70L | — | ❌ Missing |
| Underlying profile router | 179L | — | ❌ Missing |
| Alert manager | 242L | 108L | ⚠️ Basic |

## 6. Application Layer (Orchestration)

| Feature | Backend | BackendV2 | Gap |
|---------|---------|-----------|-----|
| Trading session service | 868L | — | ❌ THE core orchestrator |
| Session state manager | 444L | — | ❌ Missing |
| Session cache | 360L | — | ❌ Missing |
| Session risk coordinator | 388L | — | ❌ Missing |
| Session event logger | 312L | — | ❌ Missing |
| Session event router | 703L | — | ❌ Missing |
| Session phase manager | 155L | — | ❌ Missing |
| AMT service | 149L | — | ❌ Missing |
| Entry coordinator | 295L | — | ❌ Missing |
| Exit coordinator | 237L | — | ❌ Missing |
| Signal coordinator | 98L | — | ❌ Missing |
| Signal tracking service | 385L | — | ❌ Missing |
| State broadcaster | 353L | — | ❌ Missing |
| State snapshot builder | 215L | — | ❌ Missing |
| Tick processor | 327L | — | ❌ Missing |
| Trade journal | 907L | — | ❌ Missing |
| Engine lifecycle | 492L | — | ❌ Missing |
| Backtest engine | 98L | — | ❌ Missing |
| Forward test logger | 134L | — | ❌ Missing |
| Gap detector | 340L | — | ❌ Missing |
| Phase manager | 175L | — | ❌ Missing |
| Experiment context | 70L | — | ❌ Missing |
| AMT coordinator | 81L | — | ❌ Missing |

## 7. Application Handlers

| Feature | Backend | BackendV2 | Gap |
|---------|---------|-----------|-----|
| LLM entry handler | 1212L | — | ❌ Missing |
| LLM overseer handler | 541L | — | ❌ Missing |
| LLM decision processor | 143L | — | ❌ Missing |
| LLM worker | 54L | — | ❌ Missing |
| LLM context | 166L | — | ❌ Missing |
| LLM signal processor | 99L | — | ❌ Missing |
| LLM utils | 128L | — | ❌ Missing |
| Trade lifecycle handler | 374L | — | ❌ Missing |
| AMT handler | 208L | — | ❌ Missing |
| Entry gate coordinator | 233L | — | ❌ Missing |
| Post trade analyst | 261L | — | ❌ Missing |
| Pre candle advisor | 190L | — | ❌ Missing |
| RL handler | 54L | — | ❌ Missing |
| Institutional detector | 115L | — | ❌ Missing |
| Episodic loader | 60L | — | ❌ Missing |

## 8. API Layer

| Feature | Backend | BackendV2 | Gap |
|---------|---------|-----------|-----|
| Trading router | 103L | — | ❌ Missing |
| Health router | 388L | — | ❌ Missing |
| Market router | 55L | — | ❌ Missing |
| AI router | 271L | — | ❌ Missing |
| RL router | 201L | — | ❌ Missing |
| Alerts router | 35L | — | ❌ Missing |
| Analysis router | 63L | — | ❌ Missing |
| Observability router | 33L | — | ❌ Missing |
| Metrics router | 56L | 30L | ⚠️ Basic |
| WebSocket / SSE | gameloop.py | — | ❌ Missing |
| FastAPI app | main.py | main.py (196L) | ⚠️ Basic |
| Dependencies | dependencies.py | — | ❌ Missing |

## 9. Infrastructure

| Feature | Backend | BackendV2 | Gap |
|---------|---------|-----------|-----|
| SQLite storage | 953L | — | ❌ Missing |
| PostgreSQL adapter | — | 163L | ✅ New |
| Redis cache | — | 103L | ✅ New |
| Dhan adapter | 507L | 80L | ⚠️ Basic |
| MLX inference adapter | 750L | — | ❌ Missing |
| GGUF inference adapter | 154L | — | ❌ Missing |
| LGBM probability adapter | 166L | — | ❌ Missing |
| Paper broker | 208L | — | ❌ Missing |
| MCX broker | ~200L | — | ❌ Missing |
| Delta profile adapter | 142L | — | ❌ Missing |
| NPOC adapter | 64L | — | ❌ Missing |
| Null notification adapter | 16L | — | ❌ Missing |
| Data generator | 81L | — | ❌ Missing |
| Serialization schemas | ~300L | — | ❌ Missing |
| Exchange strategies (NSE, MCX) | ~150L | — | ❌ Missing |
| Config adapter | ~100L | — | ❌ Missing |
| MLX GPU lock | ~50L | — | ❌ Missing |

## 10. Configuration

| Feature | Backend | BackendV2 | Gap |
|---------|---------|-----------|-----|
| base.yaml | ✅ | — | ❌ Missing |
| environments/*.yaml | 3 files | — | ❌ Missing |
| strategies/*.yaml | 2 files | — | ❌ Missing |
| feature_flags.yaml | ✅ | — | ❌ Missing |
| instruments.json | ✅ | — | ❌ Missing |
| config.py | ✅ | — | ❌ Missing |
| config_models/ | 6 files | — | ❌ Missing |

---

## Priority Ranking for Zero Parity

### P0 — Blocking (can't trade without these)

1. **TradingSessionService** — the central orchestrator (868L)
2. **SessionStateManager** — per-symbol state (444L)
3. **SessionCache** — cached analysis data (360L)
4. **TickProcessor** — tick processing pipeline (327L)
5. **EntryCoordinator** — signal gating + entry (295L)
6. **ExitCoordinator** — exit management (237L)
7. **SessionRiskCoordinator** — per-symbol risk (388L)
8. **StateSnapshotBuilder** — UI state (215L)
9. **StateBroadcaster** — frontend updates (353L)
10. **TradeLifecycleHandler** — position lifecycle (374L)
11. **TradeJournal** — trade recording (907L)
12. **EngineLifecycle** — startup/shutdown (492L)
13. **SQLiteStorage** — persistence (953L)
14. **DhanAdapter** — broker (507L → need full)
15. **PaperBroker** — simulation (208L)
16. **Config system** — YAML loading, settings
17. **API routers** — health, trading, market, AI, RL, alerts, analysis
18. **FastAPI app** — full middleware, CORS, lifespan
19. **WebSocket/SSE** — real-time frontend
20. **Serialization schemas** — Pydantic DTOs

### P1 — Core AMT (can't analyze without these)

21. **VolumeProfile** — CME Two-Row pairs (488L)
22. **LVNDetector** — full percentile + smoothing (392L)
23. **MarketStateEngine** — BALANCED/IMBALANCED (145L)
24. **BreakDetector** — IB break detection (286L)
25. **DisplacementDetector** — displacement (236L)
26. **InitialBalanceEngine** — IB analysis (172L)
27. **AggressionScorer** — full 7-component (281L)
28. **OrderFlowDetectors** — BigTrade, Bubble, OFI, Absorption (343L)
29. **SessionContext** — gap, OBI, session info (596L)
30. **ProfileClassifier** — shape + POC migration (238L)
31. **SignalGenerator** — Fabio spec gating (64L)
32. **GatePipeline** — multi-stage entry gating (427L)
33. **EntryGates** — confirmation bundle, detectors, grading (~800L)
34. **MTFAnalyzer** — multi-timeframe (118L)
35. **DriveTracker** — momentum (314L)
36. **LossTracker** — daily loss + circuit breakers (528L)

### P2 — Trade Management (can't manage positions without these)

37. **ExitEngine** — main exit orchestrator (519L)
38. **ExitRules** — session-aware time stops (585L)
39. **TrailEngine** — ATR/VWAP/CVD trailing (460L)
40. **PartitionExitManager** — P1/P2/P3 (231L)
41. **PyramidManager** — structured add-on (110L)
42. **PositionSizer** — fixed fractional (136L)
43. **StructuralStopEngine** — LVN/VA/IB-based SL (335L)
44. **RiskSizingEngine** — full implementation (668L)
45. **RiskTierEngine** — risk tier management (285L)

### P3 — Risk & Operations

46. **RiskManager** — daily drawdown, kill switch (257L)
47. **CircuitBreakers** — domain-level (147L)
48. **FlashCrashProtector** — flash crash protection (123L)
49. **SelfHealing** — order rejection, DB fallback (216L)
50. **PositionReconciliation** — position sync (163L)
51. **StartupReconciliation** — startup recovery (143L)
52. **Watchdog** — monitoring (148L)
53. **StateBus** — state event bus (247L)
54. **WalkForwardValidator** — OOS validation (64L)

### P4 — AI/ML

55. **LLMEntryHandler** — LLM-based entry (1212L)
56. **LLMOverseerHandler** — overseer validation (541L)
57. **LLMDecisionProcessor** — decision processing (143L)
58. **LLMWorker** — threaded LLM (54L)
59. **PromptBuilder** — prompt construction (807L)
60. **GenerativeAIService** — LLM integration (98L)
61. **ResponseParser** — LLM response parsing (167L)
62. **MLXCompute** — Apple Silicon GPU (301L)
63. **MLXInferenceAdapter** — MLX inference (750L)
64. **GGUFInferenceAdapter** — GGUF inference (154L)
65. **LGBMProbabilityAdapter** — LGBM probability (166L)
66. **RegimeDetector** — regime classification (575L)
67. **AgentPipeline** — probability agent (~400L)
68. **RLSystem** — RL training (~600L)
69. **OptionScanner** — options chain scanning (560L)
70. **OptionSelector** — option selection (335L)

### P5 — Advanced Features

71. **BacktestEngine** — historical backtesting (98L)
72. **ForwardTestLogger** — forward test logging (134L)
73. **GapDetector** — gap detection (340L)
74. **PhaseManager** — session phase management (175L)
75. **PostTradeAnalyst** — post-trade analysis (261L)
76. **PreCandleAdvisor** — pre-candle advisory (190L)
77. **InstitutionalDetector** — institutional detection (115L)
78. **UnderlyingFuturesProvider** — underlying futures (289L)
79. **OIWallDetector/Engine** — OI wall detection (318L)
80. **FootprintAnalyzer** — footprint analysis (341L)
81. **OrderBookAnalyzer** — order book analysis (217L)
82. **MarketStructureClassifier** — market structure (423L)
83. **VPContractSelector** — volume profile contract selection (653L)
84. **MultiTimeframeAMT** — multi-timeframe AMT (506L)
85. **NPOCAnalyzer** — NPOC tracking (189L)
86. **DriveDecay** — drive decay (180L)
87. **LevelTracker** — level tracking (107L)
88. **NarrativeBuilder** — narrative building (99L)
89. **TradeThesis** — trade thesis (200L)
90. **RRValidator** — risk-reward validation (116L)
91. **SpreadNormalizer** — spread normalization (116L)
92. **OpeningTypeClassifier** — opening type (393L)
93. **OpeningClassifier** — opening classification (96L)
94. **EIACalendar** — EIA calendar (180L)
95. **NSEEventCalendar** — NSE event calendar (120L)
96. **PredictionEngine** — prediction engine (209L)
97. **LearningEngine** — learning engine (100L)
98. **AbsorptionValidator** — absorption validation (145L)
99. **AlertManager** — alert management (242L)
100. **MobileAlerts** — mobile alerts (140L)

---

## Summary

| Layer | Backend Files | BackendV2 Files | Parity |
|-------|--------------|-----------------|--------|
| Event system | 1 | 13 | ✅ Better |
| Domain models | 20 | 7 | ✅ Core done |
| AMT services | 92 | 19 | ❌ ~20% |
| Exit/Trade mgmt | ~2000L | ~160L | ❌ ~8% |
| Risk domain | ~2500L | ~60L | ❌ ~2% |
| AI/ML | ~4000L | 0L | ❌ 0% |
| Application | 56 files | 7 files | ❌ ~12% |
| Handlers | 15 files | 3 files | ❌ ~20% |
| API | 14 files | 2 files | ❌ ~14% |
| Infrastructure | 23 files | 7 files | ❌ ~30% |
| **Total** | **~273** | **~53** | **~20%** |

### Key Insight

The **domain foundation** (events, models, portfolio) is solid at ~80% parity.
The **AMT pipeline** is at ~20% — the orchestrator exists but most specialized
services are stubs. The **application layer** (orchestration, handlers) is at
~12% — the critical `TradingSessionService`, `SessionStateManager`, `EntryCoordinator`,
`ExitCoordinator`, etc. are all missing. The **AI/ML layer** is at 0%.

### Recommended Approach

Rather than porting file-by-file, focus on **vertical slices** — complete one
end-to-end flow at a time:

1. **Slice 1**: Tick → AMT analysis → Signal (core pipeline)
2. **Slice 2**: Signal → Risk check → Entry → Position opened
3. **Slice 3**: Position → Tick → Exit check → Position closed
4. **Slice 4**: LLM entry handler → Overseer → Decision
5. **Slice 5**: Full session lifecycle (init, run, shutdown, recovery)
