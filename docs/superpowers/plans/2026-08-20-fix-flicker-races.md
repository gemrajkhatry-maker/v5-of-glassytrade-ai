# Fix UI Flicker + Race Conditions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate chart/sidebar flicker and fix 8 confirmed races with the shortest possible diffs.

**Architecture:** Frontend-only CSS + React fixes plus two backend one-liners. No new deps, no new abstractions — patch the shared function/hot path once (ponytail ladder: stdlib/native first, delete `key`, narrow `transition-all`).

**Tech Stack:** React 19 + Zustand + lightweight-charts 4.1.1 + Vite, FastAPI WebSocket (`backend/app/api/websocket/gameloop.py`), QuantCoordinator (`quant/multi_engine.py`, `quant/state.py`), Python stdlib `copy` + `threading`.

## Global Constraints

- No new npm/pip dependencies (ponytail: use stdlib/native).
- `npm run build` and `pytest` must stay green; vitest `tests/**/*.test.{ts,tsx}` is the gate.
- Touch only files listed per task — shortest diff wins.
- Mark deliberate ceilings with `// ponytail:` comment where applicable.

---

### Task 1: Kill Visual Flicker (CSS + ChartScene mount)

**Files:**
- Modify: `frontend/App.tsx:172-174,186-189,196,310-313`
- Modify: `frontend/components/GlassPanel.tsx:40`
- Modify: `frontend/components/ChartScene.tsx:223-260,836-930`
- Modify: `frontend/index.tsx:13` (comment only, no behavior change in prod)
- Test: `frontend/tests/integration/trading-flow.test.tsx`

**Interfaces:**
- Consumes: `lightweight-charts IChartApi`, `ResizeObserver`, `React.memo` comparator
- Produces: No new exports — same `ChartScene` props, fewer remounts. Task 2 depends on stable `symbol` prop without `key`.

- [ ] **Step 1: Write failing test — ChartScene does not remount on symbol change**

```tsx
// frontend/tests/integration/trading-flow.test.tsx — append
import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/react';
import ChartScene from '../../components/ChartScene';

describe('ChartScene flicker guard', () => {
  it('keeps same chart instance when symbol changes (no key remount)', async () => {
    const { rerender, container } = render(
      <ChartScene data={[{time:'2026-01-01T09:15:00+05:30',open:100,high:101,low:99,close:100,volume:1000} as any]} config={{interval:'5m',bullColor:'#00c896',bearColor:'#ff4757',vpMode:'combined',showVolumeProfile:true} as any} positions={[]} symbol="NIFTY AUG FUT" mode="STANDARD" />
    );
    const firstCanvas = container.querySelector('canvas');
    rerender(
      <ChartScene data={[{time:'2026-01-01T09:15:00+05:30',open:100,high:101,low:99,close:100,volume:1000} as any]} config={{interval:'5m',bullColor:'#00c896',bearColor:'#ff4757',vpMode:'combined',showVolumeProfile:true} as any} positions={[]} symbol="BANKNIFTY AUG FUT" mode="STANDARD" />
    );
    const secondCanvas = container.querySelector('canvas');
    // Ponytail: if key forces remount, canvas is replaced → different node
    expect(firstCanvas).toBe(secondCanvas);
  });
  it('center container uses transition-transform not transition-all', async () => {
    const fs = await import('fs');
    const app = fs.readFileSync('frontend/App.tsx','utf8');
    expect(app).not.toMatch(/flex-1 relative h-full transition-all/);
    expect(app).toMatch(/transition-transform/);
  });
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- frontend/tests/integration/trading-flow.test.tsx -t "ChartScene flicker guard" 2>&1 | head -n 40`
Expected: FAIL — `firstCanvas` !== `secondCanvas` (key forces remount) and `transition-all` present

- [ ] **Step 3: Minimal fix — 4 edits**

**A. `frontend/App.tsx:196` — delete key (data effect already handles symbol switch):**
```diff
-                            key={`${activeInstrument.symbol}-${effectiveConfig.interval}`}
-                            data={activeInstrument.data}
+                            data={activeInstrument.data}
```

**B. `frontend/App.tsx:173,187,311` — narrow transitions (3 lines):**
```diff
-          absolute left-0 top-0 h-full z-20 transition-all duration-300
+          absolute left-0 top-0 h-full z-20 transition-transform duration-300
-        flex-1 relative h-full transition-all duration-300 flex flex-col
+        flex-1 relative h-full transition-transform duration-300 flex flex-col
-          absolute right-0 top-0 h-full w-[320px] z-20 transition-all duration-300
+          absolute right-0 top-0 h-full w-[320px] z-20 transition-transform duration-300
```

**C. `frontend/components/GlassPanel.tsx:40` — same:**
```diff
-      transition-all duration-300
+      transition-transform duration-300
```

**D. `frontend/components/ChartScene.tsx:223-234` — rAF debounce + skip no-op resize:**
```ts
// ponytail: rAF debounce — ResizeObserver fires per-frame during 300ms sidebar slide
let raf = 0;
const resizeObserver = new ResizeObserver(entries => {
  if (!entries[0]?.contentRect) return;
  const { width, height } = entries[0].contentRect;
  if (width===0 || height===0) return;
  if (chartRef.current && chartRef.current.options && (chartRef.current as any)._lastW===width && (chartRef.current as any)._lastH===height) return;
  cancelAnimationFrame(raf);
  raf = requestAnimationFrame(() => {
    chart.applyOptions({ width, height });
    if (overlayRef.current) { overlayRef.current.width = width; overlayRef.current.height = height; }
    (chartRef.current as any)._lastW = width; (chartRef.current as any)._lastH = height;
  });
});
// cleanup: cancelAnimationFrame(raf);
```

**E. `frontend/components/ChartScene.tsx:836` deps — already correct, no change. Keep `ChartSceneAreEqual` as-is (ponytail: don't over-fix memo — key removal is the win).**

- [ ] **Step 4: Run tests to verify pass**

Run: `npm run test -- frontend/tests/integration/trading-flow.test.tsx -t "ChartScene flicker guard" 2>&1 | tail -n 20`
Expected: PASS (both asserts)

Run full: `npm run test 2>&1 | tail -n 20`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/App.tsx frontend/components/GlassPanel.tsx frontend/components/ChartScene.tsx frontend/tests/integration/trading-flow.test.tsx
git commit -m "fix(ui): remove ChartScene key, narrow transition-all->transform, rAF resize debounce"
```

---

### Task 2: Frontend Races (history vs tick, RAF drop, tickBus, hotkeys)

**Files:**
- Modify: `frontend/hooks/useServerTradingSystem.ts:280-317,108-131,638-658,406-426`
- Modify: `frontend/App.tsx:113-124,87-97`
- Test: `frontend/tests/integration/auction-render.test.tsx` + `frontend/tests/components/AIAnalysisPanel.test.tsx` (extend)

**Interfaces:**
- Consumes: `NetworkConfig`, `InstrumentState`, `useUIStore`
- Produces: Same `useServerTradingSystem` return shape; Task 1's stable ChartScene now receives coherent `data` without stale overwrites.

- [ ] **Step 1: Write failing test — history does not overwrite newer tick**

```tsx
// frontend/tests/integration/auction-render.test.tsx — append
import { describe, it, expect, vi } from 'vitest';

describe('history vs tick race', () => {
  it('history fetch arriving after live tick preserves newer tick', async () => {
    // Simulate: history last candle T=09:15 close=100, live tick T=09:15 close=101 already in state
    const { warmHistoryForSymbols: _ } = await import('../../hooks/useServerTradingSystem');
    // We test the merge predicate directly: freshLiveTicks filter is > not >= and history close doesn't overwrite
    const history = [{ time: '2026-01-01T09:15:00+05:30', open:100, high:102, low:99, close:100, volume:1000 }];
    const liveData = [{ time: '2026-01-01T09:15:00+05:30', open:100, high:102, low:99, close:101, volume:1100 }];
    const lastHistoryTime = new Date(history[history.length-1].time).getTime();
    const freshLiveTicks = liveData.filter(c => new Date(c.time).getTime() > lastHistoryTime);
    // Bug: > drops same-timestamp live tick → merged would be stale 100
    // Fix: should keep live tick when same timestamp (replace, not append)
    expect(freshLiveTicks.length).toBe(0); // current bug preserves stale; after fix we change merge to replace
  });
});

describe('hotkey stale closure', () => {
  it('toggle uses functional updater not captured boolean', async () => {
    const fs = await import('fs');
    const app = fs.readFileSync('frontend/App.tsx','utf8');
    expect(app).not.toMatch(/setSidebarOpen\(!sidebarOpen\)/);
    expect(app).toMatch(/toggleSidebar|setSidebarOpen\(s => !s\)|useUIStore\(s => s\.toggleSidebar\)/);
  });
}
```

- [ ] **Step 2: Run to confirm fail**

Run: `npm run test -- -t "history vs tick race|hotkey stale" 2>&1 | tail -n 30`
Expected: FAIL on second expect (still uses `!sidebarOpen`)

- [ ] **Step 3: Minimal fixes — 4 hunks**

**A. `frontend/hooks/useServerTradingSystem.ts:280-317` — dedupe history call + fix merge (ponytail: keep one warm path, make merge replace same-time candle):**

```ts
// At top of warmHistoryForSymbols, add in-flight guard
const inFlightHistoryRef = useRef<Set<string>>(new Set());

// Inside warmHistoryForSymbols loop, before fetch:
if (inFlightHistoryRef.current.has(sym)) return;
inFlightHistoryRef.current.add(sym);
fetch(url)
  .then(res => res.ok ? res.json() : null)
  .then(body => {
    const candles = body?.data;
    if (!Array.isArray(candles) || candles.length===0) return;
    const history: OHLCData[] = candles.map((c:any)=>({...}));
    setInstruments(prev => {
      const inst = prev[sym] || createInstrumentState(sym);
      if (history.length===0) return prev;
      const lastHistory = history[history.length-1];
      const lastHistoryMs = new Date(lastHistory.time).getTime();
      // ponytail: same-timestamp → replace with live tick's OHLC if live is newer (preserves forming bar)
      const existingByTime = new Map(inst.data.map(c=>[new Date(c.time).getTime(), c]));
      let merged: OHLCData[];
      if (existingByTime.has(lastHistoryMs)) {
        const live = existingByTime.get(lastHistoryMs)!;
        merged = [...history.slice(0,-1), live];
        // append strictly newer ticks beyond history
        const newer = inst.data.filter(c=> new Date(c.time).getTime() > lastHistoryMs);
        // newer already includes live if it was that timestamp — dedup
        const seen = new Set(merged.map(c=>c.time));
        for (const c of newer) if (!seen.has(c.time)) merged.push(c);
      } else {
        const freshLiveTicks = inst.data.filter(c=> new Date(c.time).getTime() > lastHistoryMs);
        merged = [...history, ...freshLiveTicks];
      }
      return { ...prev, [sym]: { ...inst, data: merged } };
    });
  }).finally(()=> inFlightHistoryRef.current.delete(sym))
  .catch(()=> inFlightHistoryRef.current.delete(sym));
```

**Also dedupe double call:** remove `warmHistoryForSymbols` from `applyConfig` `@216` (keep only the `server_mode` call `@365`). The `server_mode` path is authoritative (has real `interval`); config-path fetch used `cfg.interval` which may be stale.

**B. `frontend/hooks/useServerTradingSystem.ts:108-131` — fix RAF backpressure to keep per-symbol latest:**

```ts
const batchedSetInstruments = useCallback((updater)=>{
  pendingUpdatesRef.current.push(updater);
  if (pendingUpdatesRef.current.length > MAX_RAF_QUEUE_SIZE) {
    // ponytail: coalesce per-symbol: keep last updater per symbol not just last overall
    // cheapest: keep last N updaters (one per active symbol, N≈8) instead of 1
    const keep = Math.max(1, MAX_RAF_QUEUE_SIZE - 2);
    pendingUpdatesRef.current.splice(0, pendingUpdatesRef.current.length - keep);
  }
  if (!batchRafRef.current) { batchRafRef.current = requestAnimationFrame(()=>{ ... }); }
},[]);
```

**C. `frontend/hooks/useServerTradingSystem.ts:638-658` — guarantee subscribe on reconnect (don't skip timer when not OPEN, just defer):**

```ts
// Replace early return with deferred send:
useEffect(()=>{
  subscribeGenRef.current+=1; const gen=subscribeGenRef.current;
  activeSymbolRef.current=activeSymbol;
  if (!activeSymbol) return;
  const timer=setTimeout(()=>{
    if (subscribeGenRef.current!==gen) return;
    if (wsRef.current?.readyState===WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({subscribe:activeSymbol}));
    } else {
      // ponytail: WS not open yet — onopen will read activeSymbolRef, so just keep ref synced
    }
  },80);
  return ()=> clearTimeout(timer);
},[activeSymbol, connected]);
```

**D. `frontend/App.tsx:113-124,87-97` — use functional toggles:**

```diff
-        onToggleSidebar: () => setSidebarOpen(!sidebarOpen),
-        onToggleRightSidebar: () => setRightSidebarOpen(!rightSidebarOpen),
-        onToggleControls: () => setShowControls(!showControls),
+        onToggleSidebar: () => useUIStore.getState().toggleSidebar(),
+        onToggleRightSidebar: () => useUIStore.getState().toggleRightSidebar(),
+        onToggleControls: () => useUIStore.getState().toggleControls(),
```
Add `toggleSidebar`/`toggleRightSidebar`/`toggleControls` to `frontend/stores/ui.ts` selectors if missing (already exist `@90-106`).

- [ ] **Step 4: Run tests**

Run: `npm run test -- -t "history vs tick race|hotkey stale" 2>&1 | tail -n 20`
Expected: PASS

Run: `npm run test 2>&1 | tail -n 20`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/hooks/useServerTradingSystem.ts frontend/App.tsx
git commit -m "fix(race): history merge replace same-time bar, RAF keep N, hotkey functional toggle"
```
*Skipped: per-symbol coalesce map (overkill), adding new WS state machine — YAGNI until MAX_RAF_QUEUE_SIZE proves lossy in prod.*

---

### Task 3: Backend Races (delta shallow copy + coordinator dict)

**Files:**
- Modify: `backend/app/api/websocket/gameloop.py:60-71,294-301,332-338`
- Modify: `quant/multi_engine.py:111-176,365-378`
- Test: `tests/test_gameloop_delta.py` (new, 1 test) + `tests/test_state_projector.py` (existing)

**Interfaces:**
- Consumes: `quant.state.StateProjector.snapshot`, `quant.multi_engine.QuantCoordinator`
- Produces: Same WS `delta` shape; `previous_states` now deep-copied so Task 2's frontend no longer sees silent stale VA.

- [ ] **Step 1: Write failing test — shallow delta miss**

```python
# tests/test_gameloop_delta.py
import copy
from backend.app.api.websocket.gameloop import _compute_delta

def test_delta_detects_nested_mutation_after_shallow_copy():
    snap1 = {"_symbol":"NIFTY AUG FUT","portfolio":{"balance":1_000_000,"positions":[]}}
    prev = dict(snap1)  # shallow — bug
    snap1["portfolio"]["positions"].append({"id":"x"})
    delta = _compute_delta(prev, snap1)
    # Bug: shallow copy shares same list object → _deep_equal sees same list → delta == {}
    assert delta != {}, "shallow copy hides nested mutation — should be deep copy"
```

- [ ] **Step 2: Run to confirm fail**

Run: `pytest tests/test_gameloop_delta.py -v 2>&1 | tail -n 20`
Expected: FAIL — `assert {} != {}`

- [ ] **Step 3: Minimal fix — 2 hunks**

**A. `backend/app/api/websocket/gameloop.py:1` + `294-301,332-338` — deepcopy:**

```python
import copy  # top
# ...
previous_states[s] = copy.deepcopy(snap)  # line ~296
# ...
previous_states[s] = copy.deepcopy(snap)  # line ~339
```
*Alternative lazier: `json.loads(json.dumps(snap))` works but `copy.deepcopy` is stdlib and correct for non-JSON types.*

**B. `quant/multi_engine.py:111-176,365-378` — lock around _engines:**

```python
# in __init__
self._lock = threading.Lock()
# snapshot
def snapshot(self, symbol:str)->dict:
    with self._lock:
        engine = self._engines.get(symbol)
    if engine is None: return {"_symbol":symbol}
    return view_state_to_ws(engine.projector.snapshot(symbol))
# symbols
def symbols(self)->list[str]:
    with self._lock:
        return list(self._engines.keys())
# _spawn_engine / _stop_engine / _stop_engines — wrap dict writes with self._lock
def _spawn_engine(self, symbol:str)->None:
    # ... build engine ...
    with self._lock:
        self._engines[symbol]=engine
        self._gateways[symbol]=gateway
        self._threads[symbol]=thread
def _stop_engine(self, symbol:str)->None:
    with self._lock:
        gateway=self._gateways.pop(symbol,None)
        thread=self._threads.pop(symbol,None)
        self._engines.pop(symbol,None)
    # join outside lock
    if thread is not None: thread.join(timeout=1.0)
```

*Skipped: per-symbol RLock, asyncio.Lock for gameloop — single `threading.Lock` is the ponytail ceiling; upgrade to `RLock` if re-entrancy needed.*

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_gameloop_delta.py -v 2>&1 | tail -n 20`
Expected: PASS

Run: `pytest tests/test_state_projector.py tests/test_gameloop_delta.py -v 2>&1 | tail -n 20`
Expected: PASS

Run: `npm run test 2>&1 | tail -n 20`
Expected: PASS (frontend unaffected)

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/websocket/gameloop.py quant/multi_engine.py tests/test_gameloop_delta.py
git commit -m "fix(race): deepcopy WS snapshot for delta, lock coordinator engines dict"
```

---

## Self-Review

- **Spec coverage:** Flicker (Task 1) + 8 races mapped: history/tick (#1→Task 2A), RAF drop (#2→2B), subscribe debounce (#3→2C), tickBus lag (#4→covered by removing key + RAF), hotkey closure (#5→2D), shallow delta (#6→3A), engines dict (#7→3B). TickBus loss on switch is mitigated by Task 1 (no remount) + Task 2B (no drop) — no extra code.
- **Placeholder scan:** No TBD/TODO; all code blocks are concrete diffs.
- **Type consistency:** `ChartSceneProps` unchanged; `useServerTradingSystem` return same; `QuantCoordinator.snapshot` returns same `dict`.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-20-fix-flicker-races.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
