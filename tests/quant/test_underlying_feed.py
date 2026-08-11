"""Task 8 — underlying-futures AMT feed routing.

When an ``underlying_gateway`` is provided, its ticks drive the auction bars
(AMT), while the option contract's own ticks only update quotes/depth. Without
one, the engine falls back to running AMT on the option premium with a one-shot
startup warning.
"""

from quant.brokers.gateway import Tick
from quant.events import BarClosed, DepthUpdated
from quant.runtime import QuantEngine
from tests.helpers.synthetic import SyntheticGateway
import quant.runtime as rt


def test_derive_underlying_symbol_parses_option():
    eng = QuantEngine(SyntheticGateway([]), "CRUDEOIL 17 AUG 7450 CALL",
                      interval_seconds=1, market="MCX")
    assert eng._underlying() == "CRUDEOIL"


def _quiet_option_ticks(n=6):
    return [Tick(f"o{i}", 45.0, 10, 6, 4) for i in range(n)]


def _futures_ticks(n=6):
    return [Tick(f"f{i}", 7450.0 + i, 100, 60, 40) for i in range(n)]


def test_underlying_feed_drives_bars_option_only_quotes():
    """With an underlying gateway, BarClosed prices follow the futures stream;
    the option ticks still reach the projector/depth path."""
    from quant.state import StateProjector

    futures = SyntheticGateway(_futures_ticks())
    option = SyntheticGateway(_quiet_option_ticks())
    eng = QuantEngine(option, "CRUDEOIL 17 AUG 7450 CALL",
                      interval_seconds=1, market="MCX",
                      underlying_gateway=futures)
    trace = eng.run()

    bars = [e for e in trace if isinstance(e, BarClosed)]
    assert bars, "underlying ticks must close auction bars"
    # Futures ticks start at 7450; option ticks are 45.0 — bars must NOT
    # contain the option premium (that would be running AMT on the option).
    for e in bars:
        assert float(e.bar.close) > 7000.0, "bar close must come from futures feed"
    assert all("o" not in getattr(e.bar, "time", "") for e in bars)


def test_underlying_feed_option_quotes_still_fire():
    """Option ticks continue to update projector quotes/depth."""
    option = SyntheticGateway(
        [Tick("o0", 45.0, 10, 6, 4, depth={"bids": [{"price": 44.9, "quantity": 5}],
                                            "asks": [{"price": 45.1, "quantity": 5}]})]
    )
    futures = SyntheticGateway(_futures_ticks(2))
    eng = QuantEngine(option, "CRUDEOIL 17 AUG 7450 CALL",
                      interval_seconds=1, market="MCX",
                      underlying_gateway=futures)
    eng.run()
    assert eng._last_depth is not None, "option depth must still be captured"


def test_no_underlying_feed_warns_once_and_falls_back():
    """Option contract with no underlying gateway: one warning, AMT still runs
    on the option premium (fallback)."""
    rt._UNDERLYING_WARNED = False
    option = SyntheticGateway(_quiet_option_ticks())
    eng = QuantEngine(option, "NIFTY 11 AUG 24600 CALL",
                      interval_seconds=1, market="NSE")
    trace = eng.run()
    assert any(isinstance(e, BarClosed) for e in trace), "fallback must still produce bars"
    assert rt._UNDERLYING_WARNED is True, "startup warning must be emitted once"
