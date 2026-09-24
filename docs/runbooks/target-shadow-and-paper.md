# Target Shadow and Paper Runbook

## Preconditions

- Use a temporary SQLite database and paper/read-only broker fixtures.
- Confirm `runtime_engine=target`, `mode=paper`, and no live credentials.
- Archive the release manifest, config fingerprint, and source database checksum.

## Shadow

1. Start the target runtime in `shadow` mode.
2. Confirm the broker adapter exposes no write capability.
3. Capture identical legacy/target tapes and run `ShadowRunner.compare`.
4. Investigate every semantic difference; do not promote on sequence gaps.

## Paper

1. Run one complete paper session with temporary storage.
2. Verify fills, positions, protection, EOD, and reconciliation evidence.
3. Run `evaluate_paper_acceptance`; unresolved cases or unverified EOD block promotion.
4. Repeat for NSE and MCX fixtures and a restart/EOD drill.

## Stop conditions

Any storage error, unknown broker outcome, quantity mismatch, missing protection, or unresolved reconciliation case is a hard stop. Never repair by deleting rows or regenerating goldens.
