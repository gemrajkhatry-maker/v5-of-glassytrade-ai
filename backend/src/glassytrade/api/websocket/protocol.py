"""Versioned WebSocket projection protocol validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "contracts" / "ws_v1.schema.json"
_SCHEMA = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FormatChecker())


class SequenceGap(ValueError):
    """Raised when a delta cannot be applied to the current projection."""


@dataclass(frozen=True)
class ProjectionEnvelope:
    schema_version: str
    projection_version: int
    projection_id: str
    scope: Mapping[str, Any]
    sequence: int
    base_sequence: int | None
    as_of: str
    release_id: str
    config_fingerprint: str
    mode: str
    type: str
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "projectionVersion": self.projection_version,
            "projectionId": self.projection_id,
            "scope": dict(self.scope),
            "sequence": self.sequence,
            "baseSequence": self.base_sequence,
            "asOf": self.as_of,
            "releaseId": self.release_id,
            "configFingerprint": self.config_fingerprint,
            "mode": self.mode,
            "type": self.type,
            "payload": dict(self.payload),
        }


def validate_ws_message(message: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(message)
    errors = sorted(_VALIDATOR.iter_errors(value), key=lambda error: list(error.path))
    if errors:
        raise ValueError(f"invalid projection envelope: {errors[0].message}")
    if value["schemaVersion"] != "1.0":
        raise ValueError(f"unsupported projection schema: {value['schemaVersion']}")
    if value["type"] == "snapshot":
        if value["baseSequence"] is not None:
            raise ValueError("snapshot baseSequence must be null")
    else:
        base = value["baseSequence"]
        if base is None or value["sequence"] != base + 1:
            raise SequenceGap("delta sequence is not contiguous")
    return value
