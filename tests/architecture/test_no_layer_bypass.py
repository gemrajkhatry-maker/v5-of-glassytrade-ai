"""Boundary rules: transport must not reach through abstractions. (REF-10/11)"""
import importlib
import pathlib
import re

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


def test_active_symbols_single_writer():
    src = _read("backend/app/main.py")
    assert src.count("app.state.active_symbols =") <= 1, "two writers — unify first"


def test_dependencies_owns_active_symbols():
    src = _read("backend/app/api/dependencies.py")
    assert "def get_active_symbols" in src


def test_no_engine_privates_in_transport():
    for rel in (
        "backend/app/api/websocket/gameloop.py",
        "backend/app/api/routers/health.py",
        "backend/app/api/routers/trading.py",
    ):
        src = _read(rel)
        hits = re.findall(r"coordinator\._\w+|engine\._\w+", src)
        assert hits == [], (rel, hits)


# --- Ownership ratchets (Task 2): no NEW vocabulary duplications ---------

# NOTE: the plan sketch used (?<!_OFFSET_SECONDS|...) lookbehind for the IST
# gate — that is an invalid regex in `re` (fixed-width lookbehind required),
# so gate (c) is a hardened plain-word match on a py-only file allowlist.

_LOT_SIZE_TABLE_RE = (
    r"^\s*(?:\w+\s*:\s*)?(?:Dict\[str,\s*(?:int|float)\]"
    r"|dict\[str,\s*(?:int|float)\])\s*=\s*\{[^}]*NIFTY"
)
_CONVERTER_RE = r"def\s+_to_(?:decimal|float)\s*\("
_IST_LITERAL_RE = r"\b19800\b"

_DUPS: dict[str, tuple[frozenset, str]] = {
    _LOT_SIZE_TABLE_RE: (
        frozenset({
            "brokers/broker/market_info.py",
            "brokers/broker/dhan/domain/constants.py",
        }),
        "registry-derived tables with marked extras only",
    ),
    _CONVERTER_RE: (
        frozenset({
            # GRANDFATHERED backend/app/infrastructure/adapters/dhan_broker_adapter.py:37
            # lenient adapter-edge wrapper (delegates to shared.money's strict
            # converter, adds default) — predates the ratchet, reviewer adjudicates.
            "backend/app/infrastructure/adapters/dhan_broker_adapter.py",
        }),
        "converters live in shared.money only",
    ),
    _IST_LITERAL_RE: (
        frozenset({
            "tests/quant/amt/session/test_context.py",
            "backend/tests/unit/domain/test_session_context.py",
        }),
        "IST offset literal lives in pinned tests only (py scope; "
        "frontend owner is frontend/time/ist.ts, re-exported by "
        "frontend/constants.ts — both out of the *.py scan)",
    ),
}

_EXCLUDE_DIRS = frozenset({
    ".venv", "venv", "node_modules", ".worktrees", "__pycache__", ".git",
})


def _py_files() -> list:
    out = []
    for p in sorted(ROOT.rglob("*.py")):
        if any(d in _EXCLUDE_DIRS for d in p.parts):
            continue
        out.append(p.relative_to(ROOT).as_posix())
    return out


def _hits(pattern: str, rel: str) -> list:
    return re.findall(pattern, (ROOT / rel).read_text(), re.MULTILINE)


def test_no_new_duplicate_tables():
    bad: dict = {}
    for rel in _py_files():
        for pattern, (allowed, _reason) in _DUPS.items():
            if _hits(pattern, rel) and rel not in allowed:
                bad.setdefault(rel, []).append(pattern)
    assert bad == {}, bad


_ALL_MODULES = (
    "shared.money",
    "shared.net_policy",
    "shared.reconnect",
    "brokers.broker.dhan.domain.order_status",
    "quant.execution.fills",
    "quant.execution.lots",
    "quant.contracts.instrument_registry",
)


def test_module_all_names_resolve():
    for name in _ALL_MODULES:
        mod = importlib.import_module(name)
        assert isinstance(mod.__all__, list), name
        assert mod.__all__ == sorted(mod.__all__), name
        for n in mod.__all__:
            assert hasattr(mod, n), (name, n)
