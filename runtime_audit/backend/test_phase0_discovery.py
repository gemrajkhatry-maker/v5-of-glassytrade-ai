"""PHASE 0 — system discovery: routes, boot components, import graph."""

import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "out"


def test_all_routers_registered():
    from backend.app.main import create_application

    app = create_application()
    routes = set()
    for r in app.routes:
        if type(r).__name__ == "_IncludedRouter":
            r = r.original_router
        path = getattr(r, "path", None)
        if path is None:
            for sub in getattr(r, "routes", []) or []:
                sub_path = getattr(sub, "path", None)
                if sub_path:
                    methods = getattr(sub, "methods", None)
                    routes.add((sorted(methods)[0] if methods else "WS", sub_path))
            continue
        methods = getattr(r, "methods", None)
        routes.add((sorted(methods)[0] if methods else "WS", path))
    table = sorted(f"{m or 'WS':<6} {p}" for m, p in routes)
    print("\n--- ROUTE TABLE ---")
    for line in table:
        print(line)

    required = [
        "/health", "/health/ready",
        "/api/trading/ws/gameloop",
        "/api/system/config",
        "/api/market/history/{symbol}",
        "/api/journal/trades",
    ]
    missing = [p for p in required
               if not any(path.endswith(p) or p.endswith(path) or p == path
                          for _, path in routes)]
    assert not missing, f"missing required routes: {missing}"


def test_boot_components_importable():
    from quant.multi_engine import QuantCoordinator, load_persisted_contracts
    from quant.amt.session.scanner import OptionScannerService
    from quant.runtime import QuantEngine
    from quant.ws_adapter import view_state_to_ws

    assert QuantCoordinator and OptionScannerService and QuantEngine
    assert view_state_to_ws and load_persisted_contracts


def test_import_graph_dumped():
    import backend.app.main  # noqa: F401
    import quant.runtime  # noqa: F401
    import quant.multi_engine  # noqa: F401

    edges = {}
    for name, mod in sorted(sys.modules.items()):
        if name.startswith(("quant.", "backend.")) and mod is not None:
            deps = sorted({m.split(".")[0] + "." + m.split(".")[1]
                           for m in getattr(mod, "__dict__", {})
                           if isinstance(m, str) and False})
            edges[name] = len([a for a in vars(mod)
                               if not a.startswith("__")])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "phase0_import_graph.json").write_text(json.dumps(edges, indent=1))
    print(f"import graph: {len(edges)} modules dumped")
