# PAPER → LIVE RUNBOOK

Operator checklist for paper week 1, the §5.4 acceptance gate, real-day replay capture, and go-live. Every env var below is cross-checked against the code (see `backend/app/config_models/settings_adapter.py`, `backend/config/feature_flags.yaml`, `backend/start.sh`, `backend/app/infrastructure/adapters/dhan_adapter.py`, `backend/app/shared/mode.py`).

**Canonical mode env vars**

| var | values | read by |
|---|---|---|
| `QUANT_EXECUTION_MODE` | `off` \| `shadow` \| `paper` \| `live` | `settings_adapter.py:272` (env wins over `feature_flags.yaml` `quant_execution_mode`, default `off`) |
| `GLASSYTRADE_ENV` | `development` \| `paper` \| `live` | `mode_config.py:195` (selects `environments/{env}.yaml`; `paper.yaml` has `broker_mode: "paper"`) |
| `GLASSYTRADE_STRATEGY` | `mcx_options` (default) \| `nse_options` | `mode_config.py:196` |
| `TRADING_MODE` | `paper` (any value ≠ `live`) | `app/shared/mode.py:12` — `is_live_mode()` = `GLASSYTRADE_ENV=live` OR `TRADING_MODE=live` → routes to `DhanBrokerAdapter` vs `PaperBrokerAdapter` (`di/composition_root.py:183-189`) |
| `QUANT_RECORD_REPLAY` | `1` to capture | `quant_bridge.py:162` |
| `DHAN_CLIENT_ID` | Dhan client id | `settings_adapter.py:90`, `brokers/broker/dhan/application/config.py:111` |
| `DHAN_ACCESS_TOKEN` | Dhan access token | `settings_adapter.py:91`, `brokers/broker/dhan/application/config.py:112` |

Mode routing: the closed-bar `TradingSessionService` path computes/stores the quant decision after agent facts are available. `shadow` logs the quant signal for comparison and continues the legacy path; `QUANT_EXECUTION_MODE=paper` → `session_event_router._try_execute_quant_decision` maps the stored decision → `EntryCoordinator.execute_signal` against `PaperBrokerAdapter`. `off` → decision is not evaluated (auction projection remains available and the legacy path is unchanged).

---

## 0. PREREQS

- [ ] Working tree on the deployed branch; backend venv present (`backend/venv/bin/uvicorn` — required by `backend/start.sh`; create with `python -m venv backend/venv` + `pip install -r backend/requirements.txt` if missing).
- [ ] `.env` at the **repo root** (gitignored) with Dhan creds. The canonical pair is:
      ```
      DHAN_CLIENT_ID=...
      DHAN_ACCESS_TOKEN=...
      ```
      Loaded automatically by `SettingsAdapter._load_secrets_from_env` and `DhanBroker.create`. Other keys (`DHAN_API_KEY`/`DHAN_API_SECRET`) are accepted but the Dhan adapter only consumes `DHAN_CLIENT_ID` + `DHAN_ACCESS_TOKEN`.
- [ ] Optional `GLASSYTRADE_STRATEGY` override (default `mcx_options`).
- [ ] **Market-hours caveat:** Dhan market data + orders only work when the exchange is open. Platform session windows (from `backend/config/base.yaml`): NSE/NFO `09:15–15:15 IST`, MCX `09:00–23:15 IST`, tz `Asia/Kolkata`. Run sessions during open hours or no live ticks arrive (journal stays empty).
- [ ] Frontend for monitoring: `./start_frontend.sh` (Vite on `:5190`), backend on `:9090`.

## 1. PAPER WEEK 1 (`QUANT_EXECUTION_MODE=paper`)

- [ ] Start backend: `./backend/start_paper.sh`
      This exports `QUANT_EXECUTION_MODE=paper`, `TRADING_MODE=paper`, `GLASSYTRADE_ENV=paper` and chains to `./backend/start.sh` (uvicorn `:9090`, single worker). Verify the 3 printed vars.
- [ ] Run a **full session** during market hours (see §0 caveat). One session = the whole exchange session.
- [ ] Watch in the UI (WS `:9090` snapshot → frontend `:5190`):
      - **auction WS field** → `ModelStateBanner` TRIPLE-A badge (`auction.tripleAPhase` / `auction.tripleASignal`) + absorption badge; `auction` populated from `quant_bridge.auction_state_to_dto`.
      - **quantDecision card** → `QuantDecisionCard`: `Approved` (emerald) vs `Standing By`; when approved shows signal `type @ entry`, `RR`, `SL`, `TP`, `Confidence %`; phase/reason below. Field flows from `session.last_quant_decision` → `state_snapshot_builder.py:43`.
      - **no-trade-no-edge:** a position must only open after an approved quant decision. Quiet stretch with no edge → no trades (WAITING / STANDING BY is correct).
- [ ] Journals land in `backend/live_trading_logs/journal_<YYYY-MM-DD>.jsonl` (`TradeJournal`, one file per calendar day; `SIGNAL_GENERATED` / `ENTRY_REJECTED` / `EXIT` records).

## 2. ACCEPTANCE GATE (§5.4)

Run after each paper session, from the **repo root**:

```
/Users/apple/miniconda3/envs/amt_313/bin/python \
  backend/scripts/acceptance_gate.py backend/live_trading_logs/journal_*.jsonl
```

- [ ] Optional machine-readable output: append `--json out.json`.
- [ ] Targets (evaluated on **clean** exits only): win rate `≥ 55%`, avg R:R `≥ 1.5`, max DD `≤ 10%` of equity, Sharpe (annualized) `≥ 1.0`, trades/session `3–8`. Exit code **0 = PASS**, **1 = FAIL or INCONCLUSIVE**.
- [ ] **Harness-artifact detection:** the gate flags synthetic harness EXITs (R1 underlying symbol like `NIFTY`/`CRUDEOIL` with no contract; R2 repeated `run_id`; R3 impossible `time_in_trade_s` <0 or >7d). Real paper trades carry a contract symbol (e.g. `CRUDEOIL 17 AUG 7200 CALL`) and are **not** flagged. A gate run on harness-only journals returns `INCONCLUSIVE` + exit 1 — that is **expected** before real paper data exists, not a failure.
- [ ] Do not attempt the gate in this sandbox — it needs real paper-trade journals from §1.

## 3. REAL-DAY REPLAY CAPTURE

- [ ] Capture a session: start backend with `QUANT_RECORD_REPLAY=1 ./backend/start_paper.sh` (env must be set in the same shell).
- [ ] Capture files: `backend/live_trading_logs/replay_<SYMBOL>_<YYYY-MM-DD>.jsonl` — one JSONL line per closed bar: `{symbol, time, open, high, low, close, volume, buy_volume, delta, oi, auction}` (`quant_bridge._record_replay`).
- [ ] Byte-for-byte gate (no network): from the repo root
      ```
      /Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant/replay/ -v
      ```
      `test_capture_matches_committed_golden` asserts the capture reproduces `tests/fixtures/replay/session_120.jsonl` byte-for-byte; `test_replay_committed_golden_is_byte_identical` re-replays through a fresh `AuctionCoordinator`. Any detector drift → `ReplayMismatch` → **fix/flag before going live**. All 7 tests pass today.
- [ ] Treat the live `replay_*.jsonl` as drift evidence; commit/rotate nightly (rolling golden-file, see §4).

## 4. GO-LIVE CHECKLIST

Only proceed when ALL hold:

- [ ] Paper week 1 complete: ≥ 1 full session, journals present.
- [ ] Acceptance gate **PASS** (exit 0) on clean paper-trade exits; all five §5.4 thresholds met.
- [ ] Replay gate green (`tests/quant/replay/`).
- [ ] `.env` has valid `DHAN_CLIENT_ID` / `DHAN_ACCESS_TOKEN` with live (not paper) order permission.
- [ ] **Day 1 (graduated live):** start with **1 position max on one setup**. Launch with:
      ```
      QUANT_EXECUTION_MODE=live GLASSYTRADE_ENV=live TRADING_MODE=live ./backend/start.sh
      ```
      (`live.yaml` sets `broker_mode: "live"` — required by validator RULE-2; `TRADING_MODE=live` → `is_live_mode()` → `DhanBrokerAdapter`.)
- [ ] Monitor exactly like §1 — auction WS field + quantDecision card + no-trade-no-edge.
- [ ] **Rolling golden-file nightly:** each night after market close run §3 (capture via `QUANT_RECORD_REPLAY=1` + `tests/quant/replay/`) and commit the new `replay_*.jsonl` / refresh the golden; stop live if the gate reds.

## 5. ROLLBACK

| from | to | do |
|---|---|---|
| `paper` | `off` (legacy) | `QUANT_EXECUTION_MODE=off ./backend/start.sh` (env wins over `feature_flags.yaml` default `"off"`); decision path disabled, legacy AMT path byte-identical |
| `live` | `paper` | `QUANT_EXECUTION_MODE=paper GLASSYTRADE_ENV=paper TRADING_MODE=paper` (i.e. `./backend/start_paper.sh`) |
| `live` | `off` | `QUANT_EXECUTION_MODE=off GLASSYTRADE_ENV=development TRADING_MODE=paper ./backend/start.sh` |

- [ ] To rely purely on YAML (no env override): `unset QUANT_EXECUTION_MODE` → falls back to `feature_flags.yaml` `quant_execution_mode` (`"off"` by default).
- [ ] After rollback to `off`, confirm no new `EXIT`/position records in the journal and the UI shows no quantDecision signal.
