# quantv2 End-to-End — Design (big-bang, full production)

**Goal:** `quantv2/` fully independent of v1 `quant/` (zero imports) and complete end to end: raw bars → own AMT → decision → paper/live execution → multi-symbol coordination → persistence → EOD → WS snapshots. Proof: paper-live N sessions, then broker.

**Locked decisions:** own minimal AMT from raw bars; full production boundary (broker + coordinator + persistence + EOD + WS); paper-live proof; single big-bang plan.

## Architecture

```
ticks → aggregator → amt → pipeline(decide) → oms(paper|live) → exits
       coordinator (N engines, portfolio ceiling, EOD) → store → ws snapshot
```

One trigger (main-bar close). APPROVED only post-submit. Exceptions → REJECTED.

## Components

- `amt.py` — session volume profile (POC/VAH/VAL), VWAP±2σ, CVD slope, absorption side, drive counter, break type/dir, squeeze level. Raw `Bar`s in, `Context` out. Excluded: VARS/GEX/halftrend/IB (display-only in v1, never gated entries).
- `pipeline.py` (extend) — add `submit()` step: size → gate → submit → APPROVED; try/except around detect/build → REJECTED. Stop-cap constant (200 ticks / 0.75%) kept as single constant. Delete `Context.direction` (setups own direction). Single `tick` threaded Engine→setups→stops. Canonical setup names: TRIPLE_A, SECOND_DRIVE, LVN_SNIPER, INITIATIVE, SQUEEZE, VA_FADE.
- `oms.py` — paper OMS: `submit(signal, qty) -> Position`, `close(position, price, reason) -> Fill`, partial-close. Pure in-memory, no v1 imports.
- `exits.py` — SL / TP tiers / trailing / breakeven / time-stop / session-close. Position in, exit decision out. No thesis-flip.
- `engine.py` (extend) — own aggregation (tick→bar), drive pipeline on main-bar close, own exits while positioned, EOD flatten hook. Fix `on_bar_close` double-`position_open` kw crash; return `Decision` (never bare None — use `Decision(False, "POSITION_OPEN")`).
- `risk.py` (extend) — portfolio ceiling joins the single gate (per-trade + aggregate before approval).
- `coordinator.py` — N engines, shared portfolio ceiling, session EOD square-off, force-close watchdog.
- `store.py` — JSON persistence: open positions + risk state; crash-restore path.
- `broker.py` — `IBroker`-compatible live adapter interface + paper-live mode (live feed, paper OMS). No real orders until paper-live green.
- `snapshot.py` — read-only WS view: positions, last decision per symbol, risk state. No decision logic.
- `replay.py` (extend) — real-tape runner: v1-fed contexts vs v2 contexts, assertions (v2 signals ⊆ v1 setups, zero phantom, RR≥1.5, monotonic).

## Data flow

Flat bar close → `amt(bar)` → setup arms (priority TRIPLE_A > SECOND_DRIVE > LVN_SNIPER > INITIATIVE > SQUEEZE > VA_FADE) → `stops` → `size` → portfolio+session gate → `submit` → `PositionOpened`. Positioned bars → `exits` only. Every rejection carries a reason; UI clears ENTER on any REJECTED.

## Error handling (fail closed)

Detect/build exception → REJECTED. Submit raise → unwind reservation, stay flat, loud log. Close raise → keep position, retry next bar. Corrupt store → fresh state + halted flag. No silent drops: every blocked approval emits its reason.

## Testing gate (all must pass pre-paper-live)

- Unit per module (TDD, as in P0 plan).
- Tape gate: checked-in real tapes; v2 signals ⊆ v1 setup hits; zero APPROVED without position; every SL/TP monotonic with RR≥1.5.
- Paper-live: N sessions (N chosen by operator at the time, minimum 5) on live feed with paper OMS; P&L/rejection-ratio review before broker enable.

## Non-goals

No LLM advisor, no scanner/selector, no pyramids, no tick-level partials, no v1 imports anywhere (CI-grep gate: `quantv2/` must not reference `quant.`).
