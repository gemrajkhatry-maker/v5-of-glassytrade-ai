# Backend Cleanup & Integration Plan

**Date:** 2026-08-07  
**Scope:** `backend/`, `brokers/`, `quant/`, shared integration contracts, tests, CI, and launch scripts  
**Strategy:** aggressive cleanup in small, validated batches; no blind deletion from the live trading path.

## Current baseline

- The booted service is `backend/app/main.py` → `TradingEngine` → `TradingSessionService`.
- `quant/` is the deterministic trading brain and test/replay kernel; `quant/runtime.py` is not the booted production engine.
- `backendv2/` and `brokersv2/` do not exist, but `Makefile` and CI still target them.
- Quant decision execution has a routing seam, but the normal backend path currently calls `QuantBridge.on_bar_close()` for auction projection; decision evaluation is covered primarily by test harnesses.
- Real paper acceptance evidence is not yet available; the acceptance report is inconclusive.

## Safety rules

1. Do not delete a module based only on file size, naming, or an old audit.
2. Before deletion, scan all source, tests, scripts, and docs for references.
3. Preserve the current live engine until the quant path has production bar-close integration and paper evidence.
4. Keep paper/live broker adapters and exit/watchdog code intact until contract tests pass.
5. Every batch must pass syntax/import checks; execution-path batches additionally require focused integration tests.
6. Do not install packages, commit, push, or alter credentials as part of cleanup.

## Batches

### Batch 1 — Restore repository truth (this change)

- Point `Makefile` and GitHub Actions at the actual `backend/`, `quant/`, `brokers/`, and root test trees.
- Make preflight resolve both repository-root and backend-local packages from any working directory.
- Make launchers use the selected Python interpreter consistently instead of hard-coded `venv/bin/uvicorn` or machine-specific absolute paths.
- Keep missing dependencies as explicit preflight errors, not import-path mysteries.

**Gate:** preflight reports configuration resolution correctly; compileall passes; CI paths reference only existing directories.

### Batch 2 — Integration boundary cleanup

- Give `QuantBridge` an injected instance in the backend composition root; remove the module-global bridge only after all references and state-reset tests are migrated.
- Feed quant decision evaluation from the real closed-bar path behind `QUANT_EXECUTION_MODE=shadow` first.
- Add an integration test proving: closed bar → quant decision DTO → state snapshot → shadow/paper router behavior.
- Keep legacy execution as the explicit fallback while shadow comparison is collected.

**Gate:** backend paper integration tests and quant execution E2E pass; no live mode enabled by default.

### Batch 3 — Remove verified compatibility/dead paths

- Replace imports through confirmed re-export shims with canonical `quant.*` or `app.*` modules.
- Delete only shims with zero runtime/test/script references.
- Remove obsolete compatibility config/factory/event modules only after reference scans and import tests pass.
- Update docs and operator commands at the same time.

**Gate:** no stale shim imports; compileall and focused backend tests pass.

### Batch 4 — Simplify the active session pipeline

- Extract remaining pure orchestration steps from `TradingSessionService` and `SessionEventRouter`.
- Make AMT failure fail closed for new entries while preserving deterministic exit/watchdog handling.
- Consolidate duplicate risk-state projections and startup contracts.
- Preserve broker order acknowledgement, persistence, reconciliation, and idempotent close behavior.

**Gate:** lifecycle, recovery, watchdog, broker-mock, and paper protocol tests pass.

### Batch 5 — Promote quant from brain to backend candidate

Only after paper evidence and replay gates are real:

- Add multi-symbol quant runtime support.
- Add a production Dhan gateway/adapter to the quant runtime or formally embed the quant kernel in `TradingEngine`.
- Make configuration, agent context, sizing, session rules, and risk state explicit.
- Compare legacy and quant outputs in shadow mode, then migrate authority.

**Gate:** clean paper acceptance gate, replay/golden parity, broker contract tests, and staged one-position live pilot.

## First implementation order

1. Batch 1 repository/launcher/CI correction.
2. Run compile/import/preflight checks.
3. Batch 2 quant closed-bar integration with shadow-only default.
4. Review diff and run focused integration tests.
5. Start Batch 3 deletion only after the integration seam is stable.
