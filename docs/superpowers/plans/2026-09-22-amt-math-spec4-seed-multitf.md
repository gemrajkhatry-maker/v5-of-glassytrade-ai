# AMT Math Spec 4 — Seed and Multi-TF Plan

Date: 2026-09-22

1. Lock seed replay with a production-component regression using the real
   scheduler, AMT engine, analyzer, trackers, and session-level store.
2. Replay every seeded candle through CVD, VWAP, and IB. Pin IB to the first
   seed timestamp and make equal-timestamp IB updates idempotent.
3. Stamp every engine-produced DTO with the analyzed bar time rather than
   relying on optional footprint timestamps.
4. Lock rollover retention with an engine/store/NPOC regression. Keep the
   verified rollover and EOD persistence paths unchanged.
5. Add one shared `TickHandler` freshness boundary and route futures and option
   entry call sites through it. Reject missing, unparseable, future, or
   older-than-one-macro-interval timestamps.
6. Run focused seed/IB/freshness tests, then the required architecture, AMT,
   decision, execution, and runtime merge gate.

No Gate1–4, auction, TimesFM, option-scanner, sizing, or money-path behavior is
changed.
