# Code Smell Refactoring Plan

## Overview
Refactoring plan to address code smells identified in the backend codebase, focusing on the `AMTAnalyzer` god class and related architectural issues.

## Phase 1: Foundation & Planning ✓ COMPLETE

### 1.1 Create Domain Services ✓
- [x] Create `VWAPService` - 9 tests passing
- [x] Create `VolumeProfileService` - 6 tests passing  
- [x] Create `OrderFlowService` - 6 tests passing

### 1.2 Parameter Objects ✓
- [x] `AMTAnalysisInput` - wraps 17 parameters
- [x] `GatePipelineInput` - wraps 21 parameters
- [x] `MarketStateInput` - wraps 18 parameters
- [x] `AMTAnalysisResult` - intermediate pipeline state

## Phase 2: Function Extraction ✓ COMPLETE

### 2.1 Extract Functions to fabio_detectors.py ✓
- [x] 17+ functions extracted, reducing 463 lines (30% reduction)
- [x] All tests pass (1797 passed, 235 skipped)

## Phase 3: Incremental Redesign (IN PROGRESS)

### 3.1 Pipeline Architecture ✓
- [x] Created `AMTPipeline` with clean stage-based architecture
- [x] Stage 1: `build_profile_stage()` - profile construction
- [x] Stage 2+: Will be added incrementally

### 3.2 Migration Strategy
- **Parallel implementation**: New pipeline runs alongside existing `AMTAnalyzer`
- **Feature parity**: Each stage is validated against existing behavior
- **Gradual cutover**: Switch via feature flag or config

### 3.3 Final Status (Migration Ready)

| Component | Lines | Status |
|-----------|-------|--------|
| `AMTAnalyzer` (legacy) | 1070 | Stable |
| `AMTPipeline` (new) | 330 | ✓ Ready for migration |
| `AMTAnalyzerV2` (adapter) | 126 | ✓ Complete |
| Tests | 1806 passed, 235 skipped | ✓ |

### Migration Architecture

```
AMTAnalyzer (1070) → AMTAnalyzerV2 (126) → AMTPipeline (330)
                      (backward compat)    (clean stages)
```

### Validation Results

- POC consistency: ✓ Within 0.5% tolerance
- Value area consistency: ✓ Within 1% tolerance
- All parity tests: ✓ Passing

### Next Steps for Full Migration

1. Switch `AMTAnalyzer` to use `AMTPipeline` internally
2. Run both implementations in parallel 
3. Gradually increase traffic to pipeline
4. Remove legacy code paths once validated

## Architecture Comparison

### Before (God Class)
```
AMTAnalyzer.analyze() - 500+ lines
├── Profile building (100 lines)
├── Market state (100 lines)
├── Order flow (150 lines)
├── MTF alignment (50 lines)
└── Result building (100 lines)
```

### After (Pipeline)
```
AMTPipeline
├── build_profile_stage()     # Profile/VA/LVN
├── compute_market_state()    # VWAP, displacement, IB
├── compute_order_flow()      # CVD, absorption, OFI
├── compute_mtf_alignment()   # Daily/hourly context
└── build_result()            # AMTResult construction
```

## Benefits of Pipeline Approach

1. **Testability**: Each stage can be tested independently
2. **Debuggability**: Clear data flow through stages
3. **Extensibility**: New stages can be added without modifying existing code
4. **Migrations**: Easy to run old/new side-by-side for validation