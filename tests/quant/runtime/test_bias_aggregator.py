"""Tests for the 15-minute bias interval constant and bias aggregator gating."""

from quant.bars import BIAS_INTERVAL_SEC
from quant.runtime import QuantEngine
from tests.helpers.synthetic import SyntheticGateway


def test_bias_interval_constant_exists():
    assert BIAS_INTERVAL_SEC == 900


def test_bias_interval_is_15_minutes():
    assert BIAS_INTERVAL_SEC == 15 * 60


def test_bias_built_on_production_5m_macro():
    eng = QuantEngine(SyntheticGateway([]), "TEST", interval_seconds=300)
    assert eng._bias_aggregator is not None
    assert eng._bias_aggregator.interval_seconds == BIAS_INTERVAL_SEC == 900


def test_bias_built_only_when_macro_exists():
    eng60 = QuantEngine(SyntheticGateway([]), "TEST", interval_seconds=60)
    assert eng60._micro_aggregator is None
    assert eng60._bias_aggregator is None


def test_bias_underlying_built_when_gateway_and_macro():
    eng = QuantEngine(
        SyntheticGateway([]),
        "NIFTY 1 SEP 25000 CALL",
        interval_seconds=300,
        underlying_gateway=SyntheticGateway([]),
    )
    assert eng._bias_aggregator is not None
    assert eng._bias_underlying_aggregator is not None
    assert eng._bias_underlying_aggregator.interval_seconds == BIAS_INTERVAL_SEC


def test_bias_underlying_none_without_gateway():
    eng = QuantEngine(SyntheticGateway([]), "TEST", interval_seconds=300)
    assert eng._bias_aggregator is not None
    assert eng._bias_underlying_aggregator is None
