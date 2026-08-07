# WS-SMOKE report — in-process paper-protocol smoke test (§5.5)

**Branch:** `migration/ws-smoke` (worktree `/Users/apple/Documents/wt-ws-smoke`)
**Date:** 2026-08-07

## Status: DONE — all invariants hold, nothing failed

## Commits (worktree `migration/ws-smoke`)

- `cd74a78` `test(system): paper-protocol invariants (no-trade-no-edge, no-fabricated-data, fill, idempotent exits)` — `tests/system/test_paper_protocol.py`

**Not committed** (per brief): this report lives in the main repo's
`.superpowers/` and is intentionally left out of the worktree commit; nothing
else outside `tests/system/` was touched.

## Verification

- `pytest tests/system -q --tb=short` → **19 passed** (8 new paper-protocol + 11 existing system).
- `pytest tests/quant -q --tb=short` → **1361 passed, 30 skipped** (unchanged).
- Deterministic: engine replayed twice → identical event trace (asserted).

## Deliverable — `tests/system/test_paper_protocol.py`

Boots a fresh `QuantEngine(SyntheticGateway, ...)` (interval_seconds=1,
tick_size=0.05, no network, engine untouched) on a deterministic 240-bar
session built as 480 synthetic ticks (2 ticks/bar, reconstructed 1:1 by the
interval aggregator). Session shape:

| bars | setup |
| --- | --- |
| 0–79 | quiet stretch 1 @100 (0.1 range, vol 20) → WAITING |
| 80–82 | 5× zero-range buy-absorption spike @100 + 2 quiet bars → ABSORBING → ACCUMULATING |
| 83–89 | breakout closes 100.6→102.9 above vwap.upper_1 → **AGGRESSION-LONG** (bar 83, `t166`), TP exit @102.1 (bar 87) |
| 90–169 | quiet stretch 2 @105 (zero-range, vol 200) — re-centres the volume profile @105 |
| 170 | VAL-bounce dip 104.92: zone BELOW_VA, close > VWAP, buyer CVD, no Triple-A edge → **VA_FADE LONG** (`t340`), TP exit @105.05 (bar 171) |
| 171–239 | recovery 105.05→105.5 back toward POC, then quiet tail @105 |

Approved decisions produced:
- `t166` **Triple-A**, phase AGGRESSION, LONG entry 100.6 sl 99.976 tp 101.848 rr 2.00 → closed TP 102.1, pnl +2403.85
- `t340` **VA_FADE**, phase ACCUMULATING, LONG entry 104.92 sl 104.899 tp 104.975 rr 2.61 → closed TP 105.05, pnl +6190.48

## Invariants (all asserted, all passed)

- **A — no-trade-no-edge:** each `PositionOpened` (`t166`, `t340`) maps 1:1 by
  bar-time to an `approved=True` `DecisionProduced`; the position's
  order.signal (type/entry/reason/timestamp) matches the approved decision's
  signal. **Approved-decisions-without-position: 0.** Reason: in the current
  `QuantEngine`, `_decide` is only reached while flat and opens a position
  unconditionally on `SignalApproved` — the cooldown/risk gates exist in
  `DecisionContext` (engine hardcodes them pre-open), so no approval can be
  skipped today. The test still *counts* skips, logs each with its gate results,
  and fails only on skips unexplained by gate-2 (position-open/cooldown/risk)
  or a missing signal — so it stays correct if a real cooldown gate is added.
- **B — no fabricated data:** 240 bars closed == 480 ticks / 2 (no count
  inflation); `sum(bar.volume) == sum(tick.volume)` (volumes are exactly the
  feed's, nothing invented); every bar volume > 0 (no zero-volume candles for
  non-zero-volume inputs); every bar close and every `auction.close` is a real
  price from the feed tick set; the StateProjector never emits a zero-volume
  `tick` or a `close` not present in the feed.
- **C — fill within spread:** every entry/exit fill deviates ≤ tick_size (0.05)
  from the signal bar close — actually 0.0, since PaperOMS fills at
  `signal.entry` (= bar close) and ExitEngine at the exit bar's close. Spot
  checks: entry @100.6 == `t166` close, entry @104.92 == `t340` close, exits
  @102.1 / @105.05 == their close bars.
- **D — idempotent exits:** 2 opens / 2 closes; position ids unique; closed ids
  == opened ids; each id closes exactly once (Counter == all-ones).
- **WS contract:** folding events into a fresh `StateProjector`, the approved
  setup bars still carry `auction` + `quantDecision`; `quantDecision.approved`
  True with reason Triple-A/VA_FADE and matching `signal.type`; at `t166`
  `auction.tripleAPhase == AGGRESSION`, `tripleASignal == LONG`.

## Concerns

- **Fade stop is razor-thin by construction:** `detect_va_fade` defines
  LONG `sl = val - step` with `tp = poc`, and in a real profile POC sits only a
  step or so above VAL, so the approved fade requires `entry` inside
  `(val - step, val)` and R:R ≥ 1.5 forces the stop to ~2 cents
  (entry 104.92, sl 104.90). `SessionRisk.position_size` then sizes ~50,000
  units → paper pnl +6190 on a 0.13 move. That is the engine's deterministic
  behavior (not a harness artifact) and breaks no invariant, but it is a
  realisim flag worth a future look (min stop distance / max position size).
  The chosen dip (104.92, rr 2.61) is the least extreme value in the approved
  window (104.90 gave rr 74.75).
- **WS snapshot is only as fresh as the last folded event** — the frontend sees
  the AGGRESSION bar only because this test snapshots mid-trace; the existing
  `test_quant_runtime_e2e.py` still covers the "stopped-at-signal" final state.
- **Tick-level fidelity:** high/low derive from open/close (2 ticks/bar), so the
  exit engine always sees `high == low == close`. Exit decisions (SL/TP) are
  therefore close-based only — fine for these setups (TP was reached on close),
  but a test needing intra-bar high/low would need 4-tick bars.
