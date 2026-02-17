# GlassyTrade AI - Technical Documentation

## 1. Project Overview
**GlassyTrade AI** is a React-based financial visualization and trading simulation platform. It features a "Dual-Engine" architecture:
1.  **Theorist Engine (AMT):** Analyzes market structure using Auction Market Theory (Volume Profile, POC, VWAP).
2.  **Quant Engine (AI):** A self-learning prediction model that adjusts its weighting based on historical trade outcomes.

**Current State:** The visualization has been migrated from 3D (Three.js) to High-Performance 2D (Lightweight Charts) for better accuracy and performance, while retaining the "Glassmorphism" UI aesthetic.

---

## 2. Technology Stack & Dependencies

The project uses **ES Modules** via CDN (Import Maps) to run without a local bundler like Webpack or Vite.

### Core Framework
*   **React:** `^19.2.0`
*   **React DOM:** `^19.2.0`
*   **Language:** TypeScript (TSX)

### Visualization
*   **Library:** `lightweight-charts`
*   **Version:** `4.1.1`
*   **Source:** `esm.sh` (Crucial: Used to resolve the internal `fancy-canvas` dependency automatically).
*   **Render Mode:** Canvas 2D

### Artificial Intelligence
*   **Fine-tuned LLM:** Nanbeige 3B + LoRA via MLX (Apple Silicon inference).
*   **LangChain:** Structured output for overseer decisions.

### Utilities
*   **UUID:** `^13.0.0` (For unique trade/position IDs).
*   **Icons:** `lucide-react` (`^0.555.0`).

### Styling
*   **CSS Framework:** Tailwind CSS (via CDN Script).
*   **Font:** 'Inter' (Google Fonts).
*   **Theme:** Dark Mode (Background: Slate 900 `#0f172a`).

### Deprecated / Stubbed Libraries
*   `three`, `@react-three/fiber`, `@react-three/drei` are currently present in the import map but are **unused** in the active codebase following the 2D migration.

---

## 3. Configuration & Settings

### Import Map (index.html)
```json
{
  "imports": {
    "react": "https://aistudiocdn.com/react@^19.2.0",
    "react-dom/": "https://aistudiocdn.com/react-dom@^19.2.0/",
    "lightweight-charts": "https://esm.sh/lightweight-charts@4.1.1",
    "lucide-react": "https://aistudiocdn.com/lucide-react@^0.555.0",
    "uuid": "https://aistudiocdn.com/uuid@^13.0.0"
  }
}
```

### External APIs
1.  **Binance Public Data API:**
    *   REST: `https://api.binance.com/api/v3` (Klines, Depth)
    *   WebSocket: `wss://stream.binance.com:9443/ws` (Real-time Ticker)
2.  **OpenRouter:**
    *   Endpoint: `https://openrouter.ai/api/v1/chat/completions`
    *   Model: `x-ai/grok-4.1-fast:free`

---

## 4. Architecture & Services

The application logic is decoupled from the React View layer.

### A. Trading Engine (`services/tradingEngine.ts`)
*   **Role:** Manages Portfolio, Equity, Position Sizing, and Order Execution.
*   **Logic:**
    *   Executes `TradeSignals`.
    *   Enforces Risk Management (Stop Loss / Take Profit).
    *   Prevents duplicate trades and enforces minimum stop distances.

### B. Learning Engine (`services/learningEngine.ts`)
*   **Role:** Reinforcement Learning for the Quant Model.
*   **Logic:**
    *   Monitors closed `PREDICTION` trades.
    *   **Backpropagation:** If a trade wins, it boosts the weights of the factors (Trend, Momentum, Delta) that aligned with the trade. If it loses, it penalizes them.
    *   **Output:** Dynamic `ModelWeights` passed to the Prediction Service.

### C. AMT Service (`services/amtService.ts`)
*   **Role:** Market Structure Analysis.
*   **Logic:** Calculates Volume Profile, Value Area (VAH/VAL), POC, and Order Flow Aggression.

### D. Prediction Service (`services/predictionService.ts`)
*   **Role:** Generates "Ghost Candles".
*   **Logic:** Uses weighted factors (Trend, RSI, Delta, L2 Book) to project future price action + random walk noise.

---

## 5. UI Structure

*   **App.tsx:** Main Controller. Handles the "Game Loop" (useEffect hooks) that drives data fetching and engine updates.
*   **ChartScene.tsx:** The 2D Rendering canvas.
    *   *Series 1:* Real Price (Candlesticks).
    *   *Series 2:* Volume (Histogram, Overlay).
    *   *Series 3:* Prediction/Ghost (Candlesticks, Purple).
    *   *Primitives:* Price Lines (Entry/SL/TP) and Markers (Arrows).
*   **PredictionPerformancePanel.tsx:** Visualizes the "Neural Weights" and AI confidence.
*   **ModelAnalysisPanel.tsx:** Visualizes the Fabio Playbook (AMT) stats.
*   **AIControls.tsx:** Chat interface for natural language commands.

---

## 6. How to Run
1.  Ensure an internet connection (for CDN and API access).
2.  Open `index.html` via a local server or browser environment supporting ES Modules.
3.  The app defaults to `BTCUSDT` on Binance 5m timeframe.
