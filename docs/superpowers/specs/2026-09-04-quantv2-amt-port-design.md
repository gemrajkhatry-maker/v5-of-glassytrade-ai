# quantv2 AMT Algorithm Port — Design (translate docs/amt into quantv2)

**Goal:** Make quantv2 actually implement the docs/amt institutional algorithm: translate v1's proven `quant/amt/` tracker math into typed quantv2 modules (zero v1 imports), rewrite setups/stops/exits to doc definitions, add §13 pyramiding/partials, §12 cushion risk, §15 exchange-side SL/TP, and L2 depth consumption.

**Locked scope:** full spec incl. L2; full §13; exchange SL/TP this phase; approach = translate-from-v1; futures first; paper-live gate unchanged.

**Data constraint (documented, honest):** Dhan marketfeed provides **5-level** depth for NSE F&O. Spec's 20–50-level books are not obtainable from this broker — OBI/walls compute on 5-level; guard thresholds that assume full book are re-pinned to 5-level equivalents in contract tests.

## Translation source map (v1 proven math → new quantv2 module)

| New module | Translates from | Doc anchor |
|---|---|---|
| `orderflow/prints.py` | `quant/amt/orderflow/aggressive_prints.py` | AMT §7.1 (bubbles ≥30–40 lots) |
| `orderflow/book.py` | `quant/amt/orderflow/aggression.py`, `footprint.py` | AMT §7, fabio L96 (OBI, walls, one-sided %) |
| `vwap.py` | `quant/amt/profile/vwap.py` | AMT §6.1 (anchored VWAP ±1σ/±2σ, anti-climax) |
| `cvd.py` | `quant/amt/orderflow/cvd.py`, `drive.py` | AMT §6.2 (velocity EMA3−EMA9, divergence) |
| `profile.py` | `quant/amt/profile/volume_profile.py`, `lvn.py` | AMT §5 (68.2% VA, LVN extraction, layers) |
| `absorption.py` | `quant/amt/orderflow/detectors.py`, absorption logic in `analyzer.py` | AMT §7.2 (1.5×vol, ≤0.5×range, ≥60% one-sided, cluster bounds) |
| `triple_a.py` | `quant/amt/triple_a.py` | AMT §8 (state machine, cluster-extreme aggression + VWAP + CVD expansion, 15-bar anti-stale) |
| `second_drive.py` | `quant/amt/orderflow/drive.py`, market/structure reclaim logic | fabio L104/L114 (reclaim continuation, drive counter <3) |
| `phases.py` | `quant/amt/market/opening.py`, `regime.py`, session gates in v1 runtime | AMT §10 (trap lock, discovery, exhaustion, allow_trend/reversion, warmup ≥15) |
| `guards.py` | `quant/amt/market/state_engine.py`, `vars_detector.py` + fabio gate vetoes | fabio L93–107 (DEAD, contested bubble, drive exhaustion, CVD-conflict, stacked imbalance) |

## Rewrites of existing quantv2 modules

- `setups.py` — all six arms re-verified against doc: VA-fade enters on close **back inside** VA; Second-Drive = reclaim continuation (LONG+SHORT); Squeeze retests **trapped level**; LVN uses real profile LVN; Initiative keeps CVD guard.
- `stops.py` — anchors to cluster/bubble extremes ("behind bubbles"), keeps fabio inside-offset + cap math; structural TPs (TP1 LVN 2R, TP2 POC/PDH; fade targets POC).
- `exits.py` — BE at **0.8R** close/CVD-thrust; CVD-kill exit; 1–2-tick inside shield; 50/25/25 partial ladder.
- `engine.py` — multi-position (base + pyramids), pyramid sizing +50%/+25% with risk-zero gate + bundle ratchet; emits exit orders via broker port.
- `session_risk.py` — cushion/house-money sizing, 3-loss day cutoff, MDL = 2% of equity (marked to PnL), defensive mode.
- `engine bars` — 1-minute confirmations (interval 60) + optional ATR(14) range-bar mode.
- `dhan_feed.py` — consume depth packets into the book.
- `dhan_broker.py` — place/modify SL-LMT + TP, live close, `reconcile()` wired into runner.
- `runner.py` — restore-on-startup (load_state), wire mode/BrokerAdapter into routing (closes prior review's I2/I3/I4).

## Data flow

ticks+depth → prints/book/vwap/cvd/profile/absorption → triple_a/second_drive/phases/guards → setups (doc-priority) → stops (cluster anchors) → risk (cushion) → submit (+SL/TP orders live) → exits (partials, CVD-kill, shield) → coordinator → store/journal/snapshot.

## Testing strategy

Every ported module gets **contract tests pinned to the doc's exact numbers** (1.5× avg volume, 0.5× range compression, ≥60% one-sided, 68.2% VA, 0.8R BE, 15-bar staleness, 2R/3–5R TPs, 2% MDL, 3-loss cutoff, ≥30-lot bubbles, drive counter <3). End-to-end golden: replay the doc §15 walkthrough scenario (a synthetic session tape producing absorption → triple-A → entry → partials → trail → EOD) and assert the decision journal sequence.

## Error handling

Unchanged fail-closed rules. New: depth-frame malformed → drop frame, book keeps last-good state, loud warn (no trade decisions on stale book older than 10s). Live SL/TP placement failure → REJECTED entry (never enter unprotected) or force paper-exit path.

## Non-goals

No LLM advisor, no scanner/selector, no IB scalp engine, no options (Phase B), no multi-threading.
