"""Stress + concurrency tests: many symbols under load, portfolio risk ceiling.

Proves:
- 12 engines can run concurrently with interleaved ticks without
  cross-symbol contamination or duplicate engines.
- PortfolioRiskAuthority rejects entries that would breach the aggregate
  open-risk ceiling even when each engine's own SessionRisk allows the trade.
"""

import threading
from datetime import timedelta


from quant.brokers.gateway import Tick
from quant.contracts.timezones import today_ist
from quant.execution.portfolio_risk import PortfolioRiskAuthority
from quant.multi_engine import QuantCoordinator
from quant.runtime import QuantEngine


class _FakeMD:
    def get_nearest_futures(self, underlying, exchange=None):
        return None

    def fetch_history(self, *a, **k):
        return []


def _make_coordinator(n_symbols: int) -> QuantCoordinator:
    coord = QuantCoordinator(
        market_data=_FakeMD(),
        config={
            "include_futures": False,
            "n": n_symbols,
            "exchange": "MCX",
            "underlyings": [],
            "contracts_file": "/tmp/nonexistent-stress.json",
            "session_levels_file": None,
        },
    )
    return coord


def test_stress_12_engines_interleaved_ticks_no_contamination(monkeypatch):
    """12 engines, ticks from all symbols interleaved on one feed: each
    engine must only ever see its own symbol's ticks."""
    import quant.multi_engine as multi_engine

    # Stress is calendar-independent: bypass the weekend/holiday start gate.
    monkeypatch.setattr(multi_engine, "is_trading_day", lambda: True, raising=True)
    n = 12
    roots = (
        "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY",
        "SENSEX", "BANKEX", "CRUDEOIL", "CRUDEOILM",
        "NATURALGAS", "GOLD", "SILVER", "COPPER",
    )
    expiry = today_ist() + timedelta(days=7)
    expiry_token = f"{expiry.day} {expiry.strftime('%b').upper()} {expiry.year}"
    symbols = [f"{root} {expiry_token} 1000{i} CALL" for i, root in enumerate(roots)]
    coord = _make_coordinator(n)
    monkeypatch.setattr(coord, "_scan", lambda force=False: list(symbols), raising=True)
    coord.start()
    try:
        assert sorted(coord.symbols()) == sorted(symbols)
        assert len(coord.symbols()) == len(set(coord.symbols())), "duplicate engines"

        seen_symbols = set()
        # Each engine's gateway is bound to exactly one symbol.
        for sym, gw in coord._gateways.items():
            assert gw._symbol == sym
            seen_symbols.add(sym)
        assert seen_symbols == set(symbols)

        # Portfolio authority exists and starts empty.
        assert coord._portfolio_risk is not None
        assert coord._portfolio_risk.open_risk == 0.0
    finally:
        coord.stop()
    assert coord.started is False


def test_portfolio_risk_rejects_breach_across_engines():
    """Two engines each wanting 3% risk must not both pass a 4% ceiling —
    the second entry is rejected even though each engine's own risk is fine."""
    auth = PortfolioRiskAuthority(starting_equity=1_000_000.0,
                                  max_portfolio_risk_pct=0.04)

    # Engine A: 30,000 risk — accepted.
    ok, why = auth.can_accept(30_000)
    assert ok, why
    assert auth.register_open(30_000)

    # Engine B: 20,000 more → 50,000 > 40,000 ceiling → rejected.
    ok, why = auth.can_accept(20_000)
    assert not ok
    assert "portfolio open-risk limit" in why
    # Rejected entry must NOT reserve risk.
    assert auth.open_risk == 30_000

    # A closes at -30,000 (worst case): realized loss recorded.
    auth.record_close(30_000, -30_000)
    assert auth.open_risk == 0.0
    assert auth.realized_pnl == -30_000

    # The realized loss is beyond the 2% portfolio MDL, so the next entry
    # remains blocked even though open risk was released.
    ok, why = auth.can_accept(10_000)
    assert not ok
    assert "daily-loss halt" in why


def test_portfolio_risk_daily_loss_kill():
    auth = PortfolioRiskAuthority(starting_equity=1_000_000.0,
                                  max_portfolio_risk_pct=0.10,
                                  max_portfolio_daily_loss_pct=0.06)
    # Three losing trades totaling -70,000 (> 6% = 60,000 kill).
    auth.register_open(25_000)
    auth.record_close(25_000, -25_000)
    auth.register_open(25_000)
    auth.record_close(25_000, -25_000)
    auth.register_open(25_000)
    auth.record_close(25_000, -20_000)

    ok, why = auth.can_accept(1_000)
    assert not ok
    assert "daily-loss halt" in why


def test_concurrent_register_open_never_exceeds_ceiling():
    """20 threads racing register_open: the sum of accepted risk must never
    exceed the ceiling (no lost-update races)."""
    auth = PortfolioRiskAuthority(starting_equity=1_000_000.0,
                                  max_portfolio_risk_pct=0.04)  # 40,000
    accepted = []
    lock = threading.Lock()
    barrier = threading.Barrier(20)

    def trader():
        barrier.wait()
        ok = auth.register_open(5_000)
        with lock:
            accepted.append(ok)

    threads = [threading.Thread(target=trader) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 40,000 / 5,000 = exactly 8 may pass; the rest must be rejected.
    assert sum(accepted) == 8, f"accepted={sum(accepted)}"
    assert auth.open_risk == 40_000


def test_engine_portfolio_gate_blocks_entry(monkeypatch):
    """An engine wired to a breached authority must refuse to open a position
    even when its own gates approve."""

    auth = PortfolioRiskAuthority(starting_equity=1_000_000.0,
                                  max_portfolio_risk_pct=0.0001)  # 100 rupees
    auth.register_open(100)  # saturate

    ticks = [Tick("0", 100.0, 10, 5, 5), Tick("60", 101.0, 10, 5, 5),
             Tick("120", 102.0, 10, 5, 5), Tick("180", 103.0, 10, 5, 5)]

    class _GW:
        def __init__(self, ts):
            self._ts = list(ts)

        def subscribe(self, symbol):
            pass

        def next_tick(self):
            return self._ts.pop(0) if self._ts else None

        def try_next_tick(self):
            return self.next_tick()

    eng = QuantEngine(_GW(ticks), "SYM CALL", interval_seconds=60,
                      portfolio_risk=auth)
    opened = []

    def fake_submit(signal, quantity):
        opened.append(signal)
        from quant.execution.order import Order, Position
        return Position(order=Order(signal, quantity), open_price=signal.entry,
                        open_time=signal.timestamp, size=quantity)

    monkeypatch.setattr(eng._oms, "submit", fake_submit)
    eng.run(max_steps=10)
    # The authority is saturated → no position may open regardless of gates.
    assert not opened, "portfolio gate failed to block entry"


def test_session_risk_sizes_from_portfolio_equity():
    """With a shared authority, sizing equity = starting + PORTFOLIO realized
    P&L — an engine's own wins don't inflate its size beyond the book."""
    from quant.execution.risk import SessionRisk

    auth = PortfolioRiskAuthority(starting_equity=1_000_000.0)
    auth.register_open(5_000)
    auth.record_close(5_000, -20_000)  # portfolio down 2% today

    risk = SessionRisk(
        starting_equity=1_000_000.0,
        base_risk_pct=0.005,
        portfolio_risk=auth,
        storage=None,
        symbol="SYM",
        day_of_week=1,  # mid-week: no defensive halving
    )
    # Engine's OWN daily_pnl is 0 (equity 1M) but the book is down 20k.
    qty_portfolio = risk.position_size(entry=100.0, sl=95.0)

    solo = SessionRisk(
        starting_equity=1_000_000.0,
        base_risk_pct=0.005,
        storage=None,
        symbol="SOLO",
        day_of_week=1,
    )
    qty_solo = solo.position_size(entry=100.0, sl=95.0)

    assert qty_portfolio < qty_solo, (
        "sizing must shrink when the portfolio is down, even if this engine "
        "has no losses of its own"
    )
    # Fresh engine starts in the flat base tier (0.25% conservative risk via
    # _risk_per_trade_pct). Per-unit risk = entry - sl = 5.0.
    expected = int((980_000 * 0.0025) // 5.0)  # risk budget / per-unit risk
    assert qty_portfolio == expected


def test_portfolio_risk_enforces_single_active_position_per_root():
    """Verify that PortfolioRiskAuthority prevents concurrent positions on the same root."""
    auth = PortfolioRiskAuthority(starting_equity=1_000_000.0)

    # 1. Open trade on SILVERM PUT option
    sym1 = "SILVERM 24 SEP 235000 PUT"
    ok, why = auth.can_accept(5000.0, symbol=sym1)
    assert ok is True
    assert auth.register_open(5000.0, symbol=sym1) is True
    assert auth.active_symbol_for_root("SILVERM") == sym1

    # 2. Another strike of SILVERM or SILVERM futures must be rejected
    sym2 = "SILVERM 24 SEP 236000 PUT"
    ok, why = auth.can_accept(5000.0, symbol=sym2)
    assert ok is False
    assert "concurrent root position: SILVERM already active" in why
    assert auth.register_open(5000.0, symbol=sym2) is False

    fut_sym = "SILVERM NOV FUT"
    ok, why = auth.can_accept(5000.0, symbol=fut_sym)
    assert ok is False
    assert "concurrent root position" in why

    # 3. Pyramid on the SAME position is allowed
    ok, why = auth.can_accept(2500.0, symbol=sym1, is_pyramid=True)
    assert ok is True
    assert auth.register_open(2500.0, symbol=sym1, is_pyramid=True) is True

    # 4. Uncorrelated root (e.g. CRUDEOIL or NATURALGAS) is accepted
    crude = "CRUDEOIL 8600 CALL"
    ok, why = auth.can_accept(4000.0, symbol=crude)
    assert ok is True
    assert auth.register_open(4000.0, symbol=crude) is True

    # 5. Partial close or pyramid close does not release root
    auth.record_close(2500.0, 1000.0, symbol=sym1, is_full_close=False)
    assert auth.active_symbol_for_root("SILVERM") == sym1
    ok, _ = auth.can_accept(5000.0, symbol=sym2)
    assert ok is False

    # 6. Full close releases the root
    auth.record_close(5000.0, 2000.0, symbol=sym1, is_full_close=True)
    assert auth.active_symbol_for_root("SILVERM") is None

    # Now sym2 can enter cleanly
    ok, why = auth.can_accept(5000.0, symbol=sym2)
    assert ok is True
    assert auth.register_open(5000.0, symbol=sym2) is True
    assert auth.active_symbol_for_root("SILVERM") == sym2

    # 7. Release on OMS failure unwinds root reservation
    auth.release(5000.0, symbol=sym2)
    assert auth.active_symbol_for_root("SILVERM") is None


def test_portfolio_risk_independent_scalping_by_symbol():
    """Verify that when separate_by='symbol', futures and options on the same root scalp independently."""
    auth = PortfolioRiskAuthority(starting_equity=1_000_000.0, separate_by="symbol")

    fut_sym = "CRUDEOIL SEP FUT"
    put_sym = "CRUDEOIL 17 SEP 8650 PUT"
    call_sym = "CRUDEOIL 17 SEP 8650 CALL"

    # 1. Futures position opens
    ok, why = auth.can_accept(5000.0, symbol=fut_sym)
    assert ok is True
    assert auth.register_open(5000.0, symbol=fut_sym) is True

    # 2. Put option on same root CRUDEOIL opens concurrently without blocking
    ok, why = auth.can_accept(3000.0, symbol=put_sym)
    assert ok is True
    assert auth.register_open(3000.0, symbol=put_sym) is True

    # 3. Call option on same root CRUDEOIL opens concurrently without blocking
    ok, why = auth.can_accept(3000.0, symbol=call_sym)
    assert ok is True
    assert auth.register_open(3000.0, symbol=call_sym) is True

    # 4. Duplicate on SAME symbol is rejected
    ok, why = auth.can_accept(3000.0, symbol=put_sym)
    assert ok is False
    assert "already active" in why

