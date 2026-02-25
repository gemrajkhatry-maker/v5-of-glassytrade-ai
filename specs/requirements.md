# Requirements Document: GlassyTrade AI v5 — Fabio Code Review Gaps

## Introduction

This document captures 10 prioritized improvement gaps identified from a code review of the GlassyTrade AI v5 trading platform against Fabio Valentini's Auction Market Theory (AMT) methodology. The system uses a FastAPI backend with LLM-driven entry decisions and deterministic TradeManager exits, paired with a React frontend. Each gap is independently implementable and must include unit tests with no regressions to the existing test suite.

---

## Requirements

### Requirement 1: Breakeven Too Slow

**Priority:** HIGH | **Effort:** SMALL

**User Story:** As a trader, I want my stop-loss moved to breakeven at 1R (one risk unit) instead of 50% of TP distance, so that I lock in risk-free trades faster and reduce give-back on winning positions.

#### Acceptance Criteria

1. WHEN a position's unrealised profit reaches 1R (distance from entry to initial stop-loss) THEN TradeManager SHALL move the stop-loss to breakeven (entry price + fees).
2. WHEN CVD confirms the trade direction within 1 candle of entry THEN TradeManager SHALL move the stop-loss to breakeven, regardless of profit distance.
3. WHEN both the 1R threshold and the CVD confirmation occur THEN TradeManager SHALL use whichever triggers first.
4. WHEN trail activation is evaluated THEN TradeManager SHALL activate trailing at 1R distance, not at 50% of TP distance.
5. IF a position has already been moved to breakeven THEN TradeManager SHALL NOT move the stop-loss back below breakeven.

---

### Requirement 2: Intraday Compounding / Cushion System

**Priority:** HIGH | **Effort:** MEDIUM

**User Story:** As a trader, I want my position sizing to scale dynamically based on session P&L, so that I risk less at the start, compound on winning streaks, and stop trading after consecutive losses.

#### Acceptance Criteria

1. WHEN a new trading session starts THEN RiskManager SHALL set risk-per-trade to 0.25% (conservative mode) for the first 1-2 trades.
2. WHEN session P&L is positive after the conservative phase THEN RiskManager SHALL set risk-per-trade to 0.35% plus 20% of session profit (cushion mode).
3. WHEN 2 or more consecutive wins have occurred in the session THEN RiskManager SHALL set risk-per-trade to 0.40% (momentum mode).
4. WHILE risk-per-trade is being calculated THEN RiskManager SHALL enforce a hard cap of 0.50% and never exceed 30% of session profit.
5. WHEN 1 consecutive loss occurs THEN RiskManager SHALL maintain the current risk tier.
6. WHEN 2 consecutive losses occur THEN RiskManager SHALL revert risk-per-trade to 0.25%.
7. WHEN 3 consecutive losses occur THEN RiskManager SHALL halt all new entries for the remainder of the session.
8. IF session P&L data is unavailable THEN RiskManager SHALL default to 0.25% risk-per-trade.

---

### Requirement 3: Second Drive Enforcement

**Priority:** HIGH | **Effort:** MEDIUM

**User Story:** As a trader, I want the system to distinguish first-touch from second-touch at a price level, so that second-drive entries (higher probability per AMT) are weighted more heavily.

#### Acceptance Criteria

1. WHEN price touches a tracked level for the first time THEN LevelTracker SHALL record the touch with a timestamp.
2. WHEN price moves away from a level by at least 1 ATR and then returns THEN LevelTracker SHALL mark that level as "second drive".
3. WHEN an entry signal is generated at a second-drive level THEN EntryGate SHALL add +2 to the grade_score.
4. WHEN an entry signal is generated at a first-touch level THEN EntryGate SHALL apply a -1 penalty to the grade_score.
5. IF a level has been touched 3 or more times THEN LevelTracker SHALL mark it as "exhausted" and EntryGate SHALL apply a -2 penalty.
6. WHEN a new session starts THEN LevelTracker SHALL clear intraday touches but retain prior-session structural levels.

---

### Requirement 4: VWAP Bands for Bias and Trailing

**Priority:** MEDIUM | **Effort:** SMALL

**User Story:** As a trader, I want VWAP bands actively used for entry bias filtering and dynamic trailing, so that trades respect mean-reversion zones and overextension is detected.

#### Acceptance Criteria

1. WHEN a LONG entry signal is generated below VWAP THEN EntryGate SHALL add a warning flag to the signal metadata.
2. WHEN price is at VWAP +/- 2 standard deviations THEN EntryGate SHALL adjust confidence score downward by 1 grade level.
3. WHEN a position reaches +1.5R profit THEN TradeManager SHALL trail the stop-loss to the nearest VWAP band.
4. WHEN price reaches VWAP + 2 sigma while holding a LONG position THEN TradeManager SHALL tighten the stop-loss to 50% of current distance.
5. WHEN price reaches VWAP - 2 sigma while holding a SHORT position THEN TradeManager SHALL tighten the stop-loss to 50% of current distance.

---

### Requirement 5: Aggressive Prints as Structural Levels

**Priority:** MEDIUM | **Effort:** SMALL

**User Story:** As a trader, I want aggressive prints registered as structural levels, so that they are used for entry confirmation and dynamic stop-loss anchoring.

#### Acceptance Criteria

1. WHEN an aggressive print (volume > 2.5 sigma) occurs THEN AMTAnalyzer SHALL register the price as a structural level.
2. WHEN EntryGate performs a `near_level` check THEN it SHALL include aggressive-print structural levels in the proximity search.
3. WHEN TradeManager calculates dynamic stop-loss THEN it SHALL anchor to the nearest aggressive-print level if it provides a tighter risk than the default SL.
4. IF an aggressive print level is older than 30 candles THEN the system SHALL expire it and remove it from the structural levels list.
5. WHEN multiple aggressive prints cluster within 0.1% of each other THEN the system SHALL merge them into a single level at the volume-weighted average price.

---

### Requirement 6: Prior Session Data Flow

**Priority:** MEDIUM | **Effort:** SMALL

**User Story:** As a trader, I want the system to persist and load prior session VP data, so that gap type and opening bias are computed instead of being empty.

#### Acceptance Criteria

1. WHEN a trading session closes THEN the system SHALL persist the session's POC, VAH, VAL, and profile shape to SQLite via StoragePort.
2. WHEN a new trading session opens THEN AMTAnalyzer SHALL load the prior session's POC, VAH, and VAL from storage.
3. WHEN prior session data is loaded and current open price is available THEN SessionContext SHALL compute `gap_type` (gap up, gap down, or open within range).
4. WHEN gap_type is computed THEN SessionContext SHALL derive `opening_bias` (e.g., gap-and-go vs gap-fill).
5. IF no prior session data exists (first session or data loss) THEN the system SHALL log a warning and leave prior fields empty without crashing.

---

### Requirement 7: Overseer Context Enrichment

**Priority:** HIGH | **Effort:** SMALL

**User Story:** As a trader, I want the LLM Overseer to receive the same richness of data as the entry prompt, so that hold/exit decisions are better informed.

#### Acceptance Criteria

1. WHEN the overseer prompt is built THEN PromptBuilder SHALL include the current session phase (London/NY/Asia/Expiry).
2. WHEN the overseer prompt is built THEN PromptBuilder SHALL include the current volume profile shape (P/b/D).
3. WHEN the overseer prompt is built THEN PromptBuilder SHALL include OI and PCR data if available.
4. WHEN the overseer prompt is built THEN PromptBuilder SHALL include any active LVN play signal.
5. WHEN the overseer prompt is built THEN PromptBuilder SHALL include stacked imbalances from footprint analysis.
6. IF any enrichment data source is unavailable THEN PromptBuilder SHALL omit that field gracefully without failing.

---

### Requirement 8: Volume Bubble Integration

**Priority:** HIGH | **Effort:** MEDIUM

**User Story:** As a trader, I want the three separate bubble detection systems (aggressive prints, footprint analyzer, tick accumulator) unified and wired into entry, overseer, and trade management, so that stacked imbalances drive real-time decisions.

#### Acceptance Criteria

1. WHEN footprint_analyzer detects stacked imbalances THEN the gameloop SHALL propagate them to EntryGate, PromptBuilder, and TradeManager.
2. WHEN stacked imbalances align with the entry direction THEN EntryGate SHALL add +1 to the grade_score.
3. WHEN stacked imbalances oppose the entry direction THEN EntryGate SHALL add -2 to the grade_score.
4. WHEN stacked imbalances oppose an open position THEN TradeManager SHALL immediately trigger a TIGHTEN action on the stop-loss.
5. WHEN the overseer prompt is built AND stacked imbalances are present THEN PromptBuilder SHALL include them with direction and magnitude.
6. IF no imbalance data is available from footprint_analyzer THEN the system SHALL continue without imbalance signals (no blocking).

---

### Requirement 9: LLM Instruction and Temperature Tuning

**Priority:** MEDIUM | **Effort:** SMALL

**User Story:** As a trader, I want the LLM system prompt rewritten to frame the model as an AMT practitioner (not a predictor), and temperature tuned per context, so that responses are more decisive and methodology-aligned.

#### Acceptance Criteria

1. WHEN the LLM entry prompt is constructed THEN config SHALL use the system instruction: "You are trading using Fabio Valentini's Auction Market Theory model. You are not predicting -- you are READING the auction..."
2. WHEN the LLM is called for entry decisions THEN config SHALL use temperature 0.4.
3. WHEN the LLM is called for overseer decisions THEN config SHALL use temperature 0.3.
4. IF a temperature override is provided in config THEN the system SHALL use the override value instead of the defaults.

---

### Requirement 10: Session-Aware Time Stops

**Priority:** LOW | **Effort:** SMALL

**User Story:** As a trader, I want time stops adjusted by session phase and expiry status, so that positions are not held too long during low-edge periods.

#### Acceptance Criteria

1. WHEN a position is open during the morning session phase THEN TradeManager SHALL apply time stops of 20 minutes (balanced) / 45 minutes (trending).
2. WHEN a position is open during the afternoon session phase THEN TradeManager SHALL apply time stops of 15 minutes (balanced) / 30 minutes (trending).
3. WHEN it is an expiry day AND the market state is balanced THEN TradeManager SHALL apply a 10-minute flat time stop regardless of session phase.
4. IF session phase data is unavailable THEN TradeManager SHALL fall back to the current static time stops (30 min balanced / 2 hr trending).

---

## Non-Functional Requirements

### NF-1: Test Coverage

**User Story:** As a developer, I want all changes covered by unit tests written before implementation (TDD), so that correctness is verified from the start.

#### Acceptance Criteria

1. WHEN any gap is implemented THEN the developer SHALL write unit tests before production code.
2. WHEN the full test suite is run THEN all existing tests (368+) SHALL continue to pass with no regressions.

### NF-2: Backward Compatibility

**User Story:** As an operator, I want all changes backward-compatible with the current paper trading setup, so that nothing breaks in the live forward-test environment.

#### Acceptance Criteria

1. WHEN new features are deployed THEN the system SHALL function correctly with existing configuration and data.
2. IF new configuration fields are added THEN they SHALL have sensible defaults that preserve current behavior.

### NF-3: Independent Implementability

**User Story:** As a developer, I want each gap implementable independently with no ordering dependency, so that work can be parallelised.

#### Acceptance Criteria

1. WHEN any single gap is implemented in isolation THEN the system SHALL build and pass all tests without requiring other gaps.
2. WHEN multiple gaps are implemented together THEN they SHALL not conflict or create circular dependencies.
