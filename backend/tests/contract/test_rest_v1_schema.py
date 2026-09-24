import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "src" / "glassytrade" / "contracts"


def test_rest_v1_contract_files_are_valid_json_schema():
    for name in ("event_v1.schema.json", "release_manifest.schema.json"):
        schema = json.loads((ROOT / name).read_text(encoding="utf-8"))
        assert schema["$schema"].startswith("https://json-schema.org/")
        assert schema["type"] == "object"
