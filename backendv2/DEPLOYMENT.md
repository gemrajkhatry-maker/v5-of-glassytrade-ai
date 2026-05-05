# BackendV2 Deployment Guide

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run tests
python -m pytest tests/ -v

# 3. Start API server
python app/api/main.py
```

## Architecture

```
backendv2/
├── app/
│   ├── domain/          # Pure business logic (no dependencies)
│   ├── application/     # Use cases, handlers, commands
│   ├── infrastructure/  # Adapters, database, messaging
│   └── api/            # FastAPI endpoints + SSE streaming
└── tests/              # 52 passing tests
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Root endpoint |
| GET | `/api/stream` | SSE streaming endpoint |
| POST | `/api/tick` | Process market tick |
| POST | `/api/analyze` | Analyze market data |
| GET | `/api/positions` | Get all positions |
| GET | `/health` | Health check |

## Key Features

✅ **Clean Architecture** - Domain independent of frameworks
✅ **Event-Driven** - Idempotency, audit trail
✅ **TDD** - 52 tests, 100% coverage on domain
✅ **Zero Parity** - Matches existing backend behavior
✅ **Financial Precision** - Decimal for all prices
✅ **SSE Streaming** - Real-time updates

## Configuration

Environment variables:
```bash
DATABASE_URL=backendv2.db
BINANCE_API_KEY=your_key
BINANCE_API_SECRET=your_secret
TESTNET=true
```

## Running Parallel Comparison

```bash
python scripts/parallel_test.py
```

## Production Notes

1. **Database**: SQLite for development, PostgreSQL for production
2. **Broker**: Binance adapter, extend for Dhan support
3. **Streaming**: SSE via sse-starlette
4. **Caching**: Add Redis for high-frequency data

## Next Steps

- [ ] Add Dhan broker adapter
- [ ] Implement PostgreSQL storage
- [ ] Add Redis cache layer
- [ ] Docker deployment
- [ ] Kubernetes manifests