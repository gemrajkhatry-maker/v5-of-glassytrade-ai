# WS-GATECONS — Gate/risk/exit stack consolidation review (P2.7 KEEP-BOTH, analysis only)

**Worktree:** `/Users/apple/Documents/wt-ws-gatecons` (branch `migration/ws-gatecons`). Work ONLY there.

**Context:** The ponytail audit flagged duplication: 2 SignalBuilders (`quant/decision/signal_builder.py` greenfield vs `quant/decision/gates/signal_builder.py` legacy `build_entry_signal`), 3 gate pipelines (greenfield `quant/decision/pipeline.py`, `gates/legacy_gate_pipeline.py`, `gates/gate_runner.py`), 2 ExitEngines (`quant/execution/exits.py` greenfield vs `quant/execution/exit_engine.py` production), 2 risk stacks (`quant/execution/risk.py` vs `risk_manager`+`risk_tier`+`circuit_breakers`+`loss_tracker`). The recorded P2.7 decision says KEEP BOTH (greenfield deterministic engine for the paper/WS path, production AMT engine for live). This task resolves the question with MEASUREMENT, not a behavior change.

**Task — produce `docs/GATE_CONSOLIDATION_REVIEW.md` (in the worktree; do NOT commit — report its path):**
1. For each duplicated pair/triple, map: which production path uses which, what they share, what they differ on (read the code).
2. **Differential test** `tests/quant/consolidation/test_gate_divergence.py`: feed the SAME synthetic session through BOTH the greenfield `DecisionService`/`pipeline.py` gates AND the production `gates/gate_runner.py` (or `legacy_gate_pipeline.py`); compare pass/fail decisions + resulting signals per bar. Report the agreement rate and the specific divergence cases (which gate differs, on what inputs).
   - Similarly for exits: run the greenfield `exits.py` and the production `exit_engine.py` on the same (position, auction state, bar) sequence; compare exit decisions/reasons. (Use the existing `tests/system` deterministic session or `_session_bars`.)
3. **Verdict** in the doc: (a) KEEP BOTH with the measured divergence budget (recommended if divergence is real and intentional), or (b) MERGE now (only if the differential shows near-identical behavior AND a merge is low-risk). Give the concrete merge plan if (b), including which files to delete and which tests to keep. Do NOT change production code in this task.

**Verify:** `/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant -q --tb=short` (worktree root) — the new differential test passes and nothing regresses.

**Commit:** `test(quant): gate/exit stack divergence measurement`.

**Report:** `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/ws-gatecons-report.md` (the agreement rates + divergence cases + verdict + the AMT_UNIFICATION-relevant note). Reply: status, commits, test counts, the verdict, concerns.
