# Production Safety and Paper Readiness Remediation

## Goal
Make the trading system safer to operate in paper mode and easier to transition to broker execution later, without implementing broker-facing OMS behavior now.

## Constraints
- Preserve `brokers/broker/dhan/infrastructure/symbol_mapper.py` and unrelated untracked files.
- Live readiness remains NO-GO.
- Do not modify LiveOMS or broker adapter execution behavior.
- Prefer RED tests, focused changes, and independently committed phases.

## Phase 1: Failure visibility
Replace production `except: pass` blocks with contextual logging or explicit propagation where safe. Add focused tests for malformed symbol rows, stream cleanup, and lot-size resolution failure behavior. Do not change successful-path semantics.

## Phase 2: Paper execution and reconciliation
Extend paper execution scenarios to cover partial fills, deterministic rejection, duplicate order idempotence, close timeout/retry/fallback, and restart reconciliation. Partial fills must create explicit unresolved exposure and block new entries until reconciliation. Economic close identity must be exactly-once even when retries occur.

## Phase 3: Canonical vocabulary
Consolidate duplicated broker-neutral concepts behind explicit contracts and boundary adapters. Centralize lot sizing and underlying extraction without deleting compatibility models until consumers and tests are migrated.

## Phase 4: Boundary inversion
Inject exchange metadata into broker infrastructure and route API analysis through application services. Preserve public behavior with contract tests.

## Phase 5: Targeted decomposition
Only after behavior is protected, split the largest orchestration units along ingestion, execution, state projection, scheduling, persistence, and rendering responsibilities.

## Phase 6: Hardening
Add exact-flow AMT provenance gates, canonical `DecisionRecord`, Indian-market acceptance vectors, full release-gate validation, and an explicit live-readiness report.

## Validation
Each phase requires focused tests, affected-suite tests, and a final release gate. Every changed public behavior must have a concrete test or documented acceptance check.
