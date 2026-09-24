import json
from pathlib import Path

import pytest
from jsonschema import validate

from glassytrade.api.websocket.protocol import SequenceGap, validate_ws_message

ROOT = Path(__file__).resolve().parents[2] / "src" / "glassytrade" / "contracts"


def envelope(**overrides):
    value = {
        "schemaVersion": "1.0",
        "projectionVersion": 1,
        "projectionId": "runtime-main",
        "scope": {"type": "runtime"},
        "sequence": 4,
        "baseSequence": None,
        "asOf": "2026-09-24T10:00:00+05:30",
        "releaseId": "release-test",
        "configFingerprint": "fp-test",
        "mode": "paper",
        "type": "snapshot",
        "payload": {"status": "ready"},
    }
    value.update(overrides)
    return value


def test_ws_schema_and_envelope_accept_full_snapshot():
    schema = json.loads((ROOT / "ws_v1.schema.json").read_text(encoding="utf-8"))
    validate(envelope(), schema)
    validate_ws_message(envelope())


def test_delta_requires_contiguous_sequence():
    message = envelope(type="delta", baseSequence=4, sequence=5)
    validate_ws_message(message)
    with pytest.raises(SequenceGap):
        validate_ws_message(envelope(type="delta", baseSequence=4, sequence=6))


def test_snapshot_must_not_have_base_sequence():
    with pytest.raises(ValueError, match="snapshot"):
        validate_ws_message(envelope(baseSequence=3))
