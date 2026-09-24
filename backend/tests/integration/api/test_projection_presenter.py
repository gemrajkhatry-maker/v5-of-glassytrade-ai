from glassytrade.api.presenters.snapshot_presenter import SnapshotPresenter


def test_presenter_builds_versioned_snapshot_without_private_runtime_access():
    message = SnapshotPresenter(
        projection_id="runtime-main",
        release_id="release-test",
        config_fingerprint="fp-test",
        mode="paper",
    ).runtime_snapshot(
        sequence=7,
        payload={"status": "degraded", "reasons": ["feed"]},
    )
    assert message["type"] == "snapshot"
    assert message["baseSequence"] is None
    assert message["payload"]["status"] == "degraded"
    assert message["sequence"] == 7
