"""Immutable release and evidence manifest values."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    path: str
    sha256: str

    def __post_init__(self) -> None:
        if not self.path or len(self.sha256) != 64:
            raise ValueError("artifact path and sha256 are required")


@dataclass(frozen=True, slots=True)
class EvidenceManifest:
    release_id: str
    artifacts: tuple[ArtifactRef, ...]
    verdict: str

    def __post_init__(self) -> None:
        if not self.release_id or self.verdict not in {"PASS", "FAIL"}:
            raise ValueError("invalid evidence manifest")


@dataclass(frozen=True, slots=True)
class ReleaseManifest:
    release_id: str
    git_sha: str
    lock_hash: str
    config_hash: str
    schema_version: int
    migration_id: str
    test_artifacts: tuple[ArtifactRef, ...]
    approval_id: str
    built_at: datetime

    def __post_init__(self) -> None:
        if not self.release_id or not self.approval_id:
            raise ValueError("release and approval IDs are required")
        if len(self.git_sha) < 7 or len(self.lock_hash) != 64 or len(self.config_hash) != 64:
            raise ValueError("release hashes are invalid")
        if self.schema_version < 1 or self.built_at.tzinfo is None:
            raise ValueError("release schema/time is invalid")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
