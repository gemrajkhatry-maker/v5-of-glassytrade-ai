# WS-NOREPLY — Report: Remove AI "reply/command" mode (out of scope)

**Status: ✅ DONE** — work performed exclusively in worktree `/Users/apple/Documents/wt-ws-noreply` (branch `migration/ws-noreply`). Main repo untouched.

## Commits

1. `67a6c13` `feat(backend): remove AI command/reply mode (out of scope)` — 4 files, +11/−170
2. `7caa44f` `docs: mark AI command/reply mode out of scope` — 1 file, +4

Working tree clean after commits. `.superpowers/` and `docs/superpowers/plans/` were NOT committed.

## Changes

- `backend/app/application/services/ai_command_service.py` — deleted `_SYMBOL_KEYWORDS`, `_INTERVAL_KEYWORDS`, `_COLOR_KEYWORDS`, and `parse_market_command`. Kept `analyze_market`, `get_decision_history`, `get_journal_endpoint`, `get_promotion`. Module docstring updated (reworded to avoid the literal token `parse_market_command` so the verify grep stays empty).
- `backend/app/api/routers/ai.py` — deleted `CommandRequest` model, `@router.post("/command")`, `process_command`. Kept `/analyze`, `/history`, `/journal*`, `/journal/promotion`. Removed now-unused `Any` and `Field` imports.
- `backend/app/infrastructure/serialization/schemas.py` — deleted `AICommandResponseDTO` and `CommandRequestDTO`. KEPT `ChatMessageDTO` per brief default (grep confirmed it has no other references; brief says keep unless confirmed-removable — left in place, still served by `MessageRoleDTO`).
- `backend/tests/integration/test_frontend_integration.py` — deleted the `TestAICommand` class (4 tests hitting `/api/ai/command`). **See concern 1** — this was not in the brief's scope list but was required to satisfy the verify grep.
- `docs/AMT_UNIFICATION.md` — appended "## Out of scope" section with the required note.

## Verify evidence

- Grep: `grep -rn "parse_market_command\|/command\|CommandRequest\|AICommandResponseDTO\|CommandRequestDTO" backend/app backend/tests --include="*.py"` → **no matches** (exit 1). The one false-positive hit was my own docstring text mentioning the method name; reworded the docstring so the token does not appear literally.
- Unit tests: `/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/unit -q --tb=short --continue-on-collection-errors` → **1323 passed, 64 skipped, 0 failed, 0 errors** (ran twice: 8.52s and 5.67s).
- Smoke: `PYTHONPATH=.../backend python -c "import app.main"` → **OK** (run from repo root; startup logs emitted, exit 0).

## Concerns

1. **Brief inconsistency — "no tests" was false.** `backend/tests/integration/test_frontend_integration.py` contained a `TestAICommand` class with 4 tests exercising `/api/ai/command`. The verify grep explicitly covers `backend/tests`, so leaving them would break the EMPTY requirement AND those tests would fail at runtime (404). I removed the class. Flagging for the migration lead: the brief's claim of "no tests" for `/command` was inaccurate; if that integration suite is supposed to be preserved verbatim, reconsider — but the endpoint is gone, so the tests are dead either way.

2. **Smoke recipe needs repo-root CWD.** The brief's smoke command runs `cd backend && PYTHONPATH=<worktree>/backend python -c "import app.main"`. That fails with `ModuleNotFoundError: No module named 'quant'` because `quant` is a **repo-root** package (sibling of `backend/`), so it is not on `sys.path` when CWD=backend and PYTHONPATH=backend only. This is pre-existing and independent of my change (the failing import is `quant.inference.llm_contract` in `health.py`, untouched). `import app.main` succeeds when run from the repo root with `PYTHONPATH=<worktree>/backend`. Recommend updating the verify recipe in future briefs to run from the worktree root (as the pytest runs already do — pytest picks up the path via `conftest.py`/`pytest.ini`).

3. **Integration tests not runnable in this env.** `tests/integration/test_frontend_integration.py` collection errors with `RuntimeError: The starlette.testclient module requires the httpx package to be installed` — `httpx` is not installed in `amt_313`. Pre-existing env gap, outside the brief's required `tests/unit` scope. The deleted `TestAICommand` tests cannot be executed here regardless.

4. `ChatMessageDTO` remains in schemas.py with **no usage anywhere** in the backend (only its definition matched grep). The brief's default is to keep it, so I did. If the llm_history WS path was also removed in an earlier migration (ws-ts), it may now be dead too — worth a follow-up, but out of this brief's scope.
