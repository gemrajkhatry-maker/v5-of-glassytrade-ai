from pathlib import Path


def test_no_v1_imports():
    bad = []
    for p in (Path("quantv2")).rglob("*.py"):
        text = p.read_text()
        if "from quant." in text or "import quant " in text or "from quant import" in text:
            bad.append(str(p))
    assert bad == []
