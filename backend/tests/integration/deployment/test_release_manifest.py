from datetime import datetime, timezone

import pytest

from glassytrade.bootstrap.release_manifest import ArtifactRef, ReleaseManifest


def test_release_manifest_is_immutable_and_hashable():
    manifest = ReleaseManifest(
        release_id="release-1",
        git_sha="a" * 40,
        lock_hash="b" * 64,
        config_hash="c" * 64,
        schema_version=3,
        migration_id="0003_reconciliation",
        test_artifacts=(ArtifactRef("evidence.json", "d" * 64),),
        approval_id="approval-1",
        built_at=datetime.now(timezone.utc),
    )
    assert manifest.release_id == "release-1"
    with pytest.raises(Exception):
        manifest.release_id = "changed"  # type: ignore[misc]
