# WS-RUNBOOK Report

Worktree: `/Users/apple/Documents/wt-ws-runbook` (branch `migration/ws-runbook`)
Commit: `8a7d379` — `docs: operator runbook for paper week, acceptance gate, and go-live`
Deliverable: `docs/PAPER_LIVE_RUNBOOK.md` (+ one-line echo fix in `backend/start_paper.sh`)

## Verified env vars (each cross-checked against code)

| env var | values | verified in | purpose |
|---|---|---|---|
| `QUANT_EXECUTION_MODE` | `off`/`shadow`/`paper`/`live` | `backend/app/config_models/settings_adapter.py:272` (env wins over `backend/config/feature_flags.yaml` `quant_execution_mode`, default `"off"`); routing in `backend/app/application/services/session_event_router.py:647` | execution gate; `paper` → `EntryCoordinator.execute_signal` |
| `GLASSYTRADE_ENV` | `development`/`paper`/`live` | `backend/config/mode_config.py:195`; selects `backend/config/environments/{env}.yaml` (`paper.yaml` has `broker_mode: "paper"`) | environment config |
| `GLASSYTRADE_STRATEGY` | `mcx_options` (default)/`nse_options` | `backend/config/mode_config.py:196` | strategy config (optional; not set by launcher) |
| `TRADING_MODE` | `paper` (any value ≠ `live`) | `backend/app/shared/mode.py:12`; consumed by `is_live_mode()` → broker factory `backend/app/application/di/composition_root.py:183-189` (`PaperBrokerAdapter` vs `DhanBrokerAdapter`) | live-mode detector |
| `QUANT_RECORD_REPLAY` | `1` enables capture | `backend/app/application/services/quant_bridge.py:162,169` → writes `backend/live_trading_logs/replay_<SYMBOL>_<date>.jsonl` | real-day replay capture |
| `DHAN_CLIENT_ID` | Dhan client id | `settings_adapter.py:90`, `brokers/broker/dhan/application/config.py:111`, `DhanBroker.create` (`brokers/broker/dhan/application/broker.py:140-165`) | broker auth |
| `DHAN_ACCESS_TOKEN` | Dhan access token | `settings_adapter.py:91`, `brokers/broker/dhan/application/config.py:112` | broker auth |
| `DHAN_API_KEY` / `DHAN_API_SECRET` | legacy | `settings_adapter.py:92-93` (read but NOT consumed by DhanBroker) | noted in runbook as not required |

`.env` location: repo root (loaded by `SettingsAdapter._load_secrets_from_env` at `settings_adapter.py:81`).

## start_paper.sh fixes

Preflight: already executable (`-rwxr-xr-x`), `bash -n` clean, all three mode vars correct and correctly chained (`exec ./start.sh "$@"`). No functional fixes required.
- **One edit (doc-only):** echo hint now says "from the REPO ROOT run the §5.4 acceptance gate" — the script `cd`s into `backend/`, so the bare `backend/...` path in the old hint was misleading relative to cwd.

## Acceptance gate verification

- `backend/scripts/acceptance_gate.py` run against the recorded harness journals (`journal_2026-08-{05,06,07}.jsonl`): **exit 1, VERDICT INCONCLUSIVE**, 310/310 exits flagged as harness artifacts, 0 clean — expected.
- Unit suite `backend/tests/unit/scripts/test_acceptance_gate.py`: 5 passed.
- Replay byte-for-byte gate `tests/quant/replay/test_replay.py`: 7 passed (interpreter `/Users/apple/miniconda3/envs/amt_313/bin/python`).
- Runbook command shape verified end-to-end from repo root.

## Files committed (worktree only)

- `docs/PAPER_LIVE_RUNBOOK.md` (new)
- `backend/start_paper.sh` (echo-hint edit)

## Concerns

1. **Replay capture format ≠ golden format:** the live `replay_*.jsonl` records `{symbol, time, open, ..., auction}` while `tests/quant/replay/` golden is `{bar, state}`. The live file is evidence/drift input only; the byte-for-byte gate runs against the committed synthetic golden (`tests/fixtures/replay/session_120.jsonl`). No converter exists — document as-is.
2. **`start.sh` requires `backend/venv`** (gitignored, not present in worktree). Runbook prereqs call out `python -m venv backend/venv` + `pip install -r backend/requirements.txt`; operator env must provision it.
3. **Live path needs `TRADING_MODE=live` too**, not just `QUANT_EXECUTION_MODE=live` + `GLASSYTRADE_ENV=live`, because broker selection keys off `is_live_mode()` (mode.py), not the quant gate. Runbook go-live checklist sets all three.
4. **Main repo untouched** except the report under `.superpowers/` (not committed); no commits in the main repo.
