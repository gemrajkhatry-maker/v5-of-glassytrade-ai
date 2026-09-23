# tests/quant/runtime/test_restore_open_risk.py
"""Task 3: restore_position must register REAL open risk after restart.

The restore path used to call ``register_open(0.0, symbol=...)``, so a
restarted book counted zero aggregate risk until the next entry/exit
reconciled it — the portfolio ceiling was blind to restored positions.
"""

from unittest.mock import MagicMock

import pytest

from quant.decision.signal_builder import Signal
from quant.execution.order import Order, Position
from quant.execution.portfolio_risk import PortfolioRiskAuthority
from quant.runtime import QuantEngine


def _position(entry=100.0, sl=99.0, qty=10.0, *, size=None):
    sig = Signal(
        type="LONG",
        reason="r",
        entry=entry,
        sl=sl,
        tp=entry + 2.0,
        rr=2.0,
        model_label="t",
        symbol="RESTORE-RISK",
        timestamp="t0",
    )
    return Position(
        order=Order(signal=sig, quantity=qty),
        open_price=entry,
        open_time="t0",
        size=abs(size) if size is not None else qty,
    )


def _engine(portfolio_risk):
    return QuantEngine(
        gateway=MagicMock(),
        symbol="RESTORE-RISK",
        portfolio_risk=portfolio_risk,
    )


def test_restore_registers_real_open_risk():
    pra = MagicMock()
    eng = _engine(pra)

    eng.restore_position(_position(entry=100.0, sl=99.0, qty=10.0))

    pra.register_open.assert_called_once()
    risk = pra.register_open.call_args.args[0]
    symbol = pra.register_open.call_args.kwargs.get("symbol")
    assert symbol == "RESTORE-RISK"
    assert risk > 0.0, "restore must not register 0.0 risk"
    assert risk == pytest.approx(abs(100.0 - 99.0) * 10.0)


def test_restore_updates_real_portfolio_authority():
    pra = PortfolioRiskAuthority(starting_equity=1_000_000.0)
    eng = _engine(pra)

    eng.restore_position(_position(entry=100.0, sl=99.5, qty=4.0))

    assert pra.open_risk == pytest.approx(abs(100.0 - 99.5) * 4.0)
    assert pra.active_symbol_for_root("RESTORE-RISK") == "RESTORE-RISK"


def test_restore_without_stop_registers_zero_not_invented_risk():
    """No SL → unknowable risk: 0.0 is left alone (cannot invent)."""
    pra = MagicMock()
    eng = _engine(pra)

    eng.restore_position(_position(entry=100.0, sl=0.0, qty=10.0))

    pra.register_open.assert_called_once()
    assert pra.register_open.call_args.args[0] == pytest.approx(0.0)
