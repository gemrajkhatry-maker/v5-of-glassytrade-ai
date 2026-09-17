"""Tests for the 15-minute bias interval constant."""

from quant.bars import BIAS_INTERVAL_SEC


def test_bias_interval_constant_exists():
    assert BIAS_INTERVAL_SEC == 900


def test_bias_interval_is_15_minutes():
    assert BIAS_INTERVAL_SEC == 15 * 60
