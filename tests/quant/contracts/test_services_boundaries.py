# tests/quant/contracts/test_services_boundaries.py
from shared.reconnect import ReconnectPolicy


def test_ws_curve_preserved():
    p = ReconnectPolicy(base=5.0, cap=60.0, max_attempts=30)
    assert p.delay_for(0) == 5.0
    assert p.delay_for(1) == 10.0
    assert p.delay_for(10) == 60.0
    assert p.should_retry(29) is True
    assert p.should_retry(30) is False


def test_http_curve_preserved():
    p = ReconnectPolicy(base=0.5, cap=30.0, max_attempts=3)
    assert p.delay_for(0) == 0.5
    assert p.delay_for(1) == 1.0
    assert p.delay_for(10) == 30.0


def test_feed_curve_preserved():
    # feed: backoff starts 1.0, doubles each loop, capped at reconnect_sec
    p = ReconnectPolicy(base=1.0, cap=5.0, max_attempts=10**9)
    assert p.delay_for(1) == 2.0
    assert p.delay_for(0) == 1.0
    assert p.delay_for(10) == 5.0
