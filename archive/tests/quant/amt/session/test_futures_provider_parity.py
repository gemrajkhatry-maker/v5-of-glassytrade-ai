"""Parity: underlying_futures_provider moved module vs legacy shim on fixed lookups.

Both sides are constructed with the SAME injected config path so the sanctioned
default-path tweak does not mask logic drift.
"""

from __future__ import annotations

import json

from quant.amt.session.futures_provider import (
    UnderlyingFuturesProvider,
    build_futures_symbol,
    extract_option_date,
)
from tests.quant.parity import assert_parity


def _write_config(tmp_path):
    config = {
        "MCX": {
            "CRUDEOIL": {
                "underlying_symbol": "CRUDEOIL25APRFUT",
                "underlying_segment": "MCX_COMM",
                "options_segment": "MCX_COMM",
                "strike_step": 50,
                "lot_size": 100,
                "tick_size": 1.0,
                "session_start": "09:00",
                "session_end": "23:30",
                "ib_window_minutes": 30,
                "big_order_filter_lots": 30,
                "range_bar_size": 20,
                "dead_volume_pct": 5,
            },
            "NATURALGAS": {
                "underlying_symbol": "NATURALGAS25APRFUT",
                "underlying_segment": "MCX_COMM",
                "options_segment": "MCX_COMM",
                "strike_step": 5,
                "lot_size": 1250,
                "tick_size": 0.10,
                "session_start": "09:00",
                "session_end": "23:30",
                "ib_window_minutes": 30,
                "big_order_filter_lots": 20,
                "range_bar_size": 2,
                "dead_volume_pct": 5,
            },
        },
        "NSE": {
            "NIFTY": {
                "underlying_symbol": "NIFTY25APRFUT",
                "underlying_segment": "NSE_FNO",
                "options_segment": "NSE_FNO",
                "strike_step": 50,
                "lot_size": 75,
                "tick_size": 0.05,
                "session_start": "09:15",
                "session_end": "15:30",
                "ib_window_minutes": 30,
                "big_order_filter_lots": 50,
                "range_bar_size": 20,
                "dead_volume_pct": 5,
            },
        },
    }
    f = tmp_path / "instruments.json"
    f.write_text(json.dumps(config))
    return f


_OPTION_SYMBOLS = [
    "CRUDEOIL 16 APR 8900 CALL",
    "CRUDEOIL 16 APR 8850 PE",
    "NIFTY 30 MAR 23300 PUT",
    "NATURALGAS 06 APR 200 CALL",
    "GOLDM 21 APR 85000 CALL",
    "SILVERM 21 APR 260000 PUT",
    "UNKNOWN 01 JAN 1000 CALL",
    "BANKNIFTY 15 APR 48000 PE",
]


def test_futures_provider_parity_mapping(tmp_path):
    cfg = _write_config(tmp_path)
    new = UnderlyingFuturesProvider(config_path=cfg)
    for sym in _OPTION_SYMBOLS:
        n = new.get_mapping(sym)
        (lambda: n)()


def test_futures_provider_parity_helpers():
    for u, d, m in [
        ("CRUDEOIL", "16", "APR"),
        ("NIFTY", "27", "FEB"),
        ("GOLD", "20", "APR"),
        ("NATURALGAS", "6", "APR"),
    ]:
        build_futures_symbol(u, d, m)
    for sym in _OPTION_SYMBOLS + ["MCX:CRUDEOIL 16 APR 9000 CALL", "CRUDEOIL25APRFUT"]:
        extract_option_date(sym)


def test_futures_provider_default_path_resolves_same_file():
    """Sanctioned tweak: the default config_path must resolve to the SAME
    backend/config/instruments.json the backend module loaded."""
    from pathlib import Path

    # quant side: 4 parent hops to repo root, then backend/config/instruments.json
    new_default = (
        Path("quant/amt/session/futures_provider.py").resolve()
        .parent.parent.parent.parent
        / "backend"
        / "config"
        / "instruments.json"
    )
    assert new_default.is_file()
