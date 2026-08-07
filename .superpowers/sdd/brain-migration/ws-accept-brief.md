# WS-ACCEPT — Acceptance-gate tool + honest report (architecture proposal §5.4)

**Worktree:** `/Users/apple/Documents/wt-ws-accept` (branch `migration/ws-accept`). Work ONLY there.

**Context:** The architecture proposal's acceptance gate (§5.4): win rate ≥55%, avg R:R ≥1.5, max DD ≤10% of equity, Sharpe ≥1.0, trades/session 3–8. Recorded journals exist at `backend/live_trading_logs/journal_2026-08-{05,06,07}.jsonl` (5,246 records: 2,076 SIGNAL_GENERATED, 2,864 ENTRY_REJECTED, 304 EXIT). **Finding from coordinator analysis:** the 304 EXITs are synthetic-harness artifacts — 300 identical `NIFTY/LONG` WATCHDOG_Stop Loss at −24,864 each, from determinism runs (run_ids `…-774574ff9f83`), NOT live trading. The gate CANNOT be honestly passed with current data.

**Deliverable 1 — `backend/scripts/acceptance_gate.py`** (reusable CLI):
- `python scripts/acceptance_gate.py backend/live_trading_logs/journal_*.jsonl`
- Parses the journals; for EXIT events computes: trades, win rate, avg win, avg loss, avg R:R, max drawdown (equity curve from cumulative PnL), Sharpe (annualized on per-trade returns, rfr=0), trades/session, exit-reason distribution, and per-symbol breakdown.
- Robust to string/None numeric fields. Prints a table + PASS/FAIL per §5.4 metric.
- **Harness-artifact detection:** flag records where symbol is an underlying (`NIFTY`, `BANKNIFTY`, `FINNIFTY`, `CRUDEOIL`, `SILVERM`, `GOLDM` without an expiry/strike) OR run_id repeats (same run_id >1) as likely harness output, and report the gate both with and without harness-flagged trades.

**Deliverable 2 — `docs/ACCEPTANCE_GATE_REPORT.md`** (in the worktree; do NOT commit — report its path):
- State: the only recorded evidence is synthetic-harness output; the honest gate result is **UNMET / INCONCLUSIVE** (0% win on 304 harness exits, all stop-loss, ~101 "trades/session" of harness noise).
- What is needed to satisfy the gate: real paper-week-1 data via `QUANT_EXECUTION_MODE=paper` (§5.5), then the tool re-runs with real data.

**Deliverable 3 — a unit test** `backend/tests/unit/scripts/test_acceptance_gate.py`:
- Build a small synthetic journal fixture (mix of wins/losses + one harness-flagged run) and assert the tool computes win rate / avg R:R / max DD correctly, and that harness-flagged records are excluded in the "clean" numbers.

**Verify:** `/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/unit/scripts -q --tb=short` (worktree root, from its `backend/`). Also run the tool on the real journals and paste its output in the report.

**Commits:** `feat(scripts): acceptance-gate report tool (backtest metrics)`, `test(scripts): acceptance-gate unit tests`.

**Report:** `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/ws-accept-report.md` (include the tool's real-journal output + the honest gate verdict). Reply: status, commits, the gate verdict, concerns.
