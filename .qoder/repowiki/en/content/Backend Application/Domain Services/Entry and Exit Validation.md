# Entry and Exit Validation

<cite>
**Referenced Files in This Document**
- [PHASE_5_ENTRY_GATE_EXTRACTION.md](file://backend/PHASE_5_ENTRY_GATE_EXTRACTION.md)
- [entry_gates/__init__.py](file://backend/app/domain/fabio_ai/services/entry_gates/__init__.py)
- [three_align.py](file://backend/app/domain/fabio_ai/services/entry_gates/three_align.py)
- [confirmation_bundle.py](file://backend/app/domain/fabio_ai/services/entry_gates/confirmation_bundle.py)
- [signal_builder.py](file://backend/app/domain/fabio_ai/services/entry_gates/signal_builder.py)
- [grading.py](file://backend/app/domain/fabio_ai/services/entry_gates/grading.py)
- [gate_runner.py](file://backend/app/domain/fabio_ai/services/entry_gates/gate_runner.py)
- [gate_pipeline.py](file://backend/app/domain/fabio_ai/services/gate_pipeline.py)
- [aggression_scorer.py](file://backend/app/domain/fabio_ai/services/aggression_scorer.py)
- [rr_validator.py](file://backend/app/domain/fabio_ai/services/rr_validator.py)
- [absorption_validator.py](file://backend/app/domain/fabio_ai/services/absorption_validator.py)
- [position_sizer.py](file://backend/app/domain/fabio_ai/services/position_sizer.py)
- [constants.py](file://backend/app/domain/constants.py)
- [test_aggression_scorer.py](file://backend/tests/unit/test_aggression_scorer.py)
- [test_live_trading_safeguards.py](file://backend/tests/unit/test_live_trading_safeguards.py)
</cite>

## Table of Contents
1. [Introduction](#introduction)
2. [Project Structure](#project-structure)
3. [Core Components](#core-components)
4. [Architecture Overview](#architecture-overview)
5. [Detailed Component Analysis](#detailed-component-analysis)
6. [Dependency Analysis](#dependency-analysis)
7. [Performance Considerations](#performance-considerations)
8. [Troubleshooting Guide](#troubleshooting-guide)
9. [Conclusion](#conclusion)

## Introduction
This document describes the entry and exit validation system that evaluates trading opportunities against predefined criteria. It covers:
- EntryGate service orchestration via a 12-gate pipeline
- RRValidator for dynamic risk-reward validation using live ask prices
- AbsorptionValidator for confirming accumulation/distribution phases with forward-looking displacement
- AggressionScorer for quantifying market sentiment and reaction strength
- Integration with position sizing and risk management
- Performance optimization, false positive reduction, and adaptive threshold management

## Project Structure
The entry validation logic is organized into focused modules under the entry gates package, plus supporting validators and pipeline orchestration.

```mermaid
graph TB
subgraph "Entry Gates Package"
TA["three_align.py"]
CB["confirmation_bundle.py"]
SB["signal_builder.py"]
GR["grading.py"]
GRN["gate_runner.py"]
end
GP["gate_pipeline.py"]
AS["aggression_scorer.py"]
RR["rr_validator.py"]
AV["absorption_validator.py"]
PS["position_sizer.py"]
CT["constants.py"]
TA --> GP
CB --> GP
SB --> GP
GR --> SB
GRN --> GP
AS --> GRN
RR --> GRN
AV --> GRN
PS --> GRN
CT --> GP
CT --> AS
CT --> RR
CT --> AV
```

**Diagram sources**
- [entry_gates/__init__.py:1-63](file://backend/app/domain/fabio_ai/services/entry_gates/__init__.py#L1-L63)
- [gate_pipeline.py:1-256](file://backend/app/domain/fabio_ai/services/gate_pipeline.py#L1-L256)
- [aggression_scorer.py:1-282](file://backend/app/domain/fabio_ai/services/aggression_scorer.py#L1-L282)
- [rr_validator.py:1-117](file://backend/app/domain/fabio_ai/services/rr_validator.py#L1-L117)
- [absorption_validator.py:1-146](file://backend/app/domain/fabio_ai/services/absorption_validator.py#L1-L146)
- [position_sizer.py:1-106](file://backend/app/domain/fabio_ai/services/position_sizer.py#L1-L106)
- [constants.py:1-166](file://backend/app/domain/constants.py#L1-L166)

**Section sources**
- [PHASE_5_ENTRY_GATE_EXTRACTION.md:1-114](file://backend/PHASE_5_ENTRY_GATE_EXTRACTION.md#L1-L114)
- [entry_gates/__init__.py:1-63](file://backend/app/domain/fabio_ai/services/entry_gates/__init__.py#L1-L63)

## Core Components
- EntryGate orchestration: The gate runner constructs a GateContext and invokes the GatePipeline to evaluate 12 gates in sequence.
- GatePipeline: A strict sequential pipeline that short-circuits on the first failure, returning a reason and detail.
- ConfirmationBundle: Enforces volume impulse, delta pressure, and spread tightness with time-aware adjustments.
- AggressionScorer: Additive scoring across footprint, CVD, big trades, absorption, OFI, confluence, and bubbles; includes persistent filtering.
- RRValidator: Recomputes risk-reward using live ask price to prevent slippage-induced invalid setups.
- AbsorptionValidator: Validates absorption with forward-looking displacement confirmation.
- PositionSizer: Fixed fractional sizing with hard ceilings and risk-per-trade constraints.

**Section sources**
- [gate_runner.py:1-112](file://backend/app/domain/fabio_ai/services/entry_gates/gate_runner.py#L1-L112)
- [gate_pipeline.py:1-256](file://backend/app/domain/fabio_ai/services/gate_pipeline.py#L1-L256)
- [confirmation_bundle.py:1-154](file://backend/app/domain/fabio_ai/services/entry_gates/confirmation_bundle.py#L1-L154)
- [aggression_scorer.py:1-282](file://backend/app/domain/fabio_ai/services/aggression_scorer.py#L1-L282)
- [rr_validator.py:1-117](file://backend/app/domain/fabio_ai/services/rr_validator.py#L1-L117)
- [absorption_validator.py:1-146](file://backend/app/domain/fabio_ai/services/absorption_validator.py#L1-L146)
- [position_sizer.py:1-106](file://backend/app/domain/fabio_ai/services/position_sizer.py#L1-L106)

## Architecture Overview
The system integrates multiple order flow and structural signals into a unified gating framework. The flow begins with three-align validation, confirmation bundle checks, and aggression scoring, then proceeds through the 12-gate pipeline, SL/TP construction, and position sizing.

```mermaid
sequenceDiagram
participant Data as "Market Data"
participant TA as "Three-Align Gate"
participant CB as "Confirmation Bundle"
participant AS as "AggressionScorer"
participant GRN as "GateRunner"
participant GP as "GatePipeline"
participant SB as "SignalBuilder"
participant PS as "PositionSizer"
Data->>TA : "Raw OHLC + AMTResult"
TA-->>CB : "Confirmation bundle inputs"
AS-->>GRN : "Aggression score"
GRN->>GP : "GateContext (12 gates)"
GP-->>SB : "Pass + setup type"
SB-->>PS : "SL/TP + risk"
PS-->>GRN : "Position size + risk"
GRN-->>Data : "Decision + details"
```

**Diagram sources**
- [three_align.py:111-227](file://backend/app/domain/fabio_ai/services/entry_gates/three_align.py#L111-L227)
- [confirmation_bundle.py:26-86](file://backend/app/domain/fabio_ai/services/entry_gates/confirmation_bundle.py#L26-L86)
- [aggression_scorer.py:77-153](file://backend/app/domain/fabio_ai/services/aggression_scorer.py#L77-L153)
- [gate_runner.py:6-95](file://backend/app/domain/fabio_ai/services/entry_gates/gate_runner.py#L6-L95)
- [gate_pipeline.py:139-245](file://backend/app/domain/fabio_ai/services/gate_pipeline.py#L139-L245)
- [signal_builder.py:60-232](file://backend/app/domain/fabio_ai/services/entry_gates/signal_builder.py#L60-L232)
- [position_sizer.py:32-105](file://backend/app/domain/fabio_ai/services/position_sizer.py#L32-L105)

## Detailed Component Analysis

### EntryGate Service (GateRunner)
- Builds GateContext from incoming data, AMT results, and configuration.
- Translates market state strings to enums and computes derived metrics (distance to levels, risk, reward, RR).
- Invokes GatePipeline and returns a compact decision tuple: (passed, reason, detail).
- Provides position sizing wrapper integrating with PositionSizer.

```mermaid
flowchart TD
Start(["run_gate_pipeline"]) --> Ctx["Construct GateContext<br/>+ derive metrics"]
Ctx --> Pipe["GatePipeline.evaluate(ctx)"]
Pipe --> Decision{"All gates passed?"}
Decision --> |Yes| Pass["Return (True, TRADE, detail)"]
Decision --> |No| Fail["Return (False, reason, detail)"]
```

**Diagram sources**
- [gate_runner.py:6-95](file://backend/app/domain/fabio_ai/services/entry_gates/gate_runner.py#L6-L95)
- [gate_pipeline.py:139-245](file://backend/app/domain/fabio_ai/services/gate_pipeline.py#L139-L245)

**Section sources**
- [gate_runner.py:1-112](file://backend/app/domain/fabio_ai/services/entry_gates/gate_runner.py#L1-L112)
- [gate_pipeline.py:56-137](file://backend/app/domain/fabio_ai/services/gate_pipeline.py#L56-L137)

### GatePipeline (12-Gate Orchestration)
- Gates 0–12 enforce session warm-up, data freshness, session risk, market state, profile presence, proximity to levels, drive state, aggression, cushion, R:R, position sizing, and EIA suppression windows.
- Short-circuit evaluation ensures minimal computation on failure.
- GateContext consolidates all inputs for deterministic, side-effect-free evaluation.

```mermaid
flowchart TD
A["Gate 0: Warm-up"] --> B["Gate 1: Data freshness"]
B --> C["Gate 2: Session risk halted"]
C --> D["Gate 3: NO_TRADE state"]
D --> E["Gate 4: PROBING gating"]
E --> F["Gate 5: Key level present"]
F --> G["Gate 6: Distance to level"]
G --> H["Gate 7: Drive state"]
H --> I["Gate 8: Aggression threshold"]
I --> J["Gate 9: Cushion threshold"]
J --> K["Gate 10: R:R threshold"]
K --> L["Gate 11: Position sizing"]
L --> M["Gate 12: EIA suppression"]
M --> N["All passed → TRADE"]
```

**Diagram sources**
- [gate_pipeline.py:142-245](file://backend/app/domain/fabio_ai/services/gate_pipeline.py#L142-L245)

**Section sources**
- [gate_pipeline.py:1-256](file://backend/app/domain/fabio_ai/services/gate_pipeline.py#L1-L256)

### Confirmation Bundle (Volume/Delta/Sprd + Momentum Fade)
- Enforces 2 out of 3: volume impulse (EMA-multiplier adjusted by time-of-day), delta pressure, and tight spread.
- Includes momentum fade filter to avoid entering against strong directional impulses without rejection.
- Computes ATR for robustness.

```mermaid
flowchart TD
Start(["check_confirmation_bundle"]) --> EMA["Compute EMA(20) volume"]
EMA --> VImpulse{"Volume > EMA × multiplier?"}
VImpulse --> |No| Block["Return False"]
VImpulse --> |Yes| Delta["Delta ratio > 0.15?"]
Delta --> Spread["Bid-ask tight? (bps ≤ 5)"]
Spread --> Score["Count passing components"]
Score --> Pass{"≥ 2 passed?"}
Pass --> |Yes| Ok["Return True"]
Pass --> |No| Block
```

**Diagram sources**
- [confirmation_bundle.py:26-86](file://backend/app/domain/fabio_ai/services/entry_gates/confirmation_bundle.py#L26-L86)

**Section sources**
- [confirmation_bundle.py:1-154](file://backend/app/domain/fabio_ai/services/entry_gates/confirmation_bundle.py#L1-L154)

### AggressionScorer (Sentiment and Reaction Strength)
- Additive scoring across footprint, CVD, big trades, absorption, OFI, confluence, and bubbles.
- Confidence classification and optional persistent filtering to reduce false positives.
- Supports dynamic persistence based on market state.

```mermaid
classDiagram
class AggressionScorer {
+score(footprint_confirmed, cvd_confirmed, big_trade_confirmed, absorption_detected, ofi_aligned, confluence_bonus, volume_bubble_near) AggressionResult
+summary(result) str
}
class PersistentAggressionScorer {
+set_persistence_for_state(market_state) void
+score(...) AggressionResult
+reset() void
}
class AggressionResult {
+float score
+bool confirmed
+bool pyramid_eligible
+str confidence
+dict breakdown
}
PersistentAggressionScorer --> AggressionScorer : "wraps"
```

**Diagram sources**
- [aggression_scorer.py:60-153](file://backend/app/domain/fabio_ai/services/aggression_scorer.py#L60-L153)
- [aggression_scorer.py:165-282](file://backend/app/domain/fabio_ai/services/aggression_scorer.py#L165-L282)

**Section sources**
- [aggression_scorer.py:1-282](file://backend/app/domain/fabio_ai/services/aggression_scorer.py#L1-L282)
- [test_aggression_scorer.py:44-178](file://backend/tests/unit/test_aggression_scorer.py#L44-L178)

### RRValidator (Dynamic Risk-Reward)
- Recalculates live R:R using the live ask price to guard against slippage.
- Returns a structured result indicating validity, ratio, and reason.

```mermaid
flowchart TD
Start(["RRValidator.validate_live_ask"]) --> Risk["Compute live risk"]
Risk --> Reward["Compute live reward"]
Reward --> Ratio["Ratio = reward/risk"]
Ratio --> Check{"Ratio ≥ min_rr?"}
Check --> |Yes| Valid["Return valid=True"]
Check --> |No| Invalid["Return valid=False"]
```

**Diagram sources**
- [rr_validator.py:38-117](file://backend/app/domain/fabio_ai/services/rr_validator.py#L38-L117)

**Section sources**
- [rr_validator.py:1-117](file://backend/app/domain/fabio_ai/services/rr_validator.py#L1-L117)

### AbsorptionValidator (Absorption + Displacement)
- Records absorption candles (small range, high volume).
- Validates forward-looking displacement beyond the absorption high/low within a bounded horizon.
- Resets state per session.

```mermaid
flowchart TD
Start(["record_absorption"]) --> Pending["Store absorption candle + direction"]
Pending --> Next(["validate_displacement(current_candle)"])
Next --> CheckDisp{"Displaced beyond absorption high/low?"}
CheckDisp --> |Yes| Confirm["Return valid=True"]
CheckDisp --> |No| Timeout{"Within wait window?"}
Timeout --> |Yes| Hold["Keep pending"]
Timeout --> |No| Reject["Return valid=False"]
```

**Diagram sources**
- [absorption_validator.py:59-129](file://backend/app/domain/fabio_ai/services/absorption_validator.py#L59-L129)

**Section sources**
- [absorption_validator.py:1-146](file://backend/app/domain/fabio_ai/services/absorption_validator.py#L1-L146)
- [test_live_trading_safeguards.py:117-142](file://backend/tests/unit/test_live_trading_safeguards.py#L117-L142)

### SignalBuilder (SL/TP Construction)
- Builds Signals with SL/TP according to setup type (mean reversion vs trend).
- Incorporates aggressive prints, VWAP, ATR-based floors, and tick-size rounding.
- Computes grade score and attaches metadata for downstream use.

```mermaid
flowchart TD
Start(["build_entry_signal"]) --> Setup{"Setup type"}
Setup --> MR["Mean Reversion: TP at POC"]
Setup --> TM["Trend Model: Extended TP"]
MR --> SL["Compute SL (agg print/VWAP/VA)"]
TM --> SL
SL --> ATR["ATR-based minimum SL"]
ATR --> Round["Round to tick size"]
Round --> RR["Compute RR and attach metadata"]
RR --> End(["Return Signal"])
```

**Diagram sources**
- [signal_builder.py:60-232](file://backend/app/domain/fabio_ai/services/entry_gates/signal_builder.py#L60-L232)

**Section sources**
- [signal_builder.py:1-233](file://backend/app/domain/fabio_ai/services/entry_gates/signal_builder.py#L1-L233)

### PositionSizer (Risk-Constrained Sizing)
- Fixed fractional sizing with hard ceiling per trade.
- Calculates risk per lot and caps at absolute ceiling.

```mermaid
flowchart TD
Start(["PositionSizer.calculate"]) --> RiskAmt["risk_amount = equity × risk_pct"]
RiskAmt --> RiskPerLot["risk_per_lot = |entry - SL| × point_value"]
RiskPerLot --> Lots["lots = floor(risk_amount / risk_per_lot)"]
Lots --> Cap{"Actual risk > absolute ceiling?"}
Cap --> |Yes| Adjust["Reduce lots to meet ceiling"]
Cap --> |No| Keep["Proceed with computed lots"]
Adjust --> Done(["Return PositionSize"])
Keep --> Done
```

**Diagram sources**
- [position_sizer.py:32-105](file://backend/app/domain/fabio_ai/services/position_sizer.py#L32-L105)

**Section sources**
- [position_sizer.py:1-106](file://backend/app/domain/fabio_ai/services/position_sizer.py#L1-L106)

## Dependency Analysis
- Constants are centrally configured and injected into validators and scorers.
- GateRunner depends on GatePipeline, constants, and market-state mapping.
- SignalBuilder depends on confirmation metrics and grading.
- AggressionScorer and AbsorptionValidator are independent units feeding into GateRunner.
- RRValidator is invoked during live order placement to validate R:R.

```mermaid
graph LR
CT["constants.py"] --> GP["gate_pipeline.py"]
CT --> AS["aggression_scorer.py"]
CT --> RR["rr_validator.py"]
CT --> AV["absorption_validator.py"]
GRN["gate_runner.py"] --> GP
GRN --> PS["position_sizer.py"]
SB["signal_builder.py"] --> GRN
AS --> GRN
AV --> GRN
RR --> GRN
```

**Diagram sources**
- [constants.py:1-166](file://backend/app/domain/constants.py#L1-L166)
- [gate_pipeline.py:1-256](file://backend/app/domain/fabio_ai/services/gate_pipeline.py#L1-L256)
- [aggression_scorer.py:1-282](file://backend/app/domain/fabio_ai/services/aggression_scorer.py#L1-L282)
- [rr_validator.py:1-117](file://backend/app/domain/fabio_ai/services/rr_validator.py#L1-L117)
- [absorption_validator.py:1-146](file://backend/app/domain/fabio_ai/services/absorption_validator.py#L1-L146)
- [gate_runner.py:1-112](file://backend/app/domain/fabio_ai/services/entry_gates/gate_runner.py#L1-L112)
- [position_sizer.py:1-106](file://backend/app/domain/fabio_ai/services/position_sizer.py#L1-L106)
- [signal_builder.py:1-233](file://backend/app/domain/fabio_ai/services/entry_gates/signal_builder.py#L1-L233)

**Section sources**
- [constants.py:1-166](file://backend/app/domain/constants.py#L1-L166)

## Performance Considerations
- Lazy imports and modular design minimize cold-start overhead.
- GatePipeline short-circuits on first failure to avoid unnecessary computations.
- Confirmation bundle uses lightweight EMA and simple thresholds; ATR computation is bounded by recent bars.
- Aggression scoring is additive and constant-time; persistent filter maintains bounded history.
- Position sizing is O(1) arithmetic with early exits for invalid inputs.

[No sources needed since this section provides general guidance]

## Troubleshooting Guide
Common issues and mitigations:
- Excessive rejections in PROBING: Increase probing aggression threshold or ensure key-level proximity.
- Frequent EIA suppression: Monitor EIA calendar and schedule around release windows.
- Low aggression scores: Verify footprint, CVD, big trade, absorption, OFI, and confluence signals.
- R:R failures at live price: Use RRValidator to confirm slippage-adjusted R:R before order submission.
- Absorption not confirmed: Ensure displacement occurs within the validator’s wait window.

**Section sources**
- [gate_pipeline.py:173-183](file://backend/app/domain/fabio_ai/services/gate_pipeline.py#L173-L183)
- [aggression_scorer.py:165-282](file://backend/app/domain/fabio_ai/services/aggression_scorer.py#L165-L282)
- [rr_validator.py:38-117](file://backend/app/domain/fabio_ai/services/rr_validator.py#L38-L117)
- [absorption_validator.py:79-129](file://backend/app/domain/fabio_ai/services/absorption_validator.py#L79-L129)

## Conclusion
The entry and exit validation system combines structural, order-flow, and sentiment signals into a robust, configurable pipeline. Its modular design, adaptive thresholds, and risk-aware sizing enable reliable real-time decision-making while reducing false positives through persistent filters and forward-looking validations.