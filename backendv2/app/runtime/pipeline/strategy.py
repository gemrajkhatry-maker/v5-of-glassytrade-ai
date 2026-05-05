"""Strategy runtime multiplexer."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import copy
from typing import Any
import logging

from app.runtime.pipeline import StageMetrics

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StrategyEvent:
    """Runtime envelope emitted by strategy handlers.

    Carries the emitting strategy id while preserving the handler output event.
    """

    strategy_id: str
    payload: Any


@dataclass(frozen=True)
class _StrategyBinding:
    strategy_id: str
    priority: int
    handler: Callable[[Any], Any]
    ordinal: int


class StrategyRuntime:
    """Selects strategy pipeline behavior by symbol/session context.

    Current implementation keeps a single deterministic default strategy and
    delegates via a hook map for future expansion.
    """

    def __init__(self):
        self._strategies: dict[str, list[_StrategyBinding]] = {}
        self._register_counter = 0
        self._metrics = StageMetrics(stage_name="StrategyRuntime")

    @property
    def metrics(self) -> StageMetrics:
        return self._metrics

    def register(
        self,
        symbol: str,
        strategy_id: str,
        handler: Callable[[Any], Any],
        *,
        priority: int = 100,
        replace: bool = False,
    ) -> None:
        """Register a strategy handler for a symbol.

        - strategy_id: unique per symbol for deterministic traceability and telemetry.
        - priority: lower numbers execute first.
        - replace: replace existing strategy with same id.
        """
        if not isinstance(symbol, str) or not symbol:
            return
        if not strategy_id:
            return
        if not callable(handler):
            return

        if symbol not in self._strategies:
            self._strategies[symbol] = []

        if replace:
            self._strategies[symbol] = [
                binding
                for binding in self._strategies[symbol]
                if binding.strategy_id != strategy_id
            ]

        self._register_counter += 1
        self._strategies[symbol].append(
            _StrategyBinding(
                strategy_id=strategy_id,
                priority=int(priority),
                handler=handler,
                ordinal=self._register_counter,
            )
        )

    def unregister(self, symbol: str, strategy_id: str) -> None:
        if not symbol or not strategy_id:
            return
        strategies = self._strategies.get(symbol, [])
        self._strategies[symbol] = [
            binding
            for binding in strategies
            if binding.strategy_id != strategy_id
        ]
        if not self._strategies[symbol]:
            del self._strategies[symbol]

    def clear(self, symbol: str | None = None) -> None:
        if symbol is None:
            self._strategies = {}
            return
        self._strategies.pop(symbol, None)

    def process(self, item: Any) -> list[Any]:
        self._metrics.record(0)
        if not hasattr(item, "symbol"):
            return [item]

        handlers = self._strategies.get(item.symbol)
        if not handlers:
            return [item]

        results: list[Any] = []
        for binding in sorted(handlers, key=lambda b: (b.priority, b.ordinal)):
            try:
                raw_result = binding.handler(item)
                if raw_result is None:
                    continue
                if isinstance(raw_result, (tuple, list)):
                    values = raw_result
                else:
                    values = (raw_result,)
                for value in values:
                    try:
                        safe_value = copy.deepcopy(value)
                    except Exception:
                        safe_value = value
                    results.append(
                        StrategyEvent(
                            strategy_id=binding.strategy_id,
                            payload=safe_value,
                        )
                    )
            except Exception:
                logger.exception(
                    "Strategy '%s' failed for symbol=%s",
                    binding.strategy_id,
                    item.symbol,
                )
                continue
        return results if results else [item]

    def warmup(self) -> None:
        self._strategies = {}
        self._register_counter = 0
        self._metrics.reset()

    def teardown(self) -> None:
        self._metrics.reset()

    def reset(self) -> None:
        self.warmup()

    def snapshot(self) -> dict[str, object]:
        return {
            "registered_symbols": sorted(self._strategies.keys()),
            "bindings": {
                symbol: [
                    {
                        "strategy_id": binding.strategy_id,
                        "priority": binding.priority,
                        "ordinal": binding.ordinal,
                    }
                    for binding in sorted(
                        bindings,
                        key=lambda b: (b.priority, b.ordinal),
                    )
                ]
                for symbol, bindings in self._strategies.items()
            },
        }

    def restore(self, payload: dict[str, object]) -> None:
        # Registered strategy callables are process-level dependencies and must be
        # re-registered by orchestration layer after restore.
        self._strategies = {}
        self._register_counter = 0
