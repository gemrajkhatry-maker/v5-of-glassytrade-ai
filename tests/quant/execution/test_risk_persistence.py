import json
from quant.execution.risk import SessionRisk


class MemKV:
    """Test double mimicking the real Database.kv_set/kv_get contract:
    kv_set JSON-encodes dict/list values (see database.py:850-852) and
    kv_get returns the stored string."""
    def __init__(self): self.m = {}
    def kv_set(self, k, v):
        if isinstance(v, (dict, list, tuple)):
            v = json.dumps(v)
        self.m[k] = v
    def kv_get(self, k): return self.m.get(k)


def test_risk_persists_across_restarts():
    kv = MemKV()
    r1 = SessionRisk(storage=kv, symbol="NIFTY", date="2026-08-10")
    r1.record_trade(-1000.0)
    r1.record_trade(-2000.0)  # -3000 total, default max_daily_loss is 3% of 1M = 30000, so not halted yet

    r2 = SessionRisk(storage=kv, symbol="NIFTY", date="2026-08-10")
    assert r2.state().daily_pnl == -3000.0
    assert r2.state().consecutive_losses == 2
    assert r2.state().halted is False


def test_halted_state_persists_and_refuses_new_trades():
    kv = MemKV()
    r1 = SessionRisk(storage=kv, symbol="NIFTY", date="2026-08-10",
                     max_daily_loss_pct=0.005, starting_equity=1_000_000.0)
    r1.record_trade(-6000.0)   # exceeds 0.5% of 1M = 5000 -> halted
    assert r1.state().halted is True

    r2 = SessionRisk(storage=kv, symbol="NIFTY", date="2026-08-10",
                     max_daily_loss_pct=0.005, starting_equity=1_000_000.0)
    assert r2.state().halted is True
    # Halted session refuses new trades
    assert r2.can_trade()[0] is False
    # But closing fills still update P&L accounting accurately
    r2.record_trade(-1000.0)
    assert r2.state().daily_pnl == -7000.0
    assert r2.can_trade()[0] is False


def test_new_session_date_resets_state():
    kv = MemKV()
    r1 = SessionRisk(storage=kv, symbol="NIFTY", date="2026-08-10")
    r1.record_trade(-1000.0)
    r2 = SessionRisk(storage=kv, symbol="NIFTY", date="2026-08-11")  # new day
    assert r2.state().daily_pnl == 0.0
    assert r2.state().halted is False


def test_no_storage_is_noop():
    r = SessionRisk()
    r.record_trade(-1000.0)  # must not raise
    assert r.state().daily_pnl == -1000.0


def test_corrupt_storage_falls_back_to_fresh_state():
    kv = MemKV()
    kv.m["daily_risk:NIFTY:2026-08-10"] = "{not-json"
    r = SessionRisk(storage=kv, symbol="NIFTY", date="2026-08-10")
    assert r.state().daily_pnl == 0.0
    assert r.state().halted is False


def test_sigterm_shutdown_halt_unhalts_on_restart_when_within_risk_limits():
    """SIGTERM shutdown (e.g. process restart) should unhalt on next startup if
    daily loss limit is not breached, even if trades were recorded today."""
    kv = MemKV()
    r1 = SessionRisk(storage=kv, symbol="NIFTY", date="2026-08-10",
                     max_daily_loss_pct=0.03, starting_equity=1_000_000.0)
    r1.record_trade(-500.0)  # 1 trade recorded, small loss well within 3% limit
    assert r1.state().trades_today == 1
    assert r1.state().halted is False

    # Simulate SIGTERM shutdown
    r1.halt("external/emergency: SIGTERM shutdown")
    assert r1.state().halted is True
    assert "SIGTERM shutdown" in r1.state().halt_reason

    # On restart, r2 loads state and should be unhalted to allow new session trades
    r2 = SessionRisk(storage=kv, symbol="NIFTY", date="2026-08-10",
                     max_daily_loss_pct=0.03, starting_equity=1_000_000.0)
    assert r2.state().trades_today == 1
    assert r2.state().daily_pnl == -500.0
    assert r2.state().halted is False
    assert r2.can_trade()[0] is True


def test_genuine_daily_loss_breach_remains_halted_across_restart():
    """If a real daily loss breach occurred, restart must NOT clear the halt."""
    kv = MemKV()
    r1 = SessionRisk(storage=kv, symbol="NIFTY", date="2026-08-10",
                     max_daily_loss_pct=0.01, starting_equity=1_000_000.0)
    r1.record_trade(-15000.0)  # -1.5% loss exceeds 1.0% limit
    assert r1.state().halted is True

    # On restart, r2 must remain halted for money safety
    r2 = SessionRisk(storage=kv, symbol="NIFTY", date="2026-08-10",
                     max_daily_loss_pct=0.01, starting_equity=1_000_000.0)
    assert r2.state().halted is True
    assert r2.can_trade()[0] is False
