import queue
import time

import pytest

from quant.bars import Bar
from quant.brokers.gateway import Tick
from quant.coordinator import AuctionCoordinator, QuantCoordinator


def _session_bars():
    out = []
    for i in range(30):
        close = 100 + i * 0.5
        out.append(Bar(time=f"t{i}", open=close - 0.5, high=close + 1, low=close - 1,
                       close=close, volume=100 + (i % 5) * 50,
                       buy_volume=60, sell_volume=40, delta=20))
    return out


def _history_bars():
    """Two days of 5m bars; today (2026-08-07) spans a wide range."""
    out = []
    for day in ("2026-08-06", "2026-08-07"):
        for i in range(10):
            close = 100 + (i % 5) * 2 if day == "2026-08-07" else 90 + i
            out.append(Bar(time=f"{day}T09:{i:02d}:00+05:30",
                           open=close - 0.5, high=close + 1.5, low=close - 1.5,
                           close=close, volume=100 + (i % 4) * 40,
                           buy_volume=60, sell_volume=40, delta=20))
    return out


def test_seed_history_primes_builders_for_first_live_bar():
    c = AuctionCoordinator()
    c.seed_history(_history_bars())
    state = c.on_bar_close(Bar(time="2026-08-07T10:00:00+05:30", open=103, high=104,
                                low=102, close=103, volume=200,
                                buy_volume=120, sell_volume=80, delta=40))
    # First live bar already sees a meaningful profile, not zeros.
    assert state.volume_profile.poc > 0
    assert state.volume_profile.vah > state.volume_profile.val > 0
    assert state.vwap.value > 0
    assert state.location.ib_complete is True
    assert state.triple_a_phase == "WAITING"  # machine re-arms on fresh detection only


def test_on_bar_close_returns_complete_state():
    c = AuctionCoordinator()
    trace = [c.on_bar_close(b) for b in _session_bars()]
    last = trace[-1]
    assert len(trace) == 30
    assert last.time == "t29"
    assert last.close > 0
    assert last.volume_profile.poc > 0
    assert last.vwap.value > 0
    assert isinstance(last.order_flow.cvd, float)
    assert last.location.ib_high > 0
    assert last.location.ib_low > 0
    assert last.location.ib_complete is True
    assert last.triple_a_phase in {"WAITING", "ABSORBING", "ACCUMULATING", "AGGRESSION"}
    for s in trace:
        assert s.vwap.value > 0


def test_determinism_same_input_same_output():
    c1 = AuctionCoordinator()
    trace1 = [c1.on_bar_close(b) for b in _session_bars()]
    c2 = AuctionCoordinator()
    trace2 = [c2.on_bar_close(b) for b in _session_bars()]
    assert trace1 == trace2


def _long_sequence():
    out = [Bar(time=f"t{i}", open=100, high=101, low=99, close=100, volume=100)
           for i in range(25)]
    # absorption spike + two accumulation bars as zero-range bars AT the POC
    # bucket, so the profile peak is a single bucket and POC sits at 100
    out.append(Bar(time="t25", open=100, high=100, low=100, close=100,
                   volume=500, buy_volume=450, sell_volume=50))
    out.append(Bar(time="t26", open=100, high=100, low=100, close=100,
                   volume=100, buy_volume=60, sell_volume=40))
    out.append(Bar(time="t27", open=100, high=100, low=100, close=100,
                   volume=100, buy_volume=60, sell_volume=40))
    for i in range(28, 33):
        close = 100 + (i - 27) * 4
        out.append(Bar(time=f"t{i}", open=close - 0.5, high=close + 1, low=close - 1,
                       close=close, volume=100))
    return out


def test_triple_a_signal_flows_through():
    """A BUY absorption followed by a rising market reaches AGGRESSION -> LONG."""
    c = AuctionCoordinator()
    phases, signals = [], []
    for b in _long_sequence():
        st = c.on_bar_close(b)
        phases.append(st.triple_a_phase)
        signals.append(st.triple_a_signal)
    assert "AGGRESSION" in phases
    assert "LONG" in signals
    # and it resets after the signal bar (next bar back to WAITING)
    sig_idx = signals.index("LONG")
    assert phases[sig_idx + 1] == "WAITING"


# ---------------------------------------------------------------------------
# QuantCoordinator — multi-symbol orchestrator
# ---------------------------------------------------------------------------


class _FakeGateway:
    """BrokerGateway-compatible stub: a few ticks then None (mirror
    SyntheticGateway). Accepts the (feed, symbol) factory args."""

    def __init__(self, feed, symbol):
        self.feed = feed
        self.symbol = symbol
        self.closed = False
        self._ticks = [
            Tick("t0", 100.0, 10, 6, 4),
            Tick("t1", 100.5, 10, 6, 4),
            Tick("t2", 101.0, 10, 6, 4),
        ]
        self._index = 0

    def subscribe(self, symbol):
        self._index = 0

    def next_tick(self):
        if self._index >= len(self._ticks):
            return None
        tick = self._ticks[self._index]
        self._index += 1
        return tick

    def close(self):
        self.closed = True


class _FakeFeed:
    """MultiplexedMarketFeed stub — no threads, no network."""

    def __init__(self, market_data):
        self.market_data = market_data

    def set_symbols(self, symbols):
        pass

    def subscribe(self, symbol):
        pass

    def unsubscribe(self, symbol):
        pass

    def next_tick(self, symbol):
        return None

    def close(self):
        pass


_SYM_A = "NIFTY 11 AUG 24600 CALL"
_SYM_B = "BANKNIFTY 11 AUG 50000 PUT"


@pytest.fixture
def coordinator(monkeypatch):
    monkeypatch.setattr("quant.coordinator.LiveGateway", _FakeGateway)
    monkeypatch.setattr("quant.coordinator.MultiplexedMarketFeed", _FakeFeed)
    c = QuantCoordinator(market_data=object(), config={"interval_seconds": 1})
    monkeypatch.setattr(c, "_scan", lambda: [_SYM_A, _SYM_B])
    c.start()
    return c


def test_start_spawns_engines(coordinator):
    assert coordinator.symbols() == [_SYM_A, _SYM_B]


def test_snapshot_contract_keys(coordinator):
    snap = coordinator.snapshot(_SYM_A)
    assert snap["_symbol"] == _SYM_A
    for key in (
        "portfolio", "amt", "auction", "quantDecision", "genAIAnalysis",
        "overseerAction", "overseerReason", "agentDecision", "riskState",
        "tick", "ltp", "oi", "depth",
    ):
        assert key in snap
    # unknown symbol yields a minimal stub snapshot
    assert coordinator.snapshot("missing") == {"_symbol": "missing"}


def test_rescan_returns_new_symbols(coordinator, monkeypatch):
    new = ["FINNIFTY 11 AUG 20000 CALL"]
    monkeypatch.setattr(coordinator, "_scan", lambda: new)
    assert coordinator.rescan() == new
    assert coordinator.symbols() == new
    time.sleep(0.1)  # let respawned engine thread spin up


def test_switch_symbol(coordinator):
    new = "NIFTY 11 AUG 24700 CE"
    assert coordinator.switch_symbol(_SYM_A, new) is True
    assert new in coordinator.symbols()
    assert _SYM_A not in coordinator.symbols()
    assert _SYM_B in coordinator.symbols()
    assert coordinator.switch_symbol("no-such-symbol", new) is False


def test_llm_history(coordinator):
    coordinator._history[_SYM_A].append({"direction": "LONG", "confidence": "High"})
    assert coordinator.llm_history(_SYM_A) == [
        {"direction": "LONG", "confidence": "High"}
    ]
    assert coordinator.llm_history("missing") == []
    # llm_history returns a copy — mutating it must not leak into the buffer
    history = coordinator.llm_history(_SYM_A)
    history.append({"direction": "FLAT"})
    assert len(coordinator.llm_history(_SYM_A)) == 1


def test_decisions_queue(coordinator):
    q = coordinator.decisions()
    assert isinstance(q, queue.Queue)
    # each engine closed a bar -> DecisionProduced lands on the shared queue
    deadline = time.monotonic() + 2.0
    while q.empty() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not q.empty(), "expected an engine decision on the shared queue"
    # drain engine events, tolerating in-flight emits until the engine threads exit
    for _ in range(20):
        while not q.empty():
            event = q.get_nowait()
            assert event.__class__.__name__ in {"DecisionProduced", "SignalApproved"}
        if all(not t.is_alive() for t in coordinator._threads.values()):
            break
        time.sleep(0.05)
    assert q.empty()
    # ... and it remains a plain, usable queue
    q.put("dummy")
    assert q.get_nowait() == "dummy"
