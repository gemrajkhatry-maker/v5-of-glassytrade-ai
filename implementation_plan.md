# Implementation Plan

## Overview
Complete implementation of the GlassyTrade AI backend_v2 — a clean-room rebuild of the AMT (Auction Market Theory) Order Flow trading engine implementing Fabio Valentini's methodology for NSE/MCX Indian derivatives markets. The system must be pure deterministic with zero ML/LLM in the signal pipeline, using a 12-gate sequential validation system for trade entries.

## Types
Core type definitions for the trading system including Tick, Candle, OHLC, VolumeProfile, ValueArea, MarketState enums (NO_TRADE/BALANCED/IMBALANCED/PROBING), DriveResult, AggressionResult, GateResult, PositionSize, ExitSignal, PyramidSignal, and OutputSchema with 40+ fields for signal output.

## Files
New files to be created in backend_v2/src/:
- config/engine_config.py - Frozen dataclass with 50+ thresholds (LVN=0.15, HVN=2.0, value_area_pct=0.70, etc.)
- config/instruments.py - Per-symbol config (tick_size, lot_size, point_value, session times)
- core/tick_processor.py - Tick normalization with __slots__ for memory efficiency
- core/candle_builder.py - OHLCV candle construction from tick stream
- core/session_manager.py - Session boundary detection, warmup/dead zone classification
- core/symbol_state.py - Per-symbol mutable state dataclass
- profile/volume_profile.py - Session + Leg + Delta profiles with O(1) updates
- profile/node_detector.py - LVN/HVN detection with quality scoring (thinness 60% + proximity 40%)
- profile/leg_anchor.py - Leg start/reset detection on VA breaks
- profile/profile_selector.py - Active profile selection (SESSION/LEG/COMBINED)
- orderflow/cvd_engine.py - CVD + slope (20-candle window) + divergence detection
- orderflow/footprint_engine.py - Per-candle bid/ask aggregation + 3:1 imbalance at 40% cells
- orderflow/bubble_detector.py - Volume bubble at 2σ threshold with direction classification
- orderflow/absorption_detector.py - Dual condition: range < ATR×0.3 AND volume > avg×2.0
- orderflow/big_trade_detector.py - 3+ prints ≥ 5× avg within 2 ticks
- orderflow/ofi_calculator.py - Order Flow Imbalance over 10-candle rolling window
- orderflow/vwap_engine.py - VWAP with ±1σ and ±2σ bands
- orderflow/ib_detector.py - Initial Balance (first 2 candles) + break detection
- strategy/market_state_engine.py - 4-state machine with zone sub-classification
- strategy/drive_tracker.py - D1/D2/D3+ with rejection detection and momentum fade
- strategy/aggression_scorer.py - Additive weighted scoring (max 4.5, 7 components)
- strategy/trade_constructor.py - Level-based entry/SL/TP with R:R ≥ 1.5 and cushion ≤ 10 ticks
- strategy/rationale_generator.py - Rule-based deterministic rationale (no LLM)
- strategy/pipeline.py - Master 12-gate sequential pipeline
- risk/session_risk_manager.py - 0.5% per trade, 2% daily, 3 consecutive, 3% drawdown
- risk/position_sizer.py - Fixed fractional: risk_amount / risk_per_lot
- trade_management/partition_exit_manager.py - P1(30%@33%R), P2(50%@target), P3(20% trail)
- trade_management/pyramid_manager.py - Max 2 adds, aggression≥3.0, decreasing size
- trade_management/breakeven_manager.py - BE at 35% of R toward target
- data/dhan_ws_client.py - WebSocket tick stream with exponential backoff reconnect
- data/dhan_rest_client.py - REST API for L2 DOM polling (500ms)
- data/duckdb_store.py - DuckDB persistence (ticks, profiles, signals, trades)
- data/economic_calendar.py - EIA suppression windows for NATURALGAS/CRUDEOIL
- output/schema.py - Pydantic OutputSchema with 40+ fields
- output/signal_formatter.py - Format signals with deterministic rationale
- output/ws_publisher.py - WebSocket broadcast to connected clients
- scanner/option_scanner.py - Contract selection and ranking
- scanner/subscription_manager.py - Dynamic WS subscriptions (5-min rebalance)
- api/main.py - FastAPI app factory
- api/routers/signals.py, profiles.py, risk.py, trades.py, config_router.py

Tests to be created in backend_v2/tests/:
- unit/test_profile.py - 6 tests for volume profile
- unit/test_cvd.py - 4 tests for CVD engine
- unit/test_drive_tracker.py - 5 tests for drive detection
- unit/test_aggression.py - 5 tests for aggression scoring
- unit/test_risk_manager.py - 6 tests for risk management
- unit/test_partition_exit.py - 5 tests for partition exits
- integration/test_full_pipeline.py - 6 E2E scenarios
- performance/test_latency.py - 3 performance tests (P99 < 500ms)

## Functions
New functions to implement:
- TickProcessor.normalize_tick(raw_tick) -> Tick - Normalize raw WebSocket data
- CandleBuilder.update(tick) -> Optional[Candle] - Build candles, return on close
- VolumeProfile.update_bucket(price, volume, delta) - O(1) incremental update
- VolumeProfile.get_poc() -> float - Point of Control calculation
- VolumeProfile.get_value_area() -> Tuple[float, float] - VAH/VAL via 70% rule
- NodeDetector.detect_lvns(profile, threshold=0.15) -> List[LVN] - LVN detection
- NodeDetector.detect_hvns(profile, threshold=2.0) -> List[HVN] - HVN detection
- NodeDetector.score_lvn_quality(lvn, profile, midpoint) -> float - Quality scoring
- LegAnchor.detect_leg_start(price, vah, val, candle, avg_vol) -> Optional[dict]
- LegAnchor.should_reset_leg(price, val, vah) -> bool - Reset on VA re-entry
- ProfileSelector.select_active(market_state, leg_active) -> str - SESSION/LEG/COMBINED
- CVDEngine.update(delta) - Append delta to running CVD
- CVDEngine.get_slope(window=20) -> float - Linear regression slope
- CVDEngine.detect_divergence(price_extremes) -> Optional[str] - Bullish/Bearish
- FootprintEngine.update_cell(price, bid_vol, ask_vol) - Per-level aggregation
- FootprintEngine.detect_imbalance(candle) -> bool - 40% cells at 3:1 ratio
- BubbleDetector.detect(candle, hist_candles) -> BubbleResult - 2σ threshold
- AbsorptionDetector.detect(candle, atr, avg_vol) -> AbsorptionResult - Dual condition
- BigTradeDetector.detect(ticks, avg_trade_size) -> List[BigTradeCluster] - 5× avg, 3 prints
- OFICalculator.update(tick) -> float - Rolling 10-candle OFI
- VWAPEngine.update(candle) - Update VWAP and σ bands
- IBDetector.update(candle) -> IBResult - Track IB and detect breaks
- MarketStateEngine.detect(price, poc, vah, val, tick_size, displacement, acceptance) -> MarketState
- MarketStateEngine.classify_zone(price, poc, vah, val) -> str - NEAR_VAH/VAL/POC
- DriveTracker.classify_drive(price, level, candle, direction) -> DriveResult - D1/D2/D3+
- DriveTracker.detect_rejection(candle, level, direction) -> bool - Wick + close opposite
- DriveTracker.check_momentum_fade(d2_vol, d1_vol) -> bool - D2 < D1 volume
- AggressionScorer.score(fp, cvd, big_trade, absorption, ofi, confluence, bubble) -> AggressionResult
- TradeConstructor.build(direction, level, aggressive_print, poc, atr, tick_size) -> EntrySignal
- TradeConstructor.validate_cushion(entry, sl, tick_size) -> str - excellent/acceptable/invalid
- TradeConstructor.validate_rr(entry, sl, tp) -> bool - R:R ≥ 1.5
- GatePipeline.evaluate(context) -> GateResult - Sequential 12-gate validation
- SessionRiskManager.can_trade() -> Tuple[bool, str] - Check all kill switches
- SessionRiskManager.register_trade_result(pnl) - Track consecutive/daily
- PositionSizer.calculate(equity, entry, sl, point_value) -> PositionSize
- PartitionExitManager.check_exits(position, price, cvd_slope) -> List[ExitSignal]
- PyramidManager.check_pyramid(position, price, aggression, lvns) -> Optional[PyramidSignal]
- RationaleGenerator.generate(amt_result, gate_result, aggression_result) -> str - Rule-based

## Classes
New classes to implement:
- EngineConfig (frozen dataclass) - All 50+ thresholds, module-level CFG singleton
- InstrumentConfig (frozen dataclass) - Per-symbol tick_size, lot_size, point_value, session times
- Tick (dataclass with __slots__) - price, volume, delta, timestamp, symbol
- Candle (dataclass) - open, high, low, close, volume, buy_vol, sell_vol, timestamp
- SymbolState (dataclass) - All per-symbol mutable state (profiles, buffers, indicators, positions)
- VolumeProfileEngine - Session/leg/delta profile management with O(1) updates
- NodeDetector (static methods) - LVN/HVN detection and quality scoring
- LegAnchor - Leg start/reset detection logic
- ProfileSelector - Active profile selection based on market state
- CVDEngine - Cumulative Volume Delta with slope and divergence
- FootprintEngine - Per-candle per-level bid/ask aggregation
- BubbleDetector - Volume bubble detection at 2σ
- AbsorptionDetector - Absorption candle detection (dual condition)
- BigTradeDetector - Institutional print cluster detection
- OFICalculator - Order Flow Imbalance (10-candle rolling)
- VWAPEngine - VWAP with σ bands
- IBDetector - Initial Balance tracking and break detection
- MarketStateEngine (static methods) - 4-state classification + zone sub-classification
- DriveTracker - Per-level touch history with D1/D2/D3+ classification
- AggressionScorer (static method) - Additive weighted scoring (7 components, max 4.5)
- TradeConstructor - Entry/SL/TP construction from structural levels
- RationaleGenerator (static method) - Rule-based deterministic rationale
- GatePipeline - Sequential 12-gate validation (first fail = immediate output)
- SessionRiskManager - Daily loss, drawdown, consecutive loss kill switches
- PositionSizer (static method) - Fixed fractional position sizing
- PartitionExitManager - P1/P2/P3 exits + BE + counter-aggression
- PyramidManager - Max 2 adds, aggression gate, decreasing sizing
- DhanWSClient - WebSocket connection with exponential backoff
- DhanRESTClient - REST API for L2 DOM polling
- DuckDBStore - Persistence for ticks, profiles, signals, trades
- EconomicCalendar - EIA release window suppression
- OutputSchema (Pydantic model) - 40+ field signal output
- SignalFormatter - Format signals with rationale
- WSPublisher - WebSocket broadcast to clients
- OptionScanner - Contract selection and ranking
- SubscriptionManager - Dynamic WS subscriptions
- FastAPI app with routers for signals, profiles, risk, trades, config

## Dependencies
New packages to add to pyproject.toml:
- uvloop==0.21.0 - Fast async event loop
- websockets==13.1 - WebSocket client
- aiohttp==3.11.0 - Async HTTP client for REST API
- numpy==2.2.0 - Numerical operations (CVD slope, etc.)
- pandas==2.2.0 - Data manipulation
- orjson==3.10.0 - Fast JSON parsing
- fastapi==0.115.0 - Web framework
- uvicorn[standard]==0.34.0 - ASGI server
- pydantic==2.10.0 - Data validation
- duckdb==1.2.0 - Embedded analytical database
- python-dotenv==1.0.0 - Environment variable loading
- structlog==25.1.0 - Structured logging
- prometheus-client==0.21.0 - Metrics export
- pytest==8.3.0 - Testing framework
- pytest-asyncio==0.25.0 - Async test support

## Testing
Test strategy following the QA plan (114 total tests):
- 62 unit tests covering all modules (profile, CVD, drive, aggression, risk, partition exit)
- 12 integration tests for cross-module RACI bindings
- 20 validation tests for synthetic scenario verification
- 14 spec compliance tests to verify all thresholds match plan
- 6 E2E tests for full tick-to-signal pipeline scenarios
- 3 performance tests (latency < 500ms, O(1) profile update, 10 concurrent symbols)

Key test scenarios:
- TREND_LONG_AT_LVN: IMBALANCED market, pullback to LVN, D2, aggression 4.0
- BALANCED_MEAN_REVERSION: Inside VA, VAL rejection, CVD divergence, absorption
- NO_TRADE_AT_POC: Price at POC ±2 ticks, gate 3 fails
- PROBING_SUPPRESSED: Outside VA without displacement, gate 4 fails
- COUNTER_AGGRESSION_EXIT: 2+ opposite signals = exit ALL
- PYRAMID_ADD: In profit, aggression ≥3.0, new LVN, max 2 adds

## Implementation Order
Phase 0: Project Setup (pyproject.toml, .env.example, directory structure, DuckDB schema)
Phase 1: Config Layer (engine_config.py, instruments.py with all thresholds)
Phase 2: Core Data Layer (tick_processor.py, candle_builder.py, session_manager.py, symbol_state.py)
Phase 3: Profile Engine (volume_profile.py, node_detector.py, leg_anchor.py, profile_selector.py)
Phase 4: Order Flow Engines (cvd_engine.py, footprint_engine.py, bubble_detector.py, absorption_detector.py, big_trade_detector.py, ofi_calculator.py, vwap_engine.py, ib_detector.py)
Phase 5: Strategy Core (market_state_engine.py, drive_tracker.py, aggression_scorer.py, trade_constructor.py, rationale_generator.py, pipeline.py)
Phase 6: Risk Management (session_risk_manager.py, position_sizer.py)
Phase 7: Trade Management (partition_exit_manager.py, pyramid_manager.py, breakeven_manager.py)
Phase 8: Data Layer (duckdb_store.py, dhan_ws_client.py, dhan_rest_client.py, economic_calendar.py)
Phase 9: Output Layer (schema.py, signal_formatter.py, ws_publisher.py)
Phase 10: Scanner + API (option_scanner.py, subscription_manager.py, FastAPI app + routers)
Phase 11: Tests (31 unit + 6 integration + 3 performance tests)