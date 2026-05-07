=== ARCHITECTURAL VIOLATIONS DOCUMENTATION ===
# Architectural Violations Found in Code
Date: 2026-04-30

## Violation 1: Frontend State Computation (HIGH) - ✅ RESOLVED

**File:** frontend/hooks/useServerTradingSystem.ts:710-717
**Type:** Separation of Concerns Violation

The frontend computed `cumulativeDeltas` which is derived business state:
```typescript
const cumulativeDeltas = useMemo(() => {
    if (!activeInstrument) return [];
    let runningDelta = 0;
    return activeInstrument.data.map(d => {
        runningDelta += d.delta;
        return runningDelta;
    });
}, [...]);
```

**Issue:** This derived state (running delta calculation) is business logic that should be computed in the backend and sent as part of the state snapshot.

**Fix:** ✅ **COMPLETED** - 
- Backend: `state_snapshot_builder.py` computes `cumulative_deltas` via `compute_cumulative_deltas()`
- Backend: Includes in state snapshot (line 84)
- Frontend: Receives via WebSocket delta merge and uses `activeInstrument?.cumulativeDeltas || []`

---

## Violation 2: Trading Session God Object (CRITICAL)
**File:** backend/app/application/services/trading_session.py (1,079 lines)
**Type:** Single Responsibility Principle Violation

| Method | Lines | Responsibility |
|--------|-------|----------------|
| process_tick | 145 | Orchestration |
| _session_phase_check | 130 | Session lifecycle |
| _run_amt_analysis | 94 | AMT analysis |
| _resolve_entry_decision | 52 | Signal resolution |
| _on_tick | 58 | Event handling |
| _execute_signal | 34 | Execution |
| _build_state_snapshot | 20 | Presentation |

**Issue:** Single file handles 6+ distinct responsibilities.

**Fix:** Split into:
- session_orchestrator.py - process_tick coordinator
- amt_service.py - AMT analysis
- position_service.py - position lifecycle
- state_builder.py - state snapshot
- phase_manager.py - session phase checks

---

## Violation 3: Verifier Naming Misnomer - ✅ RESOLVED

**File:** `backend/app/domain/trading/event_store.py:341-408
**Type:** Naming Violation

Previous code:
```python
class AuditStateVerifier:
    """Verifier for deterministic state reconstruction."""
    def verify_to(self, timestamp: str | None = None, ...) -> dict[str, Any]:
```

**Issue:** The previous naming suggested historical reconstruction-style behavior. This is actually an audit trail verifier for deterministic state reconstruction, NOT simulation execution.

**Fix:** ✅ **COMPLETED** - Renamed to `AuditTrailVerifier` with updated docstrings: "For audit trail verification, not for simulation execution."

---

## Violation 4: ChartScene Memoized Derived State (MEDIUM)
**File:** frontend/components/ChartScene.tsx:114
**Type:** State Logic in Presentation

```typescript
const stableData = useMemo(() => data, [data.length]);
```

**Issue:** Creating derived state in presentation component instead of receiving from backend.

---

## Violation 5: Manual Type Duplication (HIGH) - ⏳ PARTIAL

**File:** `frontend/types.ts` (428 lines)
**Type:** Single Source of Truth Violation

Every backend DTO has a manual TypeScript equivalent:
- OHLCData vs OHLCDataDTO
- OrderBook vs OrderBookDTO  
- TradePosition vs Position entity
- AMTAnalysis vs AMTAnalysisDTO

**Issue:** 28 interfaces manually maintained, drift risk.

**Fix:** ⏳ **PARTIAL** - 
- `scripts/generate_types.py` generates 6 core DTOs from Pydantic models
- Generated types in `frontend/types_generated.ts`
- `AMTDivergence` and other fields still duplicated in `frontend/types.ts`

**Remaining work:** Merge generated types into `frontend/types.ts` or resolve duplicates.
