# quantv2 Clean Implementation — Design

**Goal:** Fresh `quantv2/` with zero legacy parity: same 5 setup names, none of v1's flood. One trigger, one shared stop/RR/risk gate, no phantom APPROVED.

**Locked decisions:** setups = TRIPLE_A + SECOND_DRIVE + LVN_SNIPER + VA_FADE + INITIATIVE/SQUEEZE (explicit arms, shared gate); trigger = main bar close only; blocked approval emits REJECTED; location = `quantv2/` fresh, v1 frozen; proof = deterministic replay gate.

## Architecture

Single pipeline, no micro/underlying dual path:

```
ticks → engine (aggregate main bars) → amt_core → setups → stops → risk → submit
```

v1's 4 `_decide` sites (`quant/runtime.py:581,601,635,769`) collapse to 1. `SignalApproved` fires only after size + risk + submit succeed.

## Components (8 source files + 1 harness, ponytail: fewest that hold)

- `quantv2/types.py` — Bar, Context (Optional prices, no `0.0` defaults), Signal, Decision(REJECTED reason).
- `quantv2/amt.py` — POC/VA/VWAP±2σ, CVD slope, absorption side, drive flags, break type/dir, squeeze level, VARS flags. Display-only (GEX, halftrend, IB windows) excluded.
- `quantv2/setups.py` — 5 explicit arms returning `SetupHit | None`. No direction inference here.
- `quantv2/direction.py` — folded into setups: each arm declares its own direction; no global `_resolve_direction` fallback chain (deletes `quant/decision/context_builder.py:98` 8-fallback chain).
- `quantv2/stops.py` — sole anchor/stop/TP/RR. Port of `quant/decision/stops.py` + `SessionRisk.position_size` sizing math; deletes `va_fade.py:61` probe-stop and `signal_builder.py:121` fallback-stop.
- `quantv2/risk.py` — session halt + cooldown + portfolio ceiling in one `can_trade()` called BEFORE approval (fixes `quant/runtime.py:942` approved-then-dropped).
- `quantv2/pipeline.py` + `engine.py` — Gate1 session → Gate2 cooldown/position → Gate3 setups → Gate4 stop-cap → size → submit. Engine <300 lines: aggregate, call pipeline on main-bar close, own exits (SL/TP/trail/time only, no thesis-flip flatten).

## Data flow

Flat bar close → `amt()` → each setup arm evaluated independently → first hit wins (priority: TRIPLE_A > SECOND_DRIVE > LVN > INITIATIVE > SQUEEZE > VA_FADE) → `stops()` → `risk()` → submit → emit `PositionOpened`. Any gate fail emits `DecisionProduced(rejected, reason)`; nothing emitted as APPROVED unless the order exists.

## Single threshold table (deletes 6 CVD magnitudes, 3 stop formulas)

CVD: block ±0.5 (NSE) / ±0.3 (MCX); confirm ±0.2; squeeze ±0.1; fade >0/<0 removed (uses ±0.2). OBI ±0.20, OFI ±0.10. Proximity 2 ticks (LVN + squeeze统一). RR ≥1.5 enforced in stops (no 2R fallback pass). Stop-cap 200 ticks / 0.75% kept as single constant.

## Error handling (fail closed)

Gate exception → REJECTED. OMS submit raise → unwind portfolio reservation, keep flat, loud log (port `quant/runtime.py:990`). Zero-qty sizing → REJECTED (no phantom). No thesis-flip: positioned bars run exits only.

## Replay harness (minimal, answers "do we need replay")

`quantv2/replay.py` only: `ticks[] → engine` feeder + assert gate. Skipped: history seeding, journal/event-store fold, startup reconciliation, multi-engine replay. Reuses PaperOMS fill semantics, not its code.

## Testing gate (must pass before cutover)

Replay same tick tapes in v1 vs v2: v2 signals ≤ v1 setups hit; zero `APPROVED` without `PositionOpened`; every TP/SL pair RR ≥1.5 and monotonic; per-symbol cutover behind flag.

## Non-goals

No LLM advisor, no scanner/selector, no IB scalp engine, no pyramid add-ons, no tick-level TP partials in v2 scope. Add when a journal says so.
