"""Read-only cutover gate; promotion is a separate command."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from glassytrade.bootstrap.release_manifest import EvidenceManifest, ReleaseManifest


class CutoverBlocked(RuntimeError):
    """Raised when immutable cutover preconditions are not satisfied."""


@dataclass(frozen=True, slots=True)
class CutoverSnapshot:
    mode: str
    source_release_id: str
    target_release_id: str
    broker_snapshot_at: datetime
    positions: tuple[Any, ...]
    open_orders: tuple[Any, ...]
    unknown_attempts: tuple[Any, ...]
    open_reservations: tuple[Any, ...]
    reconciliation_cases: tuple[Any, ...]
    protective_orders: tuple[Any, ...]
    entries_blocked: bool
    scanner_stopped: bool


@dataclass(frozen=True, slots=True)
class CutoverDecision:
    allowed: bool
    blockers: tuple[str, ...]
    broker_snapshot_hash: str
    backup_manifest_hash: str
    expires_at: datetime


class CutoverGate:
    def evaluate(
        self,
        snapshot: CutoverSnapshot,
        manifest: ReleaseManifest,
        evidence_manifest: EvidenceManifest,
    ) -> CutoverDecision:
        blockers: list[str] = []
        if snapshot.target_release_id != manifest.release_id:
            blockers.append("target_release_mismatch")
        if evidence_manifest.release_id != manifest.release_id:
            blockers.append("evidence_release_mismatch")
        if evidence_manifest.verdict != "PASS":
            blockers.append("evidence_not_passed")
        for name, values in (
            ("positions", snapshot.positions),
            ("open_orders", snapshot.open_orders),
            ("unknown_attempts", snapshot.unknown_attempts),
            ("open_reservations", snapshot.open_reservations),
            ("reconciliation_cases", snapshot.reconciliation_cases),
            ("protective_orders", snapshot.protective_orders),
        ):
            if values:
                blockers.append(f"{name}_not_empty")
        if not snapshot.entries_blocked:
            blockers.append("entries_not_blocked")
        if not snapshot.scanner_stopped:
            blockers.append("scanner_not_stopped")
        if blockers:
            raise CutoverBlocked(", ".join(blockers))
        broker_payload = json.dumps(asdict(snapshot), default=str, sort_keys=True).encode()
        backup_payload = json.dumps(
            [asdict(artifact) for artifact in evidence_manifest.artifacts], sort_keys=True
        ).encode()
        return CutoverDecision(
            allowed=True,
            blockers=(),
            broker_snapshot_hash=hashlib.sha256(broker_payload).hexdigest(),
            backup_manifest_hash=hashlib.sha256(backup_payload).hexdigest(),
            expires_at=datetime.now(timezone.utc),
        )
