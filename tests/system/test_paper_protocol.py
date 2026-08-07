# tests/system/test_paper_protocol.py
"""Paper-protocol smoke test (architecture §5.5) — no-trade-no-edge.

Boots a deterministic 240-bar QuantEngine session (SyntheticGateway, no
network) that contains a clean AGGRESSION-LONG setup, a VAL-bounce fade setup,
and long quiet stretches, then asserts the paper week-1 invariants over the
full event trace:

  A. no-trade-no-edge      every PositionOpened maps to an approved QuantDecision
                           (approved-without-position counted + logged, only
                           fail on unexplained skips)
  B. no fabricated data    every bar is a real bar from the feed: volumes are
                           exactly the feed's volumes, closes are feed prices,
                           no bar-count inflation, no zero-volume candles
  C. fill within spread    entry/exit fills are within ±1 tick of the signal bar
                           close (the engine's slippage model)
  D. idempotent exits      each position closes exactly once

plus the WS contract assertion that the approved setup bar still carries the
``auction`` and ``quantDecision`` keys.
"""

import logging
from collections import Counter

from quant.bars import Bar as _Bar
from quant.brokers.gateway import Tick
from quant.brokers.synthetic import SyntheticGateway
from quant.events import (
    AuctionUpdated,
    BarClosed,
    DecisionProduced,
    PositionClosed,
    PositionOpened,
)
from quant.runtime import QuantEngine
from quant.state import StateProjector
from quant.ws_adapter import view_state_to_ws

logger = logging.getLogger(__name__)

SYMBOL = "SYM"
TICK_SIZE = 0.05
INTERVAL_SECONDS = 1

# The engine's BarAggregator (interval_seconds=1) pairs consecutive ticks into a
# bar whose time is the FIRST tick's epoch, so bar i of the session surfaces in
# the engine with time "t{2*i}". The approved bars in the fixture:
#   t166  = AGGRESSION-LONG (Triple-A, bar 83)
#   t340  = VAL-bounce fade (VA_FADE, bar 170)
AGGRESSION_BAR = "t166"
FADE_BAR = "t340"


def _bar(time, o, c, vol=20, buy_frac=0.6):
    """Zero-extra OHLCV bar; high/low derived from open/close, delta explicit."""
    bv = vol * buy_frac
    sv = vol - bv
    return _Bar(
        time=time, open=o, high=max(o, c), low=min(o, c), close=c,
        volume=vol, buy_volume=bv, sell_volume=sv, delta=bv - sv,
    )


def _session_bars():
    """Deterministic 240-bar paper session.

      bars 0-79    quiet stretch 1 @100 (0.1 range, vol 20)          -> WAITING
      bar  80      volume spike 5x, zero range @100, 90% buys        -> BUY absorption
      bars 81-82   quiet @100                                        -> ABSORBING -> ACCUMULATING
      bars 83-89   breakout 100.6..102.9 (above vwap.upper_1)        -> AGGRESSION -> LONG (bar 83)
                   rising closes take the position to TP (bar 87)    -> exit 102.1
      bars 90-169  quiet stretch 2 @105 (zero range, vol 200)        -> profile re-centres @105
      bar  170     VAL-bounce dip 104.92: BELOW_VA, close > VWAP,
                   buyer CVD, no Triple-A edge                        -> VA_FADE LONG (bar 170)
      bars 171-180 recovery 105.05..105.5 back toward POC            -> TP exit 105.05 (bar 171)
      bars 181-239 quiet tail @105 (vol 20)                          -> WAITING
    """
    out = []
    for i in range(80):
        out.append(_bar(f"t{i}", 99.95, 100.05, vol=20, buy_frac=0.6))
    out.append(_bar("t80", 100.0, 100.0, vol=100, buy_frac=0.9))
    out.append(_bar("t81", 100.0, 100.0, vol=20, buy_frac=0.6))
    out.append(_bar("t82", 100.0, 100.0, vol=20, buy_frac=0.6))
    for i, close in enumerate([100.6, 100.9, 101.3, 101.7, 102.1, 102.5, 102.9]):
        out.append(_bar(f"t{83 + i}", close - 0.1, close, vol=20, buy_frac=0.6))
    for i in range(80):
        out.append(_bar(f"t{90 + i}", 105.0, 105.0, vol=200, buy_frac=0.6))
    out.append(_bar("t170", 104.92, 104.92, vol=100, buy_frac=0.9))
    for i, close in enumerate([105.05, 105.1, 105.15, 105.2, 105.25, 105.3,
                               105.35, 105.4, 105.45, 105.5]):
        out.append(_bar(f"t{171 + i}", close - 0.05, close, vol=20, buy_frac=0.6))
    for i in range(59):
        out.append(_bar(f"t{181 + i}", 105.0, 105.0, vol=20, buy_frac=0.6))
    assert len(out) == 240
    return out


def _session_ticks():
    """Convert each session bar to two ticks (open, close) with matching time
    epochs so the interval aggregator reconstructs exactly those bars."""
    out = []
    for b in _session_bars():
        ep = int(b.time.lstrip("t"))
        out.append(Tick(f"t{2 * ep}", b.open, b.volume / 2, b.buy_volume / 2, b.sell_volume / 2))
        out.append(Tick(f"t{2 * ep + 1}", b.close, b.volume / 2, b.buy_volume / 2, b.sell_volume / 2))
    return out


def _run_trace():
    return QuantEngine(
        SyntheticGateway(_session_ticks()), SYMBOL,
        interval_seconds=INTERVAL_SECONDS, tick_size=TICK_SIZE,
    ).run()


def _index(trace):
    """Split the trace into per-kind indices keyed by bar time."""
    bars = {e.time: e.bar for e in trace if isinstance(e, BarClosed)}
    decisions = {e.time: e.decision for e in trace if isinstance(e, DecisionProduced)}
    opens = [e for e in trace if isinstance(e, PositionOpened)]
    closes = [e for e in trace if isinstance(e, PositionClosed)]
    auctions = {e.time: e.auction for e in trace if isinstance(e, AuctionUpdated)}
    return bars, decisions, opens, closes, auctions


# ---------------------------------------------------------------------------
# Invariant A — no-trade-no-edge
# ---------------------------------------------------------------------------

def test_no_trade_without_approved_decision():
    trace = _run_trace()
    bars, decisions, opens, closes, _ = _index(trace)
    assert opens, "expected the session to open positions"

    for evt in opens:
        t = evt.time
        decision = decisions.get(t)
        assert decision is not None, f"position opened at {t} with no QuantDecision"
        assert decision.approved, f"position opened at {t} from a rejected decision"
        assert decision.signal is not None
        # the open reason/trace must map to the approved decision's signal
        signal = evt.position.order.signal
        assert signal.type == decision.signal.type
        assert signal.reason in ("All 5 gates passed", "Value-Area fade")
        assert abs(signal.entry - decision.signal.entry) <= 1e-9
        assert signal.timestamp == t

    # Only the Triple-A trade opens. The VA-fade candidate (t340) is present in
    # the session but is correctly rejected by the MIN_STOP_DISTANCE_PCT guard:
    # entry 104.92 / sl 104.90 is a razor-thin ~0.02% stop (exactly the profile
    # WS-SMOKE flagged as unrealistic), so no VA-fade position may open.
    assert len(opens) == 1
    assert opens[0].time == AGGRESSION_BAR
    assert FADE_BAR not in {e.time for e in opens}
    assert all("Value-Area fade" not in (e.position.order.signal.reason or "")
               for e in opens)
    # the fade bar still produced a decision, but it was rejected
    fade_decision = decisions.get(FADE_BAR)
    assert fade_decision is not None
    assert not fade_decision.approved


def test_approved_decisions_without_position_explainable(caplog):
    """Count approved decisions that did not open a position; they must be
    explainable (cooldown / position already open / risk-halt), and are logged
    rather than failed when they are."""
    trace = _run_trace()
    _, decisions, opens, _, _ = _index(trace)
    open_times = {e.time for e in opens}

    with caplog.at_level(logging.INFO, logger=__name__):
        skips = []
        for t, d in decisions.items():
            if d.approved and d.signal is not None and t not in open_times:
                skips.append((t, d))
                logger.info(
                    "approved decision without position: bar=%s reason=%s phase=%s "
                    "gates=%s", t, d.reason, d.phase,
                    [(g.gate, g.passed, g.reason) for g in d.gate_results],
                )

    # In the current engine every approval opens a position (the cooldown/risk
    # gates live in DecisionContext and the engine drives them pre-open), so the
    # count is 0 — but the accounting must stay robust to future cooldown skips.
    for t, d in skips:
        gate2 = next((g for g in d.gate_results if g.gate == 2), None)
        explainable = (
            gate2 is not None and not gate2.passed
            and any(k in gate2.reason for k in ("Position already open", "cooldown", "Risk halted"))
        )
        assert explainable, f"unexplained approved decision without position at {t} ({d.reason})"
    assert len(skips) == 0


# ---------------------------------------------------------------------------
# Invariant B — no fabricated data
# ---------------------------------------------------------------------------

def test_no_fabricated_bars():
    ticks = _session_ticks()
    trace = _run_trace()
    bars, _, _, _, auctions = _index(trace)

    # no bar-count inflation: every pair of feed ticks produced exactly one bar
    assert len(bars) == len(ticks) // 2 == 240
    # bar volumes equal the feed's volumes, nothing invented
    assert sum(b.volume for b in bars.values()) == sum(t.volume for t in ticks)
    # no zero-volume candles for non-zero-volume inputs
    assert all(b.volume > 0 for b in bars.values())
    # every close is a real price from the feed
    feed_prices = {t.price for t in ticks}
    assert all(b.close in feed_prices for b in bars.values())
    # auction closes are real feed prices too
    assert all(a.close in feed_prices for a in auctions.values())


def test_projector_never_emits_zero_volume_or_fabricated_prices():
    ticks = _session_ticks()
    feed_prices = {t.price for t in ticks}
    trace = _run_trace()
    proj = StateProjector()
    seen_bars = 0
    for evt in trace:
        proj.on_event(evt)
        if isinstance(evt, BarClosed):
            seen_bars += 1
            snap = proj.snapshot(SYMBOL)
            assert snap.tick is not None and snap.tick["volume"] > 0
            assert snap.tick["close"] in feed_prices
    assert seen_bars == len(ticks) // 2
    # the final projected tick/auction reflect the real last bar of the feed
    snap = proj.snapshot(SYMBOL)
    assert snap.tick["close"] in feed_prices
    assert snap.auction["close"] in feed_prices


# ---------------------------------------------------------------------------
# Invariant C — fill within spread (±1 tick of the signal bar close)
# ---------------------------------------------------------------------------

def test_fills_within_one_tick_of_signal_bar_close():
    trace = _run_trace()
    bars, _, opens, closes, _ = _index(trace)

    for evt in opens:
        t = evt.time
        entry_dev = abs(evt.position.open_price - bars[t].close)
        assert entry_dev <= TICK_SIZE, (
            f"entry fill at {t} deviates {entry_dev} > tick {TICK_SIZE}"
        )

    for evt in closes:
        t = evt.time
        exit_dev = abs(evt.fill.close_price - bars[t].close)
        assert exit_dev <= TICK_SIZE, (
            f"exit fill at {t} deviates {exit_dev} > tick {TICK_SIZE}"
        )

    # spot-check the approved fill maps to its exact signal bar close; the
    # VA-fade (t340) is rejected by the min-stop guard, so it never fills
    assert len(opens) == 1
    assert opens[0].position.open_price == bars[AGGRESSION_BAR].close == 100.6
    assert closes[0].fill.close_price == bars[closes[0].time].close
    assert closes[0].fill.position.open_time == AGGRESSION_BAR


# ---------------------------------------------------------------------------
# Invariant D — idempotent exits
# ---------------------------------------------------------------------------

def test_each_position_closes_exactly_once():
    trace = _run_trace()
    _, _, opens, closes, _ = _index(trace)

    opened_ids = [e.position.open_time for e in opens]
    closed_ids = [e.fill.position.open_time for e in closes]

    assert len(closes) == len(opens) > 0
    assert len(opened_ids) == len(set(opened_ids)), "duplicate position ids"
    assert len(closed_ids) == len(set(closed_ids)), "a position closed more than once"
    assert set(closed_ids) == set(opened_ids), "closed ids must equal opened ids"
    assert Counter(closed_ids) == Counter({i: 1 for i in opened_ids})


# ---------------------------------------------------------------------------
# WS contract on the approved setup bars
# ---------------------------------------------------------------------------

def test_ws_contract_carries_auction_and_quant_decision_on_approved_bars():
    trace = _run_trace()
    proj = StateProjector()
    checks = 0
    for evt in trace:
        proj.on_event(evt)
        if not isinstance(evt, DecisionProduced) or not evt.decision.approved:
            continue
        ws = view_state_to_ws(proj.snapshot(SYMBOL))
        assert "auction" in ws and ws["auction"] is not None
        assert "quantDecision" in ws and ws["quantDecision"] is not None
        assert ws["quantDecision"]["approved"] is True
        assert ws["quantDecision"]["reason"] in ("Triple-A", "VA_FADE")
        assert ws["quantDecision"]["signal"]["type"] == evt.decision.signal.type
        checks += 1
        if evt.time == AGGRESSION_BAR:
            assert ws["quantDecision"]["phase"] == "AGGRESSION"
            assert ws["auction"]["tripleAPhase"] == "AGGRESSION"
            assert ws["auction"]["tripleASignal"] == "LONG"
            assert ws["quantDecision"]["reason"] == "Triple-A"
            assert ws["quantDecision"]["signal"]["entry"] == 100.6
    # only the Triple-A bar is approved; the VA-fade (t340) is rejected by the
    # min-stop guard and never surfaces as an approved WS decision
    assert checks == 1


def test_replay_is_deterministic():
    assert _run_trace() == _run_trace()
