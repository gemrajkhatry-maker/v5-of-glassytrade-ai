# Preview run doc — GlassyTrade AI (MCX mode)

Backend: FastAPI/uvicorn on **:9090**. Frontend: Vite dev server on **:5190** (proxies `/api` and WebSockets to the backend).

Mode is selected by `GLASSYTRADE_STRATEGY=mcx_options|nse_options` (the strategy YAMLs live in `backend/config/strategies/`). This thread currently runs **nse_options** (paper): NIFTY 18 AUG weekly CALL/PUT + BANKNIFTY/FINNIFTY monthly, per `backend/config/strategies/nse_options.yaml` (`underlying_priority`/`top_n: 4`). MCX mode (CRUDEOIL/NATURALGAS/GOLDM/SILVERM — live 09:00–23:30 IST) is the evening fallback when NSE is closed.

## Reproduce artifacts

- **`.env`** (repo root) must exist with `DHAN_ACCESS_TOKEN`, `DHAN_CLIENT_ID`, `DHAN_API_KEY`, `DHAN_API_SECRET`, `DHAN_TOTP_SECRET`, `DHAN_PIN`, `DHAN_SYMBOLS`. Copy it from the main checkout if missing (`cp /path/to/main/.env .`). Values are per-machine secrets — never commit. No `backend/.env` exists; the app loads the root `.env`.
- **Python venv**: `.venv/` at repo root (has `uvicorn`). Recreate with `python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt` if missing.
- **Frontend deps**: `frontend/node_modules` (has `vite`). Recreate with `cd frontend && npm install` if missing.

## Run the servers (NSE mode)

⚠️ **CRITICAL**: the terminal shell exports `PORT=62871` (Freebuff's own orchestrator port). If left set:
- Vite's proxy target resolves to `http://127.0.0.1:62871` (vite.config.ts reads `PORT` via `loadEnv` with prefix `''`, which merges process.env), so `/api/*` 404s with `{"error":"not found"}`.
- Backend `settings.PORT` (`os.getenv("PORT")`) reports the wrong port.

Always `unset PORT` (and `unset DEBUG`) before launching.

Backend (paper env, MCX strategy, project venv):

```bash
cd backend && unset PORT DEBUG
KMP_DUPLICATE_LIB_OK=TRUE GLASSYTRADE_ENV=paper GLASSYTRADE_STRATEGY=mcx_options \
MLX_SET_NUM_THREADS=1 MLX_DEFER_LOADING=1 PYTHONFAULTHANDLER=1 \
PYTHONPATH=<repo-root>:<repo-root>/backend \
../.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 9090 --workers 1
```

Note: the backend log lives at `.freebuff/backend.log` (first line = PID).

### LLM model selection (default unchanged)

The local MLX model + LoRA adapter are chosen by two env vars in the root `.env`:

- `MLX_MODEL_PATH=models/vibethinker-3b` + `MLX_ADAPTER_PATH=models/vibethinker-amt-lora` — **default** (live-format LoRA, ~20–60s/call).
- Alternative (copied from the POC, commented out in `.env`): `MLX_MODEL_PATH=models/lfm2.5-2.6b-mlx-8bit` + `MLX_ADAPTER_PATH=models/lfm2.5-nifty-amt-lora`. LFM2.5 2.6B is ~10× faster (~2–3s/call) but was trained on flat key:value NSE scenarios — expect format-mismatch drift on live-format prompts; verify decisions before trusting it.
- To switch: uncomment the LFM lines and comment the vibethinker lines, then restart the backend. Both paths resolve repo-relative (cwd-independent).
- Model artifacts: `models/lfm2.5-2.6b-mlx-8bit/` (2.7G safetensors), `models/lfm2.5-nifty-amt-lora/` (adapter), `amt_dataset/nifty_amt_data/` (train/val/test jsonl). Re-copy the model with `cp -RL` (HF snapshot files are symlinks).

### LLM prompt shape (live == training)

Since the LFM readiness work, `QuantEngine._llm_instruction` returns the short system prompt (`_DEFAULT_INSTRUCTION` + the SHORT-capable entry JSON schema) and `_llm_input` returns the AMT narrative + bar footer in the USER message — matching `scripts/dataset_render.py` exactly. Datasets: `amt_dataset/nifty_amt_data_livefmt/` (NSE), `amt_dataset/mcx_amt_data_livefmt/` (MCX, from `backend/scripts/generate_mcx_data.py`), `amt_dataset/amt_data_livefmt/` (combined, for retraining).

### LLM-consensus gate (advisory → execution)

`GatePipeline` now has gate 6 (`quant/decision/gates_llm.py`): when `LLM_CONSENSUS_GATE=1` (or `QuantEngine(llm_consensus_gate=True)`), an entry requires the LLM advisory to agree with the deterministic Triple-A direction at High confidence, fresh within one bar. **Default OFF** — the LLM stays advisory-only; enable only after paper validation. Surfaced via `/health` config.

### Retraining LFM

```bash
PYTHONPATH=<repo-root> .venv/bin/python -m mlx_lm.lora --config backend/scripts/mlx_lora_retrain_lfm.yaml
```
Writes to `models/lfm2.5-amt-lora-v2/`. Point `.env` `MLX_ADAPTER_PATH` at it and restart to use. Smoke-validated (5 iters); a full 500-iter run takes ~35-90 min on M1 Max depending on GPU contention.

Frontend (in a plain shell, NOT a tool shell):

```bash
cd frontend && unset PORT
TZ=Asia/Kolkata node node_modules/.bin/vite --host 0.0.0.0 --port 5190
```

### Alternate ports when 9090/5190 are taken

The default ports may already be held by another worktree's servers (e.g. `/Users/apple/Downloads/v5-of-glassytrade-ai` runs uvicorn on 9090 + vite on 5190). In that case run this worktree on **9091/5191**: pass `--port 9091` to uvicorn and `--port 5191` to vite, and point the vite proxy at this worktree's backend with `VITE_BACKEND_PORT=9091` (the config reads `VITE_BACKEND_PORT || PORT || '9090'`; `unset PORT` first so the orchestrator's `PORT` doesn't leak in).

Detached launch (tool shells kill background children on exit — plain `nohup ... &` does not survive, and `launchctl submit` fails with a TCC `Operation not permitted` on the venv under `~/Documents`):

```bash
python3 .freebuff/launch_detached.py bash -c 'unset PORT; cd backend; ... exec ../.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 9091 --workers 1' > .freebuff/preview-<thread>.log 2>&1
python3 .freebuff/launch_detached.py bash -c 'unset PORT; cd frontend; VITE_BACKEND_PORT=9091 exec node node_modules/.bin/vite --host 0.0.0.0 --port 5191' > frontend/frontend.log 2>&1
```

First line of each log is the server PID.

## Verify

- Backend: `curl http://127.0.0.1:9091/health/ready` → `{"status":"ready",...}` (takes ~15–30s; lifespan runs the option scanner and Dhan broker init).
- Proxy: `curl http://127.0.0.1:5191/api/system/config` → HTTP 200 with DHAN/MCX config.
- Frontend: `curl http://127.0.0.1:5191/` → HTTP 200 (React app).
