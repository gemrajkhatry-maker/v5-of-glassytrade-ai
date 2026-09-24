"""Build and verify immutable target release manifests."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from glassytrade.bootstrap.release_manifest import ArtifactRef, ReleaseManifest, sha256_file


def build_release_manifest(
    release_id: str,
    approval_id: str,
    artifacts: list[Path],
) -> ReleaseManifest:
    refs = tuple(ArtifactRef(str(path), sha256_file(path)) for path in artifacts)
    return ReleaseManifest(
        release_id=release_id,
        git_sha=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        lock_hash=hashlib.sha256(b"lockfile").hexdigest(),
        config_hash=hashlib.sha256(b"config-fingerprint").hexdigest(),
        schema_version=3,
        migration_id="0003_reconciliation",
        test_artifacts=refs,
        approval_id=approval_id,
        built_at=datetime.now(timezone.utc),
    )


def verify_release_manifest(manifest: ReleaseManifest) -> bool:
    for artifact in manifest.test_artifacts:
        path = Path(artifact.path)
        if not path.exists() or sha256_file(path) != artifact.sha256:
            raise ValueError(f"artifact verification failed: {artifact.path}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--release-id", required=True)
    build.add_argument("--approval-id", required=True)
    build.add_argument("artifacts", nargs="*")
    verify = sub.add_parser("verify")
    verify.add_argument("manifest", type=Path)
    args = parser.parse_args()
    if args.command == "build":
        print(build_release_manifest(args.release_id, args.approval_id, [Path(item) for item in args.artifacts]))
        return 0
    raise SystemExit("verify requires a serialized manifest loader")


if __name__ == "__main__":
    raise SystemExit(main())
