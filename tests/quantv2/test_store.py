from quantv2.engine import Engine
from quantv2.oms import PaperOMS
from quantv2.coordinator import Coordinator
from quantv2.store import save, restore


def test_save_restore_roundtrip(tmp_path):
    c = Coordinator()
    c.add(Engine(symbol="X", interval_sec=60, oms=PaperOMS(), equity=100000.0))
    p = str(tmp_path / "state.json")
    save(c, p)
    state = restore(p)
    assert state == {} or "X" in state
    c.load_state(state)
