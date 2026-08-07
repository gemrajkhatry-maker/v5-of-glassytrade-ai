# Task 0.1 — Scaffold `quant/contracts/` package

**From:** docs/superpowers/plans/2026-08-06-quant-brain-migration.md — Phase 0, Task 0.1

**Goal:** Create the `quant/contracts/` package (and its `ports/` subpackage) that will become the single source of truth for brain types. This is pure scaffolding — nothing else changes.

**Files:**
- Create: `quant/contracts/__init__.py`
- Create: `quant/contracts/ports/__init__.py`

**Interfaces:**
- Produces: importable packages `quant.contracts` and `quant.contracts.ports` (empty for now; Task 0.2 populates them).

## Steps

1. Run:
   ```bash
   cd /Users/apple/Documents/v5-of-glassytrade-ai
   mkdir -p quant/contracts/ports
   ```
2. Write `quant/contracts/__init__.py`:
   ```python
   """Shared contracts — single source of truth for brain types."""
   ```
3. Write `quant/contracts/ports/__init__.py`:
   ```python
   """Ports (interfaces) the brain consumes; implemented by backend I/O adapters."""
   ```
4. Verify:
   ```bash
   /Users/apple/miniconda3/envs/amt_313/bin/python -c "import quant.contracts, quant.contracts.ports"
   ```
   Expected: no output, exit 0.
5. Also verify the whole quant suite still passes (nothing changed):
   ```bash
   cd /Users/apple/Documents/v5-of-glassytrade-ai
   /Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant -q --tb=short
   ```
   Expected: 146 passed.
6. Commit:
   ```bash
   git add quant/contracts/
   git commit -m "feat(quant): scaffold quant.contracts package"
   ```

## Report contract

Write your report to `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/task-0.1-report.md`:
- Commit hash
- Test output tail (the 146-passed line)
- Any concerns

Return to me: status (DONE / DONE_WITH_CONCERNS / BLOCKED), commit hash, one-line test summary.
