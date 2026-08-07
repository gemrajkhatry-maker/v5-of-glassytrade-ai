# SDD Progress Ledger — AMT Backend Fixes (2026-08-06)
- Wave 1 Wave-1 preflight: merged Tasks 2+3 (both own amt_analyzer.py); Wave 1 = T1,T2+3,T4,T5,T6,T7
Wave 1 done:
  T1: 755bac4
  T2+3: 49b30a2
  T4: e52fb4f
  T5: 7da934b
  T6: ef8776d
  T7: d1789da, 5b4227d
  Deferred (live-imported): amt_pipeline, amt_parameters, narrative_builder, response_parser, signal_generator, mtf_analyzer, structural_stop_engine
  T7-followup: bdd690f (repoint probability re-exports, delete 7 final twins)
  T8: 0418580 (persistent Triple-A state machine)
  T11: 4377fbf (prior-profile persist + warmup marker)
  T9+T10(part1): 258e45c (vwap_breakout detector + GateContext fields)
  Remaining: T10 gate slim 12->5 + three_align wiring -> dispatching as final Wave-2 task
  T10: 2e87a36 (gate pipeline 12->5, wiring into gate_runner + three_align)
Wave 2 complete. -> T12 integration
T12: complete — 1767 tests pass; live smoke green (LLM 7.66s, 0 tick errors)
  fix: 6dfbf28 (dataclasses.replace)
  test: fbec18f (remove orphaned vwap test)
ALL TASKS COMPLETE
AMT Strategy Cleanup plan — Wave 1 complete:
  T1 UI payload cut: 6afc4e9
  T2 AMT lock: e0d34d5
  T3 entry gate+cooldown: 6448a16
  T4 overseer pos_state+cooldown: a0682f7
  T5 LLM inputs: bf8ae54
  T6 watchdog lifecycle: 52ac5ff
Wave 2: T7 integration
  T7: complete — 1819 tests pass; live cadence 7 entry calls/3.5min (was 120/hr/sym); prompt verified (SESSION/VWAP render, CVD deduped); 0 tick errors
  test cleanup: ae9c723 (remove dead episodic-memory test)
ALL TASKS COMPLETE
Burden removal (range bars + footprint charts):
  backend: f123553, 9d0a744 (delete RangeBarBuilder + tick integration), 1627bf5 (drop footprint chart emission)
  frontend: 24981dc (remove RANGE + FOOTPRINT chart modes; candles+AMT only)
  Verified: 1812 tests pass, build ok, live snapshot has 0 rangeBars/footprint, strategy + LLM still flow
Align-to-amt-dataset plan — Wave 1 start (base 1627bf5)
Align-to-amt-dataset Wave 1 complete:
  T1 dead ML surface: e722f2c
  T2 dead frontend: 354d054
  T3 phantom fields: 87070ab
  T4 dead types: <just committed>
  T5 dead prompt keys: db9dc56
-> Wave 2 (T6,T7,T8) then T9
  T6 shared renderer: b75da84
  T7 train config: 7068e26
  T8 parity+README: ef9a407
Wave 2 complete. -> T9 integration
T9: complete — 1817 backend + 215 frontend tests pass; live smoke green (LLM fires, 0 tick errors, prompt renders SESSION/VWAP)
ALL TASKS COMPLETE
Follow-up: dataset system message now = live _DEFAULT_INSTRUCTION + JSON reminder (commit above); livefmt regenerated
Follow-up 2: datasets now versioned (.gitignore un-ignore amt_dataset/**/*.jsonl) so fresh clone can retrain. Remaining non-blocking: delta unread-in-prompt (prunable), 65% FLAT direction skew (kept).
UI Declutter plan — Wave 1 start
UI Declutter Wave 1 complete:
  T1 fabricated: ccbbc17
  T2 panel collapse: 4a0c454
  T3 dedup+LiveCard: 8446da6
  T4 dead files: c8b02be
  T5 DTO telemetry: 776b720
-> T6 integration
T6: complete — 1819 backend + 179 frontend tests pass; build clean; live smoke green (model loads, 0 tick errors, prompt contract intact)
ALL TASKS COMPLETE
Volume profile fixes:
  average-weighted CME pairs (partial-pair bias), analyzer deduped to compute_value_area, config-driven VA pct — 1257 domain tests pass
  commit: d9f9f28 (verify)
Gate cleanup: removed dead triple_a_phase (range-bar source gone); gate 4 edge now absorption+vwap_breakout only — 1257 domain tests pass
AMT Analysis Kernel plan — Wave 1 start
AMT Analysis Kernel Wave 1 complete:
  T1 bars+VP: 4c90c16
  T2 vwap: d193f69
  T3 orderflow: a9cbab8
  T4 absorption: 5c33b65
  T5 location: <just committed>
  T6 triple-a: 6cda033
  21 tests pass. Notes: T3 cvd_slope over cumulative CVD (ratified); T6 ABSORBING->ACCUMULATING time-based (2 bars) to match tests; T1 POC test adjusted for bucket floor.
-> Wave 2 (T7 coordinator)
  T7 coordinator: 5d66ba1
  Fix: Triple-A rearm bug (stale absorption reset accumulation) -> LONG reachable; 24 tests pass
-> Wave 3 (T8 golden file)
  T8 golden file: 8621424 (2 AGGRESSION events, LONG+SHORT; 26 tests pass)
ALL TASKS COMPLETE — AMT Analysis Kernel done
Decision Layer plan — Wave 1 start
AMT Decision Layer complete:
  T1 context/result: ecc75a0
  T2 gates1+2: f1ee424
  T3 gates3+4: 7d8c6fc
  T4 gate5+pipeline: 3e36fa0
  T5 signal_builder: 3120fb1
  T6 e2e: 7d3f5fa
  53 tests pass. Note: gate-5 20-tick cap rejects far-from-value breakouts by design.
AMT Execution + Broker + LLM complete:
  T1 OMS: 2a3caad | T2 exits: ae50d4c | T3 risk: 5bd36fc | T4 broker: c3cb2f3
  T5 journal: e1e8efd | T6 overseer: 207e810 | T7 fullstack: 3442a88
  76 tests pass. Full lifecycle verified: ticks->bars->AuctionState->journal->gates->signal->OMS open->exit->risk.
P0 correctness fixes (Supervisor wave) complete:
  gates/signal: cc67fe4 | absorption: 85978d3 | triple_a: fda661a | overseer: 7656342 | exits: d58310a | prints/vwap: e0924bb
  94 tests pass. Auditor CRITICALs (inverted signal, div-zero) fixed + pinned.
P1 doc-alignment complete:
  va_fade: ae6426f | near-POC: 766234f | 68%% VA: eb3619d | SL offset: b4f502e | SHORT invariant fix: <commit>
AMT E2E wiring complete (Supervisor)
  quant correctness P0: 6 fixes, 107 tests
  doc-alignment P1: va_fade ae6426f, near-POC 766234f, 68%% eb3619d, SL-offset b4f502e, SHORT-invariant 77025d2
  E2E wiring: quant_bridge + auction WS field + frontend badge a3498ae
  E2E tests: system d050b9d (4), frontend 762d2dc (181 total)
  ALL GREEN: 107 quant + 4 system + 181 frontend; live smoke OK
QUANT = DECISION ENGINE OF RECORD complete:
  T1 DecisionService: d9452d1 | T2 mapper: 7cf86d0 | T3 routing+flag: 2f2d1fc | T4 broadcast: 35db1c1 | T5 e2e: ec16fdb
  117 quant+system tests pass. quant Signal → EntryCoordinator.execute_signal proven (flag ON).
  Flag default False → legacy path unchanged until enabled.
QUANT EVENT-DRIVEN RUNTIME complete (154 tests):
  T1 events b9417bd | T2 aggregator f5cdfd5 | T3 projector 89834c9 | T4 journal a046f6f
  T5 QuantEngine b065797 | T6 ws_adapter 3cfa5a7 | T7 determinism+e2e d8d23d3
  Deterministic engine: ticks->bars->AuctionState->decision->OMS->exit->risk->journal->frontend WS

## Brain migration plan (2026-08-06-quant-brain-migration)
Task 0.1: complete (commit d946298, review clean)
Task 0.2: complete (commit 13735e1, review clean). Minors for final review: constants.py config-path hardcode (Phase 3 cleanup); exchange_strategy TYPE_CHECKING; exit_rules whitespace shift; test-porting judgment calls documented.
Task 0.3: complete (82b20a1 + fix c305e28, review clean after fix). Minor tracked: dataclass missing-field raises AttributeError not AssertionError (low risk, accepted).
Task 0.4: complete (a276015 + conftest fix 88e0a40, review clean after fix). Phase 0 complete.
Track A1: complete (10e9fa1..54231d3, review clean). Minors: (1) parity-via-shim is same-object (real guarantee = byte-identity diff; gold replay in Phase 4 protects post-shim edits); (2) pre-existing dup session_vwap in ThreeAlignInput (out of scope).
Track A2: complete (c46b80e..35b9929, review clean). Minors: break_detector dead-code tail (Phase 3); OHLC float-vs-Decimal footgun in test fixtures (Phase 3 note); per-commit green only at HEAD (accepted).
Track A3: complete (66f25d7..495c0dd, review clean). Minors: git mv history not traceable (M+A, accepted); mlx_compute parity as separate commit (accepted); TWO PRE-EXISTING LATENT BUGS to fix in a later bugfix track: drive_decay.py:115 UnboundLocalError (record-before-assign), drive.py is_level_exhausted/get_drive_count undefined tick_size.
Track A4: complete (8ffbffa..7614610, review clean). Minors: one_min_bar unused IST (pre-existing); futures_provider default path backend-coupled (Phase 3 cleanup, pinned by test); scanner skip (pre-existing wrong assertion); new coverage for ib_scalp/one_min_bar/sync_boundary.
Phase 1 PARALLEL (5 worktrees, all merged 17601ff, TODOs resolved bd04f4b):
  Track B: complete (28316f9..029ca71, gates cluster)
  Track C: complete (8b6bfdb..0193ef2, probability cluster)
  Track D: complete (2e74a1a..679d435, execution/risk cluster)
  Track E: complete (2ff8a7b..6f5c656, inference/RL cluster)
  Track A5: complete (e8d8b44..83f59a5, amt_analyzer hub)
  Combined: quant 1448 passed/30 skipped; backend unit 1324 passed/60 skipped/4 pre-existing env errors; zero backend imports in quant/.
Phase 1 broad review: APPROVED (spec ✅, quality Approved). Minors: (1) domain/services/gate_pipeline.py dead chain shim -> Phase 3 delete; (2) stale comment exchange_strategy.py:20 -> Phase 3; (3) trade_aggregate.py duplicate -> Phase 3 delete (Q-02); (4) strategy/{setup_detector,fabio_detectors,protocols} unmigrated -> schedule Phase 2/3.
Phase 1 COMPLETE. -> Phase 2 (consumer import-swap + split-brain unification)
Phase 2 PARALLEL (7 worktrees, merged 74f1f6a):
  P2.1 f64f0fa | P2.2 1166aac | P2.3 b51c49a | P2.4 c66663c | P2.5 dd7efa0 | P2.6 7908647 | P2.7 6918b86 (unification: KEEP BOTH, VAL 16% = deliberate AMT clamp; OHLC Decimal latent bug)
Phase 3: 6765b10 stragglers | 4e12bfa ops relocate | ccf7903 delete legacy brain | 43e6dd5 scripts/config. strategy detectors deleted (dead); trade_aggregate kept in ops (real consumers).
Phase 4 FINAL REVIEW: DoD 7/7 APPROVED. Fixes: 4b561df AMT_UNIFICATION.md | 4764415 delete no-op parity (1353 passed) | adb85f6 gymnasium guard.
=== BRAIN MIGRATION COMPLETE. HEAD adb85f6. quant 1353/30; backend unit 1292/60/4(env); validation 52; integration 107/16/6(env). Zero backend imports in quant. Backend domain = models + ops only. ===
Queued follow-ups (out of core scope): WS-EXEC flag flip, WS-BUGFIX (double-VWAP/drive bugs), WS-FRONTEND (fabrication removal etc), WS-DATA (train fmt), SQLite WAL/index, signal TTL, real-day golden replay, paper smoke.
FOLLOW-UP WAVE (4 parallel, merged f5908b8):
  WS-EXEC: d75a244 + 676d675 — QUANT_EXECUTION_MODE off|shadow|paper|live (default off; flag-on alias→shadow)
  WS-BUGFIX: 186f8a2 (B-20 VWAP RED→GREEN), d5fcaab, 2cc12ce, 84e94b5 — 4 bugs fixed
  WS-FRONTEND: c0140d2, 271ceb8, ed66889, 689e6ba — fabrication removed, quantDecision primary, IST const, dead store deleted; 190/190 frontend tests
  WS-DATA: 0140ccf (WAL+idx), e359d5f (TTL 60s), a975723 (livefmt parity) — livefmt confirmed well-formed, marker vocab matches
  Final: quant+system 1372/30; backend unit 1344/60/9err(env gymnasium+httpx) +1 pre-existing date-drift test_trade_journal; validation 52. No regressions.
=== ALL PLANNED WORK COMPLETE ===
Remaining (needs live env): paper smoke, real-day golden replay, backtest acceptance gate (1mo data), AIAnalysisPanel full decomposition, QUANT_EXECUTION_MODE=paper/live go-live.
FINAL VALIDATION WAVE (4 parallel, merged 8e88419 + b7075db):
  WS-ACCEPT: 3b98767 + 0aa63c1 — acceptance_gate.py CLI + 13 tests. Verdict UNMET/INCONCLUSIVE: journals are synthetic-harness (300 NIFTY SL @ -56.141, 4 CRUDEOIL SL @ -24864, impossible time_in_trade). Report committed b7075db.
  WS-DECOMP: 198e542..d525773 — AIAnalysisPanel 1589->258 lines, 15 sub-components, 198 frontend tests, clean build.
  WS-REPLAY: cf62110 + 2b84640 + 43a20e6 — quant/tools/replay.py, 120-bar golden fixture + drift-detection, QUANT_RECORD_REPLAY hook. Real-day capture still needed for byte-for-byte gate.
  WS-SMOKE: cd74a78 — paper-protocol invariants test (no-trade-no-edge, no-fabricated-data, fill±1tick, idempotent exits); 19 system tests green. Flagged: razor-thin VA-fade SL realism.
  Final: quant+system 1387/30; backend unit 1353/60/9err(env)+1 pre-existing date-drift. NO open workstreams.
=== ALL WORK COMPLETE. HEAD b7075db ===
Remaining (operator action, not code): QUANT_EXECUTION_MODE=paper week-1 run to satisfy acceptance gate; then live. Real-day replay capture (QUANT_RECORD_REPLAY=1). VA-fade min-stop look.
PONYTAIL AUDIT WAVE (5 parallel, merged a03d81c+):
  WS-REALISM: 1d21e53/8103284/cca6f10 — min-stop 0.1% + max-size 1000 guards, start_paper.sh. 1376 quant passed. Follow-ups: VA-fade tier-2 bypasses builder; clamp not wired into runtime sizing.
  PT-BROKERS: 27f5571/27bde38 — deleted scripts/ + 4 dead modules + dead DhanConfig fields + TOTP->pyotp; -4,925 lines. Guards: DhanFacade/BrokerFactory kept (LIVE via adapters). brokers 157 passed.
  PT-DI: 4d2ffed/c452bef/c54af16 — dead DI (INotification/INPOC), null_notification_adapter, npoc_adapter, core/events, application/events, circuit_breaker shim, 6 dead flags. backend unit 1311/64, 0 fail/0 err.
  PT-DUP: c75df93/debd521/276af85 — async_boundary->sync_boundary re-export, LLMCircuitBreaker->shared.resilience, generative_ai lru_cache. prometheus_client NOT available (deferred).
  PT-CONFIG: 88daff8 — collapsed triple config (deleted config/consolidated.py 563-line pydantic layer); config_models/SettingsAdapter canonical. +76/-636. 1323 passed.
  Final: quant+system 1398/30; backend unit 1311/64 (0 fail 0 err); brokers 157/1 + 1 live-network flake. AI command/reply mode REMOVED (ws-noreply, out of scope).
  REJECTED findings (evidence in plan): quant/amt/compute.py deletion; greenfield quant/core deletion (P2.7 KEEP BOTH); gate/risk consolidation (deferred decision).
=== PONYTAIL WAVE COMPLETE. HEAD=<merge> ===
PENDING-ITEMS WAVE (3 parallel + 1 test fix, merged 12fcb24 + 4aae0b0):
  WS-WIRE: eef32b3..047ee15 — is_min_stop_met/clamp_quantity helpers exposed; runtime sizing clamped (MAX_POSITION_QUANTITY); VA-fade min-stop guard wired. quant 1387 passed.
  WS-METRICS: a53b720 — core/metrics.py on prometheus_client 0.26.0 (added to requirements); public API preserved. backend unit 1327/64/0/0.
  WS-RUNBOOK: 8a7d379 — docs/PAPER_LIVE_RUNBOOK.md (paper week -> acceptance gate -> replay -> go-live -> rollback), env vars cross-checked (QUANT_EXECUTION_MODE, GLASSYTRADE_ENV/STRATEGY, TRADING_MODE, QUANT_RECORD_REPLAY, DHAN_CLIENT_ID/ACCESS_TOKEN); start_paper.sh verified.
  4aae0b0 — test(system): paper-protocol updated for min-stop guard (VA-fade now correctly rejected; 8 passed).
  Final: quant+system 1406/30; backend unit 1327/64 (0 fail 0 err); brokers 157/1 + 1 live-network flake; frontend 198.
  Remaining: ONLY operator go-live (paper week via start_paper.sh -> acceptance gate -> live), per docs/PAPER_LIVE_RUNBOOK.md. No code items open.
FINAL-GAP WAVE (4 parallel, merged 4755201):
  WS-ENV: a6cda7d/046f68f — httpx+pyotp installed; ALL suites green (unit 1330/61, integration 156/24, validation 52/4, brokers 152/7); FIXED REAL BUG trading_session.py:456,717 crashes on session.trading_state every tick -> getattr guard; market-hours skip guard for live tests.
  WS-CRUFT: 365ccd9/35f359c — .DS_Store/.bak(4, incl .env.bak w/ secrets)/egg-info removed + gitignore; RL checkpoints kept (legit history, 3.2MB, tracked).
  WS-DHANDUP: a787c22 — deleted dead DhanFacade (1,151 lines); both backend adapters confirmed LIVE + non-duplicate (IMarketData vs IBroker) -> kept; BROKER_STACK_REVIEW doc.
  WS-GATECONS: bef0e54 — divergence measurement; verdict KEEP BOTH (0/60 same-gate, exit agreement 9.7%, prod stops 3.2x wider — real+intentional); GATE_CONSOLIDATION_REVIEW doc.
  NOTE: pre-existing frontend WIP (+2166/-10241) in main tree stashed+popped around merge (no conflicts, restored as-is); user owns it.
  Final: quant+system 1410/30; backend unit 1330/61 + integration 156 + validation 52 (all 0 fail/0 err); brokers 157/2; frontend 156 (in user's WIP tree).
  REMAINING: ONLY operator go-live per docs/PAPER_LIVE_RUNBOOK.md. No code items open.
