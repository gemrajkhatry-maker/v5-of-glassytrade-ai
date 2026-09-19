"""The coordinator manages engine lifecycle and symbol rotation.

The QuantCoordinator does not currently carry a telemetry sink —
telemetry is handled at the engine level (see
tests/quant/runtime/test_engine_telemetry_injection.py).
"""

from __future__ import annotations

from quant.multi_engine import QuantCoordinator


class _MarketData:
    """Stand-in for the market-data port; the coordinator only holds it."""


def _coordinator(tmp_path, **kwargs) -> QuantCoordinator:
    return QuantCoordinator(
        _MarketData(),
        config={"contracts_file": str(tmp_path / "contracts.json")},
        **kwargs,
    )


def test_coordinator_constructs_without_telemetry(tmp_path):
    """QuantCoordinator has no telemetry parameter — engine-level only."""
    coord = _coordinator(tmp_path)
    assert not hasattr(coord, "_telemetry")


def test_coordinator_constructs_with_config(tmp_path):
    """QuantCoordinator stores the config dict."""
    coord = _coordinator(tmp_path)
    assert "contracts_file" in coord.config


def test_spawn_engine_method_exists():
    """_spawn_engine is a method on QuantCoordinator."""
    assert hasattr(QuantCoordinator, "_spawn_engine")
    assert callable(getattr(QuantCoordinator, "_spawn_engine"))


def test_coordinator_has_engine_storage(tmp_path):
    """Coordinator starts with empty engine storage."""
    coord = _coordinator(tmp_path)
    assert coord._engines == {}
