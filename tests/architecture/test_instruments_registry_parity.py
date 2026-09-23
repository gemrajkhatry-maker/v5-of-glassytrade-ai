"""InstrumentRegistry is SSoT — instruments.json + market_info tables may not
carry independent lot/tick/strike numbers that disagree with the registry.

Known bug (Task 18): instruments.json GOLD lot_size=1 vs registry 100;
GOLDM lot_size=100 vs registry 10. Keys may be absent from the json (futures_provider
only needs underlying/session/range config) but if present they must equal the registry.
"""

from __future__ import annotations

import json
from pathlib import Path

from brokers.broker.market_info import (
    LOT_SIZES,
    STEP_SIZES,
    get_step_size,
    normalize_symbol,
)
from quant.contracts.instrument_registry import DEFAULT_REGISTRY

_ROOT = Path(__file__).resolve().parents[2]
_INSTRUMENTS_JSON = _ROOT / "backend" / "config" / "instruments.json"

# lot_size/tick_size/strike_step in json  ->  InstrumentSpec attribute
_SPEC_KEYS = (
    ("lot_size", "lot_size", int),
    ("tick_size", "tick_size", float),
    ("strike_step", "strike_interval", float),
)


def _load_json() -> dict:
    return json.loads(_INSTRUMENTS_JSON.read_text())


def test_registry_gold_goldm_lot_truth():
    """Locks the GOLD/GOLDM swap: registry is truth."""
    assert DEFAULT_REGISTRY.resolve("GOLD").lot_size == 100
    assert DEFAULT_REGISTRY.resolve("GOLDM").lot_size == 10


def test_instruments_json_roots_resolve_in_registry():
    unknown = []
    for _exchange, roots in _load_json().items():
        for root in roots:
            if DEFAULT_REGISTRY.try_resolve(root) is None:
                unknown.append(root)
    assert not unknown, f"instruments.json roots missing from registry: {unknown}"


def test_instruments_json_numeric_specs_match_registry_or_absent():
    """Every lot/tick/strike key carried by instruments.json must equal the
    registry — or the key must be removed entirely (SSoT)."""
    mismatches = []
    for _exchange, roots in _load_json().items():
        for root, cfg in roots.items():
            spec = DEFAULT_REGISTRY.try_resolve(root)
            for key, attr, cast in _SPEC_KEYS:
                if key not in cfg:
                    continue
                if spec is None:
                    mismatches.append(f"{root}.{key} present but root not in registry")
                    continue
                json_val = cast(cfg[key])
                registry_val = cast(getattr(spec, attr))
                if json_val != registry_val:
                    mismatches.append(
                        f"{root}.{key} instruments.json={json_val} registry={registry_val}"
                    )
    assert not mismatches, mismatches


def test_market_info_lot_sizes_agree_with_registry():
    mismatches = [
        f"{spec.root}: table={LOT_SIZES[spec.root]} registry={spec.lot_size}"
        for spec in DEFAULT_REGISTRY.specs()
        if spec.root in LOT_SIZES and LOT_SIZES[spec.root] != spec.lot_size
    ]
    assert not mismatches, mismatches


def test_market_info_tables_carry_no_display_alias_keys():
    """Aliases like "NIFTY 50" duplicate registry values under a second key —
    normalize_symbol already maps them; the table must not restate them."""
    for name, table in (("LOT_SIZES", LOT_SIZES), ("STEP_SIZES", STEP_SIZES)):
        aliases = [k for k in table if normalize_symbol(k) != k]
        assert not aliases, f"{name} carries non-canonical alias keys: {aliases}"


def test_market_info_step_sizes_derive_from_registry():
    for spec in DEFAULT_REGISTRY.specs():
        assert spec.root in STEP_SIZES, f"STEP_SIZES missing registry root {spec.root}"
        assert STEP_SIZES[spec.root] == float(spec.strike_interval), (
            f"{spec.root}: STEP_SIZES={STEP_SIZES[spec.root]} "
            f"registry={spec.strike_interval}"
        )
        assert get_step_size(spec.root) == float(spec.strike_interval), spec.root


def test_market_info_keeps_non_registry_extras():
    """Stocks and non-registry micros still resolve through the fallback tables."""
    from brokers.broker.market_info import get_lot_size

    assert get_lot_size("RELIANCE") == 250
    assert get_lot_size("UNKNOWN_XYZ") == 1
    assert STEP_SIZES["GOLDGUINEA"] == 10.0
    assert STEP_SIZES["SILVERMIC"] == 10.0
