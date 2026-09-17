# WS-A: Gate 1–2 Convergence Brief (parallel session)

**Worktree:** `.worktrees/ws-a` · **Branch:** `ws-a/gate-convergence` · **Base:** `25ea293f`
**Contract (user-decided):** Production wins. Gate 1 semantics = `quant/decision/gates/gate_session_phase.py` — spread cap `2.0 × tick` + NSE/MCX wall-clock blackout.

## Problem

Gates 1–2 exist twice with different behaviour; tests validate the copy production doesn't run.

- Production (imported by `quant/decision/pipeline.py`): `quant/decision/gates/gate_session_phase.py`, `gates/gate_position_cooldown.py`
- Test-only (imported by every gate test + docs): `quant/decision/gates_session_position.py` — spread cap `3.0 × tick`, no exchange blackout
- Known divergences: spread cap (2.0 vs 3.0 ×tick), blackout logic (prod-only, untested), Gate-1 setup-permission taxonomy (prod omits what the doc describes)

Note: Gate 3 (`gate_triple_a_edge`) and Gate 4 (`gate_rr`) are NOT duplicated — `gates/gate_edge.py:10` re-exports the flat `gates_edge.py`. Do not touch their logic.

## Steps

1. Diff `gates/gate_session_phase.py` vs flat `gates_session_position.py` line by line; write the divergence list into the PR description.
2. Repoint tests to production modules:
   - `tests/quant/decision/test_gates_1_2.py` (imports flat at line 2)
   - `tests/quant/decision/test_gate1_phase_permissions.py` (line 19)
   - `tests/quant/decision/test_context_builder_behavior.py` (line 173)
   Expect assertion changes for 2.0×tick and NEW tests for the blackout paths (they ship untested today).
3. Delete the flat `gates_session_position.py` once zero importers remain; keep `gates_rr.py`/`gates_edge.py` (still canonical).
4. Fix docs that reference the flat file:
   - `docs/amt/fabio_decision_pipeline.md` lines 44, 68
   - `docs/architecture/ARCHITECTURE_AND_FLOWS.md` lines 306, 309
5. Source-guard: `tests/quant/test_npoc_gate_integration.py:71` asserts `gates_edge` never references NPOC — leave that guarantee intact.

## Verification

```bash
.venv/bin/python -m pytest tests/quant/decision/ tests/quant/test_npoc_gate_integration.py -x -q
.venv/bin/python -m ruff check quant/decision/
```

## Done when

Flat `gates_session_position.py` deleted; all imports resolve to `quant.decision.gates`; blackout logic has tests; both docs match shipped behaviour; failure count vs base `25ea293f` is not worse.
