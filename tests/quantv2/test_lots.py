from quantv2.lots import load_lots, lot_of

def test_lot_lookup(tmp_path):
    p = str(tmp_path / "lots.json")
    with open(p, "w") as f:
        f.write('{"NIFTY28AUGFUT": {"lot_size": 75, "tick_size": 0.05}}')
    reg = load_lots(p)
    assert lot_of(reg, "NIFTY28AUGFUT") == (75.0, 0.05)
    assert lot_of(reg, "MISSING") == (1.0, 0.05)
