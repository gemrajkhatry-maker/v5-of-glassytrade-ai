"""Boundary rules: transport must not reach through abstractions. (REF-10/11)"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text()


def test_no_import_of_app_main_in_routers():
    for rel in (
        "backend/app/api/routers/trading.py",
        "backend/app/api/routers/health.py",
        "backend/app/api/routers/market.py",
        "backend/app/api/routers/metrics.py",
    ):
        src = _read(rel)
        assert "from app.main import" not in src, rel
        assert "import app.main" not in src, rel


def test_no_engine_privates_in_transport():
    import re
    for rel in (
        "backend/app/api/websocket/gameloop.py",
        "backend/app/api/routers/health.py",
        "backend/app/api/routers/trading.py",
    ):
        src = _read(rel)
        hits = re.findall(r"coordinator\._\w+|engine\._\w+", src)
        assert hits == [], (rel, hits)
