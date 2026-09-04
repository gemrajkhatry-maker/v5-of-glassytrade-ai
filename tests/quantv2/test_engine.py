from quantv2.engine import Engine
from quantv2.oms import PaperOMS, Position
from quantv2.types import Bar
from quantv2.exits import ExitConfig
from quantv2.clock import SessionClock
from quantv2.session_risk import RiskLimits, SessionRisk


def test_engine_holds_then_exits():
    eng = Engine(symbol="X", interval_sec=60, oms=PaperOMS(), equity=100000.0, exit_cfg=ExitConfig(tick=0.05))
    d = eng.on_tick(0, 100.0, 1.0, 0.0)
    assert d is None
    d = eng.on_tick(60, 100.0, 1.0, 0.0)
    assert d is not None and d.approved is False and d.reason in ("NO_EDGE", "HOLDING")


def test_engine_fires_time_stop_from_bar_clock():
    cfg = ExitConfig(time_stop_min=30, trail_ticks=4, tick=0.05)
    eng = Engine(symbol="X", interval_sec=60, oms=PaperOMS(), equity=100000.0, exit_cfg=cfg)
    eng.position = Position(pid="p1", symbol="X", side="LONG", qty=10.0, entry=100.0, sl=90.0, tp=200.0, setup="T", opened_at="2026-01-01T09:15:00+05:30")
    d = eng.on_bar(Bar(time="2026-01-01T09:46:00+05:30", open=100.0, high=100.5, low=99.9, close=100.2))
    assert eng.position is None and d.reason == "EXITED_TIME_STOP"
    eng2 = Engine(symbol="X", interval_sec=60, oms=PaperOMS(), equity=100000.0, exit_cfg=cfg)
    eng2.position = Position(pid="p2", symbol="X", side="LONG", qty=10.0, entry=100.0, sl=90.0, tp=200.0, setup="T", opened_at="2026-01-01T09:15:00+05:30")
    d2 = eng2.on_bar(Bar(time="2026-01-01T09:20:00+05:30", open=100.0, high=100.5, low=99.9, close=100.2))
    assert d2.reason == "HOLDING" and eng2.position is not None


def test_engine_time_stop_skips_malformed_timestamps():
    eng = Engine(symbol="X", interval_sec=60, oms=PaperOMS(), equity=100000.0, exit_cfg=ExitConfig(time_stop_min=30, trail_ticks=4, tick=0.05))
    eng.position = Position(pid="p3", symbol="X", side="LONG", qty=10.0, entry=100.0, sl=90.0, tp=200.0, setup="T", opened_at="garbage")
    d = eng.on_bar(Bar(time="2026-01-01T09:46:00+05:30", open=100.0, high=100.5, low=99.9, close=100.2))
    assert d.reason == "HOLDING" and eng.position is not None


class FailingCloseOMS(PaperOMS):
    def close(self, pos, price, reason):
        raise RuntimeError("broker down")


def test_close_raise_keeps_position():
    eng = Engine(symbol="X", interval_sec=60, oms=FailingCloseOMS(), equity=100000.0)
    eng.position = Position(pid="p1", symbol="X", side="LONG", qty=1.0, entry=100.0, sl=99.0, tp=102.0, setup="T", opened_at="t")
    d = eng.on_bar(Bar(time="2026-09-04T10:01:00+05:30", open=99.0, high=100.0, low=98.0, close=98.5))
    assert d.approved is False and d.reason == "EXIT_RETRY" and eng.position is not None


def test_clock_drives_session_open_and_force_exit():
    clock = SessionClock("NSE")
    risk = SessionRisk(RiskLimits(daily_loss_limit=100.0, max_trades=10, cooldown_sec=60))
    eng = Engine(symbol="X", interval_sec=60, oms=PaperOMS(), equity=100000.0, clock=clock, risk=risk)
    early = eng.on_bar(Bar(time="2026-09-04T09:00:00+05:30", open=100.0, high=100.5, low=99.9, close=100.2))
    assert eng.session_open is False and early.reason == "SESSION_CLOSED"
    eng.position = Position(pid="p1", symbol="X", side="LONG", qty=10.0, entry=100.0, sl=90.0, tp=200.0, setup="T", opened_at="2026-09-04T09:30:00+05:30")
    d = eng.on_bar(Bar(time="2026-09-04T15:25:00+05:30", open=100.0, high=100.5, low=99.9, close=100.2))
    assert d.reason == "EXITED_SESSION_CLOSE" and eng.position is None
    assert risk.trades == 1


def test_risk_cooldown_gates_entry():
    from datetime import datetime, timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))
    clock = SessionClock("NSE")
    risk = SessionRisk(RiskLimits(daily_loss_limit=100.0, max_trades=10, cooldown_sec=60))
    eng = Engine(symbol="X", interval_sec=60, oms=PaperOMS(), equity=100000.0, clock=clock, risk=risk)
    bar_ts = datetime(2026, 9, 4, 10, 1, tzinfo=IST).timestamp()
    risk.record_fill(-10.0, now=bar_ts - 5.0)
    d = eng.on_bar(Bar(time="2026-09-04T10:01:00+05:30", open=100.0, high=100.5, low=99.9, close=100.2))
    assert d.approved is False and d.reason == "COOLDOWN"


def test_risk_daily_loss_halt_gates_entry():
    from datetime import datetime, timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))
    clock = SessionClock("NSE")
    risk = SessionRisk(RiskLimits(daily_loss_limit=100.0, max_trades=10, cooldown_sec=0))
    bar_ts = datetime(2026, 9, 4, 10, 1, tzinfo=IST).timestamp()
    risk.record_fill(-100.0, now=bar_ts)
    eng = Engine(symbol="X", interval_sec=60, oms=PaperOMS(), equity=100000.0, clock=clock, risk=risk)
    d = eng.on_bar(Bar(time="2026-09-04T10:01:00+05:30", open=100.0, high=100.5, low=99.9, close=100.2))
    assert d.approved is False and d.reason == "DAILY_LOSS"
