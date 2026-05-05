# Frontend State Computation - Should Be Backend

## Overview
These computations in the frontend should be moved to the backend as they represent derived business state.

---

## ✅ 1. cumulativeDeltas - COMPLETED

**Location:** `frontend/hooks/useServerTradingSystem.ts`  
**Backend:** `backend/app/application/services/state_snapshot_builder.py` (compute_cumulative_deltas)

**Previous Frontend Code:**
```typescript
const cumulativeDeltas = useMemo(() => {
    if (!activeInstrument) return [];
    let runningDelta = 0;
    return activeInstrument.data.map(d => {
        runningDelta += d.delta;
        return runningDelta;
    });
}, [activeInstrument?.data?.length, activeInstrument?.data?.[activeInstrument?.data?.length - 1]?.delta]);
```

**Status:** 
- ✅ Backend computes `cumulative_deltas` via `compute_cumulative_deltas()` in `state_snapshot_builder.py`
- ✅ Backend includes `cumulative_deltas` in state snapshot (line 84)
- ✅ Frontend receives via WebSocket delta/full state merge (now handles `state.cumulative_deltas`)
- ✅ Frontend uses `activeInstrument?.cumulativeDeltas || []` (line 711)

**Benefits:** Single source of truth, business logic in backend, frontend is pure render.

---

## 2. stableData - ChartScene.tsx:114

**Location:** `frontend/components/ChartScene.tsx`
**Lines:** 114

```typescript
const stableData = useMemo(() => data, [data.length]);
```

**Issue:** Stabilizing data reference based on array length
**Fix:** Backend should send properly stabilized data with versioning

---

## 3. stableAmtAnalysis - ChartScene.tsx:83-110

**Location:** `frontend/components/ChartScene.tsx`
**Lines:** 83-110

```typescript
const stableAmtAnalysis = useMemo(() => {
    const prev = prevAmtRef.current;
    if (amtAnalysis === prev) return prev;
    // Compares: profile, legProfile, aggressivePrints arrays
    // Compares: poc, valueAreaHigh, valueAreaLow, legPoc, legVah, legVal, sessionVwap
    // Returns: memoized AMT analysis only when fields change
}, [amtAnalysis]);
```

**Issue:** Field comparison logic for change detection
**Fix:** Backend should fingerprint changes and only send updated fields

---

## 4. Array Sorting - ChartScene.tsx:264-269

**Location:** `frontend/components/ChartScene.tsx`
**Lines:** 264-269

```typescript
const sortedData = [...data].sort((a, b) => 
    new Date(a.time).getTime() - new Date(b.time).getTime()
);
const volumeData = sortedData.map(d => ({
    time: toChartTs(d.time) as any,
    value: d.volume,
    color: d.close >= d.open ? '#26a69a' : '#ef5350',
}));
```

**Issue:** Data sorting and transformation for presentation
**Fix:** Backend should send pre-sorted data, frontend should only render

---

## Recommendation Matrix

| Computation | Location | Backend Fix | Status |
|------------|----------|-------------|--------|
| cumulativeDeltas | useServerTradingSystem.ts | Add to StateBroadcaster output | ✅ COMPLETED |
| stableData memoization | ChartScene.tsx:114 | Send with generation counter | TODO |
| AMT fingerprint | ChartScene.tsx:83 | Compute server-side, send hash | TODO |
| Data sorting | ChartScene.tsx:264 | Sort before sending via WebSocket | TODO |
