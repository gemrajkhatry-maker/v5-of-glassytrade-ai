"""T7: executor shutdown with coordinator."""

import pytest
from unittest.mock import MagicMock


def test_coordinator_stop_shuts_down_engines_and_feed():
    """After coordinator.stop(), engines are stopped and the feed is closed.
    The LLM executor no longer exists on engines — the LLM layer was removed."""
    from quant.multi_engine import QuantCoordinator

    engines = [MagicMock(spec=[]), MagicMock(spec=[])]
    for eng in engines:
        assert not hasattr(eng, "_llm_executor")

    coord = QuantCoordinator.__new__(QuantCoordinator)
    coord._engines = {f"s{i}": e for i, e in enumerate(engines)}
    coord._stop = MagicMock()
    coord._stop.set = MagicMock()
    coord._stop_engines = MagicMock()
    coord._feed = MagicMock(close=MagicMock())
    import threading as _th
    coord._lifecycle_lock = _th.RLock()
    coord.started = True

    coord.stop()

    coord._stop_engines.assert_called_once()
    assert coord.started is False
    coord._feed.close.assert_called_once()
