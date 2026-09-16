# WS-B: Gate 3 → Two Models Brief (parallel session)

**Worktree:** `.worktrees/ws-b` · **Branch:** `ws-b/gate3-two-models` · **Base:** `25ea293f`
**Contract (user-decided):** Collapse Gate 3's 6 setup paths + `va_fade` fallback into the playbook's two models — `TREND` / `MEAN_REVERSION` — selected by `market_state`. Behaviour change is intended; certification traces will move.

## Problem

The Fabio playbook is 3 steps → 2 models. Gate 3 (`gate_triple_a_edge` in `quant/decision/gates_edge.py`, CC 54, ~250 lines) implements 7 entry shapes instead:

| # | Path in code | Playbook mapping |
|---|---|---|
| 1 | SetupEvidence path | TREND or MEAN_REVERSION (already model-shaped) |
| 2 | Triple-A AGGRESSION raw | TREND |
| 3 | Second Drive | TREND |
| 4 | LVN Sniper | TREND (location leg) |
| 5 | Initiative Breakout | TREND |
| 6 | Squeeze Retest | MEAN_REVERSION |
| 7 | `va_fade.py` fallback (outside Gate 3) | MEAN_REVERSION |

## Steps

1. **Verify which path is live first.** `docs/reviews/2026-09-10-audit-appendices/audit-sizing-context.md:315` claims the entire `GatePipeline`/`DecisionService` stack is bypassed on the E2E path (`runtime.py:946` calls `strategy.should_enter`). Confirm by tracing the current `runtime.py`. If true, regoldening certification traces is moot for E2E and the change is pipeline-internal — state this explicitly in the PR.
2. Write the model selector: `market_state == BALANCED → MEAN_REVERSION paths only; IMBALANCED/DEAD → TREND paths only`. Keep the existing guards (CVD conflict, candle acceptance, session permissions) — they are safety, not complexity.
3. Map each of the 7 shapes to its model; delete the ones that map to nothing (justify each deletion in the PR).
4. Regolden `tests/quant/certification/` traces. Produce a human-readable before/after diff of entries taken/dropped per trace and attach it — silent regoldens are forbidden.
5. Update `docs/amt/fabio_decision_pipeline.md` Gate-3 section to the two-model contract.
6. `va_fade.py`: fold its valid core (probe → failed acceptance → close back inside VA → LVN retest, per `2026-09-07-production-readiness.md:1366`) into the MEAN_REVERSION model, then delete the file if zero importers remain.

## Guardrails

- `tests/quant/test_npoc_gate_integration.py:71` — gates_edge must never reference NPOC.
- `tests/quant/test_market_state_enum_guard.py` — Gate 3 accepts enum OR legacy string; preserve.
- Do not touch Gate 1–2 modules (WS-A owns them; you share `docs/amt/fabio_decision_pipeline.md` — change only the Gate-3 section, expect merge order WS-A → WS-B).

## Verification

```bash
.venv/bin/python -m pytest tests/quant/decision/ tests/quant/certification/ -x -q
.venv/bin/python -m ruff check quant/decision/
```

## Done when

Every surviving setup path is attributable to TREND or MEAN_REVERSION; model-state selection is enforced in one place; certification diffs reviewed; failure count vs base `25ea293f` explained line by line (36 pre-existing failures on this branch — see ledger note).
