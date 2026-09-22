# AMT Math Spec 4 — Seed, Rollover, and Multi-TF Design

Date: 2026-09-22

## System intent

History seed, live bars, replay, and backtest must advance the same
session-scoped AMT state exactly once per bar. A micro-timeframe close may
request an entry decision only while its macro AMT snapshot is no more than
one macro interval old. Completed-session profile levels must survive both a
next-session rollover and an EOD restart.

## Expected behavior contract

Inputs:
- Chronological, current-session OHLCV bars with real timestamps and deltas.
- A closed micro execution bar and the latest closed macro AMT DTO.
- A completed session DTO containing POC, VAH, VAL, and its final close.

Outputs:
- Seeded CVD equals the sum of seeded deltas.
- Seeded session VWAP equals volume-weighted typical price over every seed bar.
- IB contains every seed bar from the first session timestamp through its
  configured build window.
- Every AMT DTO carries the analyzed macro bar timestamp.
- A decision is attempted only when `0 <= micro_time - dto_time <=
  macro_interval`.
- Rollover/EOD persistence publishes the prior POC/VAH/VAL/close and NPOC for
  non-option instruments.

Timing and state transitions:
- `NOT_STARTED -> SEEDING -> READY|DEGRADED_*|FAILED`.
- Seed replay precedes the initial DTO publication.
- Date change persists the old session before clearing candles and resetting
  analyzer state.
- Missing, synthetic, future-dated, or older-than-one-interval DTO time is a
  fail-closed decision skip.

Failure modes:
- Empty history leaves the engine degraded without fabricating AMT state.
- Fewer than five seed bars may produce an empty analytical profile, but must
  still warm CVD, VWAP, and IB.
- Persistence without a valid POC/date is a no-op.

## Current architecture and verified mismatches

`AMTEngine` owns history fetch, the session candle ring, profile persistence,
and DTO publication. `AMTAnalyzer` owns CVD, VWAP, and IB session trackers.
`TickHandler` owns macro/micro cadence and is therefore the single freshness
boundary before `DecisionLoop`.

The seed path previously replayed all but the final candle and relied on
`analyze()` to consume the final candle. That worked only once the analyzer's
five-bar minimum was met. Two-to-four-bar seeds silently omitted the final
delta, volume, and IB observation. IB replay also lacked an explicit
session-open argument and had no duplicate-time guard.

The DTO serializer derived `time` from footprints, so a normal candle-derived
DTO frequently had an empty timestamp. Both futures and option micro paths
called `_decide` without validating snapshot age.

Rollover retention was already correct: date change saves levels and close,
updates non-option NPOC, reloads prior levels, clears candles/profile, and
resets the analyzer. EOD calls `persist_session_levels()` from the coordinator,
covering restart without a next-day bar.

## One production execution cycle

Assume four five-minute bars at 09:15–09:30 with deltas 10, 20, 30, 40 and
volumes 100, 200, 300, 400:

1. The scheduler returns the current-session bars.
2. The incremental profile consumes all four bars.
3. Analyzer warmup consumes all four in timestamp order. CVD becomes 100;
   VWAP contains 1,000 volume units; IB is anchored at 09:15 and contains four
   unique bars.
4. Initial analysis may return the insufficient-data shape, but duplicate-time
   guards prevent its current bar from being accumulated again.
5. The DTO is stamped 09:30 explicitly.
6. A 09:35 micro close sees age=300 seconds and may decide. A 09:36 close sees
   age=360 seconds and is skipped before Gate1–4.
7. On the next dated bar, the 09:21 session levels are saved and loaded as
   prior levels before the new bar enters a reset analyzer.

No step depends on an unstated replay side effect.

## Correct ownership

- Session trackers own timestamp idempotence.
- `AMTAnalyzer.warmup_candles` owns complete chronological tracker replay.
- `AMTEngine` owns authoritative DTO bar time and session persistence.
- `TickHandler` owns one shared fail-closed macro freshness check.
- Gate1–4, scanner, auction, TimesFM, option selection, and sizing remain
  unchanged.
