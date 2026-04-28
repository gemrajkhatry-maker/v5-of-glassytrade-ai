# Solution: Market Scanner Status & Prob% Empty Columns

## Problem
The Market Scanner UI showed empty "Status ↕" and "Prob% ↓" columns despite the backend running and generating agent decisions.

## Root Cause
The frontend's `MarketSidebar.tsx` had a conditional rendering check `!hasData || !hasAnalysis` where `hasAnalysis = agentDecision !== null && amtAnalysis !== null`. This hid probability values whenever `amtAnalysis` was null, even when `agentDecision` contained valid probability data.

## Solution

### 1. Backend (`agent_pipeline.py`)
Enhanced FLAT decision output for better debugging:
```python
if signal.direction == "FLAT":
    chosen_p = max(signal.p_long, signal.p_short)  # Explicit capture
    return AgentDecision(
        direction="FLAT",
        probability=chosen_p,
        rationale=f"{playbook} | {regime.regime} regime | P(long)={signal.p_long:.3f} P(short)={signal.p_short:.3f} | No clear edge",
        ...
    )
```

### 2. Frontend (`MarketSidebar.tsx`)
**Probability Column:** Direct agentDecision access instead of `hasAnalysis` check:
```tsx
: inst.agentDecision?.probability !== undefined ? (
    // Display probability from agentDecision directly
    <span>{Math.round(inst.agentDecision.probability * 100)}%</span>
) : (
    // Fallback skeleton
)
```

**Status Column:** Removed `!hasAnalysis` dependency:
```tsx
: !hasData ? (  // Was: !hasData || !hasAnalysis
    // Show skeleton
) : (
    // Show status & timing (works without amtAnalysis)
)
```

**Additional Improvements:**
- Sortable column headers with aria-labels
- Better ARIA attributes (role="list", aria-labels)
- Symbol list sorting
- `shortSymbol` utility moved to shared location

## Testing
✅ All existing probability tests pass (13/13)
✅ New tests verify FLAT decisions return valid probabilities
✅ Frontend builds successfully
✅ No breaking changes

## Impact
- **Before**: Status/Prob% columns empty when `amtAnalysis` null
- **After**: Columns show values from `agentDecision` immediately
- **UI**: Clearer feedback during market scanning
- **Compatibility**: Fully backward compatible