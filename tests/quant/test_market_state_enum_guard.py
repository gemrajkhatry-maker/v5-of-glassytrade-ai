"""REF-5 guard: MarketState is an enum at internal edges.

Raw "BALANCED"/"IMBALANCED"/"DEAD" literals caused an 11-file rename blast
radius (audit SMELL-5). Internal code must use MarketState members; string
conversion happens only at the DTO/serialization boundary (amt/dto.py,
contracts/enums.py codecs) or when parsing EXTERNAL input (WS payloads).
"""

import ast
import pathlib

QUANT = pathlib.Path(__file__).resolve().parents[2] / "quant"

ALLOWLIST = {
    "contracts/enums.py",        # the enum itself + codec parsing
    "amt/dto.py",                # wire serialization boundary
    "decision/context.py",       # docstring comment only
    "execution/exit_rules.py",   # table keys use MarketState.X.value
    "decision/context_builder.py",  # parses amt_dto wire input (DTO boundary)
    "decision/gates_edge.py",       # accepts enum OR legacy string from DTOs
    "amt/analyzer.py",              # produces .value strings for the DTO
    "position_manager.py",          # parses amt_dto wire input
}


def _raw_state_literals():
    hits = []
    for path in sorted(QUANT.rglob("*.py")):
        rel = str(path.relative_to(QUANT))
        if rel in ALLOWLIST or "__pycache__" in rel:
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and node.value in ("BALANCED", "IMBALANCED", "DEAD")):
                hits.append(f"{rel}:{node.lineno}")
    return hits


def test_no_raw_market_state_literals_outside_allowlist():
    hits = _raw_state_literals()
    assert not hits, (
        "Raw MarketState string literals found — use MarketState members "
        f"or route through amt/dto.py:\n" + "\n".join(hits)
    )


def test_tick_size_is_exchange_authoritative():
    """REF-3: MCX futures tick sizes come from ExchangeConfig, not the
    legacy 0.05 NSE-option default."""
    from quant.contracts.exchange_config import ExchangeConfig

    mcx = ExchangeConfig.for_exchange("MCX")
    assert mcx.get_tick_size("GOLDM") == 1.0
    assert mcx.get_tick_size("CRUDEOIL") == 1.0

    nse = ExchangeConfig.for_exchange("NSE")
    # Fallback for unlisted NSE symbols stays 0.05 (option scale).
    assert nse.get_tick_size("UNKNOWN_SYM") == 0.05


def test_coordinator_resolves_per_symbol_tick_size(monkeypatch):
    """Engines spawned by the coordinator get the exchange-correct tick size,
    not the global default."""
    from quant.multi_engine import QuantCoordinator

    class _FakeMD:
        def get_nearest_futures(self, underlying, exchange=None):
            return None

        def fetch_history(self, *a, **k):
            return []

        def get_lot_size(self, symbol):
            return 1

    coord = QuantCoordinator(
        market_data=_FakeMD(),
        config={"include_futures": False, "n": 2, "exchange": "MCX",
                "underlyings": [], "contracts_file": "/tmp/nonexistent-ts.json"},
    )
    monkeypatch.setattr(coord, "_scan",
                        lambda force=False: ["GOLDM SEP FUT"], raising=True)
    coord.start()
    try:
        eng = coord._engines["GOLDM SEP FUT"]
        assert eng._tick_size == 1.0, (
            f"engine tick_size={eng._tick_size}, expected exchange value 1.0"
        )
    finally:
        coord.stop()
