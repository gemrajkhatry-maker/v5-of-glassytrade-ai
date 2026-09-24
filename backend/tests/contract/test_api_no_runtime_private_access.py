from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "src" / "glassytrade" / "api"


def test_target_api_modules_do_not_import_runtime_or_broker_private_modules():
    for path in ROOT.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "quant.runtime" not in source
        assert "quant.multi_engine" not in source
        assert "broker." not in source
