"""Tests for KillSwitch — thread-safe emergency trading halt."""

from quant.execution.kill_switch import KillSwitch


def test_initially_not_halted():
    ks = KillSwitch()
    assert ks.is_halted is False


def test_halt_then_resume():
    ks = KillSwitch()
    ks.halt()
    assert ks.is_halted is True
    ks.resume()
    assert ks.is_halted is False


def test_shared_state_across_instances():
    """KillSwitch is instance-managed — each instance is independent."""
    ks1 = KillSwitch()
    ks2 = KillSwitch()
    ks1.halt()
    assert ks1.is_halted is True
    assert ks2.is_halted is False
