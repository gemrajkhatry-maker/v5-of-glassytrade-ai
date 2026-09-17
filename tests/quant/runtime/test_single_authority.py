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


def test_no_code_reads_timesfm_end_to_end():
    """The entry-authority switch is gone; no module may read the env var.

    Docstrings/comments may still name the retired mode; only an actual
    environment lookup would reintroduce an env-switched authority.
    """
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[3]
    offenders = []
    for path in root.glob("quant/**/*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if "TIMESFM_END_TO_END" in line and ("getenv" in line or "environ" in line):
                offenders.append(str(path.relative_to(root)))
                break
    assert offenders == [], f"TIMESFM_END_TO_END still read in {offenders}"
