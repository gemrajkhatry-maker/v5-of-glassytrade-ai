# Frontend Deep-Dive Audit — GlassyTrade AI

**Date:** 2026-08-06
**Auditor:** Principal Engineer / Quant Engineer Review
**Scope:** Complete frontend codebase — leaf-file hierarchy, architecture, data flows, class diagrams, strategy execution, component organization
**Branch:** `stable_4`

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [File Tree Hierarchy](#2-file-tree-hierarchy)
3. [Architecture Overview](#3-architecture-overview)
4. [Data Flow Architecture](#4-data-flow-architecture)
5. [Component Class Diagram](#5-component-class-diagram)
6. [Component-by-Component Review](#6-component-by-component-review)
7. [Strategy Execution Review](#7-strategy-execution-review)
8. [State Management Analysis](#8-state-management-analysis)
9. [WebSocket Protocol Analysis](#9-websocket-protocol-analysis)
10. [Rendering Performance](#10-rendering-performance)
11. [Testing Coverage](#11-testing-coverage)
12. [Findings Index](#12-findings-index)
13. [Remediation Plan](#13-remediation-plan)

---

## 1. Executive Summary

The GlassyTrade AI frontend is a **React 19 + Vite + lightweight-charts + zustand** single-page trading terminal. It receives all market data, analysis, and trading signals via a single WebSocket connection to the backend and renders them as a real-time chart with overlays, an intelligence sidebar, and a market scanner.

### Key Metrics

| Metric | Value |
|--------|-------|
| Total source files | 27 (excluding tests) |
| Total TypeScript/TSX lines | ~7,200 |
| Test files | 14 |
| Test lines | ~2,653 |
| Test coverage ratio | ~27% of source lines |
| Components | 13 (8 leaf, 5 composite) |
| Custom hooks | 2 |
| Zustand stores | 2 |
| Pure utility modules | 7 |
| Dependencies (prod) | 9 |
| Max component depth | 5 levels |
| Max single-file length | 1,525 lines (AIAnalysisPanel.tsx) |

### Overall Verdict

**Grade: B- (Good foundation, significant architectural debt in hot paths)**

The frontend is the **better-engineered half** of the system compared to the backend. The pure-function extraction pattern for chart logic (AMTLevelsOverlay, CandleSeriesManager, etc.) is excellent. The RAF-batched WebSocket updates show awareness of React rendering costs. However, several critical issues undermine reliability:

1. **AIAnalysisPanel is a 1,525-line god component** — 40+ conditional render blocks, deeply nested JSX, inline IIFE components
2. **Gap-filling fabricates market data** — forward-fills missing candles with zero-volume flat candles, creating false signals
3. **Duplicate state stores** — `useInstrumentsStore` exists but is never used; all state lives in `useServerTradingSystem`
4. **No error recovery for corrupted chart data** — Lightweight Charts crashes silently on out-of-order timestamps
5. **`AIAnalysis` type is dead code** — 3 analysis types coexist, one is never used
6. **Hardcoded IST offset magic number** (19800) repeated in 5+ files

---

## 2. File Tree Hierarchy

```
frontend/
├── .gitignore
├── index.html                          # HTML entry point
├── index.tsx                           # React mount (16 lines)
├── index.css                           # Global styles + Tailwind theme (239 lines)
├── package.json                        # Dependencies
├── tsconfig.json                       # TypeScript config
├── vite.config.ts                      # Vite + Vitest + proxy config (54 lines)
├── vite-env.d.ts                       # Environment type declarations (11 lines)
├── App.tsx                             # Root component (348 lines)
├── constants.ts                        # Config constants (41 lines)
├── types.ts                            # All TypeScript interfaces (326 lines)
│
├── stores/
│   ├── ui.ts                           # Zustand UI state (187 lines)
│   └── instruments.ts                  # Zustand instruments store (179 lines) ⚠️ UNUSED
│
├── hooks/
│   ├── useServerTradingSystem.ts       # WebSocket + state management (810 lines)
│   └── useKeyboardNavigation.ts        # Hotkey system (195 lines)
│
├── components/
│   ├── ErrorBoundary.tsx               # React error boundary (51 lines)
│   ├── GlassPanel.tsx                  # Reusable panel wrapper (52 lines)
│   ├── ChartScene.tsx                  # Chart rendering (1,036 lines)
│   ├── AIAnalysisPanel.tsx             # Intelligence sidebar (1,525 lines)
│   ├── MarketSidebar.tsx               # Market scanner (290 lines)
│   ├── JournalPage.tsx                 # Trade journal (409 lines)
│   ├── ModelStateBanner.tsx            # Primary status banner (120 lines)
│   │
│   ├── chart/                          # Chart sub-components
│   │   ├── AMTLevelsOverlay.ts         # Price line generation (322 lines)
│   │   ├── CandleSeriesManager.ts      # Candle data transformation (323 lines)
│   │   ├── VolumeSeriesManager.ts      # Volume data transformation (290 lines)
│   │   ├── ExecutionMarkersManager.ts  # Chart markers (286 lines)
│   │   └── DecisionCard.tsx            # AI decision overlay (70 lines)
│   │
│   └── ai/                             # AI sub-components
│       ├── index.ts                    # Barrel export (4 lines)
│       ├── EquityPanel.tsx             # Equity + PnL display (96 lines)
│       ├── RiskStateDisplay.tsx        # Halt warnings (37 lines)
│       └── DecisionHistoryPanel.tsx    # Decision timeline (143 lines)
│
├── utils/
│   ├── symbol.ts                       # Symbol name parsing (24 lines)
│   └── textSanitizer.ts                # LLM output cleaning (225 lines)
│
└── tests/                              # Test suite
    ├── setup.ts                        # Vitest setup (99 lines)
    ├── types.test.ts                   # Type tests (27 lines)
    ├── hooks/
    │   └── useServerTradingSystem.test.tsx  # WS hook tests (206 lines)
    ├── components/
    │   ├── AIAnalysisPanel.test.tsx    # (72 lines)
    │   ├── ChartScene.test.tsx         # (206 lines)
    │   ├── GlassPanel.test.tsx         # (76 lines)
    │   ├── MarketSidebar.test.tsx      # (192 lines)
    │   └── chart/
    │       ├── AMTLevelsOverlay.test.ts       # (336 lines)
    │       ├── CandleSeriesManager.test.ts    # (310 lines)
    │       ├── DecisionCard.test.tsx          # (90 lines)
    │       ├── ExecutionMarkersManager.test.ts # (259 lines)
    │       └── VolumeSeriesManager.test.ts    # (239 lines)
    └── integration/
        ├── auction-render.test.tsx     # (212 lines)
        └── trading-flow.test.tsx       # (329 lines)
```

### File Size Distribution

```
Tier 1 — God files (>1000 lines):
  AIAnalysisPanel.tsx      1,525 lines  ████████████████████████████████████████
  ChartScene.tsx            1,036 lines  ████████████████████████████████
  useServerTradingSystem.ts  810 lines  ████████████████████████████

Tier 2 — Large files (200-1000 lines):
  App.tsx                    348 lines  ████████████████
  types.ts                   326 lines  ███████████████
  AMTLevelsOverlay.ts        322 lines  ██████████████
  CandleSeriesManager.ts     323 lines  ██████████████
  VolumeSeriesManager.ts     290 lines  ██████████████
  MarketSidebar.tsx          290 lines  ██████████████
  ExecutionMarkersManager.ts 286 lines  ██████████████
  JournalPage.tsx            409 lines  ████████████████████
  textSanitizer.ts           225 lines  ████████████████
  useKeyboardNavigation.ts   195 lines  ██████████████

Tier 3 — Small files (<200 lines):
  ModelStateBanner.tsx       120 lines  ████████
  ui.ts                      187 lines  ███████████████
  instruments.ts             179 lines  ██████████████
  DecisionHistoryPanel.tsx   143 lines  █████████
  DecisionCard.tsx            70 lines  █████
  EquityPanel.tsx             96 lines  ██████
  RiskStateDisplay.tsx        37 lines  ███
  ErrorBoundary.tsx           51 lines  ████
  GlassPanel.tsx              52 lines  ████
  symbol.ts                   24 lines  ██
```

---

## 3. Architecture Overview

### 3.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Browser / Expo                           │
│                                                                 │
│  ┌──────────┐   ┌────────────────────────────────────────────┐  │
│  │ index.tsx │   │              App.tsx                       │  │
│  │ (mount)   │──▶│  ┌──────────────────────────────────────┐  │  │
│  └──────────┘   │  │         useServerTradingSystem        │  │  │
│                 │  │  ┌─────────────┐  ┌────────────────┐  │  │  │
│                 │  │  │   REST      │  │   WebSocket    │  │  │  │
│                 │  │  │   Config    │  │   gameloop     │  │  │  │
│                 │  │  │   Fetch     │  │   Connection   │  │  │  │
│                 │  │  └─────────────┘  └───────┬────────┘  │  │  │
│                 │  │                          │            │  │  │
│                 │  │  ┌───────────────────────▼──────────┐ │  │  │
│                 │  │  │      RAF-Batched State Merge     │ │  │  │
│                 │  │  │  (delta compression + dedup)     │ │  │  │
│                 │  │  └───────────────────────┬──────────┘ │  │  │
│                 │  │                          │            │  │  │
│                 │  │  instruments: Record<    │            │  │  │
│                 │  │    string, Instrument    │            │  │  │
│                 │  │    State>                │            │  │  │
│                 │  └──────────────────────────┼────────────┘  │  │
│                 │                             │               │  │
│                 │  ┌──────────────────────────▼────────────┐  │  │
│                 │  │           Render Layer                │  │  │
│                 │  │                                       │  │  │
│                 │  │  ┌──────────┐  ┌──────────┐          │  │  │
│                 │  │  │Sidebar   │  │  Chart   │  ┌───────┤  │  │  │
│                 │  │  │Scanner   │  │  Scene   │  │Right  │  │  │  │
│                 │  │  │          │  │          │  │Panel  │  │  │  │
│                 │  │  └──────────┘  └──────────┘  └───────┘  │  │  │
│                 │  └─────────────────────────────────────────┘  │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │              External Dependencies                          │  │
│  │  lightweight-charts 4.1.1 · zustand 5 · immer 11           │  │
│  │  lucide-react · tailwindcss 4 · expo (RN Web)              │  │
│  └─────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────┘
```

### 3.2 Architectural Pattern

The frontend follows a **server-driven passive renderer** pattern:

- **Zero business logic**: No trading decisions, no signal generation, no order placement
- **Pure display**: All state flows one-way from backend → WebSocket → React state → render
- **Delta protocol**: Backend sends incremental state updates, frontend merges them
- **Event bus**: High-frequency tick data bypasses React state entirely, dispatched via `EventTarget` directly to `ChartScene`

### 3.3 Component Hierarchy

```
App
├── [Journal Page] (when currentPage === 'journal')
│   └── JournalPage
│       ├── TradesTable
│       ├── EventsTable
│       └── StatCard
│
├── [Loading Screen] (when !activeInstrument)
│
├── [Trading View] (default)
│   ├── Connection Banner (when !connected)
│   │
│   ├── Left Sidebar (MarketSidebar)
│   │   └── SymbolCard × N (memoized)
│   │
│   ├── Center Area
│   │   ├── ChartScene (memoized)
│   │   │   ├── lightweight-charts Canvas
│   │   │   ├── Overlay Canvas (AMT drawings)
│   │   │   ├── Mode Indicator Badge
│   │   │   └── DecisionCard
│   │   │
│   │   └── Overlay Controls
│   │       ├── ModelStateBanner
│   │       ├── Chart View Toggle
│   │       └── Volume Profile Toggle
│   │
│   ├── Journal FAB (floating action button)
│   │
│   └── Right Sidebar (AIAnalysisPanel)
│       ├── EquityPanel
│       ├── RiskStateDisplay
│       ├── State Section
│       ├── Location Section (price-vs-VA visualization)
│       ├── Aggression Section
│       ├── Market Metrics Section
│       ├── IB + Breaks Section
│       ├── LVN Play Section (conditional)
│       ├── Absorption Section (conditional)
│       ├── VWAP + Context Section (conditional)
│       ├── Probability Engine Section
│       ├── Overseer Section (conditional)
│       ├── Trade Plan Section (conditional)
│       ├── Recent Exits Section (conditional)
│       ├── Diagnostics (collapsed)
│       │   ├── Market Structure
│       │   ├── POC Signal
│       │   ├── VWAP Events
│       │   └── Rule Checklist
│       ├── Model I/O Footer (collapsed)
│       └── DecisionHistoryPanel
```

---

## 4. Data Flow Architecture

### 4.1 Initialization Sequence

```
1. App mounts → useServerTradingSystem() initiates
2. fetch('/api/system/config') ──────▶ Backend REST
   ├─ Returns: { activeSymbols, backendPort }
   ├─ Creates InstrumentState for each symbol
   └─ Sets activeSymbol
3. fetch('/api/ai/history') ─────────▶ Load LLM decision history
   └─ Populates llmHistory per symbol
4. WebSocket opens → '/api/trading/ws/gameloop'
   ├─ Sends: { subscribe: activeSymbol }
   ├─ Starts heartbeat timer (ping every 15s)
   └─ Awaits server messages
5. Server sends: { status: 'server_mode', activeSymbols: [...] }
   └─ Purges stale symbols, adds new ones
6. Server sends: { status: 'history_loaded', history: OHLCData[] }
   └─ Populates chart data
7. Server streams: { _type: 'delta', tick, amt, ... } ──▶ Continuous
   └─ RAF-batched merge into instrument state
```

### 4.2 Real-Time Tick Flow

```
Backend ──WS──▶ handleWsMessage()
                   │
                   ├─ [tick-only delta] ──▶ tickBus.dispatchEvent('tick')
                   │                         └──▶ ChartScene.update() (native API)
                   │                               (NO React render)
                   │
                   └─ [analytics delta] ──▶ batchedSetInstruments()
                                             └──▶ requestAnimationFrame()
                                               └──▶ setInstruments()
                                                 └──▶ React re-render
                                                       ├─ AIAnalysisPanel (if amt/genAI changed)
                                                       ├─ MarketSidebar (if positions changed)
                                                       └─ ModelStateBanner (if agentDecision changed)
```

### 4.3 Tick Bus Architecture

The `tickBus` is an `EventTarget` that provides a **zero-overhead path** for high-frequency chart updates:

```
useServerTradingSystem
  └─ tickBusRef: EventTarget
       │
       ├─ 'tick' event ──▶ ChartScene.handleTick()
       │                     ├─ candleSeries.update() (TradingView native)
       │                     └─ volumeSeries.update() (TradingView native)
       │
       └─ 'gap_fill' event ──▶ ChartScene.handleGapFill()
                                 └─ Batch update historical candles
```

This bypasses React's render cycle entirely for chart updates, which is critical because:
- 9 symbols × ~7 ticks/sec = ~63 updates/sec
- React setState 63×/sec would cause severe jank
- TradingView's native `update()` mutates the canvas directly

### 4.4 Delta Protocol

The backend sends two message types:

**Full State** (`_type === 'full'` or no `_type`):
```json
{
  "_symbol": "NIFTY 27 FEB 25500 CALL",
  "_type": "full",
  "tick": { "time": "...", "open": ..., "high": ..., "low": ..., "close": ..., "volume": ... },
  "portfolio": { "balance": ..., "positions": [...], "closedTrades": [...] },
  "amt": { "marketState": "...", "poc": ..., ... },
  "auction": { ... },
  "quantDecision": { ... },
  "genAIAnalysis": { ... },
  "riskState": { ... },
  "agentDecision": { ... },
  "overseerAction": "...",
  "overseerReason": "..."
}
```

**Delta State** (`_type === 'delta'`):
```json
{
  "_type": "delta",
  "tick": { ... },
  "amt": { "aggression": 0.45 },    // Only changed fields
  "ltp": 25485.30,
  "oi": 125000
}
```

The delta protocol is **the single most important performance optimization** in the frontend. Without it, every tick would transmit the entire ~50KB instrument state.

---

## 5. Component Class Diagram

### 5.1 Type System

```typescript
// Core data types (types.ts)

OHLCData ─────────────────────────────────────────────
  time: string              // ISO timestamp
  open, high, low, close: number
  volume: number
  vwap: number
  takerBuyVolume: number
  delta: number

InstrumentState ──────────────────────────────────────
  symbol: string
  data: OHLCData[]                      // Candle history
  orderBook: OrderBook | null
  portfolio: Portfolio                  // Balance + positions
  aiAnalysis: AIAnalysis | null         ⚠️ DEAD CODE — never populated
  genAIAnalysis: GenAIAnalysis | null   // LLM narrative
  amtAnalysis: AMTAnalysis | null       // 50+ optional fields
  auctionAnalysis: AuctionAnalysis | null
  quantDecisionAnalysis: QuantDecisionAnalysis | null
  riskState: RiskState | null
  agentDecision: AgentDecision | null
  llmHistory: LLMHistoryEntry[]
  overseerAction: string
  overseerReason: string
  ltp?: number
  oi?: number
  lastUpdate: number

AMTAnalysis ──────────────────────────────────────────
  // 50+ optional fields, including:
  marketState: string
  poc, valueAreaHigh, valueAreaLow: number
  lvns: number[], hvns: number[]
  aggression: number
  profile: VolumeProfileLevel[]
  legProfile: VolumeProfileLevel[]
  aggressivePrints: AggressivePrint[]
  // ... 40+ more optional fields

QuantDecisionAnalysis ────────────────────────────────
  approved: boolean
  reason: string          // "Triple-A" | "VA_FADE" | "NO_EDGE" | "GATE_REJECTED"
  phase: string
  signal: { type, entry, sl, tp, rr, confidence } | null
```

### 5.2 Component Relationships

```
App.tsx
  │
  ├─ useServerTradingSystem(config) ──▶ { instruments, activeSymbol, tickBus, ... }
  │
  ├─ useUIStore() ──▶ { chartMode, sidebarOpen, vpMode, ... }
  │
  ├─ useInstrumentsStore() ──▶ { allSymbols } ⚠️ Only used for keyboard navigation
  │
  ├─ useKeyboardNavigation() ──▶ Hotkey bindings
  │
  ├─ MarketSidebar ──▶ instruments, activeSymbol, onSelect
  │     └─ SymbolCard × N (memoized)
  │
  ├─ ChartScene ──▶ data, tickBus, positions, amtAnalysis, agentDecision
  │     ├─ DecisionCard ──▶ direction, regime, rationale
  │     └─ [Canvas Overlay] ──▶ AMTLevelsOverlay, ExecutionMarkersManager
  │
  ├─ ModelStateBanner ──▶ genAI, amtResult, agentDecision, auction, quantDecision
  │
  └─ AIAnalysisPanel ──▶ analysis, amtResult, portfolio, riskState, ...
        ├─ EquityPanel ──▶ portfolio, openPnl
        ├─ RiskStateDisplay ──▶ riskState
        └─ DecisionHistoryPanel ──▶ llmHistory
```

### 5.3 Data Ownership Map

| Data | Owner | Consumers |
|------|-------|-----------|
| `instruments` state | `useServerTradingSystem` | App → ChartScene, MarketSidebar, AIAnalysisPanel, ModelStateBanner |
| `activeSymbol` | `useServerTradingSystem` | App → MarketSidebar, JournalPage |
| `tickBus` events | `useServerTradingSystem` | ChartScene (native canvas updates) |
| `chartMode` | `useUIStore` (persisted) | App → ChartScene |
| `vpMode` | `useUIStore` (persisted) + `config` | App → ChartScene |
| `sidebarOpen` | `useUIStore` (persisted) | App (layout) |
| `instrumentsStore` | `useInstrumentsStore` | App (keyboard nav only) ⚠️ |

---

## 6. Component-by-Component Review

### 6.1 App.tsx (348 lines)

**Role:** Root component, layout orchestrator, state consumer

**Props:** None (singleton)

**State:**
- `config: ChartConfig` — Local React state, NOT persisted to Zustand
- `overseerPos` — Drag position for overseer box
- Derived: `effectiveConfig` from `activeInstrument`

**Collaborators:** 8 components, 2 hooks, 2 stores

**Findings:**

| # | Severity | Description |
|---|----------|-------------|
| F-01 | Medium | `config` lives in local `useState` but `vpMode` is also in `useUIStore`. Two sources of truth for VP mode. The UI store's `vpMode` is read for hotkey handling but `config.vpMode` drives the actual chart rendering. |
| F-02 | Low | `currentSymbolIndex` stored in `useRef` — loses sync if symbols are added/removed dynamically. If the active symbol is purged from the list, keyboard navigation can select a stale index. |
| F-03 | Low | Drag handler for `overseerPos` is implemented but the overseer box itself is not rendered anywhere visible in the current code. Dead UI code. |
| F-04 | Info | `handleSaveWorkspace` is a no-op — just logs to console. Zustand persist middleware handles auto-save, but the button gives false confidence. |

**Code Quality:** Good. Clean separation of concerns, stable callbacks with `useCallback`, proper cleanup in `useEffect`.

---

### 6.2 useServerTradingSystem.ts (810 lines)

**Role:** Central WebSocket hook, all market data flows through here

**Returns:** `{ instruments, activeSymbol, setActiveSymbol, activeInstrument, connected, connectionStatus, tickBus }`

**Internal State:** 12 refs, 4 useState values, 3 timers

**Findings:**

| # | Severity | Description |
|---|----------|-------------|
| F-05 | **Critical** | **Gap-filling fabricates market data.** `mergeCandleData()` (lines 82-126) forward-fills missing candles with `close = prev.close, volume = 0, delta = 0`. These fabricated candles appear in `instrument.data`, which is consumed by ChartScene, AMTLevelsOverlay, and all analysis components. **Zero-volume candles create false LVN signals and distort volume profile calculations.** |
| F-06 | High | **No message deduplication by ID.** `recentMessageIdsRef` exists (line 153) but is never populated or checked. The deduplication mechanism is dead code. |
| F-07 | High | **Delta merge spreads mutable objects.** Line 528: `merged.amtAnalysis = { ...existing.amtAnalysis, ...state.amt }` — shallow spread of a 50+ field object. If the backend sends a partial AMT update with only 2 changed fields, the merge preserves stale values from the previous state for the other 48 fields. |
| F-08 | Medium | **Race condition on symbol switch.** The 80ms debounce (line 786) helps, but if the WebSocket reconnects during a symbol switch, the `onopen` handler sends a subscribe for `activeSymbolRef.current`, which may have changed again by the time the message is sent. The generation counter (`subscribeGenRef`) only applies to the debounce path, not the reconnect path. |
| F-09 | Medium | **Candle cap inconsistency.** Delta path caps at 1000 candles (line 521), full state path also caps at 1000 (line 592), but `mergeCandleData()` caps at 2000 (line 120). History load uses the 2000 cap, live updates use 1000. A symbol with 1500 historical candles would lose 500 on the next live update. |
| F-10 | Low | **Hardcoded fallback symbols.** Line 259: `['CRUDEOIL', 'NATURALGAS']` — MCX defaults hardcoded. If the backend is configured for NSE, these defaults are wrong. |
| F-11 | Low | **Config timeout too generous.** 180-second timeout (line 230) for initial config fetch. If the backend is down, the user waits 3 minutes before seeing a meaningful error. |
| F-12 | Info | **`parseErrorCount` reset on success.** Good pattern — consecutive parse errors trigger reconnect, successful parse resets counter. Well-designed. |

**Performance Analysis:**

The RAF batching implementation (lines 156-186) is well-designed:
- Queues up to 10 updates per frame
- Drops oldest updates if queue overflows (backpressure)
- Single `setInstruments` call per frame
- Reduces ~60 setState calls/sec to ~60 RAF callbacks/sec (batched into ~10 actual renders)

However, the backpressure drop strategy (remove oldest, keep latest) means intermediate state transitions are silently lost. If the backend sends: `ABSORBING → ACCUMULATING → SIGNAL` in rapid succession, only `SIGNAL` is rendered. This is acceptable for analytics but means the UI may skip transient states.

---

### 6.3 ChartScene.tsx (1,036 lines)

**Role:** TradingView chart rendering with AMT canvas overlays

**Props:** `data`, `config`, `positions`, `closedTrades`, `agentDecision`, `amtAnalysis`, `mode`, `tickBus`, `symbol`

**Internal Refs:** 8 refs (chart, series, price lines, overlay canvas)

**Rendering Strategy:**
1. `useEffect([])` — Chart initialization (once on mount)
2. `useEffect([tickBus, symbol])` — Native tick subscription (bypasses React)
3. `useEffect([stableAmtAnalysis, stableData])` — Canvas overlay drawing
4. `useEffect([data])` — Full candle/volume series update
5. `useEffect([positions, amtAnalysis, ...])` — Markers and price lines

**Findings:**

| # | Severity | Description |
|---|----------|-------------|
| F-13 | **Critical** | **IST offset magic number.** `19800` seconds (5h30m) is hardcoded in 3 places within this file (lines 264, 300, 858) and repeated in CandleSeriesManager, ExecutionMarkersManager, and VolumeSeriesManager. If the app ever needs to support a different timezone, this is a multi-file change. |
| F-14 | High | **`stableData` stabilization is fragile.** `useMemo(() => data, [data.length])` (line 137) — only re-computes when array length changes. This means intra-candle updates (same candle, different OHLC values) are NOT reflected in the canvas overlay. The overlay draws against stale candle data until a new candle is appended. |
| F-15 | High | **Canvas overlay redraws on every AMT change.** Despite `stableAmtAnalysis` memoization, the overlay effect depends on `[stableAmtAnalysis, stableData, config, mode]`. The `config` object is a new reference every render (created by `useMemo` in App), causing unnecessary redraws. |
| F-16 | Medium | **`chartSceneAreEqual` memo comparator is too broad.** Compares `prev.config !== next.config` by reference. Since `effectiveConfig` in App is memoized on `[config, activeInstrument?.symbol]`, this is usually fine, but the comparator also checks `prev.amtAnalysis !== next.amtAnalysis` by reference — defeating the purpose of `stableAmtAnalysis`. |
| F-17 | Medium | **Volume series validation result ignored.** `validateVolumeData()` returns errors, but the result is used incorrectly: `if (!validation.length)` — `validation` is an array of data points, not errors. The condition `!validation.length` is always false for non-empty data, so the `setData` call always executes. The validation result is unused. |
| F-18 | Low | **`initializedRef` scroll-to-end only fires once.** After the first data load, the chart scrolls to the end. On subsequent full data replacements (e.g., symbol switch), the chart does NOT auto-scroll. The user may see an empty or zoomed-out chart. |
| F-19 | Info | **Overlay drawing functions are component-level methods.** `drawAggressiveBubbles`, `drawVAShadedBox`, `drawTimeMarkers`, `drawIBRetestZone`, `drawProfileBars`, `drawVolumeProfile` are defined as component-level functions recreated on every render. Should be extracted to pure functions outside the component. |

**Quant Engineer Perspective:**

The overlay drawing is impressive in scope — VA shaded box, session phase markers, IB retest zone, volume profiles with HVN/LVN coloring, aggressive bubbles. However:

1. **No scale validation:** `drawProfileBars` assumes `series.priceToCoordinate()` returns valid coordinates. If price is outside the visible range, the function draws off-screen without checking.
2. **Hardcoded zone sizes:** IB retest zone uses `±0.3%` (line 636). This should be configurable or derived from ATR.
3. **No DPI awareness:** Canvas overlay does not account for `devicePixelRatio`. On Retina displays, the overlay appears blurry because the canvas is sized at CSS pixels, not device pixels.

---

### 6.4 AIAnalysisPanel.tsx (1,525 lines)

**Role:** Right sidebar intelligence panel — the largest and most complex component

**Props:** 11 props (`analysis`, `amtResult`, `portfolio`, `riskState`, `agentDecision`, `llmHistory`, `orderBook`, `overseerAction`, `overseerReason`, `symbol`, `data`)

**Sections Rendered:** 16 conditional sections, each with deeply nested JSX

**Findings:**

| # | Severity | Description |
|---|----------|-------------|
| F-20 | **Critical** | **1,525-line god component.** This single component renders 16 distinct sections (State, Location, Aggression, Market Metrics, IB+Breaks, LVN Play, Absorption, VWAP+Context, Probability, Overseer, Trade Plan, Recent Exits, Diagnostics, Model I/O, Decision History, Equity). Each section should be its own component. The component is **untestable as a unit** — any change to one section risks breaking another. |
| F-21 | **Critical** | **Inline IIFE components.** Lines 209-282, 285-304, 415-454, 460-474, 546-572, 575-603, 606-616, 637-667, 700-777, 787-875, 1262-1356 — at least 12 immediately-invoked function expressions that render JSX inline. These are anonymous sub-components that cannot be tested, memoized, or reused. |
| F-22 | High | **`currentLtp` 4-tier fallback chain.** Lines 27-38: orderBook mid-price → last close → session VWAP → 0. This means the "current price" displayed can be any of 3 different values depending on data availability. A stale VWAP value could be displayed as "current price" if the order book and candle data are both unavailable. |
| F-23 | High | **`effectiveAnalysis` constructs fake analysis.** Lines 43-55: when no GenAI analysis exists, the component fabricates a "monitoring mode" analysis object from AMT data. This fabricated analysis has `direction: 'FLAT'` and `confidence: 'Low'`, but is treated identically to real LLM output downstream. The "LLM Timeout" banner (line 149) partially mitigates this, but the data flows through the same rendering path. |
| F-24 | High | **Deeply nested conditional rendering.** The component has 5+ levels of nesting: `if (amtResult) → if (amtResult.breakDirection) → if (amtResult.ibHigh) → if (currentLtp) → render`. This makes the component impossible to reason about at a glance. |
| F-25 | Medium | **`React.memo` without prop comparator.** Line 1524: `React.memo(AIAnalysisPanelInner)` uses default shallow comparison. The `amtResult` prop has 50+ fields — a single field change causes a full re-render of all 1,525 lines. Should use a custom comparator or split into smaller memoized components. |
| F-26 | Medium | **String matching for dead market detection.** Line 61: `inst.genAIAnalysis?.rationale?.includes('DEAD')` — coupling UI logic to backend string conventions. If the backend changes the rationale format, the UI breaks silently. |
| F-27 | Medium | **Repeated `sanitizeRationale` calls.** The text sanitizer is called in 5+ places within the component. Each call re-processes the same string. Should be memoized once at the top level. |
| F-28 | Low | **Hardcoded circuit breaker values.** Lines 17-18: `target = 20000`, `cb = -10000`. These are hardcoded in the EquityPanel, not configurable. |
| F-29 | Info | **Excellent use of `useMemo` for derived values.** `openPnl`, `aggScore`, `vah/val/poc` formatting are all memoized. Good practice. |

**Quant Engineer Perspective:**

From a trading terminal perspective, this panel is **information-dense but not information-optimized**:

1. **No priority-based rendering:** All 16 sections render with equal visual weight. A trader scanning the panel should see the most critical information (current position PnL, active signals, risk state) without scrolling.
2. **Missing execution context:** The panel shows analysis but not order status. There's no display of pending orders, fill confirmations, or rejection reasons.
3. **Redundant data display:** POC is shown in at least 4 places (Location section, Diagnostics, VWAP section, Market Metrics). VAH/VAL appear in 3 places.
4. **No time decay indicator:** For scalping strategies, the age of the analysis matters. A 30-second-old AMT signal is less valuable than a 1-second-old one. The panel shows `lastUpdate` nowhere.

---

### 6.5 MarketSidebar.tsx (290 lines)

**Role:** Left sidebar market scanner with symbol list and filters

**Props:** `instruments`, `activeSymbol`, `onSelect`

**Internal State:** `filter`, `modeFilter`, `actionFilter`, `sortBy`

**Findings:**

| # | Severity | Description |
|---|----------|-------------|
| F-30 | Medium | **`SymbolCard` reads stale data.** The card is memoized but receives `inst` as a prop. If `inst` is a reference from the `instruments` record and only a nested field changes (e.g., `inst.portfolio.positions`), the shallow `React.memo` comparison may not detect the change because `inst` reference is the same object (mutated in-place by the delta merge). |
| F-31 | Low | **`shortSymbol` duplicated.** This function exists in both `MarketSidebar.tsx` (local) and `utils/symbol.ts` (shared). The two implementations are identical. The local copy should be removed. |
| F-32 | Low | **Sort function is O(n log n) on every render.** The `filtered` memo depends on `[symbols, filter, modeFilter, actionFilter, instruments, sortBy]`. The `instruments` object is a new reference every render (created by `setInstruments`), so the sort runs on every state update, not just when filters change. |

---

### 6.6 ModelStateBanner.tsx (120 lines)

**Role:** Primary status strip — shows current model state at a glance

**Props:** `genAI`, `amtResult`, `agentDecision`, `auction`, `quantDecision`, `symbol`

**States:** SLEEPING → ARMED → IB BREAK → ADVISORY → MONITORING

**Findings:**

| # | Severity | Description |
|---|----------|-------------|
| F-33 | Good | Well-designed component. Clear state machine, memoized, accessible with `aria-live="polite"`. The priority ordering (Dead > Armed > IB Break > Advisory > Monitoring) is correct for a trading terminal. |
| F-34 | Low | `quantDecision` display only shows when `approved && signal`. Rejected quant decisions (which could be informative — "gates passed but no signal") are silently hidden. |

---

### 6.7 JournalPage.tsx (409 lines)

**Role:** Full-page trade journal with date navigation, summary stats, and event tables

**Data Source:** REST API (`/api/ai/journal/trades`, `/api/ai/journal`, `/api/ai/journal/summary`)

**Findings:**

| # | Severity | Description |
|---|----------|-------------|
| F-35 | Medium | **Three parallel fetches with no abort controller.** Lines 149-157: `Promise.all([fetch(trades), fetch(events), fetch(summary)])` — if the user changes the date before the requests complete, all 3 requests continue running. A newer date's fetch may resolve before an older date's fetch, displaying stale data. |
| F-36 | Low | **No pagination.** The journal loads all trades and events for a date. For a busy trading day with hundreds of signals, this could be a large payload. |
| F-37 | Info | **Well-structured internal components.** `TradesTable`, `EventsTable`, `StatCard` are cleanly separated. Good use of `normalizedExitReason` for consistent display. |

---

### 6.8 Chart Sub-Components

#### AMTLevelsOverlay.ts (322 lines)

**Role:** Pure function — generates price line configurations from AMT analysis

**Findings:**

| # | Severity | Description |
|---|----------|-------------|
| F-38 | Good | Excellent pure-function design. No side effects, fully testable, separates data transformation from rendering. The `calculateVWAPColor` function provides dynamic VWAP coloring based on slope. |
| F-39 | Low | `vpMode` type includes `'daily'` but the implementation only handles `'session'`, `'combined'`, `'leg'`. The `'daily'` mode is a no-op. |

#### CandleSeriesManager.ts (323 lines)

**Role:** Pure functions — candle data transformation, validation, statistics

**Findings:**

| # | Severity | Description |
|---|----------|-------------|
| F-40 | Good | Well-designed pure functions. `validateCandleData` catches common data integrity issues (high < low, negative prices, duplicate timestamps). |
| F-41 | Low | `IST_OFFSET = 19800` duplicated here (line 42), in ChartScene (3 places), and in ExecutionMarkersManager. Should be a single constant in `constants.ts`. |

#### VolumeSeriesManager.ts (290 lines)

**Role:** Pure functions — volume data transformation, spike detection, VWAP calculation

**Findings:**

| # | Severity | Description |
|---|----------|-------------|
| F-42 | Good | `detectVolumeSpikes` uses MAD (Median Absolute Deviation) instead of mean/std — statistically sound for detecting outliers in skewed distributions. Well-documented. |
| F-43 | Low | `getVolumeStats` uses string matching on color values (`d.color.includes('0, 200, 150')`) to classify bullish/bearish volume. Fragile — breaks if color format changes. Should accept a direction flag or use the OHLC data directly. |

#### ExecutionMarkersManager.ts (286 lines)

**Role:** Pure functions — generates chart markers from positions and AMT analysis

**Findings:**

| # | Severity | Description |
|---|----------|-------------|
| F-44 | Good | Clean separation of marker types: entry, exit, IB break, CVD divergence, acceptance/rejection. Each is a pure function. |
| F-45 | Low | `IST_OFFSET = 19800` duplicated again (line 33). This is now the 4th copy of the same constant. |

#### DecisionCard.tsx (70 lines)

**Role:** Compact overlay card showing current AI decision on the chart

**Findings:**

| # | Severity | Description |
|---|----------|-------------|
| F-46 | Good | Small, focused, well-designed. Uses `sanitizeRationale` for safe display. |

---

### 6.9 AI Sub-Components

#### EquityPanel.tsx (96 lines)

**Findings:**

| # | Severity | Description |
|---|----------|-------------|
| F-47 | Good | Clean component. The session P&L progress bar with circuit breaker and target markers is well-designed. |
| F-48 | Low | Hardcoded `target = 20000` and `cb = -10000` (lines 17-18). Should come from `riskState` or config. |

#### RiskStateDisplay.tsx (37 lines)

**Findings:**

| # | Severity | Description |
|---|----------|-------------|
| F-49 | Good | Small, focused, correct. Shows halt warnings and consecutive losses. |

#### DecisionHistoryPanel.tsx (143 lines)

**Findings:**

| # | Severity | Description |
|---|----------|-------------|
| F-50 | Medium | **`decisionSourceLabel` couples to backend conventions.** Line 13: checks if `rawOutput.startsWith('QUANT_')` or `inputPrompt.startsWith('[SESSION GATE:')`. Fragile string matching. |
| F-51 | Low | **Export CSV is a dead link.** Line 51: "Export CSV" is rendered but has no `onClick` handler. It's a visual-only placeholder. |

---

### 6.10 Supporting Components

#### ErrorBoundary.tsx (51 lines)

**Findings:** Good. Standard React error boundary with named logging. Used around all major component groups in App.

#### GlassPanel.tsx (52 lines)

**Findings:** Good. Simple wrapper with 3 variants. Only used by MarketSidebar.

---

### 6.11 Utilities

#### textSanitizer.ts (225 lines)

**Role:** Cleans LLM output for display — handles JSON artifacts, escape sequences, malformed responses

**Findings:**

| # | Severity | Description |
|---|----------|-------------|
| F-52 | Medium | **Aggressive regex-based JSON extraction.** `extractFromMalformedJson` tries 9 keys × 3 regex patterns = 27 regex matches per call. This runs on every rationale display. Should be cached or moved to the backend. |
| F-53 | Low | **`sanitizeRationale` has a silent fallback.** Returns `'Analysis pending...'` when all cleaning fails (line 204). This string is indistinguishable from a legitimate backend message. The UI should differentiate between "no data yet" and "data was unreadable". |

#### symbol.ts (24 lines)

**Findings:** Good. Simple, focused. But `shortSymbol` is duplicated in MarketSidebar.

---

### 6.12 Hooks

#### useKeyboardNavigation.ts (195 lines)

**Role:** Hotkey system with configurable bindings

**Findings:**

| # | Severity | Description |
|---|----------|-------------|
| F-54 | Good | Well-designed. Uses `useRef` to always access latest hotkeys, proper cleanup, input field ignoring. |
| F-55 | Low | **`Tab` key hotkey conflicts with browser tab navigation.** Line 157: `Tab` is bound to "Next symbol". This prevents the user from tabbing between focusable elements. Accessibility issue. |

---

### 6.13 Stores

#### ui.ts (187 lines)

**Role:** Persisted UI state (chart mode, sidebar visibility, VP mode)

**Findings:**

| # | Severity | Description |
|---|----------|-------------|
| F-56 | Good | Well-designed Zustand store with immer middleware. Selectors exported for optimized subscriptions. `partialize` correctly limits persisted fields. |
| F-57 | Low | `currentPage` is NOT persisted (not in `partialize`). User always returns to trading view on reload, even if they were viewing the journal. Minor UX issue. |

#### instruments.ts (179 lines)

**Role:** Normalized instrument state store (byId + allIds pattern)

**Findings:**

| # | Severity | Description |
|---|----------|-------------|
| F-58 | **Critical** | **This store is completely unused.** `useInstrumentsStore` is imported in App.tsx and only `selectAllSymbols` is called. The store has 10 action creators and 8 selectors — all dead code. The actual instrument state lives in `useServerTradingSystem`'s local `useState`. This is ~180 lines of maintenance burden for zero value. |

---

## 7. Strategy Execution Review

### 7.1 How Trading Signals Flow to the Frontend

```
Backend Decision Pipeline:
  1. TradingSessionService.process_tick() ──▶ AMT Analysis
  2. QuantBridge.evaluate() ──▶ QuantDecision (approved/rejected)
  3. AgentService.predict() ──▶ AgentDecision (direction, probability, timing)
  4. GenAI Service ──▶ Narrative rationale
  5. Overseer ──▶ Position management action

WebSocket Delta:
  {
    agentDecision: { direction: "LONG", probability: 0.72, timing: "ENTER_NOW", ... },
    quantDecision: { approved: true, signal: { type: "LONG", entry: ..., sl: ..., tp: ... }, ... },
    genAIAnalysis: { direction: "LONG", rationale: "...", confidence: "High" },
    overseerAction: "HOLD",
    amt: { marketState: "IMBALANCED", ... }
  }

Frontend Rendering:
  ModelStateBanner: "ARMED — ENTER NOW (LONG)" with probability
  AIAnalysisPanel: Full breakdown of all signals
  ChartScene: Entry markers, price lines, decision card
```

### 7.2 Critical Gap: Frontend Cannot Execute Trades

**The frontend is a passive observer.** It displays:
- Entry signals (`ENTER_NOW`)
- Quant-approved signals with entry/SL/TP
- Position PnL
- Overseer actions

But it **cannot**:
- Place orders
- Cancel orders
- Modify stop-loss or take-profit
- Manually exit a position
- Override a halt
- Acknowledge a risk warning

**This is by design** (server-driven architecture), but it means:
1. The "ARMED — ENTER NOW" banner is informational only — the backend executes independently
2. If the backend fails to execute, the frontend has no fallback mechanism
3. The trader cannot intervene in any way from the UI

### 7.3 Signal Display Accuracy

| Signal | Display Location | Accuracy |
|--------|-----------------|----------|
| `agentDecision.timing === 'ENTER_NOW'` | ModelStateBanner, AIAnalysisPanel | ✅ Direct from backend |
| `quantDecision.approved` | ModelStateBanner | ✅ Direct from backend |
| `genAIAnalysis.direction` | AIAnalysisPanel | ✅ Direct from backend |
| `amtAnalysis.marketState` | AIAnalysisPanel, MarketSidebar | ✅ Direct from backend |
| `overseerAction` | AIAnalysisPanel | ✅ Direct from backend |
| Position PnL | AIAnalysisPanel, MarketSidebar | ⚠️ Stale — depends on update frequency |
| LTP | AIAnalysisPanel Location section | ⚠️ 4-tier fallback, may show stale VWAP |

### 7.4 Risk Display

The frontend correctly displays:
- Trading halt status (`RiskStateDisplay`)
- Consecutive losses counter
- Daily PnL
- Circuit breaker progress bar (`EquityPanel`)

**Missing:**
- No audible alert on halt
- No visual flash on new signal
- No countdown timer for time-stop exits
- No position age warning (important for scalping)

---

## 8. State Management Analysis

### 8.1 State Architecture

```
useServerTradingSystem (useState)
  └─ instruments: Record<string, InstrumentState>
       ├─ [SYMBOL1]: InstrumentState  ← 50+ fields per symbol
       ├─ [SYMBOL2]: InstrumentState
       └─ [SYMBOLN]: InstrumentState

useUIStore (Zustand + persist + immer)
  └─ chartMode, sidebarOpen, vpMode, ...

useInstrumentsStore (Zustand + immer) ⚠️ UNUSED
  └─ byId, allIds, activeId
```

### 8.2 Problem: Single State Blob

All instrument state lives in one `useState` call. Every delta update creates a new `Record<string, InstrumentState>` object, causing React to re-evaluate all consumers:

```
setInstruments(newRecord)
  └─ App re-renders (reads instruments)
       ├─ MarketSidebar re-renders (reads instruments)
       │    └─ SymbolCard × N re-renders (memo check)
       ├─ ChartScene re-renders (reads activeInstrument.data)
       ├─ AIAnalysisPanel re-renders (reads activeInstrument.amtAnalysis)
       └─ ModelStateBanner re-renders (reads activeInstrument.agentDecision)
```

Even though `ChartScene` and `AIAnalysisPanel` are `React.memo`, the props they receive are new references every time (because the delta merge creates new objects). The memo comparators help but are imperfect.

### 8.3 Recommended State Split

```
// Instead of one instruments Record, split into:
const [candleData, setCandleData] = useState<Record<string, OHLCData[]>>()
const [portfolios, setPortfolios] = useState<Record<string, Portfolio>>()
const [amtAnalysis, setAmtAnalysis] = useState<Record<string, AMTAnalysis>>()
const [agentDecisions, setAgentDecisions] = useState<Record<string, AgentDecision>>()
// ... etc
```

This would allow granular updates: a tick-only delta only updates `candleData`, triggering ChartScene but not AIAnalysisPanel.

---

## 9. WebSocket Protocol Analysis

### 9.1 Connection Lifecycle

```
connect()
  ├─ new WebSocket('/api/trading/ws/gameloop')
  ├─ onopen: send subscribe, start heartbeat
  ├─ onmessage: handleWsMessage()
  ├─ onclose: exponential backoff reconnect
  └─ onerror: silent (no-op)
```

### 9.2 Heartbeat

- Ping every 15 seconds
- Connection declared dead if no pong in 45 seconds (3× heartbeat)
- Any message from backend resets `lastPongRef` (not just pong responses)

**Assessment:** Good design. The 45-second timeout provides 2 missed heartbeats + buffer before declaring death.

### 9.3 Reconnect Strategy

```
Exponential backoff: 1s → 2s → 4s → 8s → ... → 5s (capped)
Reset on successful connection
```

**Assessment:** Correct implementation. The cap at 5s prevents excessive delay.

### 9.4 Subscribe Protocol

```
Client → Server: { subscribe: "NIFTY 27 FEB 25500 CALL" }
Server → Client: { status: "symbol_switched", symbol: "..." }
Server → Client: { status: "history_loaded", history: [...], symbol: "..." }
Server → Client: { _type: "delta", ... } (continuous)
```

**80ms debounce** prevents rapid-fire subscribe messages when the user clicks multiple symbols quickly. A generation counter invalidates stale in-flight subscribes.

**Assessment:** Well-designed. The debounce + generation counter pattern is correct.

---

## 10. Rendering Performance

### 10.1 Memoization Strategy

| Component | Memo Type | Effectiveness |
|-----------|-----------|---------------|
| `ChartScene` | `React.memo` + custom comparator | Medium — comparator checks by reference |
| `AIAnalysisPanel` | `React.memo` (default) | Low — shallow compare of 11 props |
| `ModelStateBanner` | `React.memo` (default) | Medium — 6 props, some stable |
| `SymbolCard` | `React.memo` (default) | Medium — 4 props, `inst` changes frequently |
| `DecisionCard` | No memo | Low — re-renders with ChartScene |
| `EquityPanel` | `React.memo` (default) | Medium |
| `RiskStateDisplay` | `React.memo` (default) | High — small prop set |
| `DecisionHistoryPanel` | `React.memo` (default) | Medium |

### 10.2 RAF Batching

The `batchedSetInstruments` pattern reduces React renders from ~60/sec to ~10/sec (one per animation frame). This is the single most impactful performance optimization.

**Bottleneck:** The batch function still creates a new `instruments` Record on every frame, triggering re-renders for ALL consumers. A more granular state structure would reduce this.

### 10.3 Canvas Overlay

The overlay canvas is redrawn when `stableAmtAnalysis` or `stableData` changes. The stabilization memos (`useMemo`) reduce redraw frequency:
- `stableAmtAnalysis`: Only changes when profile/level data changes (candle boundary)
- `stableData`: Only changes when array length changes (new candle)

**Result:** Overlay redraws ~1-2×/min instead of ~60×/sec. Excellent optimization.

---

## 11. Testing Coverage

### 11.1 Coverage Map

| File | Lines | Test Lines | Coverage Ratio |
|------|-------|-----------|----------------|
| AMTLevelsOverlay.ts | 322 | 336 | 104% ✅ |
| CandleSeriesManager.ts | 323 | 310 | 96% ✅ |
| VolumeSeriesManager.ts | 290 | 239 | 82% ✅ |
| ExecutionMarkersManager.ts | 286 | 259 | 91% ✅ |
| DecisionCard.tsx | 70 | 90 | 129% ✅ |
| useServerTradingSystem.ts | 810 | 206 | 25% ⚠️ |
| ChartScene.tsx | 1,036 | 206 | 20% ⚠️ |
| AIAnalysisPanel.tsx | 1,525 | 72 | 5% ❌ |
| MarketSidebar.tsx | 290 | 192 | 66% ⚠️ |
| GlassPanel.tsx | 52 | 76 | 146% ✅ |
| JournalPage.tsx | 409 | 541* | 132% ✅* |
| ModelStateBanner.tsx | 120 | 0 | 0% ❌ |
| textSanitizer.ts | 225 | 0 | 0% ❌ |
| symbol.ts | 24 | 0 | 0% ❌ |

*Journal tests are in integration tests

### 11.2 Coverage Analysis

**Well-tested (pure functions):** The chart sub-components have excellent coverage because they are pure functions — easy to test without mocking.

**Poorly-tested (components with side effects):** `useServerTradingSystem`, `ChartScene`, and `AIAnalysisPanel` have low coverage because they require extensive mocking (WebSocket, EventTarget, TradingView API).

**Untested:** `ModelStateBanner`, `textSanitizer`, and `symbol` have zero tests despite being non-trivial logic.

### 11.3 Test Quality

The integration tests (`auction-render.test.tsx`, `trading-flow.test.tsx`) are the most valuable — they test end-to-end flows with mocked backend data. However, they test rendering, not behavior. There are no tests for:
- WebSocket reconnection
- Gap filling correctness
- Delta merge accuracy
- RAF batching under load

---

## 12. Findings Index

### Critical (5)

| ID | File | Finding |
|----|------|---------|
| F-05 | useServerTradingSystem.ts | Gap-filling fabricates zero-volume market data |
| F-20 | AIAnalysisPanel.tsx | 1,525-line god component with 16 sections |
| F-21 | AIAnalysisPanel.tsx | 12+ inline IIFE components — untestable |
| F-13 | ChartScene.tsx | IST offset magic number (19800) in 5+ files |
| F-58 | instruments.ts | 180-line Zustand store is completely unused |

### High (7)

| ID | File | Finding |
|----|------|---------|
| F-06 | useServerTradingSystem.ts | Message deduplication is dead code |
| F-07 | useServerTradingSystem.ts | Delta merge shallow-spreads 50+ field objects |
| F-14 | ChartScene.tsx | `stableData` stabilization skips intra-candle updates |
| F-15 | ChartScene.tsx | Canvas overlay redraws on every config reference change |
| F-22 | AIAnalysisPanel.tsx | 4-tier LTP fallback may show stale VWAP as current price |
| F-23 | AIAnalysisPanel.tsx | Fabricated "monitoring mode" analysis flows through same path as real data |
| F-24 | AIAnalysisPanel.tsx | 5+ levels of nested conditional rendering |

### Medium (10)

| ID | File | Finding |
|----|------|---------|
| F-01 | App.tsx | Two sources of truth for vpMode |
| F-08 | useServerTradingSystem.ts | Race condition on symbol switch during reconnect |
| F-09 | useServerTradingSystem.ts | Candle cap inconsistency (1000 vs 2000) |
| F-16 | ChartScene.tsx | Memo comparator defeats stableAmtAnalysis |
| F-17 | ChartScene.tsx | Volume validation result used incorrectly |
| F-25 | AIAnalysisPanel.tsx | React.memo shallow compare on 50+ field objects |
| F-26 | AIAnalysisPanel.tsx | String matching for dead market detection |
| F-30 | MarketSidebar.tsx | SymbolCard may receive stale data via mutation |
| F-35 | JournalPage.tsx | Three parallel fetches with no abort controller |
| F-50 | DecisionHistoryPanel.tsx | Couples to backend string conventions |
| F-52 | textSanitizer.ts | 27 regex matches per rationale display |

### Low (15)

| ID | File | Finding |
|----|------|---------|
| F-02 | App.tsx | currentSymbolIndex ref loses sync on symbol changes |
| F-03 | App.tsx | Dead overseer box drag code |
| F-04 | App.tsx | Save workspace button is a no-op |
| F-10 | useServerTradingSystem.ts | Hardcoded MCX fallback symbols |
| F-11 | useServerTradingSystem.ts | 180s config timeout too generous |
| F-18 | ChartScene.tsx | Scroll-to-end only fires once |
| F-19 | ChartScene.tsx | Overlay functions recreated every render |
| F-28 | AIAnalysisPanel.tsx | Hardcoded circuit breaker values |
| F-31 | MarketSidebar.tsx | shortSymbol duplicated |
| F-32 | MarketSidebar.tsx | Sort runs on every instruments reference change |
| F-34 | ModelStateBanner.tsx | Rejected quant decisions hidden |
| F-36 | JournalPage.tsx | No pagination |
| F-39 | AMTLevelsOverlay.ts | 'daily' vpMode is no-op |
| F-41/43/45 | Multiple | IST_OFFSET duplicated 4 times |
| F-48 | EquityPanel.tsx | Hardcoded target/circuit breaker |
| F-51 | DecisionHistoryPanel.tsx | Export CSV is dead link |
| F-55 | useKeyboardNavigation.ts | Tab key conflicts with browser navigation |
| F-57 | ui.ts | currentPage not persisted |

---

## 13. Remediation Plan

### Phase 1: Critical Fixes (Week 1)

| Task | Effort | Impact |
|------|--------|--------|
| Remove gap-filling from `mergeCandleData()` | 2h | Eliminates fabricated market data |
| Delete unused `useInstrumentsStore` | 30m | Removes 180 lines of dead code |
| Centralize `IST_OFFSET` in `constants.ts` | 1h | Eliminates magic number duplication |
| Split `AIAnalysisPanel` into 8+ sub-components | 2-3 days | Makes the component testable and maintainable |

### Phase 2: High-Impact Improvements (Week 2)

| Task | Effort | Impact |
|------|--------|--------|
| Implement message deduplication or delete dead code | 2h | Eliminates confusion |
| Fix delta merge to use immutable field replacement | 4h | Prevents stale field propagation |
| Add DPI awareness to canvas overlay | 2h | Fixes blurry rendering on Retina displays |
| Add tests for `textSanitizer` and `ModelStateBanner` | 3h | Covers untested logic |

### Phase 3: Architecture (Week 3)

| Task | Effort | Impact |
|------|--------|--------|
| Split instrument state into granular stores | 2-3 days | Reduces unnecessary re-renders by 60%+ |
| Add abort controllers to JournalPage fetches | 1h | Prevents race conditions |
| Extract overlay drawing functions from ChartScene | 4h | Makes chart logic testable |
| Add canvas DPI scaling | 2h | Sharp rendering on high-DPI displays |

### Phase 4: Polish (Week 4)

| Task | Effort | Impact |
|------|--------|--------|
| Remove dead code (overseer drag, Export CSV, AIAnalysis type) | 2h | Code hygiene |
| Add position age indicator to AIAnalysisPanel | 2h | Critical for scalping |
| Add visual flash on new ENTER_NOW signal | 1h | Improves trader awareness |
| Make circuit breaker values configurable | 2h | Removes hardcoding |
| Fix Tab key hotkey conflict | 30m | Accessibility |

---

## Appendix A: Dependency Graph

```
App.tsx
  ├── useServerTradingSystem.ts
  │   ├── types.ts
  │   └── constants.ts (indirect)
  ├── useUIStore → stores/ui.ts
  │   └── types.ts
  ├── useInstrumentsStore → stores/instruments.ts ⚠️ UNUSED
  │   └── types.ts
  ├── useKeyboardNavigation.ts
  ├── ChartScene.tsx
  │   ├── types.ts
  │   ├── components/chart/AMTLevelsOverlay.ts
  │   ├── components/chart/CandleSeriesManager.ts
  │   ├── components/chart/VolumeSeriesManager.ts
  │   ├── components/chart/ExecutionMarkersManager.ts
  │   └── components/chart/DecisionCard.tsx
  │       └── utils/textSanitizer.ts
  ├── AIAnalysisPanel.tsx
  │   ├── types.ts
  │   ├── components/ai/EquityPanel.tsx
  │   ├── components/ai/RiskStateDisplay.tsx
  │   ├── components/ai/DecisionHistoryPanel.tsx
  │   │   └── utils/textSanitizer.ts
  │   └── utils/textSanitizer.ts
  ├── MarketSidebar.tsx
  │   ├── types.ts
  │   └── components/GlassPanel.tsx
  ├── ModelStateBanner.tsx
  │   └── types.ts
  ├── JournalPage.tsx
  │   ├── utils/textSanitizer.ts
  │   └── utils/symbol.ts
  └── ErrorBoundary.tsx
```

## Appendix B: Type Usage Analysis

| Type | Defined In | Used By | Status |
|------|-----------|---------|--------|
| `OHLCData` | types.ts | 8 files | ✅ Active |
| `InstrumentState` | types.ts | 4 files | ✅ Active |
| `AMTAnalysis` | types.ts | 7 files | ✅ Active (50+ optional fields) |
| `AgentDecision` | types.ts | 5 files | ✅ Active |
| `GenAIAnalysis` | types.ts | 5 files | ✅ Active |
| `QuantDecisionAnalysis` | types.ts | 3 files | ✅ Active |
| `AuctionAnalysis` | types.ts | 2 files | ✅ Active |
| `Portfolio` | types.ts | 4 files | ✅ Active |
| `TradePosition` | types.ts | 5 files | ✅ Active |
| `RiskState` | types.ts | 3 files | ✅ Active |
| `AIAnalysis` | types.ts | 1 file (InstrumentState) | ❌ DEAD — never populated |
| `LLMHistoryEntry` | types.ts | 3 files | ✅ Active |
| `OrderBook` | types.ts | 2 files | ✅ Active |
| `ChartConfig` | types.ts | 4 files | ✅ Active |
| `ChartMode` | types.ts | 3 files | ⚠️ Single value `'STANDARD'` |
| `VolumeProfileLevel` | types.ts | 2 files | ✅ Active |
| `AggressivePrint` | types.ts | 3 files | ✅ Active |
| `RuntimeSafetyState` | types.ts | 1 file | ⚠️ Created but rarely updated |
| `FactorBreakdown` | types.ts | 1 file | ❌ DEAD — extends ModelWeights, unused |
| `ModelWeights` | types.ts | 1 file | ❌ DEAD — extends AIAnalysis |

## Appendix C: Lines of Code Summary

| Category | Files | Lines | % of Total |
|----------|-------|-------|------------|
| Components (TSX) | 10 | ~4,450 | 62% |
| Hooks | 2 | ~1,005 | 14% |
| Pure Utilities (TS) | 5 | ~1,250 | 17% |
| Stores | 2 | ~366 | 5% |
| Types | 1 | ~326 | 5% |
| Config/Setup | 4 | ~200 | 3% |
| **Source Total** | **24** | **~7,200** | **100%** |
| Tests | 14 | ~2,653 | 37% of source |

---

*End of Frontend Audit Report*