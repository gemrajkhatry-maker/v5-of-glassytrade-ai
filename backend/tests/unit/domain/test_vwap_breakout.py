from app.domain.fabio_ai.services.vwap_breakout import detect_vwap_breakout


def test_long_on_breakout_with_volume():
    assert detect_vwap_breakout(vwap=100, std=5, price=108, volume=250, avg_volume=100) == "LONG"


def test_short_on_breakdown_with_volume():
    assert detect_vwap_breakout(vwap=100, std=5, price=92, volume=250, avg_volume=100) == "SHORT"


def test_no_signal_without_volume_confirmation():
    assert detect_vwap_breakout(vwap=100, std=5, price=108, volume=100, avg_volume=100) is None


def test_no_signal_inside_bands():
    assert detect_vwap_breakout(vwap=100, std=5, price=102, volume=300, avg_volume=100) is None


def test_guards_zero_inputs():
    assert detect_vwap_breakout(vwap=0, std=5, price=108, volume=250, avg_volume=100) is None
    assert detect_vwap_breakout(vwap=100, std=0, price=108, volume=250, avg_volume=100) is None
