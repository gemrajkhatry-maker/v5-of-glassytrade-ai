# WS-BUGFIX — Sanctioned brain bug fixes (audit B-20 + latent bugs)

**Worktree:** `/Users/apple/Documents/wt-ws-bugfix` (branch `migration/ws-bugfix`). Work ONLY there.

**From:** brain-migration plan AUDIT ADOPTION → WS-BUGFIX. These are the sanctioned deviations from "no behavior change": real bugs, each fixed in its own commit with a regression test.

**Bug 1 — Double VWAP accumulation (audit B-20, Critical).** `quant/amt/analyzer.py` calls `self._update_session_vwap(current, typical_price)` at BOTH line 1029 and line 1096 inside `analyze()`, so volume+quote-volume accumulate twice per bar, corrupting VWAP. Read both call sites (lines ~1020-1100) and determine which one is the real update (the one whose result is USED to build the VWAP bands in the returned state) — keep that one, delete the other (the audit says the duplicate at 1030/1097 double-accumulates). Add a regression test: feed a known 2-candle series through `AMTAnalyzer.analyze` twice and assert the VWAP value equals the single-pass expectation (i.e., not double-accumulated). This test must FAIL before the fix and PASS after.

**Bug 2 — `drive_decay.py` UnboundLocalError.** `quant/amt/orderflow/drive_decay.py` (~line 115) references a variable (`record`) before assignment in some path (flagged in Track A3). Read it, fix the assignment order, add a regression test hitting the failing path.

**Bug 3 — `drive.py` undefined `tick_size`.** `quant/amt/orderflow/drive.py::is_level_exhausted` / `get_drive_count` use a `tick_size` parameter that isn't defined in scope (flagged in Track A3). Fix (add the parameter with the module's default, or use a class default), add a regression test.

**Bug 4 — `break_detector.py` dead-code tail.** `quant/amt/market/break_detector.py` lines ~205-286 are an unreachable duplicated tail (flagged in Track A2 review). Delete it, confirm the module's public behavior is unchanged (existing tests pass).

**Verify (after each fix):** `/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant -q --tb=short` (worktree root). Then the backend unit suite to confirm nothing regressed. Report exact counts (4 pre-existing env errors acceptable).

**Commits:** one per bug: `fix(quant): single VWAP accumulation per bar (B-20)`, `fix(quant): drive_decay record-before-assign`, `fix(quant): drive undefined tick_size`, `fix(quant): remove dead code tail in break_detector`.

**Report:** `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/ws-bugfix-report.md`. Reply: status, commits, test counts (incl. the RED→GREEN evidence for Bug 1), concerns.
