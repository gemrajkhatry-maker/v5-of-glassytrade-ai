# Target Cutover and Rollback Runbook

## Pre-cutover

- Build and verify an immutable release manifest and approval ID.
- Run migration and restore drills against temporary copies.
- Verify shadow and paper evidence, including EOD and protection.
- Capture broker snapshot hash and block entries.

## Cutover

1. Stop the legacy supervisor with SIGTERM and bounded escalation.
2. Confirm the process lease and ports are clear.
3. Restore the verified target database if required.
4. Start the target release with the explicit paper/live profile.
5. Run recovery and reconciliation; do not publish readiness on any blocker.
6. Observe health and broker snapshots before enabling entries.

## Rollback

Any unknown order, quantity mismatch, protection failure, storage error, or evidence mismatch triggers rollback: stop the target process, restore the last verified backup, restart the prior release, and preserve all target evidence. Never delete or mutate the source database during diagnosis.
