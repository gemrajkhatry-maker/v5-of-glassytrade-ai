from datetime import datetime, timezone

import pytest

from glassytrade.application.runtime.cutover import (
    CutoverBlocked,
    CutoverGate,
    CutoverSnapshot,
)
from glassytrade.bootstrap.release_manifest import (
    ArtifactRef,
    EvidenceManifest,
    ReleaseManifest,
)

NOW = datetime.now(timezone.utc)


def manifest(release_id="release-1") -> ReleaseManifest:
    return ReleaseManifest(
        release_id=release_id,
        git_sha="a" * 40,
        lock_hash="b" * 64,
        config_hash="c" * 64,
        schema_version=3,
        migration_id="0003_reconciliation",
        test_artifacts=(ArtifactRef("evidence.json", "d" * 64),),
        approval_id="approval-1",
        built_at=NOW,
    )


def evidence() -> EvidenceManifest:
    return EvidenceManifest(
        release_id="release-1",
        artifacts=(ArtifactRef("evidence.json", "d" * 64),),
        verdict="PASS",
    )


def snapshot(**overrides) -> CutoverSnapshot:
    values = {
        "mode": "paper",
        "source_release_id": "release-0",
        "target_release_id": "release-1",
        "broker_snapshot_at": NOW,
        "positions": (),
        "open_orders": (),
        "unknown_attempts": (),
        "open_reservations": (),
        "reconciliation_cases": (),
        "protective_orders": (),
        "entries_blocked": True,
        "scanner_stopped": True,
    }
    values.update(overrides)
    return CutoverSnapshot(**values)


def test_cutover_requires_flat_book_and_verified_evidence():
    decision = CutoverGate().evaluate(snapshot(), manifest(), evidence())
    assert decision.allowed is True
    assert decision.blockers == ()


def test_live_cutover_blocks_unknown_orders():
    with pytest.raises(CutoverBlocked):
        CutoverGate().evaluate(
            snapshot(mode="live", unknown_attempts=(object(),)),
            manifest(),
            evidence(),
        )
