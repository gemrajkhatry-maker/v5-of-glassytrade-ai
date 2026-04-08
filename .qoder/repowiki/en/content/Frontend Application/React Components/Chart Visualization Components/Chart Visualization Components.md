# Chart Visualization Components

<cite>
**Referenced Files in This Document**
- [ChartScene.tsx](file://frontend/components/ChartScene.tsx)
- [types.ts](file://frontend/types.ts)
- [App.tsx](file://frontend/App.tsx)
- [constants.ts](file://frontend/constants.ts)
- [useServerTradingSystem.ts](file://frontend/hooks/useServerTradingSystem.ts)
- [ChartScene.test.tsx](file://frontend/tests/components/ChartScene.test.tsx)
- [MarketSidebar.tsx](file://frontend/components/MarketSidebar.tsx)
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
This document provides comprehensive technical documentation for the ChartScene component and related chart visualization functionality. It covers the candlestick chart implementation with support for STANDARD, FOOTPRINT, and RANGE modes, integration with the Lightweight Charts library, canvas overlay rendering for volume profiles and aggressive prints, and real-time tick streaming via WebSocket. It also documents chart configuration options, mode switching, responsive design, performance optimizations including memoization strategies, examples of initialization, data binding, event handling, and custom drawing operations. Finally, it addresses chart lifecycle management, memory cleanup, and error handling patterns.

## Project Structure
The chart visualization is implemented in the frontend directory under components and hooks. The primary chart component is ChartScene, which integrates with a WebSocket-based trading system hook and is embedded within the main App shell alongside a market scanner sidebar.

```mermaid
graph TB
subgraph "Frontend"
App["App.tsx"]
CS["ChartScene.tsx"]
Hook["useServerTradingSystem.ts"]
Types["types.ts"]
Consts["constants.ts"]
MS["MarketSidebar.tsx"]
end
App --> CS
App --> MS
App --> Hook
CS --> Types
Hook --> Types
App --> Consts
```

**Diagram sources**
- [App.tsx:16-395](file://frontend/App.tsx#L16-L395)
- [ChartScene.tsx:1-1514](file://frontend/components/ChartScene.tsx#L1-L1514)
- [useServerTradingSystem.ts:1-655](file://frontend/hooks/useServerTradingSystem.ts#L1-L655)
- [types.ts:1-376](file://frontend/types.ts#L1-L376)
- [constants.ts:1-28](file://frontend/constants.ts#L1-L28)
- [MarketSidebar.tsx:1-388](file://frontend/components/MarketSidebar.tsx#L1-L388)

**Section sources**
- [App.tsx:16-395](file://frontend/App.tsx#L16-L395)
- [ChartScene.tsx:1-1514](file://frontend/components/ChartScene.tsx#L1-L1514)
- [useServerTradingSystem.ts:1-655](file://frontend/hooks/useServerTradingSystem.ts#L1-L655)
- [types.ts:1-376](file://frontend/types.ts#L1-L376)
- [constants.ts:1-28](file://frontend/constants.ts#L1-L28)
- [MarketSidebar.tsx:1-388](file://frontend/components/MarketSidebar.tsx#L1-L388)

## Core Components
- ChartScene: The main chart component that renders candlesticks, overlays, and handles real-time updates. It supports STANDARD, FOOTPRINT, and RANGE modes and integrates with Lightweight Charts and a canvas overlay system.
- useServerTradingSystem: A WebSocket-based hook that streams market data and state updates to the UI without triggering React renders for every tick.
- App: Orchestrates the chart instances, controls, and UI layout, including mode switching and dual volume profile tabs.
- types: Defines data structures for OHLC data, chart configuration, AMT analysis, footprint data, and range bar data.
- constants: Provides default chart configuration values.

Key responsibilities:
- ChartScene manages chart lifecycle, data binding, mode switching, canvas overlays, and real-time tick updates.
- useServerTradingSystem manages WebSocket connectivity, batching updates, and dispatching tick events via an event bus.
- App composes multiple ChartScene instances for concurrent STANDARD, FOOTPRINT, and RANGE views and exposes configuration controls.

**Section sources**
- [ChartScene.tsx:51-1514](file://frontend/components/ChartScene.tsx#L51-L1514)
- [useServerTradingSystem.ts:59-654](file://frontend/hooks/useServerTradingSystem.ts#L59-L654)
- [App.tsx:150-206](file://frontend/App.tsx#L150-L206)
- [types.ts:144-376](file://frontend/types.ts#L144-L376)
- [constants.ts:4-19](file://frontend/constants.ts#L4-L19)

## Architecture Overview
The chart visualization architecture combines Lightweight Charts for native candlestick rendering with a custom canvas overlay for advanced orderflow and profile visualizations. Real-time updates are streamed via WebSocket and delivered through an event bus to avoid unnecessary React re-renders.

```mermaid
sequenceDiagram
participant WS as "WebSocket Server"
participant Hook as "useServerTradingSystem"
participant Bus as "Event Bus"
participant CS as "ChartScene"
participant LC as "Lightweight Charts"
participant Canvas as "Canvas Overlay"
WS->>Hook : "JSON state deltas"
Hook->>Hook : "Batch updates per animation frame"
Hook->>Bus : "dispatchEvent('tick', {symbol, tick})"
Bus-->>CS : "tick event"
CS->>LC : "update candlestick series"
CS->>Canvas : "draw overlays (VP, POC, HVN/LVN, aggressive prints)"
Note over CS,Canvas : "Mode switching and resize handled internally"
```

**Diagram sources**
- [useServerTradingSystem.ts:204-498](file://frontend/hooks/useServerTradingSystem.ts#L204-L498)
- [ChartScene.tsx:278-319](file://frontend/components/ChartScene.tsx#L278-L319)
- [ChartScene.tsx:376-425](file://frontend/components/ChartScene.tsx#L376-L425)

## Detailed Component Analysis

### ChartScene Component
ChartScene is a React component that:
- Initializes Lightweight Charts with candlestick and histogram series.
- Manages three chart modes: STANDARD, FOOTPRINT, and RANGE.
- Renders a canvas overlay for volume profiles, POC levels, HVN/LVN zones, and aggressive prints.
- Handles real-time tick streaming via an event bus.
- Implements responsive design with ResizeObserver and maintains aspect ratios across modes.
- Uses memoization to stabilize references and reduce overlay redraws.

Key implementation patterns:
- Chart initialization and options: creates chart, series, applies grid and layout options, and adjusts price scale margins for FOOTPRINT and RANGE modes.
- Mode switching: toggles series visibility and colors without remounting.
- Data binding: sets historical data for STANDARD mode and range bars for RANGE mode; updates series incrementally for real-time ticks.
- Canvas overlay: draws volume profiles, footprint cells, CVD line, and aggressive bubbles with dynamic sizing and color intensity.
- Responsive behavior: observes container size changes and updates chart and overlay dimensions.
- Lifecycle: cleans up observers and removes the chart on unmount.

Performance optimizations:
- Memoization of AMT analysis to avoid overlay redraws when only reference identity changes.
- Stabilizing data references to prevent overlay redraws on intra-candle tick updates.
- RAF batching for overlay redraws triggered by pan/zoom events.
- Efficient coordinate conversions using Lightweight Charts APIs.

Error handling:
- Try/catch around tick updates to prevent crashes from stale or out-of-order timestamps.
- Graceful handling of missing overlay contexts and hidden states.

Examples:
- Initialization: [ChartScene.tsx:117-275](file://frontend/components/ChartScene.tsx#L117-L275)
- Real-time tick handling: [ChartScene.tsx:278-319](file://frontend/components/ChartScene.tsx#L278-L319)
- Canvas overlay drawing: [ChartScene.tsx:376-425](file://frontend/components/ChartScene.tsx#L376-L425)
- Volume profile drawing: [ChartScene.tsx:626-652](file://frontend/components/ChartScene.tsx#L626-L652)
- Footprint drawing: [ChartScene.tsx:686-980](file://frontend/components/ChartScene.tsx#L686-L980)
- Aggressive prints drawing: [ChartScene.tsx:429-484](file://frontend/components/ChartScene.tsx#L429-L484)
- Range bars overlay: [ChartScene.tsx:982-1086](file://frontend/components/ChartScene.tsx#L982-L1086)
- Mode switching: [ChartScene.tsx:342-373](file://frontend/components/ChartScene.tsx#L342-L373)
- Responsive resize: [ChartScene.tsx:221-234](file://frontend/components/ChartScene.tsx#L221-L234)

```mermaid
classDiagram
class ChartScene {
+props : ChartSceneProps
+ref : chartContainerRef, overlayRef
+refs : candleSeriesRef, volumeSeriesRef, predictionSeriesRef
+state : initializedRef, activePriceLinesRef, amtLinesRef
+render() : JSX.Element
+drawVolumeProfile()
+drawFootprint()
+drawAggressiveBubbles()
+drawRangeBars()
}
class ChartSceneProps {
+data : OHLCData[]
+predictions : OHLCData[]
+config : ChartConfig
+activeSignal : TradeSignal
+positions : TradePosition[]
+closedTrades : TradePosition[]
+aiAnalysis : AIAnalysis
+amtAnalysis : AMTAnalysis
+mode : ChartMode
+isHidden : boolean
+footprintData : Record<string, FootprintCandle>
+cumulativeDeltas : number[]
+tickBus : EventTarget
+symbol : string
+rangeBarData : RangeBarData
}
ChartScene --> ChartSceneProps : "consumes"
```

**Diagram sources**
- [ChartScene.tsx:18-34](file://frontend/components/ChartScene.tsx#L18-L34)
- [ChartScene.tsx:51-67](file://frontend/components/ChartScene.tsx#L51-L67)

**Section sources**
- [ChartScene.tsx:51-1514](file://frontend/components/ChartScene.tsx#L51-L1514)
- [types.ts:144-301](file://frontend/types.ts#L144-L301)

### Canvas Overlay System
The canvas overlay system enables advanced visualizations:
- Volume Profiles: Draws session and leg profiles on the right side of the chart with directional coloring, alpha blending, and value area shading.
- Footprint: Renders footprint cells with bid/ask bars, imbalance indicators, stacked imbalance borders, and POC highlights within candle bodies.
- Aggressive Prints: Renders bubbles sized by volume with radial gradients and labels.
- CVD Line: Plots cumulative delta within the footprint summary area.
- Range Bars: Draws VWAP, POC, VAH/VAL lines and Triple-A markers on range bar charts.

Drawing helpers:
- drawProfileBars: Core routine for volume profile bars with zone-aware coloring and glassy effects.
- drawVolumeProfile: Switches between session, leg, and combined modes.
- drawFootprint: Renders footprint grid, spine, imbalance bars, and summary statistics.
- drawAggressiveBubbles: Renders volume bubbles with gradient fills and text labels.
- drawRangeBars: Renders range bar overlays including VWAP, POC, VAH/VAL, and Triple-A indicators.

```mermaid
flowchart TD
Start(["Overlay Draw Entry"]) --> ModeCheck{"Mode"}
ModeCheck --> |RANGE| RangeVP["Draw Range Volume Profile"]
ModeCheck --> |RANGE| RangeBars["Draw Range Bars"]
ModeCheck --> |STANDARD| StdVP["Draw Volume Profile"]
ModeCheck --> |STANDARD| AggPrints["Draw Aggressive Bubbles"]
StdVP --> FPCheck{"Footprint Mode?"}
FPCheck --> |Yes| Footprint["Draw Footprint"]
FPCheck --> |No| End
AggPrints --> End
RangeVP --> End
RangeBars --> End
Footprint --> End
```

**Diagram sources**
- [ChartScene.tsx:384-412](file://frontend/components/ChartScene.tsx#L384-L412)
- [ChartScene.tsx:626-652](file://frontend/components/ChartScene.tsx#L626-L652)
- [ChartScene.tsx:654-683](file://frontend/components/ChartScene.tsx#L654-L683)
- [ChartScene.tsx:686-980](file://frontend/components/ChartScene.tsx#L686-L980)
- [ChartScene.tsx:429-484](file://frontend/components/ChartScene.tsx#L429-L484)
- [ChartScene.tsx:982-1086](file://frontend/components/ChartScene.tsx#L982-L1086)

**Section sources**
- [ChartScene.tsx:376-1086](file://frontend/components/ChartScene.tsx#L376-L1086)

### Real-Time Tick Streaming via WebSocket
The WebSocket integration uses a dedicated hook that:
- Establishes a WebSocket connection to the backend trading loop endpoint.
- Batches state updates per animation frame to minimize React renders.
- Dispatches tick events via an EventTarget to avoid updating React state for every tick.
- Maintains heartbeat and automatic reconnection logic.
- Supports symbol switching with generation-based de-duplication.

```mermaid
sequenceDiagram
participant App as "App"
participant Hook as "useServerTradingSystem"
participant WS as "WebSocket"
participant Bus as "EventTarget"
participant CS as "ChartScene"
App->>Hook : "Initialize with config"
Hook->>WS : "Connect to /api/trading/ws/gameloop"
WS-->>Hook : "Send state deltas"
Hook->>Hook : "Batch updates per RAF"
Hook->>Bus : "dispatchEvent('tick', payload)"
Bus-->>CS : "tick event listener"
CS->>CS : "update candlestick series"
CS->>CS : "trigger overlay redraw"
```

**Diagram sources**
- [useServerTradingSystem.ts:509-571](file://frontend/hooks/useServerTradingSystem.ts#L509-L571)
- [useServerTradingSystem.ts:204-498](file://frontend/hooks/useServerTradingSystem.ts#L204-L498)
- [ChartScene.tsx:278-319](file://frontend/components/ChartScene.tsx#L278-L319)

**Section sources**
- [useServerTradingSystem.ts:59-654](file://frontend/hooks/useServerTradingSystem.ts#L59-L654)
- [ChartScene.tsx:278-319](file://frontend/components/ChartScene.tsx#L278-L319)

### Chart Configuration and Mode Switching
Chart configuration is centralized in ChartConfig and includes:
- Bull/Bear colors for candles and overlays.
- Glass opacity, roughness, and transmission for canvas effects.
- Grid visibility, auto rotation, and prediction visibility.
- Volume profile toggle and mode selection (session, leg, combined, off).
- Trend classification.

Mode switching:
- STANDARD: Standard candlesticks with prediction series and markers.
- FOOTPRINT: Transparent candle bodies with footprint overlay and summary area.
- RANGE: Range bars with volume profile and Triple-A indicators.

Dual volume profile tabs:
- Session, Leg, Combined, Off modes selectable from the UI.

**Section sources**
- [types.ts:204-219](file://frontend/types.ts#L204-L219)
- [constants.ts:4-19](file://frontend/constants.ts#L4-L19)
- [App.tsx:222-278](file://frontend/App.tsx#L222-L278)
- [ChartScene.tsx:177-220](file://frontend/components/ChartScene.tsx#L177-L220)
- [ChartScene.tsx:342-373](file://frontend/components/ChartScene.tsx#L342-L373)

### Responsive Design and Lifecycle Management
Responsive behavior:
- ResizeObserver monitors chart container size and updates chart and overlay dimensions.
- Price scale margins adjust for FOOTPRINT and RANGE modes to accommodate overlays.

Lifecycle management:
- Chart removal and observer disconnection on unmount.
- Visibility change handling to avoid unnecessary chart updates when hidden.
- Cleanup of drag listeners and timers in App.

**Section sources**
- [ChartScene.tsx:221-234](file://frontend/components/ChartScene.tsx#L221-L234)
- [ChartScene.tsx:270-275](file://frontend/components/ChartScene.tsx#L270-L275)
- [App.tsx:58-60](file://frontend/App.tsx#L58-L60)

## Dependency Analysis
ChartScene depends on:
- Lightweight Charts for native candlestick and histogram rendering.
- React hooks for state, refs, effects, and memoization.
- EventTarget for real-time tick delivery without React renders.
- Internal types for data structures and configuration.

Integration points:
- App composes three ChartScene instances for concurrent modes.
- useServerTradingSystem provides tickBus and instrument state.
- MarketSidebar drives symbol selection and influences activeInstrument.

```mermaid
graph LR
App["App.tsx"] --> CS["ChartScene.tsx"]
App --> Hook["useServerTradingSystem.ts"]
CS --> LC["lightweight-charts"]
CS --> Types["types.ts"]
Hook --> Types
App --> MS["MarketSidebar.tsx"]
```

**Diagram sources**
- [App.tsx:150-206](file://frontend/App.tsx#L150-L206)
- [ChartScene.tsx:2-16](file://frontend/components/ChartScene.tsx#L2-L16)
- [useServerTradingSystem.ts:1-11](file://frontend/hooks/useServerTradingSystem.ts#L1-L11)
- [types.ts:1-17](file://frontend/types.ts#L1-L17)
- [MarketSidebar.tsx:1-6](file://frontend/components/MarketSidebar.tsx#L1-L6)

**Section sources**
- [ChartScene.tsx:2-16](file://frontend/components/ChartScene.tsx#L2-L16)
- [useServerTradingSystem.ts:1-11](file://frontend/hooks/useServerTradingSystem.ts#L1-L11)
- [App.tsx:150-206](file://frontend/App.tsx#L150-L206)

## Performance Considerations
- Memoization strategies:
  - Memoized AMT analysis to avoid overlay redraws when only reference identity changes.
  - Stable data reference to prevent overlay redraws on intra-candle tick updates.
  - React.memo on ChartScene with a custom equality checker to avoid re-renders.
- RAF batching:
  - Overlay redraws triggered by pan/zoom are batched to reduce CPU overhead.
- Efficient coordinate conversions:
  - Using Lightweight Charts APIs for time/price to coordinate conversions.
- Canvas optimizations:
  - Conditional drawing checks and early returns when overlay is hidden.
  - Minimal DOM manipulation; overlay is pointer-events-none.
- WebSocket batching:
  - Batched state updates per animation frame to reduce React renders.

[No sources needed since this section provides general guidance]

## Troubleshooting Guide
Common issues and resolutions:
- Stale or out-of-order tick updates:
  - ChartScene wraps tick updates in try/catch and logs ignored updates to prevent crashes.
  - useServerTradingSystem ensures history is sorted and filters stale ticks.
- Hidden chart visibility:
  - Overlay drawing is skipped when the chart is hidden to avoid unnecessary work.
- WebSocket disconnections:
  - Automatic reconnection with exponential backoff and heartbeat monitoring.
- Memory leaks:
  - Proper cleanup of observers, timers, and WebSocket connections on unmount.
- Canvas overlay errors:
  - Try/catch around overlay drawing to prevent UI crashes.

**Section sources**
- [ChartScene.tsx:297-312](file://frontend/components/ChartScene.tsx#L297-L312)
- [useServerTradingSystem.ts:258-272](file://frontend/hooks/useServerTradingSystem.ts#L258-L272)
- [ChartScene.tsx:409-411](file://frontend/components/ChartScene.tsx#L409-L411)
- [ChartScene.tsx:270-275](file://frontend/components/ChartScene.tsx#L270-L275)
- [useServerTradingSystem.ts:550-565](file://frontend/hooks/useServerTradingSystem.ts#L550-L565)

## Conclusion
ChartScene delivers a robust, high-performance chart visualization solution that seamlessly integrates Lightweight Charts with a custom canvas overlay system. It supports multiple visualization modes, real-time tick streaming via WebSocket, responsive design, and extensive performance optimizations. The component’s architecture balances flexibility and efficiency, enabling advanced orderflow and profile visualizations while maintaining smooth interactivity and reliable lifecycle management.