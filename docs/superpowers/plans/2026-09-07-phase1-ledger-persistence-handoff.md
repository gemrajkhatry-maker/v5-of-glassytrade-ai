# Phase 1 — Ledger/Persistence Contract Handoff

> Date: 2026-09-07
> Base commit: `1589060b`
> Status: integrated and validated in the primary worktree; Phase 1 complete.

## Verified isolated deliverables

### Agent A — `agent/ledger-contract`

- Extended ledger reconstruction with explicit side normalization.
- Accepts canonical `BUY`/`SELL` and legacy `LONG`/`SHORT` entry aliases.
- Rejects non-finite, non-positive, malformed, and unsupported-side records.
- Detects conflicting duplicate fill IDs.
- Quarantines the associated position when duplicate accounting payloads conflict.
- Preserves idempotency for identical duplicate fills.
- Tests: `8 passed`.

### Agent B — `agent/persistence-ledger`

- Normalizes persisted entry sides to canonical `BUY`/`SELL`.
- Keeps exit sides opposite the position direction.
- Retains stable `entry:<position_id>` fill IDs and existing close/partial IDs.
- Existing database order/storage tests: `5 passed`.

## Contract decisions

| Concern | Decision |
|---|---|
| Long entry | `BUY` |
| Long exit | `SELL` |
| Short entry | `SELL` |
| Short exit | `BUY` |
| Legacy entry aliases | `LONG` → long; `SHORT` → short |
| Duplicate identical fill | Ignore after first occurrence |
| Duplicate conflicting fill | Add `conflicting-fill:<fill_id>` and quarantine position |
| Invalid number | Quarantine fill |
| Over-close | Quarantine position |
| Empty/closed-only ledger | No restored position |
| Backend dependency | None in ledger module |

## Integration blockers to resolve before Phase 2

1. Port Agent A's ledger changes onto the protected primary edit rather than overwriting it wholesale.
2. Port Agent B's entry-side normalization onto the protected persistence/coordinator baseline.
3. Add storage-level tests for conflicting duplicate IDs; SQLite `INSERT OR IGNORE` currently prevents double insertion but does not by itself expose payload conflicts.
4. Verify partial-fill position IDs remain stable from `PositionOpened` through `PositionReduced` and `PositionClosed`.
5. Verify coordinator restoration treats any ledger issue as a startup unresolved condition and does not restore the snapshot row.
6. Run the combined primary focused suite after the port.

## Phase 1 exit criteria

- [x] Ledger contract defined.
- [x] Persistence direction mismatch identified and corrected in isolation.
- [x] Invalid and conflicting-fill behavior tested in isolation.
- [x] Focused isolated tests pass.
- [x] Primary worktree protected from unreviewed overwrites.
- [x] Contract changes ported to primary worktree.
- [x] Coordinator integration tests pass.
