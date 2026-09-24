# Target Shadow Cutover Runbook

1. Archive the immutable release, database backup, migration manifest, and evidence bundle.
2. Verify the target release in shadow and paper mode with a read-only broker.
3. Confirm rollback artifact and database restore procedure in a temporary environment.
4. Obtain explicit operator approval for the maintenance window.
5. Stop the legacy process with the bounded supervisor shutdown path.
6. Restore/verify the target database and run startup recovery.
7. Publish readiness only after reconciliation, protection, and EOD gates pass.

No cutover is permitted from a failed, timed-out, or incomplete evidence run. Do not dispatch live orders during validation.
