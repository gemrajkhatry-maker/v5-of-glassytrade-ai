# ADR-0003: Eliminate ServiceGraph Service Locator

Date: 2026-05-01
Status: PROPOSED

## Context

`ServiceGraph` (`backend/app/application/service_graph.py`) is a **service locator** — an anti-pattern where dependencies are hidden behind a runtime lookup rather than explicit in constructor signatures.

### Problems with ServiceGraph

1. **Hidden dependencies**: `TradingSessionService.__init__(self, service_graph: ServiceGraph)` doesn't reveal what dependencies it needs. A reader must inspect the body to find `self._broker = service_graph.broker`.

2. **Harder to test**: Tests must mock the entire ServiceGraph or create a real one, rather than passing mock dependencies directly to constructors.

3. **Wide, shallow interface**: ServiceGraph has 16 methods/properties, most of which are one-line pass-throughs to the DI container. This is exactly the "shallow module" pattern called out in the improve-codebase-architecture skill.

4. **Violates explicit dependency principle**: FastAPI's `Depends()` pattern is designed for explicit dependency injection, but ServiceGraph bypasses it.

### Current Usage

```
main.py → creates ServiceGraph → stores in app.state.service_graph
    ↓
dependencies.py → wraps ServiceGraph with FastAPI Depends()
    ↓
routers/*.py → access via request.app.state.service_graph
```

## Decision

We will **eliminate ServiceGraph** and replace it with **constructor-based dependency injection**.

### Target Architecture

```
main.py → creates dependencies → passes to constructors
    ↓
TradingSessionService.__init__(broker, storage, gen_ai_service, ...)
    ↓
dependencies.py → uses FastAPI Depends() with module-level singletons
    ↓
routers/*.py → Depends(get_trading_session), Depends(get_broker), etc.
```

## Consequences

### Positive

1. **Explicit dependencies**: Constructor signatures reveal what each service needs.
2. **Easier testing**: Tests can pass mock dependencies directly.
3. **No service locator**: Eliminates the anti-pattern.
4. **Thinner modules**: ServiceGraph (~90 lines) is deleted.

### Negative

1. **Large refactor**: Touches `main.py`, `engine.py`, `dependencies.py`, and all routers.
2. **Module-level singletons**: FastAPI needs module-level singletons for `Depends()` to work.

### Neutral

1. **Learning curve**: Developers must understand FastAPI's dependency injection.

## Implementation Plan

### Phase 1: Create explicit constructors

Update `TradingSessionService` and other services to accept explicit dependencies:

```python
class TradingSessionService:
    def __init__(
        self,
        broker: IBroker,
        gen_ai_service: GenerativeAIService,
        storage: IStorage | None = None,
        probability_engine: IProbabilityInference | None = None,
        # ... etc.
    ) -> None:
        self._broker = broker
        # ... etc.
```

### Phase 2: Create module-level singletons

In `dependencies.py`:

```python
from fastapi import Depends

# Module-level singletons (created at startup)
_trading_session: TradingSessionService | None = None
_broker: IBroker | None = None
# ... etc.

def init_singletons(config: Configuration) -> None:
    """Call this from main.py at startup."""
    global _trading_session, _broker, ...
    container = compose_container(config)
    _broker = container.resolve(IBroker)
    # ... etc.

# FastAPI dependencies
def get_trading_session() -> TradingSessionService:
    return _trading_session

TradingSessionDep = Annotated[TradingSessionService, Depends(get_trading_session)]
```

### Phase 3: Update routers

Change from:
```python
def my_endpoint(request: Request):
    graph = request.app.state.service_graph
    session = graph.trading_session
```

To:
```python
def my_endpoint(session: TradingSessionDep):
    # use session directly
```

### Phase 4: Delete ServiceGraph

Once all callers are updated, delete `service_graph.py`.

## References

- Improve Codebase Architecture skill (Candidate 2: ServiceGraph)
- Martin Fowler: "Service Locator is an Anti-Pattern"
- FastAPI Dependency Injection documentation
