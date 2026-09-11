# Production Safety Remediation Implementation Plan

## Order of work
1. Inventory and classify silent exception blocks. Add RED tests for behavior-sensitive paths.
2. Implement contextual logging without touching the pre-existing symbol mapper change.
3. Add paper reconciliation state transitions for partial fills and restart recovery.
4. Add close timeout/retry/idempotency tests and implementation.
5. Run focused, affected, and release-gate suites after each commit.
6. Defer model consolidation and god-class decomposition until safety behavior is covered.

## Commit boundaries
- `fix: make broker failure paths observable`
- `feat: reconcile partial paper exposure`
- `feat: model paper close retries exactly once`
- `test: add market acceptance vectors`

## Guardrails
No LiveOMS changes, no broker execution behavior, no edits to `symbol_mapper.py`, and no staging unrelated files.
