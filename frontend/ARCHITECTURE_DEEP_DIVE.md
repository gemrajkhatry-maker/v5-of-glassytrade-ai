# Frontend Trading Dashboard — Complete Architecture & How-It-Works Guide

> **Scope**: Every component, every flow, every protocol. From WebSocket messages to pixel-perfect chart rendering.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Tech Stack & Dependencies](#2-tech-stack--dependencies)
3. [Project Structure](#3-project-structure)
4. [Application Entry & Root Orchestrator](#4-application-entry--root-orchestrator)
5. [Type System](#5-type-system)
6. [Central Data Hook — useServerTradingSystem](#6-central-data-hook--useservertradingsystem)
7. [Chart Architecture — ChartScene](#7-chart-architecture--chartscene)
8. [AI Analysis Panel — Intelligence Dashboard](#8-ai-analysis-panel--intelligence-dashboard)
9. [Market Sidebar — Scanner](#9-market-sidebar--scanner)
10. [Journal Page](#10-journal-page)
11. [System Status Bar](#11-system-status-bar)
12. [AI Controls — Natural Language Commands](#12-ai-controls--natural-language-commands)
13. [WebSocket Protocol](#13-websocket-protocol)
14. [Performance Architecture](#14-performance-architecture)
15. [UI Component Library](#15-ui-component-library)
16. [Build & Configuration](#16-build--configuration)
17. [Test Suite](#17-test-suite)
18. [Complete Flow Diagrams](#18-complete-flow-diagrams)
19. [Component Interaction Map](#19-component-interaction-map)
20. [Known Limitations & Technical Debt](#20-known-limitations--technical-debt)

---

## 1. System Overview

The frontend is a **React 19 single-page trading dashboard** for Indian derivatives markets. It is a **pure renderer** — all market data, analysis, and trading logic runs on a Python backend (port 9090). The frontend connects via WebSocket for real-time state and REST for journal/history.

### Architectural Style

**Backend-Driven Rendering + WebSocket-First + EventBus for High-Frequency Data + RAF-Batched State Updates**

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              FRONTEND (React 19)                                    │
│                                                                                     │
│   ┌───────────────────────────────────────────────────────────────────────────┐     │
│   │  App.tsx (Root Orchestrator)                                              │     │
│   │  ├── Left Sidebar: MarketSidebar (360px)                                  │     │
│   │  ├── Center: ChartScene (flex)                                            │     │
│   │  └── Right Sidebar: AIAnalysisPanel (320px)                               │     │
│   └───────────────────────────────────────────────────────────────────────────┘     │
│                                                                                     │
│   ┌───────────────────────────────────────────────────────────────────────────┐     │
│   │  useServerTradingSystem Hook (626 lines)                                  │     │
│   │  ├── WebSocket: ws://backend:9090/api/trading/ws/gameloop                 │     │
│   │  ├── EventBus (EventTarget): Zero-render tick dispatch                    │     │
│   │  ├── RAF-Batched State Updates                                            │     │
│   │  ├── Delta Compression Merge                                              │     │
│   │  └── Exponential Backoff Reconnection                                     │     │
│   └───────────────────────────────────────────────────────────────────────────┘     │
│                                                                                     │
│   ┌───────────────────────────────────────────────────────────────────────────┐     │
│   │  ChartScene (1488 lines)                                                  │     │
│   │  ├── TradingView lightweight-charts                                       │     │
│   │  ├── Canvas Overlay: Footprint / Volume Profile / Bubbles / Range Bars    │     │
│   │  └── 3 Modes: STANDARD / FOOTPRINT / RANGE                                │     │
│   └───────────────────────────────────────────────────────────────────────────┘     │
│                                                                                     │
│   ┌───────────────────────────────────────────────────────────────────────────┐     │
│   │  AIAnalysisPanel (1020 lines)                                             │     │
│   │  ├── Equity, Risk State, Session/Leg State                                │     │
│   │  ├── Market Metrics, Structure, IB, LVN, VWAP                             │     │
│   │  ├── Probability Engine, Overseer, Trade Plan                             │     │
│   │  └── Model I/O, Decision History                                          │     │
│   └───────────────────────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              BACKEND (Python/FastAPI)                               │
│                                                                                     │
│   Port 9090: REST API + WebSocket                                                   │
│   TradingEngine → State Snapshots → Delta Compression → WS Broadcast                │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### Key Design Principles

1. **Backend-Driven**: All analysis (AMT, probability, LLM) runs server-side. Frontend is a pure renderer.
2. **WebSocket-First**: Real-time state via WebSocket with delta compression. REST only for journal/history.
3. **EventBus for Ticks**: High-frequency tick data bypasses React renders via `EventTarget` + `CustomEvent`.
4. **RAF-Batched Updates**: Multiple WebSocket messages merged into a single `requestAnimationFrame` render.
5. **No External State Library**: Pure React `useState` + `useMemo` + `React.memo` with custom comparators.

---

## 2. Tech Stack & Dependencies

### Core Framework
| Package | Version | Purpose |
|---------|---------|---------|
| `react` | 19.2.0 | UI framework |
| `react-dom` | 19.2.0 | DOM rendering |

### Build Tooling
| Package | Version | Purpose |
|---------|---------|---------|
| `vite` | 6.2.0 | Build tool + dev server |
| `@vitejs/plugin-react` | 5.1.4 | React HMR support |
| `typescript` | ~5.8.2 | Type checking |

### Styling
| Package | Version | Purpose |
|---------|---------|---------|
| `tailwindcss` | 4.2.1 | Utility-first CSS |
| `@tailwindcss/vite` | 4.2.1 | Tailwind Vite plugin |

### Charting
| Package | Version | Purpose |
|---------|---------|---------|
| `lightweight-charts` | 4.1.1 | TradingView candlestick charts |

### 3D Graphics
| Package | Version | Purpose |
|---------|---------|---------|
| `three` | 0.181.2 | WebGL 3D rendering |
| `@react-three/fiber` | 9.4.0 | React Three.js renderer |
| `@react-three/drei` | 10.7.7 | Three.js helpers |

### Mobile
| Package | Version | Purpose |
|---------|---------|---------|
| `expo` | 54.0.33 | React Native framework |
| `react-native-web` | 0.21.0 | RN → web compatibility |

### Utilities
| Package | Version | Purpose |
|---------|---------|---------|
| `lucide-react` | 0.555.0 | Icon library |
| `uuid` | 13.0.0 | Unique ID generation |

### Testing
| Package | Version | Purpose |
|---------|---------|---------|
| `vitest` | 4.0.18 | Test runner |
| `@testing-library/react` | 16.3.2 | Component testing |
| `@testing-library/jest-dom` | 6.9.1 | DOM assertions |
| `jsdom` | 28.1.0 | DOM simulation |

---

## 3. Project Structure

```
frontend/
├── index.html                    # HTML template (Inter font, slate-900 bg)
├── index.tsx                     # Entry point (ReactDOM.createRoot)
├── index.css                     # Tailwind v4 entry (@import "tailwindcss")
├── App.tsx                       # Root orchestrator (394 lines)
├── types.ts                      # Core TypeScript interfaces (367 lines)
├── types_rl.ts                   # RL training status types (14 lines)
├── constants.ts                  # Default config + sample prompts (27 lines)
├── vite.config.ts                # Vite build config (port 5190, proxy to 9090)
├── tsconfig.json                 # TypeScript config (ES2022, path aliases)
├── .env.local                    # Environment variables
│
├── hooks/
│   └── useServerTradingSystem.ts # Central data hook (626 lines)
│
├── components/
│   ├── ChartScene.tsx            # Core chart (1488 lines)
│   ├── AIAnalysisPanel.tsx       # Right sidebar intelligence (1020 lines)
│   ├── MarketSidebar.tsx         # Left sidebar scanner (351 lines)
│   ├── JournalPage.tsx           # Trade journal page (376 lines)
│   ├── SystemStatusBar.tsx       # Status bar with phase timer (148 lines)
│   ├── AIControls.tsx            # Natural language commands (149 lines)
│   ├── ErrorBoundary.tsx         # Class error boundary (59 lines)
│   ├── GlassPanel.tsx            # Reusable glassmorphic container (32 lines)
│   ├── VolumeAccessory.tsx       # Deprecated (returns null)
│   ├── AIAgentAvatar.tsx         # Deprecated (returns null)
│   │
│   └── ai/
│       ├── index.ts              # Barrel exports
│       ├── LiveOpportunityCard.tsx  # Best ENTER_NOW signal (93 lines)
│       ├── EquityPanel.tsx          # Equity/PnL display (75 lines)
│       ├── RiskStateDisplay.tsx     # Halt warnings (36 lines)
│       ├── ModelIOPanel.tsx         # LLM debug panel (35 lines)
│       └── DecisionHistoryPanel.tsx # LLM decision timeline (97 lines)
│
├── utils/
│   └── textSanitizer.ts          # LLM text cleaning (50 lines)
│
├── services/                     # Empty (all API in useServerTradingSystem)
│
├── tests/
│   ├── setup.ts                  # Test setup (mocks)
│   ├── components/
│   │   ├── ChartScene.test.tsx   # 9 tests
│   │   ├── GlassPanel.test.tsx   # 6 tests
│   │   └── MarketSidebar.test.tsx # 12 tests
│   ├── hooks/
│   │   └── useServerTradingSystem.test.tsx # 7 tests
│   └── integration/
│       └── trading-flow.test.tsx # 6 integration tests
│
└── dist/                         # Build output
```

---

## 4. Application Entry & Root Orchestrator

### 4.1 Entry Point (`index.tsx`)

```tsx
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
```

Standard React 18+ root creation. Mounts to `<div id="root">` in `index.html`.

### 4.2 App.tsx — Root Orchestrator (394 lines)

**State Management**:
```tsx
const [config, setConfig] = useState<ChartConfig>(DEFAULT_CONFIG);
const [chartMode, setChartMode] = useState<ChartMode>('STANDARD');
const [showControls, setShowControls] = useState(false);
const [sidebarOpen, setSidebarOpen] = useState(true);
const [rightSidebarOpen, setRightSidebarOpen] = useState(true);
const [currentPage, setCurrentPage] = useState<'trading' | 'journal'>('trading');
const [overseerPos, setOverseerPos] = useState({ x: 0, y: 0 }); // draggable position
```

**Central Hook**:
```tsx
const {
  instruments,           // Map<symbol, InstrumentState>
  activeSymbol,          // Currently viewed symbol
  setActiveSymbol,       // Symbol switch function
  activeInstrument,      // Current InstrumentState
  activeFootprint,       // Current footprint data
  connected,             // WebSocket connection status
  connectionStatus,      // Detailed status string
  tickBus,               // EventBus (EventTarget) for zero-render updates
} = useServerTradingSystem(config);
```

**Three-Panel Layout**:
```
┌──────────────┬─────────────────────────────────────────┬──────────────┐
│   Left       │              Center                     │   Right      │
│   Sidebar    │              ChartScene                 │   Sidebar    │
│   (360px)    │              (flex)                     │   (320px)    │
│              │                                         │              │
│ Market-      │ 3 ChartScene instances:                 │ AIAnalysis-  │
│ Sidebar      │   - STANDARD (isHidden toggle)          │ Panel        │
│              │   - FOOTPRINT (isHidden toggle)         │              │
│              │   - RANGE (isHidden toggle)             │              │
│              │                                         │              │
│ Symbol cards │ Volume Profile modes:                   │ Fabio        │
│ with LTP,    │   session, leg, combined, off           │ Playbook     │
│ mode,        │                                         │ dashboard    │
│ action,      │ Price lines: SL/TP/entry positions      │              │
│ probability  │                                         │              │
└──────────────┴─────────────────────────────────────────┴──────────────┘
```

**Key Features**:
- **Status Pin**: Shows model state (ENTRY/MONITORING/SLEEPING), live scanning status, volume status
- **Live Opportunity**: Finds best `ENTER_NOW` signal across all instruments, shows `LiveOpportunityCard`
- **Journal Button**: Bottom-right button to switch to `JournalPage`
- **Draggable Overseer Box**: Mouse-drag positioning with proper cleanup (mousedown/mousemove/mouseup)
- **Chart Mode Toggle**: STANDARD / FOOTPRINT / RANGE — renders all 3 instances with `isHidden` CSS toggle (keeps chart state alive when switching)

**Volume Profile Modes**: `session` (full session), `leg` (since last aggression), `combined` (both), `off`.

---

## 5. Type System

### 5.1 Core Types (`types.ts` — 367 lines)

#### Market Data Types

```typescript
interface OHLCData {
  time: string;                    // ISO timestamp or Unix epoch
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  vwap?: number;
  takerBuyVolume?: number;
  delta?: number;
}

interface OrderBook {
  bids: Array<{ price: number; quantity: number }>;
  asks: Array<{ price: number; quantity: number }>;
}

interface FootprintLevel {
  price: number;
  bid: number;
  ask: number;
  delta: number;
  imbalance: boolean;
  stacked: boolean;
}

interface FootprintCandle {
  time: string;
  levels: FootprintLevel[];
  pocPrice: number;
  totalDelta: number;
  stepPrice: number;
}

interface VolumeProfileLevel {
  price: number;
  volume: number;
  buyVolume: number;
  sellVolume: number;
}
```

#### AI & Analysis Types

```typescript
interface AIAnalysis {
  sentiment: string;
  confidence: number;
  trend: string;
  volatility: number;
  quantScore: number;
  projectedPrice: number;
  reasoning: string;
  factorBreakdown: FactorBreakdown;
}

interface GenAIAnalysis {
  direction: 'LONG' | 'SHORT' | 'FLAT';
  rationale: string;
  confidence: number;
  inputPrompt: string;
  rawOutput: string;
  marketState: string;
  aggression: number;
  quantProbability: number;
  quantDirection: string;
}

interface AgentDecision {
  direction: string;
  probability: number;
  regime: string;
  timing: string;
  sizeFraction: number;
  slAdjust: number;
  tpAdjust: number;
  latencyUs: number;
  rationale: string;
}

interface AMTAnalysis {
  // Market State
  marketState: string;
  poc: number;
  vah: number;
  val: number;
  lvns: number[];
  hvns: number[];
  aggression: number;
  signal: string;
  setup: string;
  profile: string;
  aggressivePrints: AggressivePrint[];

  // Leg Profile
  legProfile: VolumeProfileLevel[];
  legLvns: number[];
  legPoc: number;
  legVah: number;
  legVal: number;

  // Structure
  hasDisplacement: boolean;
  profileShape: string;
  balanceRatio: number;
  ofi: number;
  cvdSlope: number;
  cvdDivergence: number;

  // VWAP
  sessionVwap: number;
  vwapUpper1: number;
  vwapUpper2: number;
  vwapLower1: number;
  vwapLower2: number;

  // Market Structure
  marketStructure: string;
  structureConfidence: number;

  // Initial Balance
  ibHigh: number;
  ibLow: number;
  ibComplete: boolean;

  // Prior Day
  priorDayHigh: number;
  priorDayLow: number;
  priorDayClose: number;
  gapType: string;
  openingBias: string;

  // Signals
  acceptanceSignal: string;
  rejectionSignal: string;
  priceVelocity: number;
  breakDetected: boolean;
  pocSignal: string;
  lvnPlay: string;

  // LLM
  llmThinking: string;
  llmJson: string;
  tickSize: number;
}
```

#### Trading Types

```typescript
interface TradePosition {
  id: string;
  symbol: string;
  side: 'LONG' | 'SHORT';
  source: string;
  entryPrice: number;
  size: number;
  stopLoss: number;
  takeProfit: number;
  pnl: number;
  entryTime: string;
  status: 'OPEN' | 'CLOSED';
  exitPrice?: number;
  exitTime?: string;
  exitReason?: string;
  partialRealizedPnl?: number;
  originalSize?: number;
  metadata?: Record<string, any>;
}

interface Portfolio {
  balance: number;
  equity: number;
  leverage: number;
  positions: TradePosition[];
  closedTrades: any[];
  history: any[];
}

interface RiskState {
  halted: boolean;
  haltReason?: string;
  consecutiveLosses: number;
  dailyPnl: number;
}

interface TradeSignal {
  type: string;
  price: number;
  reason: string;
  stopLoss: number;
  takeProfit: number;
  timestamp: string;
  setup: string;
  source: string;
  metadata?: Record<string, any>;
}

interface StrategyStats {
  totalTrades: number;
  wins: number;
  losses: number;
  winRate: number;
  netProfit: number;
  avgProfit: number;
  largestWin: number;
  largestLoss: number;
}
```

#### Instrument State (The Master Type)

```typescript
interface InstrumentState {
  symbol: string;
  data: OHLCData[];                    // Candle data
  orderBook: OrderBook | null;
  portfolio: Portfolio;
  modelWeights: ModelWeights | null;
  generation: number;                  // For delta compression
  aiAnalysis: AIAnalysis | null;
  genAIAnalysis: GenAIAnalysis | null;
  amtAnalysis: AMTAnalysis | null;
  riskState: RiskState | null;
  agentDecision: AgentDecision | null;
  llmHistory: LLMHistoryEntry[];
  predictions: any[];
  overseerAction: string | null;
  overseerReason: string | null;
  stats: StrategyStats | null;
  depth20Active: boolean;
  stale: boolean;
  ltp: number;
  oi: number;
  rangeBars: RangeBarData | null;
  lastUpdate: number;                  // Timestamp
}
```

#### Chart Configuration

```typescript
type ChartMode = 'STANDARD' | 'FOOTPRINT' | 'RANGE';

interface ChartConfig {
  symbol: string;
  interval: string;
  dataSource: string;
  bullColor: string;
  bearColor: string;
  glassOpacity: number;
  roughness: number;
  transmission: number;
  showGrid: boolean;
  autoRotate: boolean;
  showPredictions: boolean;
  showVolumeProfile: boolean;
  vpMode: 'session' | 'leg' | 'combined' | 'off';
  trend: string;
}
```

#### Range Bar Types

```typescript
interface RangeBar {
  time: string;
  ohlc: { open: number; high: number; low: number; close: number };
  volume: number;
  buyVolume: number;
  sellVolume: number;
  delta: number;
  tickCount: number;
}

interface RangeBarVPLevel {
  price: number;
  volume: number;
  buyVolume: number;
  sellVolume: number;
}

interface RangeBarVP {
  poc: number;
  vah: number;
  val: number;
  levels: RangeBarVPLevel[];
}

interface TripleAPattern {
  detected: boolean;
  phase: string;
  direction: string;
  barIndices: number[];
  pocAtDetection: number;
  vahAtDetection: number;
  valAtDetection: number;
}

interface RangeBarData {
  bars: RangeBar[];
  volumeProfile: RangeBarVP | null;
  sessionProfile: RangeBarVP | null;
  legProfile: RangeBarVP | null;
  vwap: number;
  cumulativeDelta: number;
  tripleA: TripleAPattern;
  rangeSize: number;
}
```

#### App State & Misc

```typescript
interface AppState {
  config: ChartConfig;
  instruments: Map<string, InstrumentState>;
  activeSymbol: string;
  isScanning: boolean;
  chartMode: ChartMode;
}

interface AggressivePrint {
  price: number;
  time: string;
  side: string;
  volume: number;
  delta: number;
}

interface ModelWeights {
  trend: number;
  momentum: number;
  delta: number;
  orderBook: number;
  volatility: number;
}

interface LLMHistoryEntry {
  timestamp: string;
  direction: string;
  confidence: number;
  rationale: string;
  inputPrompt: string;
  rawOutput: string;
}

type MessageRole = 'USER' | 'ASSISTANT' | 'SYSTEM';

interface ChatMessage {
  id: string;
  role: MessageRole;
  text: string;
}

interface AICommandResponse {
  message: string;
  configUpdates: Record<string, any>;
  action: string;
}
```

### 5.2 RL Types (`types_rl.ts` — 14 lines)

```typescript
interface RLTrainingStatus {
  state: 'idle' | 'training' | 'done' | 'error';
  modelLoaded: boolean;
  timestepsDone: number;
  totalTimesteps: number;
  episodeCount: number;
  meanReward: number;
  meanSharpe: number;
  totalTrades: number;
  elapsedSeconds: number;
  error: string | null;
  modelPath: string | null;
}
```

---

## 6. Central Data Hook — useServerTradingSystem

**File**: `hooks/useServerTradingSystem.ts` (626 lines)

The single most important piece of the frontend. All data flows through this hook.

### 6.1 WebSocket Connection

```
Mount → Detect ws/wss based on page protocol
    │
    ├── Connect to ws://hostname:9090/api/trading/ws/gameloop
    ├── On open: send { subscribe: activeSymbol }
    ├── On message: parse JSON, dispatch to handlers
    └── On close: exponential backoff reconnect
        ├── Attempt 1: 500ms delay
        ├── Attempt 2: 1000ms delay
        ├── Attempt 3: 2000ms delay
        └── Max delay: 5000ms
```

### 6.2 Heartbeat Mechanism

```
Ping every 15 seconds
    │
    ├── Send { type: 'ping' }
    ├── Expect { type: 'pong' } within 45 seconds
    └── If no pong → connection dead → force reconnect
```

### 6.3 Message Handlers

| Message Type | Handler Action |
|-------------|----------------|
| `server_mode` | Multi-symbol initialization — sets up all instruments at once |
| `history_loaded` | Marks history as loaded for a symbol |
| `delta` | Compressed state update — merges only changed fields |
| `full` | Full state snapshot — replaces entire instrument state |
| `tick` | High-frequency tick — dispatched via EventBus (no React render) |
| `footprint` | Footprint data update — dispatched via EventBus |
| `pong` | Heartbeat acknowledgment |
| `symbol_switched` | Confirms symbol change |
| `stale` | Marks instrument as stale |
| `error` | Logs error, updates connection status |

### 6.4 RAF-Batched State Updates

```
WebSocket Message Received
    │
    ▼
Queue message in pendingUpdates[]
    │
    ▼
requestAnimationFrame scheduled? (flag check)
    │
    ├── Yes → skip (already scheduled)
    └── No → schedule rAF
             │
             ▼
        rAF callback fires
             │
             ▼
        Process all pendingUpdates[]
             │
             ├── Merge delta updates into instrument state
             │   └── Only changed fields are merged (not full replace)
             ├── Update generation counter
             └── Single setState call for all accumulated changes
```

**Why this matters**: Without RAF batching, 60+ WebSocket messages/sec would trigger 60+ React renders. With batching, all messages between animation frames are merged into a single render.

### 6.5 EventBus (TickBus)

```
EventTarget-based pub/sub system
    │
    ├── dispatchTickEvent(tick) — fires CustomEvent('tick', { detail: tick })
    ├── dispatchFootprintEvent(data) — fires CustomEvent('footprint', { detail: data })
    └── ChartScene subscribes via addEventListener for zero-render updates
```

**Purpose**: High-frequency tick data updates the chart directly via TradingView's native `update()` API, completely bypassing React's render cycle.

### 6.6 Delta Compression

```
Backend sends: { type: 'delta', symbol: 'NIFTY', changes: { ltp: 22150, pnl: 500 } }
    │
    ▼
Frontend merges:
    const existing = instruments.get(symbol);
    const updated = { ...existing, ...changes, generation: changes.generation };
    instruments.set(symbol, updated);
```

Only changed fields are transmitted and merged. The `generation` counter ensures ordering — stale deltas (lower generation) are ignored.

### 6.7 Symbol Subscription

```
setActiveSymbol(newSymbol)
    │
    ├── Debounce: 80ms delay
    ├── Clear previous debounce timer
    ├── Send { subscribe: newSymbol } via WebSocket
    └── Update activeSymbol state
```

Debouncing prevents rapid symbol switching from overwhelming the backend.

### 6.8 Backend Config Fetch

```
Mount → Fetch /api/system/config
    │
    ├── Retry with exponential backoff on failure
    ├── Parse response into ChartConfig
    └── Update config state
```

### 6.9 LLM History Load

```
Mount → Fetch /api/ai/history
    │
    ├── Parse response into LLMHistoryEntry[]
    └── Attach to active instrument's llmHistory
```

### 6.10 Return Values

```typescript
return {
  instruments: Map<string, InstrumentState>,  // All instrument states
  activeSymbol: string,                        // Currently viewed symbol
  setActiveSymbol: (symbol: string) => void,   // Switch symbol
  activeInstrument: InstrumentState | null,    // Current instrument state
  activeFootprint: FootprintCandle[] | null,   // Current footprint data
  connected: boolean,                          // WebSocket connected?
  connectionStatus: string,                    // Detailed status
  tickBus: EventTarget,                        // EventBus for zero-render updates
};
```

---

## 7. Chart Architecture — ChartScene

**File**: `components/ChartScene.tsx` (1488 lines)

The most complex component. Renders TradingView lightweight-charts with extensive canvas overlay visualizations.

### 7.1 Chart Initialization

```
useEffect on mount
    │
    ├── Create chart: createChart(container, options)
    ├── Add candlestick series: chart.addCandlestickSeries()
    │   └── bullColor/bearColor from config
    ├── Add prediction series (purple candles): chart.addCandlestickSeries()
    ├── Add volume histogram: chart.addHistogramSeries()
    │   └── Positioned at bottom 20% of chart
    ├── Add ResizeObserver for responsive sizing
    └── Cleanup: chart.remove() on unmount
```

### 7.2 Three Chart Modes

| Mode | Rendering | Overlay |
|------|-----------|---------|
| **STANDARD** | Normal candlesticks + prediction candles + volume | Volume profile bars, aggressive bubbles, price lines |
| **FOOTPRINT** | Invisible candles (placeholder) | Full canvas overlay: bid/ask volume bars, imbalances, stacked imbalances, POC highlights, delta cards, CVD line |
| **RANGE** | Range bars (price-movement-based) | Volume profile, VWAP line, Triple-A pattern markers, POC/VAH/VAL lines |

### 7.3 Canvas Overlay Drawing Functions

#### `drawFootprint()` — Orderflow Footprint
```
For each visible candle:
    │
    ├── Draw bid volume bars (left side, green)
    ├── Draw ask volume bars (right side, red)
    ├── Highlight imbalances (bold border on dominant side)
    ├── Highlight stacked imbalances (3+ consecutive imbalances)
    ├── Mark POC level (bright dot)
    ├── Draw delta card (net delta below candle)
    └── Draw CVD line in summary area
```

#### `drawVolumeProfile()` — Volume Profile
```
Session Profile (full lookback):
    │
    ├── Draw horizontal bars on right side
    ├── Color by zone:
    │   ├── Value Area (70%): semi-transparent
    │   ├── Above VAH: muted
    │   └── Below VAL: muted
    ├── Mark POC (bright line)
    ├── Mark VAH/VAL (dashed lines)
    └── Color HVN/LVN zones differently

Leg Profile (since last aggression):
    └── Same as session but with different color palette
```

#### `drawAggressiveBubbles()` — Fabio Valentini Style Volume Bubbles
```
For each aggressive print:
    │
    ├── Calculate bubble radius: log(volume) * scale
    ├── Draw circle at price level
    ├── Color by side: green (buy) / red (sell)
    ├── Add glassy gradient effect
    └── Show volume label inside bubble
```

#### `drawRangeBars()` — Range Bar Visualization
```
For each range bar:
    │
    ├── Draw OHLC bar
    ├── Draw VWAP line across bars
    ├── Draw POC/VAH/VAL lines from volume profile
    ├── Mark Triple-A pattern phases (A1/A2/A3)
    └── Color bars by direction
```

#### `drawProfileBars()` — Generic VP Bar Drawing
```
For each volume profile level:
    │
    ├── Calculate bar width: volume / maxVolume * maxWidth
    ├── Draw horizontal bar at price level
    ├── Color by zone (VA, above, below)
    ├── Apply glassy gradient
    └── Add buy/sell volume split
```

### 7.4 Real-Time Updates

```
Two update paths:

1. React State Updates (low-frequency):
   WebSocket → RAF batch → setState → React re-render → Chart data update
   ├── Candlestick series.setData()
   ├── Volume series.setData()
   └── Prediction series.setData()

2. EventBus Updates (high-frequency, zero-render):
   WebSocket → tickBus.dispatchEvent() → ChartScene event listener
   └── candlestickSeries.update(latestCandle)  // Native TV API
   └── volumeSeries.update(latestVolume)
```

**Stale Tick Protection**: All EventBus handlers wrapped in try-catch to prevent chart crashes from malformed data.

### 7.5 Price Lines

```
AMT Levels:
    ├── POC (solid yellow line)
    ├── VAH (dashed green line)
    ├── VAL (dashed red line)
    ├── HVN markers
    ├── LVN markers
    ├── Leg POC/VAH/VAL
    └── Prior day levels

Position Lines:
    ├── Entry price (blue line)
    ├── Stop loss (red line)
    └── Take profit (green line)

Signal Markers:
    ├── Entry arrows (green up / red down)
    └── Exit markers
```

### 7.6 Performance Optimization

```
React.memo with custom comparator:
    function chartSceneAreEqual(prev, next) {
        return (
            prev.symbol === next.symbol &&
            prev.chartMode === next.chartMode &&
            prev.isHidden === next.isHidden &&
            prev.data === next.data &&              // Reference equality
            prev.positions === next.positions &&     // Reference equality
            prev.amtAnalysis === next.amtAnalysis    // Stabilized reference
        );
    }

useMemo for stable references:
    ├── Stabilized amtAnalysis (prevents overlay redraws)
    ├── Stabilized positions array
    └── Stabilized footprint data

EventBus for high-frequency:
    └── Tick updates bypass React entirely
```

---

## 8. AI Analysis Panel — Intelligence Dashboard

**File**: `components/AIAnalysisPanel.tsx` (1020 lines)

The "Fabio Playbook" execution engine display. 320px wide right sidebar.

### 8.1 Panel Sections (Top to Bottom)

| Section | Content |
|---------|---------|
| **Header** | "Intelligence" title, toggle button |
| **Engine Bar** | Armed status, target vs circuit breaker progress bar |
| **Equity Panel** | Equity, open PnL, session P&L, progress bar (target: 20K, CB: -10K), partial TP info |
| **Risk State** | Trading halt warnings, consecutive loss counter |
| **Session & Leg State** | Session phase badge, leg state badge |
| **Location** | Interactive bar showing VAH/VAL/POC/LTP relative positions |
| **Volume Aggression** | Score with progress bar |
| **Market Metrics** | OFI, CVD slope, balance ratio, profile shape, spread, depth |
| **Market Structure** | Donut chart with 5-state classifier + confidence |
| **Initial Balance** | IB high/low, break detection status |
| **LVN Velocity Play** | LVN play detection result |
| **VWAP + Context** | VWAP value, sigma deviation meter |
| **Probability Engine** | Direction, probability, timing, size, regime (4-agent cascade output) |
| **Overseer Actions** | Current overseer action + reason |
| **Trade Plan** | Open positions with SL/TP/R-multiple |
| **Recent Closed Trades** | Last 5 closed trades with PnL |
| **Rule Checklist** | 4 rules with pass/fail status |
| **Model I/O** | Expandable section showing raw LLM prompt and output |
| **LLM Decision History** | Timeline of past LLM decisions with direction, confidence, rationale |

### 8.2 Sub-Components (`components/ai/`)

#### EquityPanel (75 lines)
```
Props: portfolio (Portfolio)
    │
    ├── Equity: balance + unrealized PnL
    ├── Session P&L: progress bar
    │   ├── Target: 20K (green zone)
    │   └── Circuit Breaker: -10K (red zone)
    ├── Partial TP info
    └── Memoized with React.memo
```

#### RiskStateDisplay (36 lines)
```
Props: riskState (RiskState | null)
    │
    ├── If halted: show halt reason warning
    ├── Show consecutive loss counter
    └── Memoized with React.memo
```

#### ModelIOPanel (35 lines)
```
Props: genAIAnalysis (GenAIAnalysis | null)
    │
    ├── Show raw LLM prompt (inputPrompt)
    ├── Show model output (rawOutput)
    └── Memoized with React.memo
```

#### DecisionHistoryPanel (97 lines)
```
Props: llmHistory (LLMHistoryEntry[])
    │
    ├── Timeline of past decisions
    ├── Each entry: direction, confidence, rationale, timestamp
    ├── Error state detection: 3+ consecutive errors → warning
    └── Memoized with React.memo
```

#### LiveOpportunityCard (93 lines)
```
Props: instruments (Map<string, InstrumentState>)
    │
    ├── Find best ENTER_NOW signal across all instruments
    ├── Show symbol, direction, probability
    ├── Show estimated SL/TP
    └── "View Chart" button to switch to that symbol
```

---

## 9. Market Sidebar — Scanner

**File**: `components/MarketSidebar.tsx` (351 lines)

360px wide left panel. Market scanner with symbol cards.

### 9.1 Symbol Card (`React.memo`)

```
Props: symbol, state, isActive, onClick
    │
    ├── Symbol name (bold)
    ├── Mode badge: BALANCED / PROBING / TRENDING / BREAKING / DEAD
    ├── Action timing: ENTER_NOW / MONITOR / SKIP
    ├── Probability bar (visual progress bar)
    ├── LTP (last traded price)
    ├── Change % (green/red)
    └── Click → setActiveSymbol(symbol)
```

### 9.2 Filtering & Sorting

```
Text Search:
    └── Filter symbols by name substring

Dropdown Filters:
    ├── Filter by mode (BALANCED, PROBING, etc.)
    └── Filter by action (ENTER_NOW, MONITOR, SKIP)

Sorting:
    ├── By action priority (ENTER_NOW first)
    └── By probability (highest first)
```

### 9.3 Dead Market Detection

```
If marketState === 'NO_TRADE' or 'DEAD':
    ├── Dim the symbol card
    ├── Show "DEAD" badge
    └── Reduce opacity
```

### 9.4 Trade History Section

```
Bottom section of sidebar:
    └── Shows recent trade history for active symbol
        ├── Entry/exit pairs
        ├── PnL
        └── Exit reasons
```

---

## 10. Journal Page

**File**: `components/JournalPage.tsx` (376 lines)

Full-screen trade journal page, accessible via journal button in App.tsx.

### 10.1 Layout

```
┌─────────────────────────────────────────────────────────────┐
│  Journal Header                                             │
│  ├── Date navigation (< prev day | current date | next day >)│
│  └── Day shift buttons (-5, -1, +1, +5 days)                │
├─────────────────────────────────────────────────────────────┤
│  Summary Cards                                              │
│  ├── Signals | Entries | Rejections | Exits                 │
│  ├── Wins | Losses | Win Rate | Total PnL                   │
├─────────────────────────────────────────────────────────────┤
│  Tabs: [Trades] [Events]                                    │
│                                                             │
│  Trades Tab:                                                │
│  ├── Entry/exit pairs with PnL                              │
│  ├── Exit reasons (color-coded)                             │
│  └── Duration, R-multiple                                   │
│                                                             │
│  Events Tab:                                                │
│  ├── Filterable event table                                 │
│  ├── Event types: SIGNAL, ENTRY, EXIT, OVERSEER, etc.       │
│  ├── Hide flat signals toggle                               │
│  └── Timestamp, symbol, details                             │
└─────────────────────────────────────────────────────────────┘
```

### 10.2 API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /api/ai/journal/trades` | Completed trades (entry+exit pairs) |
| `GET /api/ai/journal` | All journal entries for date/run |
| `GET /api/ai/journal/summary` | Trade summary statistics |

### 10.3 Sub-Components

```
StatCard: Reusable stat display (label, value, color)
TradesTable: Sortable table of completed trades
EventsTable: Filterable table of all events
```

---

## 11. System Status Bar

**File**: `components/SystemStatusBar.tsx` (148 lines)

### 11.1 Connection Status

```
Connection Dots:
    ├── Feed (WebSocket market data)
    ├── LLM (LLM inference readiness)
    ├── Models (ML model loaded)
    └── Market (Market open/closed)
```

Each dot: green (connected) / yellow (degraded) / red (disconnected).

### 11.2 Trading Mode Badge

```
LIVE (green) / SIM (yellow)
```

### 11.3 Circuit Breaker Warning

```
If riskState.halted:
    └── Red warning banner with halt reason
```

### 11.4 Phase Timer (`usePhaseTimer` hook)

```
Indian market session phases:
    ├── Pre-market (09:00 - 09:15)
    ├── Phase 1 (09:15 - 10:00) — Opening
    ├── Phase 2 (10:00 - 12:00) — Morning
    ├── Phase 3 (12:00 - 14:00) — Midday
    ├── Phase 4 (14:00 - 15:15) — Closing
    ├── Phase 5 (15:15 - 15:30) — Post-market
    └── Closed (after 15:30)

Progress bar: 09:15 to 15:30
```

---

## 12. AI Controls — Natural Language Commands

**File**: `components/AIControls.tsx` (149 lines)

### 12.1 Chat Interface

```
Text Input:
    ├── Placeholder: "Command the system..."
    ├── Send button
    └── Enter key submits

Chat History:
    ├── User messages (right-aligned, blue)
    ├── Bot responses (left-aligned, gray)
    └── Auto-scroll to bottom
```

### 12.2 Command Processing

```
User types command → POST /api/ai/command
    │
    ├── Response: AICommandResponse { message, configUpdates, action }
    ├── Apply configUpdates to ChartConfig
    └── Display bot response message
```

### 12.3 Supported Commands (Keyword Maps)

| Category | Keywords | Action |
|----------|----------|--------|
| Symbol | "switch to", "show", "view" + symbol name | Change active symbol |
| Interval | "1m", "5m", "15m", "1h" | Change chart interval |
| Color | "bull", "bear", "color" | Change chart colors |
| Toggle | "volume profile", "predictions", "footprint" | Toggle chart features |

### 12.4 API Key Warning

```
If no API key configured:
    └── Show warning overlay before sending commands
```

---

## 13. WebSocket Protocol

### 13.1 Connection Details

```
URL: ws://hostname:9090/api/trading/ws/gameloop
Protocol: Auto-detects ws vs wss based on page protocol
Reconnection: Exponential backoff (500ms * 2^n, max 5s)
Heartbeat: Ping every 15s, 45s timeout
Cleanup: Close code 1000 on unmount
```

### 13.2 Message Formats

#### Subscribe (Client → Server)
```json
{ "subscribe": "NIFTY" }
```

#### Ping (Client → Server)
```json
{ "type": "ping" }
```

#### Server Mode (Server → Client)
```json
{
  "type": "server_mode",
  "instruments": { "NIFTY": {...}, "BANKNIFTY": {...} }
}
```

#### Delta Update (Server → Client)
```json
{
  "type": "delta",
  "symbol": "NIFTY",
  "changes": { "ltp": 22150, "pnl": 500, "generation": 42 }
}
```

#### Full State (Server → Client)
```json
{
  "type": "full",
  "symbol": "NIFTY",
  "state": { ...complete InstrumentState... }
}
```

#### Tick (Server → Client)
```json
{
  "type": "tick",
  "symbol": "NIFTY",
  "tick": { "ltp": 22150, "volume": 100, "timestamp": "..." }
}
```

#### Pong (Server → Client)
```json
{ "type": "pong" }
```

### 13.3 Vite Proxy Configuration

```typescript
// vite.config.ts
server: {
  port: 5190,
  host: '0.0.0.0',
  proxy: {
    '/api': {
      target: 'http://127.0.0.1:9090',
      ws: true,
    },
  },
}
```

**Important**: The WebSocket connection bypasses the Vite proxy and connects directly to port 9090. REST API calls go through the proxy.

---

## 14. Performance Architecture

### 14.1 Render Optimization Strategy

```
┌─────────────────────────────────────────────────────────────┐
│                    DATA FLOW                                 │
│                                                             │
│  WebSocket (60 msg/sec)                                     │
│       │                                                     │
│       ├──→ EventBus (EventTarget) → ChartScene (zero-render)│
│       │                                                     │
│       └──→ RAF Queue → requestAnimationFrame                │
│                        │                                    │
│                        ▼                                    │
│                   setState (1 render/frame)                  │
│                        │                                    │
│                        ▼                                    │
│              React.memo comparators                          │
│              ┌──────────┬──────────┬──────────┐             │
│              │ Chart-   │ Market-  │ AI-      │             │
│              │ Scene    │ Sidebar  │ Panel    │             │
│              │ (custom) │ (custom) │ (custom) │             │
│              └──────────┴──────────┴──────────┘             │
└─────────────────────────────────────────────────────────────┘
```

### 14.2 Optimization Techniques

| Technique | Where Used | Effect |
|-----------|------------|--------|
| **EventBus (EventTarget)** | Tick data → ChartScene | 0 React renders for high-frequency ticks |
| **RAF Batching** | All WebSocket state updates | 60+ messages → 1 render per frame (~16ms) |
| **React.memo + custom comparator** | ChartScene, SymbolCard, AIAnalysisPanel | Skip render if props unchanged by reference |
| **useMemo** | Derived state throughout | Prevent recalculation on unrelated state changes |
| **Stabilized references** | amtAnalysis, positions, footprint | Prevent overlay redraws from new object references |
| **Debounced symbol switching** | setActiveSymbol (80ms) | Prevent rapid switching from overwhelming backend |
| **Generation counter** | Delta updates | Ignore stale deltas (race condition prevention) |
| **isHidden CSS toggle** | 3 ChartScene instances | Keep chart state alive when switching modes |
| **try-catch on EventBus** | ChartScene tick handlers | Prevent chart crashes from malformed data |

### 14.3 Memory Management

```
Cleanup on unmount:
    ├── WebSocket.close(1000)
    ├── ResizeObserver.disconnect()
    ├── Chart.remove()
    ├── EventBus listeners removed
    └── Debounce timers cleared
```

---

## 15. UI Component Library

### 15.1 Reusable Components

#### GlassPanel (32 lines)
```tsx
<GlassPanel className="..." onClick={() => {}}>
  {children}
</GlassPanel>
```

Glassmorphic container with:
- `backdrop-blur-xl`
- Gradient overlay
- Rounded borders
- Configurable opacity via `glassOpacity` from config

#### ErrorBoundary (59 lines)
```
Class component error boundary:
    ├── Catches render errors in child components
    ├── Retry logic (max 3 retries)
    ├── Error display with message
    └── Reset on retry
```

### 15.2 Deprecated Components

| Component | Status |
|-----------|--------|
| `VolumeAccessory.tsx` | Returns null |
| `AIAgentAvatar.tsx` | Returns null |

---

## 16. Build & Configuration

### 16.1 Vite Config (`vite.config.ts`)

```typescript
export default defineConfig({
  plugins: [tailwindcss(), react()],
  server: {
    port: 5190,
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:9090',
        ws: true,
      },
    },
  },
  resolve: {
    alias: { '@': path.resolve(__dirname, './') },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/setup.ts'],
    coverage: { provider: 'v8' },
  },
});
```

### 16.2 TypeScript Config (`tsconfig.json`)

```json
{
  "extends": "expo/tsconfig.base",
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "jsx": "react-jsx",
    "moduleResolution": "bundler",
    "paths": { "@/*": ["./*"] }
  }
}
```

### 16.3 HTML Template (`index.html`)

- Mounts to `<div id="root">`
- Loads `/index.tsx` as ES module
- Uses Inter font from Google Fonts
- Base background: `#0f172a` (slate-900)

### 16.4 CSS (`index.css`)

```css
@import "tailwindcss";
```

Single line — Tailwind v4 directive. All styling is utility-first via Tailwind classes.

---

## 17. Test Suite

### 17.1 Test Setup (`tests/setup.ts`)

Mocks:
- `fetch` — returns empty responses
- `WebSocket` — mock constructor with send/onmessage/onclose
- `ResizeObserver` — mock observe/unobserve
- `matchMedia` — mock for CSS media queries
- Suppresses React console warnings

### 17.2 Unit Tests

#### ChartScene (9 tests)
- Renders without crashing
- Renders container element
- Handles empty data
- Handles hidden mode
- Standard mode indicator
- Footprint mode indicator
- Renders with positions
- Renders with symbol
- Canvas overlay present

#### GlassPanel (6 tests)
- Renders children
- Custom className applied
- Default glass styling
- Click events work
- Multiple children
- Transition classes

#### MarketSidebar (12 tests)
- Renders header
- Symbol count display
- Filter input present
- Filtering works
- Symbol selection triggers callback
- Live feed status display
- Scanning count display
- Trade history section
- Empty state handling
- Loading state display
- Symbol name display
- Button presence

### 17.3 Hook Tests

#### useServerTradingSystem (7 tests)
- Initializes with empty state
- Starts in disconnected state
- Empty connection status
- tickBus exists
- Setting active symbol works
- Default portfolio structure
- All return properties present

### 17.4 Integration Tests

#### Trading Flow (6 tests)
- Renders both ChartScene and MarketSidebar together
- Symbol selection updates ChartScene
- Correct instrument data display
- Filter state maintenance
- Live feed status propagation
- Mode switching (STANDARD/FOOTPRINT)

### 17.5 Test Summary

| Category | Count | Coverage |
|----------|-------|----------|
| Unit (components) | 27 | ChartScene, GlassPanel, MarketSidebar |
| Hook | 7 | useServerTradingSystem |
| Integration | 6 | Trading flow |
| **Total** | **43** | |

---

## 18. Complete Flow Diagrams

### 18.1 Application Startup Flow

```
Browser loads index.html
    │
    ▼
index.tsx → ReactDOM.createRoot(<App />)
    │
    ▼
App.tsx mounts
    │
    ├── useServerTradingSystem(config) hook
    │   ├── Fetch /api/system/config (retry with backoff)
    │   ├── Fetch /api/ai/history
    │   └── Connect WebSocket → ws://backend:9090/api/trading/ws/gameloop
    │       ├── On open: send { subscribe: activeSymbol }
    │       ├── Start heartbeat (ping every 15s)
    │       └── Start message handler
    │
    ├── Render layout:
    │   ├── MarketSidebar (left, 360px)
    │   ├── ChartScene x3 (center, flex) — STANDARD/FOOTPRINT/RANGE
    │   └── AIAnalysisPanel (right, 320px)
    │
    └── Render SystemStatusBar (top)
```

### 18.2 Real-Time Update Flow

```
Backend emits state snapshot
    │
    ▼
WebSocket message sent to frontend
    │
    ├── Message type: 'delta' or 'full'
    │
    ├── 'delta' path:
    │   ├── Parse changes object
    │   ├── Merge into existing instrument state
    │   ├── Queue in pendingUpdates[]
    │   └── Schedule rAF (if not already scheduled)
    │
    ├── 'full' path:
    │   ├── Replace entire instrument state
    │   ├── Queue in pendingUpdates[]
    │   └── Schedule rAF
    │
    ├── 'tick' path:
    │   └── Dispatch via EventBus (no React render)
    │       └── ChartScene event listener → native TV update()
    │
    ▼
rAF callback fires (~16ms)
    │
    ▼
Process all pendingUpdates[]
    │
    ├── Merge all deltas
    ├── Update generation counter
    └── Single setState call
        │
        ▼
    React re-render
        │
        ├── MarketSidebar (memo — skip if symbols unchanged)
        ├── AIAnalysisPanel (memo — skip if data unchanged)
        └── ChartScene (memo — skip if data unchanged)
```

### 18.3 Symbol Switch Flow

```
User clicks symbol in MarketSidebar
    │
    ▼
setActiveSymbol(newSymbol) called
    │
    ├── Clear previous debounce timer
    ├── Start 80ms debounce timer
    │   └── After 80ms:
    │       ├── Update activeSymbol state
    │       ├── Send { subscribe: newSymbol } via WebSocket
    │       └── Backend switches symbol stream
    │
    ▼
Backend sends history + current state
    │
    ├── 'history_loaded' message
    ├── 'full' state message
    └── ChartScene updates with new data
```

### 18.4 Chart Mode Switch Flow

```
User clicks mode toggle (STANDARD/FOOTPRINT/RANGE)
    │
    ▼
setChartMode(newMode) called
    │
    ├── Update chartMode state
    │
    ▼
App.tsx re-renders
    │
    ├── All 3 ChartScene instances exist (always mounted)
    ├── Active mode: isHidden=false (visible)
    └── Other modes: isHidden=true (CSS display:none)
        │
        └── Chart state preserved (no re-initialization)
```

---

## 19. Component Interaction Map

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                                    App.tsx                                          │
│                                                                                     │
│  State: config, chartMode, showControls, sidebarOpen, rightSidebarOpen,             │
│         currentPage, overseerPos                                                    │
│                                                                                     │
│  Hook: useServerTradingSystem(config)                                               │
│        ├── WebSocket connection                                                     │
│        ├── EventBus (tickBus)                                                       │
│        ├── RAF-batched state updates                                                │
│        └── Returns: instruments, activeSymbol, activeInstrument, connected, etc.    │
└──────┬──────────────────────────┬──────────────────────────┬────────────────────────┘
       │                          │                          │
       ▼                          ▼                          ▼
┌──────────────┐      ┌──────────────────────┐      ┌──────────────────┐
│ Market-      │      │    ChartScene x3     │      │ AIAnalysis-      │
│ Sidebar      │      │    (STANDARD/        │      │ Panel            │
│ (351L)       │      │     FOOTPRINT/       │      │ (1020L)          │
│              │      │     RANGE)           │      │                  │
│ Symbol cards │─────▶│ (1488L)              │◀─────│ Intelligence     │
│ with:        │      │                      │      │ dashboard        │
│ - LTP        │      │ TradingView charts   │      │ - Equity/Risk    │
│ - Mode       │      │ Canvas overlays:     │      │ - Session/Leg    │
│ - Action     │      │ - Footprint          │      │ - Market metrics │
│ - Probability│      │ - Volume Profile     │      │ - Probability    │
│ - Change %   │      │ - Bubbles            │      │ - Trade plan     │
│              │      │ - Range Bars         │      │ - Decision hist  │
│ Filters:     │      │                      │      │                  │
│ - Text       │      │ EventBus:            │      │ Sub-components:  │
│ - Mode       │      │ - Zero-render ticks  │      │ - EquityPanel    │
│ - Action     │      │ - Native TV update() │      │ - RiskState      │
│              │      │                      │      │ - ModelIO        │
│ Trade history│      │ Price lines:         │      │ - DecisionHist   │
│ for active   │      │ - SL/TP/Entry        │      │ - LiveOppCard    │
│ symbol       │      │ - AMT levels         │      │                  │
└──────────────┘      └──────────────────────┘      └──────────────────┘
       │                          │                          │
       │                          │                          │
       ▼                          ▼                          ▼
┌──────────────┐      ┌──────────────────────┐      ┌──────────────────┐
│ SystemStatus │      │   JournalPage        │      │ AIControls       │
│ Bar (148L)   │      │   (376L)             │      │ (149L)           │
│              │      │                      │      │                  │
│ - Conn dots  │      │ - Date navigation    │      │ - Chat interface │
│ - Mode badge │      │ - Summary cards      │      │ - NLP commands   │
│ - CB warning │      │ - Trades/Events tabs │      │ - Config updates │
│ - Phase timer│      │ - Event filtering    │      │ - API key warn   │
└──────────────┘      └──────────────────────┘      └──────────────────┘
```

---

## 20. Known Limitations & Technical Debt

### 20.1 Architectural Limitations

| Issue | Impact | Recommendation |
|-------|--------|----------------|
| No external state management | Prop drilling through 3+ levels for some data | Consider Zustand/Jotai for shared state |
| No React Context | All data flows via props from App.tsx | Add Context for config, connection status |
| Empty `services/` directory | All API logic in one hook (626 lines) | Split into separate service modules |
| Direct WebSocket URL | Bypasses Vite proxy, hardcodes port 9090 | Use environment variable for backend URL |
| Deprecated components | `VolumeAccessory.tsx`, `AIAgentAvatar.tsx` return null | Remove dead code |

### 20.2 Performance Risks

| Risk | Current Mitigation | Residual Risk |
|------|-------------------|---------------|
| Large instrument state objects | RAF batching + memo | Full state snapshots still cause deep comparisons |
| Canvas overlay redraws | Stabilized references | Complex overlays (footprint) still expensive |
| WebSocket message backlog | RAF batching | Burst of 100+ messages could still cause frame drops |
| Memory leaks in chart | Cleanup on unmount | ChartScene re-mounts on error may leak |

### 20.3 Missing Functionality

| Feature | Status | Effort |
|---------|--------|--------|
| Dark/light theme toggle | Not implemented | 2-3 hours |
| Mobile responsive layout | Partial (Expo RN web) | 1-2 days |
| Keyboard shortcuts | Not implemented | 4-6 hours |
| Multi-chart layout | Not implemented (single chart) | 1-2 days |
| Drawing tools | Not implemented | 2-3 days |
| Export chart as image | Not implemented | 2-4 hours |
| Real-time PnL chart | Not implemented | 4-6 hours |
| Alert notifications | Not implemented | 1-2 days |

### 20.4 Testing Gaps

| Area | Current Coverage | Missing |
|------|-----------------|---------|
| ChartScene | 9 unit tests | Footprint rendering, range bars, EventBus integration |
| AIAnalysisPanel | 0 tests | All sub-components untested |
| JournalPage | 0 tests | Date navigation, filtering, API integration |
| SystemStatusBar | 0 tests | Phase timer, connection status |
| AIControls | 0 tests | Command parsing, config updates |
| useServerTradingSystem | 7 tests | Reconnection logic, delta merge, heartbeat |
| Integration | 6 tests | Full trading flow with real WebSocket |

---

*Analysis completed: 2026-03-31*
*Files analyzed: 25+ frontend files*
*Lines analyzed: ~5,500+*
*Sections: 20*
