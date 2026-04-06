# GlassyTrade AI — UI Replication Specification

> **Scope:** Complete visual & interaction design specification for replicating the GlassyTrade AI trading dashboard. The LLM/AI inference layer is explicitly excluded. All component behaviors described here are driven by deterministic trading logic and real-time market data feeds.

***

## 1. Design System

### 1.1 Aesthetic Direction

**Theme:** Dark-mode-first glassmorphism trading terminal. The UI communicates precision, authority, and real-time urgency. Think Bloomberg Terminal meets Linear — sober, data-dense, high-contrast.

**Art Direction Keywords:** `terminal`, `glass`, `precision`, `dark`, `monochrome + signal color`

### 1.2 Color Palette

All colors must be defined as CSS custom properties. The palette is divided into **neutral surfaces** (the vast majority of the UI) and **signal colors** (used only to communicate market state).

```css
:root {
  /* === SURFACES (dark glassmorphism) === */
  --color-bg:              #090b0f;          /* Deepest background */
  --color-surface:         #0f1117;          /* Primary panel */
  --color-surface-2:       #161921;          /* Nested panel / card */
  --color-surface-3:       #1c202a;          /* Elevated element */
  --color-surface-glass:   rgba(22,25,33,0.72); /* Glassmorphism panels */
  --color-border:          rgba(255,255,255,0.07);
  --color-border-subtle:   rgba(255,255,255,0.04);
  --color-divider:         rgba(255,255,255,0.05);

  /* === TEXT === */
  --color-text:            #e2e4ea;          /* Primary */
  --color-text-muted:      #7a7f8e;          /* Secondary */
  --color-text-faint:      #3e4354;          /* Tertiary / disabled */
  --color-text-inverse:    #090b0f;

  /* === SIGNAL COLORS (market state only) === */
  --color-bullish:         #00c896;          /* Long / up / active */
  --color-bullish-dim:     rgba(0,200,150,0.12);
  --color-bearish:         #ff4d6a;          /* Short / down */
  --color-bearish-dim:     rgba(255,77,106,0.12);
  --color-flat:            #6b7280;          /* Flat / no trade */
  --color-warning:         #f59e0b;          /* Monitor / wait */
  --color-warning-dim:     rgba(245,158,11,0.12);

  /* === SYSTEM ACCENT === */
  --color-accent:          #3b82f6;          /* UI accent — buttons, focus rings */
  --color-accent-dim:      rgba(59,130,246,0.15);

  /* === SHADOWS === */
  --shadow-panel: 0 0 0 1px rgba(255,255,255,0.05), 0 4px 24px rgba(0,0,0,0.5);
  --shadow-glass: 0 8px 32px rgba(0,0,0,0.6), inset 0 1px 0 rgba(255,255,255,0.06);

  /* === RADIUS === */
  --radius-sm:   4px;
  --radius-md:   6px;
  --radius-lg:   10px;
  --radius-xl:   14px;

  /* === TRANSITIONS === */
  --transition-fast: 120ms cubic-bezier(0.16, 1, 0.3, 1);
  --transition-std:  220ms cubic-bezier(0.16, 1, 0.3, 1);
}
```

### 1.3 Typography

```css
/* Font stacks */
--font-mono:  'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
--font-ui:    'Inter', 'DM Sans', system-ui, sans-serif;
--font-label: 'Inter', system-ui, sans-serif;
```

**Loading via CDN:**
```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300..700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
```

**Type Scale (trading dashboard — compact):**

| Role | Font | Size | Weight | Notes |
|---|---|---|---|---|
| Section header labels | `--font-label` | 9px | 600 | ALL CAPS, letter-spacing: 0.1em |
| Body / tooltip text | `--font-ui` | 11–12px | 400 | |
| Button / tag text | `--font-ui` | 11px | 500 | |
| Data values (LTP, PnL) | `--font-mono` | 12–14px | 500 | `tabular-nums` |
| Large data values | `--font-mono` | 18–22px | 600 | `tabular-nums` |
| Panel title | `--font-label` | 10px | 700 | ALL CAPS |
| Probability % big display | `--font-mono` | 28–36px | 700 | `tabular-nums` |

**Rule:** All numeric data (prices, PnL, probability %, delta, sigma values) must use `font-variant-numeric: tabular-nums lining-nums` so digits align in columns.

### 1.4 Glassmorphism Mixin

```css
.glass-panel {
  background: var(--color-surface-glass);
  backdrop-filter: blur(16px) saturate(1.4);
  -webkit-backdrop-filter: blur(16px) saturate(1.4);
  border: 1px solid var(--color-border);
  box-shadow: var(--shadow-glass);
}
```

***

## 2. Layout Architecture

### 2.1 Overall Grid

The dashboard uses a **3-column layout** at desktop (≥1280px):

```
┌────────────────┬──────────────────────────────┬─────────────────┐
│ LEFT RAIL      │ CENTER — MAIN ANALYSIS PANEL │ RIGHT RAIL      │
│ 280px fixed    │ flex: 1 (min 480px)           │ 320px fixed     │
│                │                               │                 │
│ Market Scanner │ Chart Area (Live Feed)        │ Execution Engine│
│ Trade List     │ Opportunity Alert             │ Session & Leg   │
│                │ Trade Intelligence            │ Volume Metrics  │
│                │ Rule Checklist                │ IB + VWAP       │
│                │ Decision History              │                 │
└────────────────┴──────────────────────────────┴─────────────────┘
```

```css
.app-layout {
  display: grid;
  grid-template-columns: 280px 1fr 320px;
  grid-template-rows: 100vh;
  overflow: hidden;   /* ONE scroll region rule: only panels scroll internally */
  background: var(--color-bg);
}
```

**Critical rule: ONE scroll region.** The viewport itself never scrolls. Each panel (Left Rail, Center, Right Rail) manages its own `overflow-y: auto` internally. This is non-negotiable for professional trading dashboards.

### 2.2 Panel Anatomy

Every panel follows the same structure:

```html
<section class="panel">
  <header class="panel-header">
    <span class="panel-label">SECTION NAME</span>
    <span class="panel-meta">3 of 3</span>       <!-- optional -->
    <div class="panel-actions">...</div>           <!-- optional -->
  </header>
  <div class="panel-body">
    <!-- content -->
  </div>
</section>
```

```css
.panel {
  display: flex;
  flex-direction: column;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--color-divider);
  background: var(--color-surface-2);
  min-height: 36px;
}

.panel-label {
  font: 600 9px/1 var(--font-label);
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--color-text-muted);
}

.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  scrollbar-width: thin;
  scrollbar-color: var(--color-surface-3) transparent;
}
```

***

## 3. Component Specifications

### 3.1 Market Scanner

**Location:** Left rail, top section.

**Layout:** Full-height flex column.

#### Scanner Header Bar
```
[MARKET SCANNER]  [3 of 3]  [Filter input] [Mode ▾] [Action ▾]
```

- Filter input: minimal, borderless on dark bg, placeholder "Filter symbols..."
- Dropdowns: compact selects, 11px text, custom styled with `--color-surface-3` background

**Dropdown Options:**
- Mode: All Modes | Balanced | Imbalanced | Dead Market
- Action: All Actions | Enter Now | Skip | Monitor/Wait

#### Scanner Table

```
SYMBOL         MODE    ACTION  ↕  PROB%↓  LTP      CHNG
NIFTY 22200 PE PROB    SKIP       55%     261.4    +2.2%
NIFTY 22200 CE NO_T    SKIP       0%      336.4    -1.5%
NIFTY 22150 CE NO_T    SKIP       0%      366.7    -1.2%
```

**Column specs:**

| Column | Width | Alignment | Font | Notes |
|---|---|---|---|---|
| SYMBOL | auto/flex | Left | `--font-mono` 11px | Instrument name (e.g. "NIFTY 22200 PE") |
| MODE | 52px | Center | `--font-mono` 10px | Badge: PROB / SKIP / NO_T |
| ACTION | 60px | Center | 10px | Badge: ENTER / SKIP / MON |
| ↕ | 24px | Center | — | Sort icon |
| PROB% | 52px | Right | `--font-mono` 11px | `tabular-nums` |
| LTP | 60px | Right | `--font-mono` 11px | Last traded price |
| CHNG | 56px | Right | `--font-mono` 10px | % change, colored |

**Row states:**
- Default: `background: transparent`
- Hover: `background: var(--color-surface-3)` — cursor pointer
- Selected/active: `background: var(--color-accent-dim)`, left border `2px solid var(--color-accent)`
- ENTER NOW row: subtle `background: var(--color-bullish-dim)`

**MODE badge styles:**

```css
.badge-prob  { background: var(--color-warning-dim); color: var(--color-warning); }
.badge-no-t  { background: var(--color-flat); opacity: 0.6; color: var(--color-text-faint); }
.badge-skip  { background: transparent; color: var(--color-text-faint); }
.badge-enter { background: var(--color-bullish-dim); color: var(--color-bullish); font-weight: 600; }
```

**CHNG coloring:**
- Positive (`+`): `color: var(--color-bullish)`
- Negative (`-`): `color: var(--color-bearish)`
- Zero: `color: var(--color-text-muted)`

***

### 3.2 Live Feed / Chart Area

**Location:** Center column, top section (largest area in the UI).

#### Chart Type Tab Bar
Horizontal scrollable tab strip directly below the panel header:

```
[Standard Candles] [Footprint] [Range] [Session] [Leg] [Combined] [Off]
```

Tab styles:
```css
.chart-tab {
  padding: 4px 10px;
  font: 500 11px var(--font-ui);
  border-radius: var(--radius-md);
  color: var(--color-text-muted);
  cursor: pointer;
  border: none;
  background: none;
  white-space: nowrap;
  transition: color var(--transition-fast), background var(--transition-fast);
}
.chart-tab.active {
  background: var(--color-surface-3);
  color: var(--color-text);
}
.chart-tab:hover:not(.active) {
  color: var(--color-text);
}
```

Active sub-mode indicator (text below tabs, e.g. "Standard Candles → Combined Profile"):
```css
.chart-mode-label {
  font: 400 10px var(--font-mono);
  color: var(--color-text-faint);
  padding: 2px 12px;
}
```

#### Model Status Bar
A slim status strip above the chart:

```
MODEL:  [MONITORING]    [LIVE SCANNING]    [Vol OK]
```

```css
.model-status-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 4px 12px;
  background: var(--color-surface-2);
  border-bottom: 1px solid var(--color-divider);
  font: 500 10px var(--font-mono);
  color: var(--color-text-muted);
}
.model-status-pill {
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}
.pill-monitoring { background: var(--color-warning-dim); color: var(--color-warning); }
.pill-scanning   { background: var(--color-bullish-dim); color: var(--color-bullish); }
.pill-vol-ok     { background: var(--color-accent-dim);  color: var(--color-accent); }
```

#### Chart Canvas
- Fills remaining space in the center panel
- Recommended library: **Lightweight Charts** (TradingView's open-source library) — handles OHLC candles, volume bars, footprint overlays
- Background: `var(--color-bg)` — not the panel surface
- Grid lines: `rgba(255,255,255,0.04)` (very subtle)
- Watermark text (symbol name): `rgba(255,255,255,0.03)`

***

### 3.3 Live Opportunity Alert

**Location:** Center column, below chart area. Compact alert banner.

**States:**

**Scanning (no signal):**
```
🔭  SCANNING MARKETS
    No actionable 'ENTER_NOW' signals
```
```css
.opportunity-panel {
  padding: 16px;
  text-align: center;
  color: var(--color-text-faint);
  border-top: 1px solid var(--color-divider);
}
.opportunity-icon { font-size: 20px; margin-bottom: 4px; }
.opportunity-label { font: 700 9px var(--font-label); letter-spacing: 0.1em; text-transform: uppercase; color: var(--color-text-muted); }
.opportunity-sub   { font: 400 11px var(--font-ui); color: var(--color-text-faint); }
```

**ENTER NOW signal (active):**
Background shifts to `var(--color-bullish-dim)`, label color `var(--color-bullish)`, pulsing border animation:
```css
@keyframes pulse-border {
  0%, 100% { border-color: var(--color-bullish); opacity: 1; }
  50%       { border-color: var(--color-bullish); opacity: 0.4; }
}
.opportunity-panel.active {
  background: var(--color-bullish-dim);
  border: 1px solid var(--color-bullish);
  animation: pulse-border 2s ease-in-out infinite;
}
```

***

### 3.4 Execution Engine Panel

**Location:** Right rail, top section.

```
┌─ EXECUTION ENGINE ─────────────────────────────┐
│ [ENGINE ARMED]                                  │
│                                                 │
│ TARGET VS CIRCUIT                               │
│ ─────────────────────────────────              │
│ -₹30K (Circuit)          +₹15K (Target)        │
│                                                 │
│ EQUITY          ₹10,00,000                      │
│ OPEN PNL        +₹0.00                          │
│ Daily Target    ₹20,000                         │
│ Circuit Breaker -₹10,000                        │
│ Session P&L     +₹0.00                          │
│ Closed          0                               │
└─────────────────────────────────────────────────┘
```

#### Engine Status Badge
```css
.engine-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: var(--radius-sm);
  font: 700 10px var(--font-mono);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.engine-armed {
  background: var(--color-bullish-dim);
  color: var(--color-bullish);
  border: 1px solid rgba(0,200,150,0.2);
}
.engine-armed::before {
  content: '';
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--color-bullish);
  box-shadow: 0 0 6px var(--color-bullish);
  animation: blink 1.8s ease-in-out infinite;
}
@keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.3} }
.engine-disarmed {
  background: var(--color-surface-3);
  color: var(--color-text-faint);
}
```

#### Target vs Circuit Bar
Visual range bar showing circuit (left, red) and target (right, green) relative to zero:

```
│ -₹30K ◀━━━━━━━━━━━━━━━━━━━━ 0 ━━━━━━━━━━━▶ +₹15K │
│        [CIRCUIT]                          [TARGET]  │
```

```css
.pnl-range-bar {
  display: flex;
  height: 4px;
  border-radius: var(--radius-full);
  overflow: hidden;
  background: var(--color-surface-3);
  margin: 8px 0;
}
.pnl-range-circuit { flex: 2; background: var(--color-bearish); opacity: 0.6; }
.pnl-range-center  { width: 2px; background: var(--color-text-faint); }
.pnl-range-target  { flex: 1; background: var(--color-bullish); opacity: 0.6; }
```

#### Metrics Row Grid
```css
.exec-metrics {
  display: grid;
  grid-template-columns: 1fr auto;
  row-gap: 6px;
  padding: 8px 0;
}
.exec-metric-label {
  font: 400 10px var(--font-ui);
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.exec-metric-value {
  font: 600 12px var(--font-mono);
  color: var(--color-text);
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.exec-metric-value.positive { color: var(--color-bullish); }
.exec-metric-value.negative { color: var(--color-bearish); }
```

***

### 3.5 Session & Leg Panel

**Location:** Right rail, below Execution Engine.

```
┌─ SESSION & LEG ─────────────────────────────────┐
│ SESSION     LEG          LOCATION                │
│ NO_TRADE    BALANCED     VAH / VAL / POC         │
│                          332.83 / 333.7          │
└─────────────────────────────────────────────────┘
```

**3-column layout within panel:**
```css
.session-leg-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 8px;
  padding: 10px 12px;
}
.session-leg-item { display: flex; flex-direction: column; gap: 4px; }
.session-leg-label { font: 600 8px var(--font-label); letter-spacing: 0.1em; text-transform: uppercase; color: var(--color-text-faint); }
.session-leg-value { font: 700 12px var(--font-mono); color: var(--color-text); }
```

**Value badge styles:**

| Value | Style |
|---|---|
| `NO_TRADE` | `color: var(--color-text-muted)` |
| `BALANCED` | `color: var(--color-warning)` |
| `IMBALANCED` | `color: var(--color-bullish)` |
| `TREND` | `color: var(--color-accent)` |
| VAH/VAL/POC | Stacked mono values, `--font-mono` 11px, muted color for labels |

***

### 3.6 Volume Aggression (Section 03)

**Location:** Right rail, below Session & Leg.

```
┌─ 03. VOLUME AGGRESSION ─────────────────────────┐
│ Delta Score              [BULLS IN CONTROL]      │
│                                                  │
│             +1.00                                │
│       ▓▓▓▓▓▓▓▓░░░░░░ (progress bar)             │
└─────────────────────────────────────────────────┘
```

**Delta score display:**
```css
.delta-score {
  font: 700 28px var(--font-mono);
  color: var(--color-text);
  font-variant-numeric: tabular-nums;
}
.delta-label-badge {
  font: 700 9px var(--font-label);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  padding: 2px 8px;
  border-radius: var(--radius-sm);
}
/* State-dependent colors */
.bulls-in-control { background: var(--color-bullish-dim); color: var(--color-bullish); }
.bears-in-control { background: var(--color-bearish-dim); color: var(--color-bearish); }
.neutral-control  { background: var(--color-surface-3);  color: var(--color-text-muted); }
```

**Control bar (delta visualization):**
```css
.delta-bar { height: 3px; border-radius: var(--radius-full); background: var(--color-surface-3); overflow: hidden; }
.delta-bar-fill { height: 100%; transition: width var(--transition-std); }
.delta-bar-fill.bullish { background: var(--color-bullish); }
.delta-bar-fill.bearish { background: var(--color-bearish); }
```

***

### 3.7 Market Metrics (Section 03B)

**Location:** Right rail, below Volume Aggression.

```
┌─ 03B. MARKET METRICS ───────────────────────────┐
│ OFI        ╱╲↗     +0.190                        │
│ CVD Slope  ╲╱↘     -3.7                          │
│ Balance    0       % in VA                       │
│ Shape      D Balanced    18.0 bps   Depth-5      │
└─────────────────────────────────────────────────┘
```

**Metrics row layout:**
```css
.metric-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 5px 0;
  border-bottom: 1px solid var(--color-divider);
}
.metric-key   { font: 400 10px var(--font-ui); color: var(--color-text-muted); width: 80px; }
.metric-spark { font: 400 11px var(--font-mono); color: var(--color-text-faint); width: 40px; } /* sparkline characters */
.metric-val   { font: 600 12px var(--font-mono); color: var(--color-text); text-align: right; font-variant-numeric: tabular-nums; }
```

**Sparkline direction characters** (use Unicode box-drawing / arrow chars):
- `╱╲↗` = rising then descending then up  
- `╲╱↘` = descending then rising then down  
- `─` = flat  
- These are purely decorative text — no canvas/SVG needed.

**Coloring rules for values:**
- Positive OFI: `var(--color-bullish)`, Negative: `var(--color-bearish)`
- CVD Slope positive: `var(--color-bullish)`, negative: `var(--color-bearish)`

***

### 3.8 Structure Panel (Section 03C)

**Location:** Right rail.

```
┌─ 03C. STRUCTURE ────────────────────────────────┐
│  0%    BALANCE    STRUCTURE                      │
│  No acceptance/rejection signals                 │
└─────────────────────────────────────────────────┘
```

Structure state tags (similar styling to MODE badges):
```css
.structure-tag { font: 700 9px var(--font-label); letter-spacing: 0.08em; text-transform: uppercase; padding: 1px 6px; border-radius: var(--radius-sm); }
.structure-balance    { color: var(--color-warning); background: var(--color-warning-dim); }
.structure-imbalance  { color: var(--color-bullish); background: var(--color-bullish-dim); }
```

***

### 3.9 IB + Breaks Panel (Section 03D)

```
┌─ 03D. IB + BREAKS ──────────────────────────────┐
│ IB Range    244.05  ──  383.30                   │
│             ✅ INTACT                             │
│             No break detected                    │
└─────────────────────────────────────────────────┘
```

```css
.ib-range-display {
  display: flex;
  align-items: center;
  gap: 8px;
  font: 600 12px var(--font-mono);
  color: var(--color-text);
  font-variant-numeric: tabular-nums;
}
.ib-range-separator {
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, var(--color-bearish) 0%, var(--color-bullish) 100%);
  opacity: 0.5;
}
.ib-status-intact  { color: var(--color-bullish); font: 600 10px var(--font-mono); }
.ib-status-broken  { color: var(--color-bearish); font: 600 10px var(--font-mono); }
```

***

### 3.10 VWAP + Context Panel (Section 03E)

```
┌─ 03E. VWAP + CONTEXT ───────────────────────────┐
│ Session VWAP   332.80                            │
│ +2σ / +1σ      339.89 / 336.34                  │
│ -1σ / -2σ      329.25 / 325.70                  │
│                                                  │
│     -3σ  VWAP  +3σ  (visual scale marker)       │
│     LTP is +0.26σ from VWAP                     │
│     Price Velocity   0.0550/s                    │
└─────────────────────────────────────────────────┘
```

**VWAP position indicator (linear scale):**
```
   [-3σ]───────────[VWAP]────●───────────[+3σ]
                              ↑ LTP position
```

```css
.vwap-scale-track {
  height: 4px;
  background: linear-gradient(90deg, var(--color-bearish) 0%, var(--color-surface-3) 50%, var(--color-bullish) 100%);
  border-radius: var(--radius-full);
  position: relative;
  margin: 8px 0;
}
.vwap-scale-dot {
  position: absolute;
  width: 8px; height: 8px;
  background: var(--color-text);
  border: 2px solid var(--color-bg);
  border-radius: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  /* left: computed as % of scale range */
}
```

**Sigma values:** Two-column grid (label left, value right), `--font-mono`, `tabular-nums`.

***

### 3.11 Probability Panel (Section 04)

```
┌─ 04. PROBABILITY ───────────────────────────────┐
│ Direction   FLAT      P(target)   0.0%           │
│ Timing/Size SKIP      0.0%                       │
└─────────────────────────────────────────────────┘
```

**Direction display:**
```css
.prob-direction {
  font: 800 20px var(--font-mono);
  letter-spacing: 0.05em;
}
.prob-direction.flat  { color: var(--color-text-muted); }
.prob-direction.long  { color: var(--color-bullish); }
.prob-direction.short { color: var(--color-bearish); }
```

**P(target) gauge:**
```css
.prob-gauge-track { height: 3px; background: var(--color-surface-3); border-radius: var(--radius-full); }
.prob-gauge-fill  { height: 100%; border-radius: var(--radius-full); transition: width var(--transition-std);
                    background: linear-gradient(90deg, var(--color-warning), var(--color-bullish)); }
```

***

### 3.12 Rule Checklist (Section 05)

```
┌─ 05. RULE CHECKLIST ──────────────────────────── [HIDE] ┐
│  1 / 4 PASSED                                            │
│                                                          │
│  ✗  AAA PRE-1    Session    NO_TRADE                     │
│  ✓  MR Location  Price near POC/Mid                      │
│  ⏸  Volume Alive  ACTIVE                                 │
│  ⏸  Timing       SKIP                                    │
│                                                          │
│  [View Rule Book]                                        │
│                                                          │
│  Verdict:  MONITOR -> WAIT                               │
└──────────────────────────────────────────────────────────┘
```

**Pass/Fail counter:**
```css
.rule-counter {
  font: 700 11px var(--font-mono);
  color: var(--color-text-muted);
}
.rule-counter .passed { color: var(--color-bullish); }
```

**Individual rule row:**
```css
.rule-row {
  display: grid;
  grid-template-columns: 16px 1fr auto;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font: 400 11px var(--font-ui);
}
.rule-icon-pass { color: var(--color-bullish); }
.rule-icon-fail { color: var(--color-bearish); }
.rule-icon-wait { color: var(--color-warning); }
.rule-value     { font: 500 10px var(--font-mono); color: var(--color-text-muted); }
```

**Verdict row:**
```css
.verdict-row {
  padding: 8px 10px;
  border-radius: var(--radius-md);
  background: var(--color-surface-2);
  font: 600 10px var(--font-mono);
  letter-spacing: 0.05em;
  text-transform: uppercase;
  border-left: 2px solid var(--color-warning);
  color: var(--color-warning);
  margin-top: 8px;
}
```

Verdict border-left color by state:
- `ENTER NOW`: `var(--color-bullish)`
- `MONITOR -> WAIT`: `var(--color-warning)`
- `SKIP`: `var(--color-flat)` / muted
- `FAILED AUCTION`: `var(--color-bearish)`

***

### 3.13 Decision History (Section 06)

**Location:** Center column, bottom section.

```
┌─ 06. DECISION HISTORY ─── [17] ─────── [EXPORT CSV ↓] ┐
│                                                         │
│  FLAT   No   Conf: High    11:58:15 AM                  │
│  No quant edge: P=0.505 near 50/50. Wait for setup.     │
│  ─────────────────────────────────────────────────────  │
│  FLAT   {direction:  Conf: Medium   11:57:45 AM          │
│  direction: LONG, confidence: Medium, rationale: ...     │
└─────────────────────────────────────────────────────────┘
```

**Entry layout:**
```css
.history-entry {
  padding: 8px 0;
  border-bottom: 1px solid var(--color-divider);
}
.history-entry-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.history-direction-badge {
  font: 700 9px var(--font-mono);
  letter-spacing: 0.06em;
  padding: 1px 6px;
  border-radius: var(--radius-sm);
  text-transform: uppercase;
}
.history-conf {
  font: 400 10px var(--font-ui);
  color: var(--color-text-faint);
}
.history-conf .conf-high   { color: var(--color-bullish); }
.history-conf .conf-medium { color: var(--color-warning); }
.history-conf .conf-low    { color: var(--color-bearish); }
.history-time {
  margin-left: auto;
  font: 400 10px var(--font-mono);
  color: var(--color-text-faint);
  font-variant-numeric: tabular-nums;
}
.history-rationale {
  font: 400 11px var(--font-ui);
  color: var(--color-text-muted);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;           /* Truncate to 2 lines by default */
  -webkit-box-orient: vertical;
  overflow: hidden;
  cursor: pointer;
}
.history-rationale.expanded { -webkit-line-clamp: unset; }
```

Direction badge colors (same as scanner badges):
```css
.dir-flat  { background: var(--color-surface-3); color: var(--color-text-muted); }
.dir-long  { background: var(--color-bullish-dim); color: var(--color-bullish); }
.dir-short { background: var(--color-bearish-dim); color: var(--color-bearish); }
```

**Export CSV button:**
```css
.btn-export {
  padding: 3px 10px;
  border-radius: var(--radius-sm);
  font: 600 9px var(--font-label);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  background: var(--color-surface-3);
  color: var(--color-text-muted);
  border: 1px solid var(--color-border);
  cursor: pointer;
  transition: background var(--transition-fast), color var(--transition-fast);
}
.btn-export:hover { background: var(--color-surface-glass); color: var(--color-text); }
```

***

### 3.14 Fabio Playbook Panel

**Location:** Center column, within Trade Intelligence section.

```