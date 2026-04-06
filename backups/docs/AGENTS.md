# AGENTS.md — GlassyTrade AI

## Project Overview

**GlassyTrade AI** — AMT Options Scalper System. Dual-engine trading platform with:
- **Theorist Engine** (AMT): Auction Market Theory analysis
- **Quant Engine** (AI): Self-learning prediction using fine-tuned LLMs

### Tech Stack
| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11+, FastAPI, Pydantic v2 |
| Frontend | React 19, TypeScript, Vite |
| AI/ML | MLX (Apple Silicon), LightGBM |
| DB | SQLite |
| Styling | Tailwind CSS v4 |
| Charts | lightweight-charts, Three.js |

---

## Commands

### Backend (Python/FastAPI)
```bash
cd backend

# Run all tests
python -m pytest

# Run unit tests only
python -m pytest tests/unit/
python -m pytest -m unit

# Run a single test file
python -m pytest tests/unit/test_gate_chain.py

# Run a specific test
python -m pytest tests/unit/test_gate_chain.py::TestGateChain::test_all_gates_pass

# Exclude slow tests
python -m pytest -m "not slow"

# Run integration tests
python -m pytest tests/integration/
```

### Frontend (React/Vite)
```bash
cd frontend

# Dev server (port 5190)
npm run dev

# Production build
npm run build

# Run all tests
npm test

# Run a single test file
npx vitest run tests/components/ChartScene.test.tsx

# Watch mode
npm run test:watch
```

### Full System
```bash
# Start backend (port 9090) + frontend (port 5190)
./start.sh
```

### Backend v2 (Next-gen)
```bash
cd backend_v2

# Lint
ruff check .

# Type check
mypy .

# Test with coverage
pytest --cov
```

---

## Code Style

### Python (Backend)

**Imports:**
```python
from __future__ import annotations
from typing import TYPE_CHECKING

# Standard library
import os
from decimal import Decimal

# Third-party
import pydantic

# Local (absolute paths, DDD layers)
from app.domain.ports.broker import BrokerPort
from app.domain.models.value_objects import OHLC
```

**Formatting:**
- 4-space indentation, 100-char line limit
- Double quotes for strings
- Google-style docstrings on all public functions/classes

**Types:**
- Type hints on ALL function signatures
- Use `T | None` (not `Optional[T]`)
- `Decimal` for all financial values (never `float`)
- `from __future__ import annotations` at top of every file

**Naming:**
- Classes: `PascalCase` (`AMTHandler`, `BrokerPort`)
- Functions/methods: `snake_case` (`fetch_history`, `execute_order`)
- Private members: `_leading_underscore`
- Constants: `UPPER_SNAKE_CASE` (`_LOOKBACK`, `_RATE_LIMIT`)
- Files/modules: `snake_case` (`amt_handler.py`)

**Error Handling:**
```python
# Pattern 1: Non-critical (decorator)
@handle_errors(error_types=(Exception,), default_return=None)
def non_critical(): ...

# Pattern 2: Critical (context manager)
with ErrorContext("operation", reraise=True):
    ...

# Pattern 3: Optional (safe execute)
result = safe_execute(func, *args, default_return=fallback)
```
- Use custom exceptions: `TradingError`, `SignalError`, `GateError`, `LLMError`, `StorageError`, `RiskError`
- Never silently swallow exceptions — always log with `exc_info=True`
- Structured logging: `logger.error("msg: %s", e, exc_info=True)`

**File Size Limits:**
| Type | Max Lines |
|------|-----------|
| Handler | 300 |
| Service | 250 |
| Utility | 200 |
| Model | 150 |
| Test | 300 |

### TypeScript (Frontend)

**Imports:**
```typescript
import { useState, useEffect } from 'react'
import { ChartConfig, ChartMode } from './types'
import { useServerTradingSystem } from '@/hooks/useServerTradingSystem'
```

**Formatting:**
- 4-space indentation
- No ESLint/Prettier config — follow existing code style
- Double quotes for strings

**Types:**
- **NO `any` types allowed** — use strict typing everywhere
- Interfaces for all data structures (`OHLCData`, `InstrumentState`)
- Discriminated unions: `'LONG' | 'SHORT' | 'FLAT'`
- Path alias: `@/*` maps to `./`

**Naming:**
- Components: `PascalCase` (`ChartScene`, `MarketSidebar`)
- Hooks: `camelCase` with `use` prefix (`useServerTradingSystem`)
- Variables/functions: `camelCase`
- Types/interfaces: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`

**Styling:**
- Tailwind utility classes exclusively
- No custom CSS except Three.js shaders or global resets
- Lucide React for icons only

---

## Architecture

### Backend (DDD Structure)
```
backend/app/
  domain/        # Ports, models, services (business logic)
  application/   # Use cases, handlers
  infrastructure/# Adapters (Dhan, SQLite, WebSocket)
  api/           # REST/WebSocket routers
```

**Principles:**
1. **DIP**: Depend on abstractions (Ports), not concretions (Adapters)
2. **Event-Driven**: Use `InMemoryEventBus` to decouple layers
3. **Immutability**: Frozen dataclasses/Pydantic models for value objects
4. **Pydantic mandatory**: All data-carrying objects inherit `pydantic.BaseModel`
5. **Async def**: For all handlers involving network I/O

### Testing

**Backend (pytest):**
- Arrange-Act-Assert pattern
- Test naming: `test_<function>_<scenario>`
- Test classes: `Test<ClassName>`
- Markers: `unit`, `integration`, `slow`
- Fixtures in `tests/conftest.py`

**Frontend (Vitest + Testing Library):**
- Global mocks in `tests/setup.ts` (fetch, WebSocket, matchMedia, ResizeObserver)
- Test files: `tests/**/*.test.{ts,tsx}`

---

## Key Rules (from AI_RULES.md)

- **Pydantic**: MANDATORY for all data-carrying objects
- **FastAPI**: Use `async def` for handlers with network I/O
- **MLX**: Primary LLM inference (Apple Silicon native)
- **LightGBM**: For probability gates — no deep learning in live paths
- **TypeScript**: No `any` types
- **lightweight-charts**: Exclusive 2D charting library
- **Tailwind CSS**: Utility classes only for styling
- **SQLite**: Trade history, positions, risk state
