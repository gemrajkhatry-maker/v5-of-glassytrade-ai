from datetime import datetime, timezone, timedelta

from quantv2.journal import Journal
from quantv2.runner import Runner, RunnerConfig

IST = timezone(timedelta(hours=5, minutes=30))


def _ist(h: int, m: int) -> float:
    return datetime(2026, 9, 4, h, m, tzinfo=IST).timestamp()


def test_runner_paper_step_and_watchdog():
    cfg = RunnerConfig(symbols=["NF"], interval_sec=60, mode="paper", equity=100000.0)
    r = Runner.build(cfg)
    n = r.step({"security_id": r.security_ids["NF"], "ltp": 100.0, "volume": 1.0, "ts": 60.0})
    assert n == 1
    r.tick_watchdog(_ist(15, 25))  # 15:25 IST
    snap = r.snapshot()
    assert "NF" in snap and snap["NF"]["position"] is None


def test_runner_build_assigns_amt():
    cfg = RunnerConfig(symbols=["NF"], interval_sec=60, mode="paper", equity=100000.0)
    r = Runner.build(cfg)
    eng = r.coordinator.engines["NF"]
    assert eng.amt is not None


def test_runner_journal_logs_decisions(tmp_path):
    j = Journal(str(tmp_path / "journal.jsonl"))
    cfg = RunnerConfig(symbols=["NF"], interval_sec=60, mode="paper", equity=100000.0)
    r = Runner.build(cfg, journal=j)
    r.step({"security_id": r.security_ids["NF"], "ltp": 100.0, "volume": 1.0, "ts": 60.0})
    r.step({"security_id": r.security_ids["NF"], "ltp": 100.5, "volume": 1.0, "ts": 120.0})
    lines = j.lines()
    assert any('"kind": "decision"' in ln for ln in lines)
    assert any('"symbol": "NF"' in ln for ln in lines)


def test_runner_journal_logs_fills(tmp_path):
    from quantv2.oms import Position
    from quantv2.types import Bar
    j = Journal(str(tmp_path / "journal.jsonl"))
    cfg = RunnerConfig(symbols=["NF"], interval_sec=60, mode="paper", equity=100000.0)
    r = Runner.build(cfg, journal=j)
    eng = r.coordinator.engines["NF"]
    eng.position = Position(pid="p1", symbol="NF", side="LONG", qty=10.0, entry=100.0, sl=90.0, tp=102.0, setup="T", opened_at="2026-09-04T10:00:00+05:30")
    d = eng.on_bar(Bar(time="2026-09-04T10:31:00+05:30", open=101.0, high=103.0, low=100.5, close=102.5))
    assert d.reason == "EXITED_TAKE_PROFIT"
    lines = j.lines()
    assert any('"kind": "fill"' in ln and '"symbol": "NF"' in ln for ln in lines)