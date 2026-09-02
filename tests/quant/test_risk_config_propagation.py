"""Regression coverage for runtime risk configuration propagation."""

from quant.runtime import QuantEngine


class _Gateway:
    def __iter__(self):
        return iter(())


def test_quant_engine_passes_all_session_limits_to_risk():
    engine = QuantEngine(
        _Gateway(),
        "TEST",
        max_trades_per_session=11,
        risk_per_trade_pct=0.002,
        max_daily_loss_pct=0.01,
        max_consecutive_losses=2,
    )

    assert engine._risk._base_risk_pct == 0.002
    assert engine._risk._max_daily_loss_pct == 0.01
    assert engine._risk._max_consecutive_losses == 2
    assert engine._risk._max_trades_per_session == 11
