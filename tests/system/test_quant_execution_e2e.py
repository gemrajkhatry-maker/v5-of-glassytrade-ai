"""System E2E: quant decision drives execution in the current architecture.

The QuantEngine folds each closed bar through AuctionCoordinator (Triple-A),
runs the decision gates, and on an approved signal opens a position through
its PaperOMS with the SL/TP from the quant Signal. This proves the
strategy -> signal -> risk -> paper OMS chain end-to-end on the deterministic
AGGRESSION-LONG session, and that a no-setup session never trades.
"""

import pathlib
import sys

_BACKEND = pathlib.Path(__file__).resolve().parents[2] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from quant.brokers.gateway import Tick  # noqa: E402
from quant.events import DecisionProduced, PositionOpened, SignalApproved  # noqa: E402
from quant.runtime import QuantEngine  # noqa: E402
from tests.helpers.synthetic import SyntheticGateway  # noqa: E402

SYMBOL = "SYM"


def _session_ticks():
    """Deterministic AGGRESSION-LONG session from paper protocol."""
    from tests.system.test_paper_protocol import _session_ticks as _ticks_fn
    return _ticks_fn()


def test_aggression_long_session_drives_paper_fill():
    from quant.execution.risk import SessionRisk
    SessionRisk(storage=None, symbol=SYMBOL).reset_session()
    eng = QuantEngine(
        SyntheticGateway(_session_ticks()), SYMBOL, interval_seconds=2
    )
    trace = eng.run()

    # The AGGRESSION-LONG breakout must produce an approved LONG signal...
    approved = [e for e in trace if isinstance(e, SignalApproved)]
    assert approved, "AGGRESSION-LONG session must produce an approved signal"
    signal_evt = approved[-1]
    assert signal_evt.signal.type == "LONG"

    # ...and the paper OMS must fill it with SL/TP taken from the quant Signal.
    opened = next(e for e in trace if isinstance(e, PositionOpened))
    sig = opened.position.order.signal
    assert opened.position.open_price == sig.entry
    assert sig.sl < sig.entry
    assert sig.tp > sig.entry

    # The decision that drove the fill is the deterministic Triple-A one.
    decisions = [e for e in trace if isinstance(e, DecisionProduced) and e.decision.approved]
    assert decisions
    last = decisions[0].decision
    assert last.approved is True
    assert last.reason == "Triple-A"
    assert last.signal is not None and last.signal.type == "LONG"


def test_no_setup_session_never_executes():
    """A flat, quiet session (no absorption, no breakout) must never produce
    an approved signal or touch the OMS."""
    ticks = [Tick(f"t{i}", 100.0, 10, 6, 4) for i in range(120)]
    eng = QuantEngine(SyntheticGateway(ticks), SYMBOL, interval_seconds=1)
    trace = eng.run()

    assert not any(isinstance(e, SignalApproved) for e in trace)
    assert not any(isinstance(e, PositionOpened) for e in trace)
