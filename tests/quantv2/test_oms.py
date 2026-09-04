from quantv2.types import Signal
from quantv2.oms import PaperOMS
import pytest


def test_submit_close_pnl():
    oms = PaperOMS()
    sig = Signal(type="LONG", entry=100.0, sl=99.0, tp=102.0, rr=2.0, setup="TRIPLE_A", symbol="X", timestamp="t")
    pos = oms.submit(sig, 10)
    f = oms.close(pos, 101.0, "TAKE_PROFIT")
    assert f.pnl == 10.0
    with pytest.raises(ValueError):
        oms.submit(sig, 0)
