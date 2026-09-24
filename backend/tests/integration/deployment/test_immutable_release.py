import pytest

from backend.scripts.release import build_release_manifest, verify_release_manifest


def test_release_manifest_verification_detects_artifact_tampering(tmp_path):
    artifact = tmp_path / "evidence.txt"
    artifact.write_text("pass", encoding="utf-8")
    manifest = build_release_manifest("release-1", "approval-1", [artifact])
    assert verify_release_manifest(manifest) is True
    artifact.write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="artifact"):
        verify_release_manifest(manifest)
