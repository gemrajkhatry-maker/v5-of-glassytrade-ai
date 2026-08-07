# WS-EXEC — Wire quant decisions to execution behind an A/B mode

**Worktree:** `/Users/apple/Documents/wt-ws-exec` (branch `migration/ws-exec`). Work ONLY there.

**From:** brain-migration plan AUDIT ADOPTION → WS-EXEC (audit B-22/B-12: "quant decisions never execute").

**Goal:** make the quant decision path *able* to execute, behind an explicit mode, with a SAFE default that changes nothing dangerous. Honors the architecture proposal §5.5 paper→live protocol.

**Design:**
- Add `QUANT_EXECUTION_MODE` config with values `off | shadow | paper | live`. **Default: `off`** (byte-identical to today).
  - `off`: decisions are NOT computed (identical to today's `QUANT_DECISION_ENABLED=false`).
  - `shadow`: decisions ARE computed and broadcast as `quantDecision` (what today's flag-on does) but `_try_execute_quant_decision` does NOT route to the entry coordinator (it logs what it WOULD have executed).
  - `paper`: shadow + route the approved quant signal to `EntryCoordinator.execute_signal` (the paper broker is the configured broker in paper mode).
  - `live`: shadow + route to `EntryCoordinator.execute_signal` (live broker).
- Keep `QUANT_DECISION_ENABLED` as a back-compat alias (its value maps: true→`shadow` unless mode explicitly set; false→`off`).

**Files:**
- Modify `backend/app/config_models/settings_adapter.py`: add `QUANT_EXECUTION_MODE` property (read `QUANT_EXECUTION_MODE` env, else `feature_flags.yaml` key `quant_execution_mode`, else `"off"`).
- Modify `backend/app/application/services/session_event_router.py::_try_execute_quant_decision` (~line 647): after the existing approved-decision check, gate on mode — `off` → return False (never execute); `shadow` → log `SHADOW quant execution would execute <dir> entry=...` and return True (so the legacy path is skipped, matching today's flag-on behavior); `paper`/`live` → proceed to `quant_signal_mapper` + `entry_coordinator.execute_signal` (existing path).
- Modify `backend/app/application/services/quant_bridge.py::on_bar_close_with_decision`: currently skips computing the decision when `QUANT_DECISION_ENABLED` is off. Change the guard to "compute the decision when mode != off" (shadow/paper/live all compute). Store on the session as today.
- Update `backend/config/feature_flags.yaml`: add `quant_execution_mode: off` under features (documented).

**Tests** (`backend/tests/unit/application/test_quant_execution_mode.py` + extend `tests/system/test_quant_execution_e2e.py` or add a new system test):
- mode=off → no decision computed, router never executes (existing flag-off behavior).
- mode=shadow → decision computed + broadcast, router returns True but `entry_coordinator.execute_signal` NOT called (mock), log line present.
- mode=paper → decision computed, `execute_signal` called once with the mapped domain signal (reuse the 60-bar AGGRESSION-LONG fixture from `tests/system/test_quant_execution_e2e.py`).
- mode=live → same as paper (same code path).
- back-compat: `QUANT_DECISION_ENABLED=true` (no mode set) behaves as shadow.

**Verify:** worktree has its own `backend/`. `/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/unit tests/system -q --tb=short --continue-on-collection-errors` (from worktree root, with repo-root `tests/` on path via the existing conftest). Report exact counts (4 pre-existing env errors acceptable). Also `python -c "import app.main"` smoke.

**Commit:** `feat(backend): QUANT_EXECUTION_MODE off|shadow|paper|live wires quant decisions to execution` (+ separate commits for tests).

**Report:** `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/ws-exec-report.md`. Reply: status, commits, test counts, concerns.
