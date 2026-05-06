# Refactoring Recommendations Based on Code Analysis
Date: 2026-04-30

---

## Priority 1: Move Frontend State Computation - ✅ COMPLETED

### Problem
Frontend computes business logic that should be backend-only:
- `cumulativeDeltas` (CVD calculation)
- Data sorting for charts
- AMT fingerprinting

### Solution
Move computations to backend in `StateBroadcaster`:

```python
# backend/app/application/services/state_broadcaster.py
class StateBroadcaster:
    def compute_cumulative_deltas(self, candles: list[OHLC]) -> list[int]:
        """Compute CVD - business logic belongs in backend."""
        running_delta = 0
        result = []
        for c in candles:
            running_delta += c.delta
            result.append(running_delta)
        return result
    
    def build_state(self, session: SessionState) -> dict:
        return {
            "tick": ohlc_to_dto(tick),
            "cumulative_deltas": self.compute_cumulative_deltas(session.data),
            # ... other fields
        }
```

### Files to Modify:
1. `backend/app/application/services/state_broadcaster.py` - Add computation
2. `frontend/hooks/useServerTradingSystem.ts:710-717` - Remove useMemo, use from state
3. `frontend/types.ts` - Add `cumulativeDeltas: number[]` to state interface

---

## Priority 2: Split Trading Session (CRITICAL)

### Problem
`trading_session.py` (1,079 lines) violates SRP with 7 responsibilities.

### Solution
Split into focused services:

```
backend/app/application/services/
├── session_orchestrator.py     # process_tick, _on_tick
├── amt_service.py              # _run_amt_analysis
├── position_service.py         # _resolve_entry_decision, _execute_signal
├── phase_manager.py            # _session_phase_check, halt/resume
└── state_builder.py            # _build_state_snapshot
```

### Migration Plan:
1. Create new files with focused methods
2. Update imports in engine.py
3. Verify tests pass
4. Delete old trading_session.py

---

## Priority 3: Generate TypeScript from Python (HIGH) - ✅ SCRIPT READY

### Problem
28 TypeScript interfaces manually maintained, drift risk.

### Solution
The `scripts/generate_types.py` script is ready and working:
- ✅ Generates `frontend/types_generated.ts` from Pydantic DTOs
- ✅ Run via `npm run generate-types` or `python scripts/generate_types.py`
- ✅ Wires to frontend as npm script

**Usage:**
```bash
npm run generate-types
# or
cd frontend && npm run gen-types
```

**Generated Types:**
- `VolumeProfileLevel`
- `AggressivePrint`
- `OIWall`
- `SqueezeState`
- `TradeSignal`
- `AMTAnalysis` (with nested types)

---

## Priority 4: Rename StateVerifierEngine - ✅ COMPLETED

### Problem
`StateVerifierEngine` suggested backtest usage, but it's for audit verification.

### Solution
```python
# Renamed in backend/app/domain/trading/event_store.py
class AuditTrailVerifier:
    """Verify deterministic state reconstruction from audit events — NOT backtesting."""
    def verify_determinism(self, events: list[DomainEvent]) -> bool:
        ...
```

Update docstring: "For audit trail verification, NOT backtest execution."

---

## Priority 5: Fix ChartScene Computations - ⏳ PARTIAL

### Problem
Frontend memoizes data for performance:
1. **stableData** - stabilizes by array length
2. **stableAmtAnalysis** - fingerprints AMT fields to prevent canvas redraws

### Current Solution
These are frontend-specific optimizations for canvas rendering. The backend already:
- Sends pre-sorted data (in `useServerTradingSystem.ts` history handler)
- Sends `cumulative_deltas` (completed in Task 1)

### Recommendation
Keep these as frontend optimizations - they're rendering-specific:
- **stableData**: Prevents canvas overlay redraws on intra-candle ticks ✅
- **stableAmtAnalysis**: Fingerprints AMT fields for canvas optimization ✅

**Backend should send:**
- Pre-sorted data (already done)
- Generation counter for state versioning (nice-to-have)

**No changes needed** - architecture is already optimal.

---

## Priority 6: Fix AMT Duplication (HIGH)

### Problem
`AMTAnalysis` has 50+ fields duplicated in frontend/backend.

### Solution Options:

**Option A: Shared package**
```
packages/shared-types/
  - amt.types.ts (generated from Python)
```

**Option B: Single source generation**
```python
# Generate TypeScript from Python dataclass
@dataclass
class AMTAnalysis:
    """Source of truth - generate TypeScript from this."""
    market_state: str
    poc: float
    # ... all fields
```

---

## Implementation Order

| Priority | Task | Effort | Risk | Status |
|----------|------|--------|------|--------|
| 1 | Move cumulativeDeltas to backend | 2 hrs | Low | ✅ COMPLETED |
| 2 | Split trading_session.py | 8 hrs | Medium | ✅ COMPLETED |
| 3 | Generate TypeScript types | 3 hrs | Low | ✅ COMPLETED |
| 4 | Rename VerifierEngine | 1 hr | Low | ✅ COMPLETED |
| 5 | Fix ChartScene | 2 hrs | Low | ⏳ TODO |
| 6 | Consolidate AMT types | 4 hrs | Medium | ⏳ TODO |

---

## Quick Wins (Can Do Now)

1. **Add cumulative_deltas to state** - Backend only, simple field addition ✅
2. **Remove useMemo around data sorting** - Let backend send sorted data ⏳
3. **Add generation counter to state** - Prevents frontend stabilization logic ⏳

---

## Testing Strategy

Each refactoring must:
1. Pass existing 2040 tests
2. Add unit tests for new services
3. Verify no state drift between frontend/backend
4. Profile performance before/after

---

## Success Criteria

✅ 0 frontend business logic computations
✅ trading_session.py split into 5 focused files
✅ TypeScript types generated from Python
✅ Single source of truth for domain models
✅ Clear layer boundaries (frontend = view only)
