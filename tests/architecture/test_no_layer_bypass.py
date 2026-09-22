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

# NOTE: hardened to span ONE nesting level (the LOT_SIZES tables embed a
# {**registry...} comprehension). A bare [\s\S]*? was tried and REJECTED:
# it spans to any later "NIFTY" in the file, false-positiving on
# quant/amt/session/selector.py (MCX_LOT_SIZES comps + far-below BANKNIFTY)
# and quant/multi_engine.py (empty dict[str, float] locals + far-below
# comment). This bounded form keeps the hit set identical to the old
# [^}]* while genuinely catching the nested-brace LOT_SIZES table the old
# form missed (verified: old misses that block, this catches it).
_LOT_SIZE_TABLE_RE = (
    r"^\s*(?:\w+\s*:\s*)?(?:Dict\[str,\s*(?:int|float)\]"
    r"|dict\[str,\s*(?:int|float)\])\s*=\s*\{(?:[^{}]|\{[^{}]*\})*?NIFTY"
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


# --- New-code logging hygiene (ADR-0003): facade-only, no bare except -----
#
# Files CREATED by Plans A–E, hardcoded with intent (explicit > clever — do
# not generalize to a "created by plans" heuristic). New code must use the
# logging facades (brokers/broker/logging, backend/app/core/logging), never
# raw logging.getLogger, and never bare `except Exception`. Everything else
# is grandfathered (no mass migration — YAGNI). This file itself is NOT in
# the list (it contains the patterns as string literals).
_NEW_CODE_HYGIENE_FILES = frozenset({
    "shared/money.py",
    "shared/net_policy.py",
    "shared/reconnect.py",
    "brokers/broker/dhan/domain/order_status.py",
    "quant/execution/fills.py",
    "quant/execution/lots.py",
    "quant/amt/session/scanner_config.py",
    "tests/quant/contracts/test_money_parity.py",
    "tests/quant/contracts/test_services_boundaries.py",
    "tests/quant/contracts/test_telemetry_standards.py",
})

_GETLOGGER_RE = r"logging\.getLogger\s*\("
_BARE_EXCEPT_RE = r"except\s+Exception\s*(:|as\b)"


def test_new_code_logging_hygiene():
    bad: dict = {}
    for rel in sorted(_NEW_CODE_HYGIENE_FILES):
        src = _read(rel)
        if re.search(_GETLOGGER_RE, src):
            bad.setdefault(rel, []).append("logging.getLogger (use a facade)")
        if re.search(_BARE_EXCEPT_RE, src):
            bad.setdefault(rel, []).append("bare except Exception")
    assert bad == {}, bad


# --- Engine-type boundary (ADR-0001, Plan E Task 2 deferred item) -----------
#
# DECISION (expressibility verdict, 2026-09-03): only the execution/order
# half is gated. The entities half was measured and SKIPPED as too
# diffuse: legit non-test runtime importers span three layers —
# quant/contracts/aggregates.py (same bounded context), 
# quant/contracts/ports/broker.py (port definition), and
# backend/app/application/services/trading_query_service.py (read model) —
# plus a TYPE_CHECKING-only use in quant/execution/exit_rules.py. An
# allowlist covering all of those would be near-vacuous, so ADR-0001's
# prose carries the entities rule instead. Evidence: grep
# "from quant.contracts.entities import" (7 non-test .py importers).
#
# The order half IS stable: engine Order/Position/Fill may only be
# imported at runtime by execution/*, state, event_store,
# persistence_bridge, multi_engine, and tests. TYPE_CHECKING-only imports
# (quant/events.py) are stripped before matching — they emit no runtime
# crossing. Alternate spellings checked 2026-09-03: no
# "from quant.execution import order" / "import quant.execution.order"
# exists in the tree, so the single literal covers the idiom in use.
_ORDER_IMPORT_RE = r"from quant\.execution\.order import"

_ORDER_ALLOWED_FILES = frozenset({
    "quant/state.py",
    "quant/event_store.py",
    "quant/persistence_bridge.py",
    "quant/multi_engine.py",
})

_ORDER_ALLOWED_PREFIXES = ("quant/execution/",)

_TEST_SCOPE_PREFIXES = ("tests/", "backend/tests/", "runtime_audit/")


def _without_type_checking(src: str) -> str:
    """Drop `if TYPE_CHECKING:` blocks (indent-delimited) from *src*."""
    out = []
    skipping = False
    for line in src.splitlines(keepends=True):
        stripped = line.lstrip()
        if re.match(r"if\s+TYPE_CHECKING\s*:", stripped):
            skipping = True
            continue
        if skipping:
            if stripped == "" or line[:1] in (" ", "\t"):
                continue
            skipping = False
        out.append(line)
    return "".join(out)


def _order_importer_allowed(rel: str) -> bool:
    if rel.startswith(_TEST_SCOPE_PREFIXES):
        return True
    if rel in _ORDER_ALLOWED_FILES:
        return True
    return rel.startswith(_ORDER_ALLOWED_PREFIXES)


# --- Brain -> host direction: quant must not import the application --------
#
# quant is the deterministic brain and must run standalone (replay, scripts,
# CI, an embedding) with the backend package absent from sys.path. The host
# imports quant, never the reverse; the seam for anything quant needs from the
# host is a port in quant/contracts/ports (implemented by a backend adapter).
#
# Concrete regression this gates: the decision-loop telemetry hook reached for
# app.infrastructure.metrics behind `try/except ImportError` and kept counting
# into a counter nothing served — silently, and only where the backend
# package happened to be importable.
_QUANT_PREFIX = "quant/"
_HOST_IMPORT_RE = r"^\s*(?:from|import)\s+(?:app|backend)\b"


def test_quant_never_imports_the_host_application():
    bad: list = []
    for rel in _py_files():
        if not rel.startswith(_QUANT_PREFIX):
            continue
        if re.search(_HOST_IMPORT_RE, _read(rel), re.MULTILINE):
            bad.append(rel)
    assert bad == [], bad


def test_engine_order_imports_stay_in_allowlist():
    bad: list = []
    for rel in _py_files():
        if _order_importer_allowed(rel):
            continue
        if re.search(_ORDER_IMPORT_RE, _without_type_checking(_read(rel))):
            bad.append(rel)
    assert bad == [], bad


# --- ADR-0001 crossing-function allowlist (Consequences section, now built) --
#
# Engine (float) and broker (Decimal) entity families may cross ONLY through
# the four named mappers, and those mappers may be referenced only from their
# defining modules and the three sanctioned call sites. Any new hit elsewhere
# is an unreviewed crossing — the exact defect class (qty dropped, field
# sniffing) this ADR exists to prevent. Definitions live in the allowlist, so
# the gate governs callers.
_CROSSING_RE = re.compile(
    r"\b(to_broker_signal|broker_position_to_fill|position_to_row|row_to_position)\s*\("
)

_CROSSING_ALLOWED_FILES = frozenset({
    "quant/execution/broker_mapper.py",   # defines to_broker_signal
    "quant/execution/fills.py",           # defines broker_position_to_fill
    "quant/execution/order.py",           # defines position_to_row / row_to_position
    "quant/execution/live_oms.py",        # sanctioned crossings (ADR-0001)
    "quant/persistence_bridge.py",        # sanctioned crossings (ADR-0001)
    "quant/multi_engine.py",              # sanctioned restore call (ADR-0001)
})


def test_crossing_functions_stay_in_allowlist():
    bad: list = []
    for rel in _py_files():
        if rel.startswith(_TEST_SCOPE_PREFIXES) or rel in _CROSSING_ALLOWED_FILES:
            continue
        if _CROSSING_RE.search(_without_type_checking(_read(rel))):
            bad.append(rel)
    assert bad == [], (
        "engine↔broker entity crossing outside ADR-0001's named mappers — "
        f"route it through broker_mapper/fills/order instead: {bad}"
    )
