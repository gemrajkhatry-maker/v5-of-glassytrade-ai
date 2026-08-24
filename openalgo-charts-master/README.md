<div align="center">

# OpenAlgo Charts

**A from-scratch, dependency-free HTML5-canvas charting engine for OpenAlgo.**

Professional interactive charts, indicators, drawing tools, order flow, market replay, linked chart grids, and on-chart trading. Six lazy-loaded tiers, zero runtime dependencies, ~53 KB Brotli for the base engine.

[![npm version](https://img.shields.io/npm/v/openalgo-charts.svg?color=cb3837&label=npm)](https://www.npmjs.com/package/openalgo-charts)
[![license](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](./LICENSE)
[![bundle](https://img.shields.io/badge/brotli-53%20KB%20base%20%C2%B7%20111%20KB%20all%20tiers-brightgreen.svg)](#size-budget)
[![tests](https://img.shields.io/badge/tests-1719%20passing-brightgreen.svg)](#develop)
[![dependencies](https://img.shields.io/badge/runtime%20deps-0-brightgreen.svg)](#principles)

[**Documentation**](https://marketcalls.github.io/openalgo-charts/) &nbsp;·&nbsp; [**Live examples**](https://marketcalls.github.io/openalgo-charts/examples) &nbsp;·&nbsp; [**Getting started**](./docs/getting-started.md) &nbsp;·&nbsp; [**Architecture**](./ARCHITECTURE.md)

<img src="docs/architecture-diagram.png" alt="OpenAlgo Charts - layered architecture from public API down to feeds and data, with loadable bundle tiers" width="920" />

</div>

---

## Live OpenAlgo trading terminal

Right-click the chart to place market / limit / stop orders, drag the order and TP/SL bracket lines to modify, and watch live P&amp;L on the position line - all on real OpenAlgo history + WebSocket tick data, with an analyzer (sandbox) mode so nothing goes live until you arm it.

<p align="center">
  <img src="docs/trading.png" alt="OpenAlgo Charts live trading terminal: RELIANCE 5m candles with order lines, a right-click order menu, a long position with live P&L, and volume" width="920" />
</p>

## Examples gallery

Every chart in the [live gallery](https://marketcalls.github.io/openalgo-charts/examples) is the real library running in your browser - switch tabs, hover the crosshair, drag the order lines, place a drawing. What you see is the code that ran.

<p align="center">
  <img src="docs/demo1.png" alt="Chart-type switcher, custom themes, data tooltips, and event markers" width="49%" />
  <img src="docs/demo2.png" alt="Range switcher, legend, series compare, and indicators and markers" width="49%" />
</p>
<p align="center">
  <img src="docs/demo3.png" alt="More live OpenAlgo Charts examples" width="49%" />
  <img src="docs/demo4.png" alt="More live OpenAlgo Charts examples" width="49%" />
</p>

## Install

```bash
npm install openalgo-charts
```

```ts
import { createChart, generateBars } from 'openalgo-charts';

const chart = createChart(document.getElementById('chart'));
chart.addSeries('candlestick').setData(generateBars(1700000000, 200, 3600));
```

## Tiers

Import only what you use. Each tier is a separate bundle that registers into the base engine's registries, so the cost of a feature you don't load is zero.

| Import | Contents | Brotli |
|---|---|---|
| `openalgo-charts` | Engine, 13 chart types, panes &amp; scales, primitives, registries, chart state, chart linking, bar cache, interval registry, trading overlay, OpenAlgo feeds | 52.9 KB |
| `openalgo-charts/indicators` | 91 built-in indicators + the Tier-2 (external-data) contract | 24.9 KB |
| `openalgo-charts/draw` | 43 drawing tools + a headless drawing controller and clipboard | 13.1 KB |
| `openalgo-charts/transform` | Heikin Ashi, Renko, Range bars, Line Break, Point &amp; Figure, Kagi | 2.7 KB |
| `openalgo-charts/profile` | Volume Profile, Market Profile (TPO), Footprint, order flow | 10.7 KB |
| `openalgo-charts/trade` | Order / position / bracket tools + DOM ladder | 6.6 KB |

Everything together is **110.8 KB Brotli**. Figures are the measured `size-limit` output; the trade tier is a delta over the base, which is why base + trade (59.5 KB) is less than their listed sum.

## What's built

### Chart types &amp; transforms
Candles, hollow and volume candles, OHLC bars, high-low, line, line+markers, step, area, HLC-area, baseline, columns, histogram, plus Heikin Ashi, Renko, Range bars, Line Break, **Point &amp; Figure** (fixed / percent / ATR box sizing, high-low or close construction), and Kagi.

### Indicators

```ts
import 'openalgo-charts/indicators';

chart.addIndicator('bollinger');                      // overlays the price pane
const macd = chart.addIndicator('macd', { fastPeriod: 8 });   // gets its own pane
macd.setSettings({ 'macd:width': 2, 'macd:lineStyle': 'dashed' });
```

91 built-ins across Trend, Momentum, Volatility and Volume, from the everyday (SMA, EMA, WMA, VWAP, Bollinger Bands, RSI, MACD, Stochastic, ADX/DMI, ATR) through Supertrend, HalfTrend, Ichimoku, Keltner, Donchian, Chandelier Exit and CPR with floor pivots to Connors RSI, Fisher Transform, Woodies CCI, Klinger, Vortex, WaveTrend Pro, Chop Zone and Williams Fractals. Twenty-five of them draw shaded bands, five emit named buy/sell markers, and Seasonality draws a monthly return heatmap as a table over the chart. The full catalogue with ids and defaults is in the docs.

The chart owns the whole lifecycle: series, pane placement, reference levels, fixed ranges (RSI 0..100), recompute on data change, teardown. Every plot gets colour, opacity, thickness, and line style for free, generated from the descriptor. Write your own with `registerIndicator`, or use the **Tier-2 contract** for indicators whose data isn't derived from OHLCV (open interest, CVD, any external feed).

### Drawing tools

```ts
import { DrawingController } from 'openalgo-charts/draw';

const draw = new DrawingController(chart, { magnet: true });
draw.setTool('trend-line');   // the next two clicks place it
```

43 tools. Lines: trend line, ray, extended line, arrow, horizontal line/ray, vertical line, cross line. Shapes: rectangle, rotated rectangle, ellipse, circle, triangle. Paths: path, polyline, arc, curve, double curve. Channels: parallel channel, fib channel. Fibonacci: retracement, extension, time zone, speed fan. Gann: fan, box. Cycles: cyclic lines, time cycles, sine line. Forecasting: long/short position (1:1 from one click, with risk/reward and risk-based sizing), forecast. Measurers: price range, date range, measure. Arrows: mark up, mark down. Text and notes: text, price label, callout, flag mark. Brushes: brush, highlighter (freehand).

Headless by design: no toolbar, no dialogs. Placement with live preview, selection, whole-shape and per-anchor dragging, magnet snap to O/H/L/C, undo/redo (a drag is one step), and persistence. Anchors are `{ time, price }`, never pixels, so they survive zoom and resolve inside collapsed session gaps and past the last bar.

`draw.copy()`, `draw.cut()` and `draw.paste()` move drawings through the OS clipboard, including between two charts on the page. The payload is JSON under one namespaced key, so foreign text pastes nothing instead of throwing at your Ctrl+V handler, and every field is validated before it reaches the model. A refused clipboard permission does not lose the copy: every write also lands in a shared in-memory clipboard, and a cut deletes only after the write succeeds. A paste is one undo step of fresh objects, nudged two bars and 16 px so it is visibly a second shape. The key bindings stay yours; the engine installs no listeners.

### Panes, scales &amp; legends
Draggable pane dividers, move / maximize / remove, and pane legends showing one reading per plot in that plot's own colour, with inline show-hide / settings / move / delete controls revealed on hover. The status line is switchable field by field (logo, title, market status, OHLC, bar change, volume, last day change, last value) over a host-supplied data source.

Each pane carries a right, a left and a hidden overlay price scale, in four modes: linear, logarithmic, and the two rebasing modes **percentage** (`+3.42%`) and **indexed-to-100** (`103.42`), which quote every price against a baseline taken from the first visible bar, so panning re-bases the axis.

### Reference levels and axis chrome

```ts
import { PriceLevels } from 'openalgo-charts';

const levels = new PriceLevels({
  levels: { previousClose: { line: true, label: true }, sessionHigh: { line: true, label: false } },
});
chart.addPrimitive(levels, 0);
levels.available('bid');   // false until a quote is fed: render that control disabled, not hidden
```

One primitive over ten levels: previous close, session high and low, last price, the four extended-hours opens and closes, and bid and ask. Each level's line across the plot and its tag on the price axis are two flags in the same options group, so they cannot drift apart. The session comes from the gaps in the bars rather than from a calendar midnight, and the session in view follows the viewport's right edge, so scrolling back through history moves the previous close back with it. A level with no data is `null`, never `0`: nothing draws at zero, and `available(kind)` is the signal to render that control disabled with its state visible instead of hiding it.

Axis chrome is off until a chart asks for it. `createChart(el, { axisChrome: { sessionClock: true, barCountdown: true } })` puts a live clock in the corner where the two axis strips meet, in the chart's own timezone with the zone's UTC offset under it, and a countdown to the current bar's close as a second row inside the last-price tag, with the interval read back off the bars so a timeframe switch is followed. Tick labels that the last-price tag would cover are dropped rather than drawn through it, on a priority order that puts the crosshair above the last price, above a price line, above a session level.

### Timezones

```ts
const chart = createChart(el, { timezone: 'America/New_York' });
chart.setTimezone('Europe/London');    // relabels and recomputes on the next frame
```

An IANA name, never a fixed offset, so daylight saving is followed rather than approximated. The zone drives the time axis (including which ticks escalate to a day, month or year label), the crosshair time tag, and every calendar-anchored study (VWAP and TWAP anchors, CPR's weekly and monthly frames, the month a Seasonality bar counts in), and it rides along in `getState()`. Profile session windows carry their own zone, so `TRADING_HOURS['us-regular']` reads as 09:30-16:00 `America/New_York` whatever the chart is displayed in. The default is `Asia/Kolkata` on the same fixed-offset arithmetic it always used, so a chart that names no zone labels and computes exactly as before.

### Market replay

```ts
import { ReplayController } from 'openalgo-charts';

const replay = new ReplayController(chart, { bars, startIndex: 200, barMs: 500 });
replay.play({ speed: 2 });          // emits replay:frame per bar
```

Headless: the controller owns the playhead and ships no DOM, so the transport bar is yours to draw from `state()` and the `replay:*` events. Each step hands the series a prefix of the session through the ordinary `setData` path, which is what makes every indicator, level, fill, marker and legend row reconstruct itself as it stood at that bar. `stop()` puts the full history and the exact viewport back.

### Symbol comparison

```ts
import { addComparison } from 'openalgo-charts';

const bn = addComparison(chart, { symbol: 'BANKNIFTY', bars });
```

The comparison rides the pane's hidden overlay scale in its own real prices, the pane rebases to percentage (or indexed-to-100), and the overlay's range is mirrored from the primary's, so equal percentage moves land on equal pixels instead of each line filling the pane. Alignment is by timestamp: a comparison print with no primary bar is dropped, a primary bar with no print becomes a gap.

### Linked chart grids

```ts
import { createLinkGroup } from 'openalgo-charts';

const group = createLinkGroup({ crosshair: true, viewport: true, symbol: false });
group.add(daily);
group.add(hourly, { symbol: 'RELIANCE', onSymbol: (s, c) => loadBars(s, c) });
```

Hover one chart and the same **instant** is marked on the others; pan or zoom one and the others move to the same wall-clock window. Each channel switches on its own, because mirroring the cursor across four timeframes while keeping each zoom is a different thing from slaving every chart's instrument.

Nothing crosses a chart boundary as a logical index. The x axis is a gapless index over each chart's own bars, so index 300 is a different instant on every chart: every value is converted index to time on the sender and time back to index on the receiver, against that chart's own data. A daily chart and an hourly chart with different history depth therefore stay on the same instant, which the naive index copy gets right only when both charts hold the same bars. An instant outside a follower's first or last bar is an absence, not a gap, so it draws nothing; inside its range with no bar there it snaps to the nearest bar in time, or draws nothing under `whenMissing: 'hide'`. The linked crosshair is a vertical line only, at reduced opacity: a mirrored horizontal line would assert a price that belongs to another instrument.

Headless like the rest, and the engine has no instrument concept, so symbol sync is a partnership: the host emits `'symbol'` on the chart's bus (or calls `group.setSymbol`) and supplies the per-member `onSymbol` that loads the bars. A member with no `onSymbol` broadcasts but never follows, which is how you pin one chart of a grid.

### Settings &amp; context menu
`chartSettingsSchema(chart)` describes a full settings dialog as tabs of controls, in the same descriptor vocabulary the indicator settings form already uses; `readChartSettings` and `applyChartSettings` are its round trip over flat, JSON-safe keys. Five tabs (Price, Readout, Axes, Appearance, Trading), and a bullish/bearish pair is **one** `colorPair` row carrying its switch and both swatches instead of two stacked rows. Grid, crosshair, scale text, plot margins, status-line fields, the chart timezone, trading colours and the primary series' own style are all real options behind it, so no control in the schema is inert.

`chart.on('contextmenu', ...)` reports the pane, price, time, logical index and what sits under the pointer: a drawing, an indicator instance, a legend, a primitive, a series, a price scale (with the side and the scale id it names), the time scale, or empty plot. For a menu raised on a price axis, `chart.priceAxisState(pane, scaleId)` reads back every item that menu draws (auto-fit, invert, scale mode, price-per-bar lock, whether the axis is movable) and `setPriceAxisOptions`, `setPriceAxisAutoFit`, `setPriceAxisLockRatio` and `movePriceAxis` act on it, so no row is ticked with nothing behind it.

### Trading
Order, position, and bracket lines with live P&amp;L, one-click and drag-to-modify, OCO, validation, an order state machine, analyzer (sandbox) mode, and a depth-of-market ladder (5 to 200 levels).

### Profiles &amp; order flow
Volume Profile, Market Profile (TPO), Footprint, and cumulative delta.

### Warm-load cache &amp; interval registry

```ts
import { withBarCache, registerInterval } from 'openalgo-charts';

const feed = withBarCache(new OpenAlgoDataFeed(cfg), { ttlMs: 60_000 });
registerInterval({ code: '1MO', bucketing: { mode: 'calendar', unit: 'month' } });
```

`withBarCache` wraps **any** `DataFeed`, so a custom feed warms up too. One entry per `symbol|exchange|interval` holds the widest range fetched so far and a narrower request is sliced out of it, because keying on the range would miss on every pan. **The forming bar is never stored**: a frozen snapshot of a live candle reaching the last-price line, the header LTP and every indicator computed off that close is worse than no cache at all, so coverage ends at the last closed bar and a hit is short by the one bar a live subscription re-supplies. Freshness is two gates, a TTL and "nothing new can have closed", the second measured on the feed's own bar grid rather than UTC midnight. Bounded LRU on entries and on total bars, in-memory by default with an injectable store if you want localStorage or IndexedDB, and `noCache`, `invalidate()`, `clear()` and `stats()` for the rest.

An interval code resolves through a registry whose entry is a **bucketing rule, not a duration**: fixed seconds, a calendar month/quarter/year that opens at local midnight in a named zone, N ticks, or N traded quantity. That is the vocabulary the tick aggregator already used, widened by one case. An unrecognised code now throws `UnknownIntervalError` instead of quietly meaning 60 seconds, so a subscription fails at subscribe time rather than drawing minute bars under someone else's label; `tryResolveInterval` and `isKnownInterval` are the non-throwing probes for validating a picker.

### State
`chart.getState()` / `chart.restoreState()` capture the viewport, grid, panes, price scales, indicator instances, drawings, and the whole settings block (canvas, status line, trading colours, event filters) as one JSON payload: saved layouts and templates with no extra storage plumbing.

### Data
OpenAlgo REST history + WebSocket ticks with auto-reconnect and resubscribe, live candle aggregation, tick/volume bars, a unified `chart.on(...)` event bus, markers and signals, earnings/dividend/expiry event markers, an IANA chart timezone, and custom price/time formatters.

## Size budget

Enforced in CI by [`size-limit`](./.size-limit.json). Nothing is excluded, because there are no runtime dependencies to exclude.

| Bundle | Limit | Actual |
|---|---|---|
| Base engine | 55 KB | 52.88 KB |
| Base + trade | 62 KB | 59.46 KB |
| Indicators tier | 27 KB | 24.88 KB |
| Draw tier | 14 KB | 13.11 KB |
| Transform tier | 5 KB | 2.66 KB |
| Profile tier | 11 KB | 10.66 KB |
| **Everything** | **120 KB** | **110.76 KB** |

## Documentation

Full docs, the interactive example gallery, and the generated API reference live at:

**https://marketcalls.github.io/openalgo-charts/**

The site is built with Nextra (in [`website/`](./website)) and statically exported to GitHub Pages on every push. Every code sample on a docs page is a *live* chart running the real library, so what you read is what runs. To run the site locally:

```bash
npm run build                               # build the library (dist/) the live demos import
cd website && npm install && npm run dev    # http://localhost:3000/openalgo-charts
```

## Agent skills

Teach your AI coding assistant this library:

```bash
npx skills add https://github.com/marketcalls/openalgo-charts
```

Installs six skills from [`.github/skills/`](./.github/skills) - a reference hub with 21 deep-dive files covering the whole API surface and its foot-guns, plus task skills for scaffolding a chart, adding indicators, building a terminal, writing a plugin, and debugging. Works with Claude Code, Cursor, Codex, Copilot, Gemini CLI and the rest of the `skills` CLI's supported agents.

## Examples

Runnable demos in [`examples/`](./examples), including a full **yfinance terminal** ([`examples/yfinance`](./examples/yfinance)) with a full terminal shell: symbol search, interval pills, chart-type picker, indicator menu, a vertical drawing rail, a floating properties bar, generated indicator settings, and layout persistence.

```bash
npm run build
cd examples/yfinance && pip install -r requirements.txt && python server.py
# → http://127.0.0.1:8000/examples/yfinance/index.html
```

## Develop

```bash
npm install        # install dev toolchain
npm run typecheck  # strict TypeScript check
npm test           # unit tests (vitest) - 1719 across 91 files
npm run build      # Rollup -> dist/ (minified ESM per tier + types)
npm run size       # size-limit (Brotli) against the budget
npm run e2e        # Playwright Chromium smoke tests
npm run verify     # typecheck + test + build + size
```

## Principles

- **Single canvas pipeline** (no SVG, no DOM-per-bar): small and fast.
- **Gapless time axis by default**: weekends, holidays, and session breaks collapse.
- **Registries, not switches**: chart types, indicators, and drawing tools are all descriptors. Adding one is a registration, never a core change.
- **Zero runtime dependencies**: nothing is excluded from the size budget.
- **Apache-2.0**, original code.

## Status &amp; limitations

Version **1.6.0**. All engine build phases are implemented with 1882 unit tests across 100 files.

Known gaps, stated plainly:

- **Footprint and order flow need trade-by-trade data classified bid/ask.** OpenAlgo does not store this by default, so it is live-session-only unless you add a tick recorder: `FootprintAggregator` is the live path. See [`ARCHITECTURE.md`](./ARCHITECTURE.md) §6A.
- **Only `Footprint` is theme-aware among the profile primitives.** `VolumeProfile`, `MarketProfile` and `HorizontalProfile` never read `rc.theme`; their defaults are dark-tuned, so a light theme needs explicit colours. `HorizontalProfile` also hardcodes its POC / value-area line colours and has no `setOptions`.
- The OpenAlgo **WS/trade adapter wire schemas** ship with injectable transports and offline tests, but the exact field names should be verified against your running OpenAlgo build.
- **A pane has exactly one hidden overlay scale**, so every symbol comparison on a pane shares one baseline. That is right for a single comparison, the common case, but a second one on the same pane is quoted against the first instrument's price; put further instruments on their own pane with `paneIndex` until the overlay scales are keyed.
- An optional **DOM chrome package** (toolbar, dialogs, command palette, objects panel) is the next planned piece; today that UI lives in the examples.

See [`ARCHITECTURE.md`](./ARCHITECTURE.md) §13a for the full deferred list.

## License

[Apache-2.0](./LICENSE). See [`NOTICE`](./NOTICE).
