# Preview run doc — GlassyTrade AI (NSE mode)

Backend: FastAPI/uvicorn on **:9091**. Frontend: Vite dev server on **:5191** (proxies `/api` and WebSockets to the backend).

Mode is selected by `GLASSYTRADE_STRATEGY=mcx_options|nse_options` (the strategy YAMLs live in `backend/config/strategies/`). This thread currently runs **nse_options** (paper): NIFTY 18 AUG weekly CALL/PUT + BANKNIFTY/FINNIFTY monthly, per `backend/config/strategies/nse_options.yaml` (`underlying_priority`/`top_n: 4`). MCX mode (CRUDEOIL/NATURALGAS/GOLDM/SILVERM — live 09:00–23:30 IST) is the evening fallback when NSE is closed.

> **The LLM layer was removed (stable_5).** There is no MLX/GGUF model, no `/api/ai/*` or `/api/rl/*` endpoints, no `llm:` config, and no LLM env vars (`MLX_*`, `LLM_*` are ignored). The decision brain is 100% deterministic (QuantCoordinator + Fabio gates 1–4). The trade journal moved from `/api/ai/journal/*` to `/api/journal/*`.
>
> **Timeframe is 1 minute.** `candle_timeframe_minutes: 1` in `backend/config/base.yaml` flows to the coordinator's bar interval (60s), the WS `interval: 1m`, and Dhan history (`1m` → Dhan `1`). The engine's AMT history seed derives its interval from the aggregator (`_seed_interval_str`), so seeded candles always match live bars.

## Reproduce artifacts

- **`.env`** (repo root) must exist with `DHAN_ACCESS_TOKEN`, `DHAN_CLIENT_ID`, `DHAN_API_KEY`, `DHAN_API_SECRET`, `DHAN_TOTP_SECRET`, `DHAN_PIN`, `DHAN_SYMBOLS`. Copy it from the main checkout if missing (`cp /path/to/main/.env .`). Values are per-machine secrets — never commit. No `backend/.env` exists; the app loads the root `.env`.
- **Python venv**: `.venv/` at repo root (has `uvicorn`). Recreate with `python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt` if missing.
- **Frontend deps**: `frontend/node_modules` (has `vite`). Recreate with `cd frontend && npm install` if missing.

## Run the servers (NSE mode)

⚠️ **CRITICAL**: the terminal shell exports `PORT=62871` (Freebuff's own orchestrator port). If left set:
- Vite's proxy target resolves to `http://127.0.0.1:62871` (vite.config.ts reads `PORT` via `loadEnv` with prefix `''`, which merges process.env), so `/api/*` 404s with `{"error":"not found"}`.
- Backend `settings.PORT` (`os.getenv("PORT")`) reports the wrong port.

Always `unset PORT` (and `unset DEBUG`) before launching.

Backend (paper env, NSE strategy, project venv):

```bash
cd backend && unset PORT DEBUG
KMP_DUPLICATE_LIB_OK=TRUE GLASSYTRADE_ENV=paper GLASSYTRADE_STRATEGY=nse_options \
PYTHONFAULTHANDLER=1 PYTHONPATH=<repo-root>:<repo-root>/backend \
../.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 9091 --workers 1
```

Frontend (in a plain shell, NOT a tool shell):

```bash
cd frontend && unset PORT
TZ=Asia/Kolkata VITE_BACKEND_PORT=9091 node node_modules/.bin/vite --host 0.0.0.0 --port 5191
```

### Alternate ports when 9090/5190 are taken

The default ports may already be held by another worktree's servers. This worktree runs on **9091/5191**: pass `--port 9091` to uvicorn and `--port 5191` to vite, and point the vite proxy at this worktree's backend with `VITE_BACKEND_PORT=9091` (the config reads `VITE_BACKEND_PORT || PORT || '9090'`; `unset PORT` first so the orchestrator's `PORT` doesn't leak in).

Detached launch (tool shells kill background children on exit — plain `nohup ... &` does not survive, and `launchctl submit` fails with a TCC `Operation not permitted` on the venv under `~/Documents`):

```bash
python3 .freebuff/launch_detached.py bash -c 'unset PORT; cd backend; ... exec ../.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 9091 --workers 1' > .freebuff/preview-<thread>.log 2>&1
python3 .freebuff/launch_detached.py bash -c 'unset PORT; cd frontend; VITE_BACKEND_PORT=9091 exec node node_modules/.bin/vite --host 0.0.0.0 --port 5191' > frontend/frontend.log 2>&1
```

First line of each log is the server PID.

## Verify

- Backend: `curl http://127.0.0.1:9091/health/ready` → `{"status":"ready",...}` (takes ~15–30s; lifespan runs the option scanner and Dhan broker init). No `llm` key in `checks` — the LLM layer is gone.
- Proxy: `curl http://127.0.0.1:5191/api/system/config` → HTTP 200 with DHAN/NSE config and **no `llm*` keys**.
- Frontend: `curl http://127.0.0.1:5191/` → HTTP 200 (React app).
- Removed surface: `/api/ai/*`, `/api/rl/*`, `/api/analysis/predict` → HTTP 404. Journal lives at `/api/journal/*`.
