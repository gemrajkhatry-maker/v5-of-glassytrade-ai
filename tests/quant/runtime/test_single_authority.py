"""QuantEngine's entry strategy is the AMT playbook regardless of env."""
from unittest.mock import MagicMock
from quant.runtime import QuantEngine
from quant.strategies.amt_scalping import AmtScalpingStrategy


def _engine(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("TIMESFM_END_TO_END", raising=False)
    else:
        monkeypatch.setenv("TIMESFM_END_TO_END", value)
    return QuantEngine(gateway=MagicMock(), symbol="CRUDEOIL")


def test_default_strategy_is_amt(monkeypatch):
    assert isinstance(_engine(monkeypatch, None)._strategy, AmtScalpingStrategy)


def test_env_true_does_not_select_timesfm(monkeypatch):
    assert isinstance(_engine(monkeypatch, "true")._strategy, AmtScalpingStrategy)


def test_env_false_still_amt(monkeypatch):
    assert isinstance(_engine(monkeypatch, "false")._strategy, AmtScalpingStrategy)
