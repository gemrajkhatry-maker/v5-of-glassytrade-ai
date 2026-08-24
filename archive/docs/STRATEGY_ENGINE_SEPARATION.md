# Engine / Strategy Separation

The trading engine and the trading *strategy* are two different concerns, and
they now live behind a single seam.

## What each side owns

| Side | Owns | Does not own |
|---|---|---|
| **Engine** (`quant/runtime.py` `QuantEngine`, backend `QuantBridge`) | tick → bar aggregation, auction projection (`AuctionCoordinator`), risk sizing, OMS, exit engine, session risk, event bus/journal, persistence | *when/where to enter* |
| **Strategy** (`quant/strategy.py` `Strategy`) | the decision policy: `evaluate(ctx) -> QuantDecision` (gates, signal construction, fallback) | loop, state, execution, persistence |

The engine asks the strategy one question per closed bar: *"given this
`DecisionContext`, what do I do?"* The strategy is **stateless** — same context,
same decision — so it can be rebuilt per bar or per session with no drift.

## The seam

```python
# quant/strategy.py
@runtime_checkable
class Strategy(Protocol):
    name: str
    def evaluate(self, ctx: DecisionContext) -> QuantDecision: ...

register_strategy(name, factory)   # name -> factory
get_strategy(name=None, **kwargs)  # resolve by name (default "amt")
```

`DecisionContext` carries everything a strategy may need: the immutable auction
snapshot, the bar, and session facts (position open, cooldown, risk halt, agent
direction, equity, risk-per-trade, tick size).

## How to add / replace a strategy

```python
from quant.decision.context import DecisionContext
from quant.decision.decision_service import QuantDecision
from quant.strategy import register_strategy


class MyStrategy:
    name = "mean_reversion"

    def evaluate(self, ctx: DecisionContext) -> QuantDecision:
        # ... your edge logic ...
        return QuantDecision(True, signal, "MEAN_REVERSION", ctx.state.triple_a_phase, ())
```

Then pick it in one of two ways:

- **Programmatic (engine):**
  `QuantEngine(gateway, "SYM", strategy=MyStrategy())`
- **Config-driven (live backend):** register it at startup, then
  `QUANT_STRATEGY=mean_reversion` (env) — read by `settings.QUANT_STRATEGY`,
  resolved by `QuantBridge` via `get_strategy(settings.QUANT_STRATEGY)`.

The default is `amt` (`quant/decision/decision_service.py` `DecisionService`,
the triple-A + value-area-fade policy), so nothing changes until you opt in.

## Non-goals (deliberate)

This seam separates *decision policy* from *engine mechanics* only. It does not
attempt to unify the two AMT kernels (`AMTAnalyzer` vs `AuctionCoordinator`) or
the two gate pipelines — that consolidation is tracked separately in
`PRINCIPAL_REVIEW.md` §5 and remains gated behind replay-parity proof.
