"""Strategy — the pluggable decision policy behind the trading engine.

The engine (``quant.runtime.QuantEngine`` and the backend ``QuantBridge``)
owns the loop, bar aggregation, auction projection, risk, OMS, exits, and
persistence. The *strategy* owns exactly one question:

    "given this ``DecisionContext``, what ``QuantDecision`` do I make?"

A strategy is any object exposing ``evaluate(ctx) -> QuantDecision`` (plus a
human-readable ``name``). It must be stateless: the same context always yields
the same decision, so the engine can rebuild it per bar or per session without
observable state drift.

To swap the trading logic you replace the strategy, not the engine:

    from quant.runtime import QuantEngine
    from my_strategies import MeanReversionStrategy

    engine = QuantEngine(gateway, "SYM", strategy=MeanReversionStrategy())

or, in the live backend, set ``QUANT_STRATEGY=mean_reversion`` after calling
``register_strategy("mean_reversion", MeanReversionStrategy)`` at startup.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Protocol, runtime_checkable

from quant.decision.context import DecisionContext

if TYPE_CHECKING:  # pragma: no cover - type only
    from quant.decision.decision_service import QuantDecision


@runtime_checkable
class Strategy(Protocol):
    """Contract a decision policy must satisfy to plug into the engine."""

    name: str

    def evaluate(self, ctx: DecisionContext) -> "QuantDecision":
        """Produce the decision for one closed-bar context.

        ``ctx`` carries the immutable auction snapshot, the bar, and the session
        facts (position open, cooldown, risk halt, agent direction, sizing
        inputs). The returned ``QuantDecision`` decides entry or stand-down.
        """
        ...


# name -> zero-arg(-ish) factory. Factories are lazy so importing this module
# never force-loads the concrete strategy packages.
_STRATEGIES: dict[str, Callable[..., Strategy]] = {}

DEFAULT_STRATEGY = "amt"


def register_strategy(name: str, factory: Callable[..., Strategy]) -> None:
    """Register a strategy factory under a normalized name."""
    key = name.strip().lower()
    if not key:
        raise ValueError("strategy name must be non-empty")
    _STRATEGIES[key] = factory


def get_strategy(name: str | None = None, **kwargs) -> Strategy:
    """Resolve a strategy instance by name (default ``amt``).

    Extra kwargs are forwarded to the strategy factory (e.g. ``min_rr=``).
    Raises ``KeyError`` with the registered names on an unknown strategy.
    """
    key = (name or DEFAULT_STRATEGY).strip().lower()
    try:
        factory = _STRATEGIES[key]
    except KeyError:
        raise KeyError(
            f"Unknown quant strategy {key!r}; registered: {sorted(_STRATEGIES)}"
        ) from None
    return factory(**kwargs)


def _amt_factory(**kwargs) -> Strategy:
    from quant.decision.decision_service import DecisionService

    return DecisionService(**kwargs)


register_strategy("amt", _amt_factory)
