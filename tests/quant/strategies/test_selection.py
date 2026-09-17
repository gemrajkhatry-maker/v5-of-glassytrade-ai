"""The entry authority is always the deterministic Fabio AMT playbook."""
from quant.strategies.selection import build_strategy
from quant.strategies.amt_scalping import AmtScalpingStrategy


def test_build_strategy_returns_amt_scalping():
    assert isinstance(build_strategy(), AmtScalpingStrategy)


def test_env_cannot_change_entry_authority(monkeypatch):
    """TIMESFM_END_TO_END must not select a different entry authority."""
    monkeypatch.setenv("TIMESFM_END_TO_END", "true")
    assert isinstance(build_strategy(), AmtScalpingStrategy)
