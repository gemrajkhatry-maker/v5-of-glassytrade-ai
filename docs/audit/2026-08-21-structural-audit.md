# Structural Audit: Shotgun Surgery & Consolidation — 2026-08-21

Full-codebase audit of structural inconsistencies and shotgun-surgery smells,
with git-history evidence. Executed fixes are recorded here; deferred items
carry explicit trigger conditions.

## Evidence base

- Source-tree walk: `backend/` (~9.8k files incl. tests), `brokers/`, `quant/`,
  `shared/`, root strays.
- Git history: last 40 commits mined for cross-file change footprints.

## Confirmed shotgun-surgery instances (pre-fix)

| # | Pattern | Evidence commit | Footprint |
|---|---------|-----------------|-----------|
| S1 | Feature removal ripples through API/DI/storage/config | `cbef181` (LLM/RL purge), `044c8d1` | 45 + 16 files |
| S2 | Dead parallel implementations forcing dual maintenance | `ae8cd33`, `3cfdaf9`, `ee34678`, `0acbea4` | ~1,505 files deleted |
| S3 | AMT pipeline edits span backend + frontend | `f685fba`, `2b386f5` | 94–142 files |
| S4 | Decision-path logic spread over gates/risk/runtime/session/context | `cd8b963` | 17 files |
| S5 | Chart lifecycle fixes need multi-point frontend surgery | `cfcb501` | 8 files |
| S6 | Config defined in 4 places (root `config/config.py`, `backend/config/`, `app/config.py`, `app/config_models/`) | every new setting | 4-file edit |
| S7 | Broker logic duplicated across `backend/app/infrastructure/adapters/` and `brokers/broker/dhan/**`; copies had already diverged (anchored CALL/PUT detection fix present in only one) | found in audit | silent behavior drift |

## Executed remediation (branch `stable_6`)

| Commit | Fix | Kills |
|--------|-----|-------|
| `994e667` | Deleted `.worktrees/codebase-health-fixes` duplicate tree, stray root tests, `.env.bak-*`; gitignore'd backups | hygiene noise amplifying every search/refactor |
| `7e9619d` | Deleted root `config/config.py` (zero importers proven by grep sweep); `backend/app/config_models/` is the single config authority; `app/config.py` stays as thin facade | S6 |
| `c3bdadd` | Extracted `_dhan_common.py` (sys.path bootstrap, `_exchange_enum`, anchored `classify_symbol()`); both adapters consume it; boundary test forbids `brokers.*` imports outside `infrastructure/adapters/` | S7 |
| `3a98473` | Finished deleting dead auction WS plumbing left by `ae8cd33` (`AuctionUpdated`, `ViewState.auction`, WS adapter key, `WSSnapshot.auction`, stale tests); phase1 fixture rebuilt on live `DecisionContext` API | S2 residue; suite fully green again |

Result: net code reduction, WS snapshot contract shrunk 11 → 10 keys,
anchored-detection bug fixed in the broker adapter, both suites green
(root 1011 passed / backend 858 passed).

## Deferred backlog (executed 2026-08-21, same day)

All five items resolved:

1. **Metrics modules** — audited, NOT duplicates (Prometheus registry vs
   business-KPI dict). Kept separate with mutual cross-reference comments.
   Forced merge would combine unrelated APIs.
2. **Test trees** — audited: `tests/` (quant pkg) vs `backend/tests/` (app pkg)
   is per-package co-location, not duplication. Root strays moved:
   `qa_sanity_*.py` → `tests/qa/`.
3. **Frontend chart hook** — audited: all chart lifecycle logic already lives
   in one component (`ChartScene.tsx`); the 8-file commit `cfcb501` was 4
   chart files + 3 unrelated UI tweaks. No hook created (would be a
   single-consumer abstraction).
4. **Decision-path cohesion** — `quant/decision_context_builder.py` moved into
   `quant/decision/context_builder.py`; 5 importers updated.
5. **Data/docs relocation** — `amt_dataset/` → `data/`, `amt_docs/` →
   `docs/amt/`; 6 path references updated (train configs, tests, docstrings,
   LoRA adapter config).

Final suites: root 1011 passed, backend 858 passed, frontend 220 passed.

## Coding standards to prevent recurrence

- Config: settings are declared once in `backend/app/config_models/`;
  environments differ by YAML values only. Enforced by convention +
  `test_config_architecture.py`.
- Broker access: `backend/app` may import `brokers.*` ONLY from
  `backend/app/infrastructure/adapters/` — enforced by
  `TestBrokersImportBoundary` in `backend/tests/unit/architecture/test_module_boundaries.py`.
- No new top-level `test_*.py` or parallel config modules; new shared logic
  goes through an existing layer before a new module is created.
- Deletion rule: removing a producer means removing its event class, view-state
  fields, serializer keys, and tests in the same commit (the `ae8cd33`
  partial-deletion is the cautionary tale).
