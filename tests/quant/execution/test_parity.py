"""Parity tests — prove moved quant.execution.* modules match their legacy twins.

Each test drives the legacy module via its re-export shim (``app.domain.*``)
and the moved module (``quant.execution.*``) with identical inputs and asserts
byte-identical observable output via ``assert_parity``.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests.quant.parity import assert_parity

from quant.contracts.entities import Position
from quant.contracts.enums import Side, CushionState
from quant.execution.trail import TrailEngine as QuantTrailEngine


# ---------------------------------------------------------------------------
# TrailEngine
# ---------------------------------------------------------------------------


def _trail_position(side: Side = Side.LONG) -> Position:
    pos = Position(
        symbol="CRUDEOIL",
        side=side,
        entry_price=Decimal("6500.0"),
        size=Decimal("100"),
        stop_loss=Decimal("6480.0"),
        initial_stop=Decimal("6480.0"),
        take_profit=Decimal("6540.0"),
    )
    pos.partial_taken = True
    return pos


def _run_atr_trail(engine_cls) -> dict:
    engine = engine_cls()
    pos = _trail_position()
    engine.apply_atr_trail(pos, 6520.0)  # arm at 1R
    engine.apply_atr_trail(pos, 6540.0)  # trail to 2R
    return {
        "stop_loss": float(pos.stop_loss),
        "peak_profit": float(pos.peak_profit),
        "atr_trail_active": pos.atr_trail_active,
        "cushion_state": pos.cushion_state.value,
    }


def _run_vwap_trail(engine_cls) -> dict:
    engine = engine_cls()
    pos = _trail_position()
    engine.apply_vwap_trail(
        pos, current_price=6530.0,
        vwap=6495.0, vwap_upper_1=6505.0, vwap_lower_1=6485.0,
        vwap_upper_2=6515.0, vwap_lower_2=6475.0,
    )
    return {"stop_loss": float(pos.stop_loss)}


def _run_imbalance_tighten(engine_cls) -> dict:
    engine = engine_cls()
    pos = _trail_position()
    imbalances = [type("Imbalance", (), {"direction": "SELL"})()]
    tightened = engine.apply_imbalance_tighten(pos, imbalances, current_price=6510.0)
    return {"tightened": tightened, "stop_loss": float(pos.stop_loss)}


def _run_cvd_breakeven(engine_cls) -> dict:
    engine = engine_cls()
    pos = _trail_position()
    moved = engine.apply_cvd_breakeven(pos, cvd_slope=0.6)
    return {"moved": moved, "stop_loss": float(pos.stop_loss), "breakeven_set": pos.breakeven_set}


def _run_adjust_sl(engine_cls) -> dict:
    engine = engine_cls()
    pos = _trail_position()
    ok = engine.adjust_stop_loss(pos, 6485.123)
    return {"ok": ok, "stop_loss": float(pos.stop_loss)}


def test_trail_atr_parity():
    import importlib
    legacy = importlib.import_module("app.domain.fabio_ai.services.trail_engine").TrailEngine
    assert_parity(
        lambda: _run_atr_trail(legacy),
        lambda: _run_atr_trail(QuantTrailEngine),
    )


def test_trail_vwap_parity():
    import importlib
    legacy = importlib.import_module("app.domain.fabio_ai.services.trail_engine").TrailEngine
    assert_parity(
        lambda: _run_vwap_trail(legacy),
        lambda: _run_vwap_trail(QuantTrailEngine),
    )


def test_trail_imbalance_tighten_parity():
    import importlib
    legacy = importlib.import_module("app.domain.fabio_ai.services.trail_engine").TrailEngine
    assert_parity(
        lambda: _run_imbalance_tighten(legacy),
        lambda: _run_imbalance_tighten(QuantTrailEngine),
    )


def test_trail_cvd_breakeven_parity():
    import importlib
    legacy = importlib.import_module("app.domain.fabio_ai.services.trail_engine").TrailEngine
    assert_parity(
        lambda: _run_cvd_breakeven(legacy),
        lambda: _run_cvd_breakeven(QuantTrailEngine),
    )


def test_trail_adjust_sl_parity():
    import importlib
    legacy = importlib.import_module("app.domain.fabio_ai.services.trail_engine").TrailEngine
    assert_parity(
        lambda: _run_adjust_sl(legacy),
        lambda: _run_adjust_sl(QuantTrailEngine),
    )
