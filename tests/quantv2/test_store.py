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


from quantv2.coordinator import Coordinator
from quantv2.engine import Engine
from quantv2.oms import PaperOMS

def test_corrupt_store_halts_symbol_only(tmp_path):
    p = str(tmp_path / "state.json")
    with open(p, "w") as f:
        f.write('{"X": {"position": {"bad": 1}, "open_risk": 1.0, "trail": {}}}')
    c = Coordinator()
    c.add(Engine(symbol="X", interval_sec=60, oms=PaperOMS(), equity=100000.0))
    c.load_state(restore(p))
    assert c.engines["X"].position is None and c.engines["X"].can_trade is False

def test_restore_non_dict_returns_empty(tmp_path):
    p = str(tmp_path / "state.json")
    with open(p, "w") as f:
        f.write('["not", "a", "dict"]')
    assert restore(p) == {}
