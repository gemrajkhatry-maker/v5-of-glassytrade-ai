# Backend Startup Runbook

Use this mapping when startup telemetry or logs indicate a startup failure.

## Crash/Failure Categories

| Category | Meaning | Primary checks | Operator action |
|---|---|---|---|
| `syntax` | Python parse/import error during preflight | `/backend/start_preflight.sh` output | Fix code at reported line, rerun preflight, then restart startup script |
| `config` | Config/env resolution failed | `/backend/start_preflight.sh` + `backend/main.py` logs | Validate `GLASSYTRADE_ENV`, `GLASSYTRADE_STRATEGY`, and strategy/env YAML files |
| `mlx` | MLX/LLM unavailable at boot | `startup_unresolved` or `DEGRADED_NO_LOCAL_MODEL` state in `health/ready` | Confirm `MLX_MODEL_PATH`, adapter path, `LLM_CLOUD_FALLBACK_ENABLED`, and fallback API key |
| `symbol_resolution` | Option symbol could not be resolved to an underlying/futures context | `GET /api/metrics/startup` `symbol_resolution.missing_symbols` | Validate `instruments.json` and active symbol format; compare broker symbol naming |
| `engine` | Trading engine did not start | `backend/backend.log`, `Trading engine failed to start` | Verify storage/market-data availability and rerun startup |
| `runtime` | Unexpected startup exception not covered above | stack trace in `backend/backend.log` | Check dependency resolution, startup telemetry, and config drift |

## Operator Steps

1. Run `backend/start_preflight.sh` before launching `backend/start.sh`.
2. Start with `backend/start.sh` or mode-specific launcher (`start_mcx.sh`, `start_nse.sh`).
3. Confirm `/api/health/ready` returns `{ "status": "ready" }`.
4. If ready is delayed, check `/api/metrics/startup` and `/api/metrics/summary` for phase durations and missing symbol list.
