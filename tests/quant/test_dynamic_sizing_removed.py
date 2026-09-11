"""Task 3: dead scanner dynamicSizing payload must be gone.

Sizing authority is SessionRisk.position_size() — the scanner must not
emit a dynamicSizing payload.
"""
import inspect
import pathlib

from quant.decision import timesfm_agents as agents


def test_no_dynamic_sizing_payload():
    src = inspect.getsource(agents.TimesFMScanningAgent.evaluate)
    assert "dynamicSizing" not in src


def test_no_quant_dynamic_sizing_readers():
    root = pathlib.Path(__file__).resolve().parents[2] / "quant"
    hits = [
        str(p)
        for p in root.rglob("*.py")
        if "dynamicSizing" in p.read_text(encoding="utf-8", errors="ignore")
    ]
    assert hits == [], f"quant/ dynamicSizing readers remain: {hits}"
