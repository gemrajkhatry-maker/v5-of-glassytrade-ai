# WS-RUNBOOK — Operator runbook: paper week → acceptance gate → go-live

**Worktree:** `/Users/apple/Documents/wt-ws-runbook` (branch `migration/ws-runbook`). Work ONLY there.

**Context:** The paper-week / go-live steps need live Dhan credentials + market hours, so they can't run here — but the OPERATOR RUNBOOK must be precise and preflight-verified so the operator can execute it one-shot. This workstream produces that runbook + verifies the launcher.

**Tasks:**
1. **Preflight-verify the launcher:** `backend/start_paper.sh` must be executable (`ls -l`), `bash -n` clean, and set the correct mode vars. Read `backend/start.sh` and `backend/app/config_models/settings_adapter.py` + `backend/config/feature_flags.yaml` to confirm the exact env var names the launcher must set for paper mode + `QUANT_EXECUTION_MODE=paper`. Fix `start_paper.sh` if the var names are wrong or the chain to `start.sh` is broken. ALSO verify `backend/scripts/acceptance_gate.py` runs on the recorded journals (it should exit 1 with the harness-artifact verdict — that's expected).
2. **Write `docs/PAPER_LIVE_RUNBOOK.md`** covering:
   - **Prereqs:** `amt_313` env, `.env` with Dhan creds (`DHAN_CLIENT_ID`/`DHAN_ACCESS_TOKEN` — confirm the exact var names from the code), market-hours caveat.
   - **Paper week 1:** `QUANT_EXECUTION_MODE=paper` via `start_paper.sh`; what to watch (auction WS field, quantDecision card, no-trade-no-edge), how long (a full session), where journals land (`backend/live_trading_logs/journal_<date>.jsonl`).
   - **Acceptance gate:** after each session run `backend/scripts/acceptance_gate.py backend/live_trading_logs/journal_*.jsonl`; the §5.4 targets (win rate ≥55%, avg R:R ≥1.5, max DD ≤10%, Sharpe ≥1.0, 3–8 trades/session); note the harness-artifact detection so the operator knows real paper trades are NOT flagged.
   - **Real-day replay:** `QUANT_RECORD_REPLAY=1` capture, then `tests/quant/replay/` byte-for-byte gate.
   - **Go-live checklist:** gate passes → `QUANT_EXECUTION_MODE=live`; start with 1 position max on one setup; rolling golden-file nightly.
   - **Rollback:** how to go back to `off`/legacy mode (set `QUANT_EXECUTION_MODE=off`).
3. Keep it a crisp checklist doc — no prose padding.

**Verify:** `bash -n backend/start_paper.sh`; `ls -l backend/start_paper.sh` (executable); the runbook references only real env vars (cross-check each against the code).

**Commit:** `docs: operator runbook for paper week, acceptance gate, and go-live`.

**Report:** `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/ws-runbook-report.md` (list the env vars you confirmed and any start_paper.sh fixes). Reply: status, commits, the confirmed env var list, concerns.
