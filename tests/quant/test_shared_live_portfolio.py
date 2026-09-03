"""Live engines must share one capital book."""

import threading

from quant.execution.live_oms import LiveOMS
from quant.multi_engine import QuantCoordinator


class _MarketData:
    def get_nearest_futures(self, *args, **kwargs):
        return None

    def get_lot_size(self, symbol):
        return 1.0

    async def fetch_history(self, *args, **kwargs):
        return []


class _Broker:
    pass


def test_live_oms_instances_share_coordinator_portfolio(monkeypatch, tmp_path):
    monkeypatch.setattr("quant.amt_engine.AMTEngine.seed", lambda self: None)

    # Engines run on the coordinator's bounded pool; suppress the run task
    # so no pool worker blocks on a tick queue mid-assertion.
    monkeypatch.setattr(
        QuantCoordinator, "_start_engine_loop", lambda self, engine: None
    )

    coordinator = QuantCoordinator(
        _MarketData(),
        broker=_Broker(),
        config={
            "live_oms_enabled": True,
            "underlyings": ["NIFTY", "BANKNIFTY"],
            "n": 2,
            "contracts_file": str(tmp_path / "contracts.json"),
            "session_levels_file": str(tmp_path / "session_levels.json"),
            "include_futures": False,
        },
    )

    first = coordinator._spawn_engine("NIFTY AUG FUT")
    second = coordinator._spawn_engine("BANKNIFTY AUG FUT")

    assert isinstance(first._oms, LiveOMS)
    assert isinstance(second._oms, LiveOMS)
    assert first._oms._portfolio is coordinator._portfolio
    assert second._oms._portfolio is coordinator._portfolio
    assert first._oms._portfolio is second._oms._portfolio
