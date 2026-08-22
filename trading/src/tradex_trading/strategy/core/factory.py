"""Config-driven strategy instantiation (P1b).

Nautilus-style typed configuration: one strategy class reused across
instruments and parameter sets without code changes. A :class:`StrategySpec`
carries the class, a strategy id, the instrument, and a parameter dict that is
unpacked into the strategy's constructor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tradex_domain.instruments import Instrument


@dataclass(frozen=True, slots=True)
class StrategySpec:
    """Declarative description of a strategy instance to build.

    Parameters
    ----------
    strategy_class:
        The strategy class (constructor: ``(strategy_id, instrument, **params)``).
    strategy_id:
        Unique identifier for the built instance.
    instrument:
        Instrument the strategy trades.
    params:
        Constructor keyword arguments (e.g. ``fast``/``slow`` for a crossover).
    """

    strategy_class: type
    strategy_id: str
    instrument: Instrument
    params: dict[str, Any] = field(default_factory=dict)


def build_strategy(spec: StrategySpec) -> Any:
    """Instantiate the strategy described by *spec*."""
    return spec.strategy_class(
        spec.strategy_id, spec.instrument, **spec.params
    )


__all__ = ["StrategySpec", "build_strategy"]
