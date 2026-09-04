from quantv2.coordinator import Coordinator
from quantv2.engine import Engine
from quantv2.oms import PaperOMS
from quantv2.amt import SessionAMT
from quantv2.store import save, restore


def test_full_loop_approve_exit_eod_restore(tmp_path):
    c = Coordinator(risk_cap=1_000_000.0)
    eng = Engine(symbol="X", interval_sec=60, oms=PaperOMS(), equity=100000.0)
    eng.amt = SessionAMT(tick=0.05)
    c.add(eng)
    # 3 flat bars (no setup) in buckets 0..2
    for i in range(3):
        c.on_tick("X", 60 * i, 100.0, 5.0, 0.0)
    # break tick starts the bucket-3 bar (rises above forming VAH with strong delta)
    c.on_tick("X", 180, 100.5, 2.0, 12.0)
    # first tick of bucket 4 flushes the break bar -> INITIATIVE-UP approve
    c.on_tick("X", 240, 100.7, 1.0, 1.0)
    approved = eng.last_decision
    assert approved is not None and approved.approved and approved.reason == "INITIATIVE"
    assert approved.position is not None and approved.position.side == "LONG"
    pos = eng.position
    assert pos is not None
    # next bar: rising ticks drive high through the take-profit; sentinel bucket-5 tick closes it
    c.on_tick("X", 260, 101.0, 1.0, 1.0)
    c.on_tick("X", 280, pos.tp + 0.2, 1.0, 1.0)
    c.on_tick("X", 300, 101.4, 1.0, 0.0)
    assert eng.position is None
    assert eng.last_decision.reason == "EXITED_TAKE_PROFIT"
    # EOD flatten is a no-op now; save + restore into a fresh coordinator
    assert c.eod_flatten() == 0
    p = str(tmp_path / "s.json")
    save(c, p)
    c2 = Coordinator(risk_cap=1_000_000.0)
    c2.add(Engine(symbol="X", interval_sec=60, oms=PaperOMS(), equity=100000.0))
    c2.load_state(restore(p))
    assert c2.engines["X"].position is None
    # engine still decides after restore
    out = c2.on_tick("X", 480, 101.0, 1.0, 0.0)
    assert out is None  # mid-bar, no crash