# WS-DATA/INFRA — Persistence hardening + signal TTL + training-data format guard

**Worktree:** `/Users/apple/Documents/wt-ws-data` (branch `migration/ws-data`). Work ONLY there.

**From:** brain-migration plan AUDIT ADOPTION → B-39/B-40 (SQLite WAL + index), B-13 (signal TTL), FULL_SYSTEM §7 (training-data format mismatch). Also architecture proposal §5.1-5.3 test expectations.

**Task 1 — SQLite WAL + index (B-39/B-40).** `backend/app/infrastructure/storage/database.py`:
- Enable WAL mode at connection init (`PRAGMA journal_mode=WAL`) plus `PRAGMA synchronous=NORMAL` and `PRAGMA busy_timeout`.
- Add an index on `ticks(symbol, time)` if the ticks table has those columns (check the schema/`CREATE TABLE`; if it's a different name, index the actual columns). Create it idempotently alongside table creation.
- Add a unit test asserting the pragma is set (inspect `db.execute("PRAGMA journal_mode").fetchone()`) and the index exists (`PRAGMA index_list('ticks')` or `sqlite_master`).

**Task 2 — Signal TTL (B-13/audit).** The stale-signal threshold is 10 minutes (`AGENT_DECISION_THRESHOLD`, used in `backend/app/application/services/trading_session.py` and/or `session_event_router.py`; grep `600` / `AGENT_DECISION_THRESHOLD` / `signal_age`). Make it configurable with a DEFAULT of 60 seconds: add a settings property (e.g. `SIGNAL_STALE_SECONDS`, env `SIGNAL_STALE_SECONDS`, default `60`) and use it where the 600-constant is currently checked. Update any test that asserts the 600 behavior. Note in the report where the constant lived and what changed.

**Task 3 — Training-data format guard (FULL_SYSTEM §7).** Add a validation test that guards the LLM training/inference format parity:
- Read `backend/app/domain/...` no — prompt_builder now lives at `quant/inference/prompt_builder.py`. The test (put it at `tests/quant/inference/test_train_livefmt_parity.py`) should: build a representative `AuctionState`-derived dict, render `quant.inference.prompt_builder.build_entry_prompt` on it, and assert the rendered prompt's SECTION KEYS/format markers (e.g. `SESSION:`, `MARKET STATE:`, `VALUE AREA:`, `ORDER FLOW & AGGRESSION:`, `CVD:`, `TRIPLE-A PHASE:`) appear — i.e., the live prompt structure matches the `amt_dataset/nifty_amt_data_livefmt/*.jsonl` training samples' shape (read 1-2 sample lines from `amt_dataset/nifty_amt_data_livefmt/train.jsonl` and assert the same section vocabulary). Keep the test data-driven and robust to wording (assert section-label substrings). If the livefmt files are absent/misformatted, write the test against the prompt's own structure and report the livefmt status.

**Verify:** `/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant backend/tests/unit -q --tb=short --continue-on-collection-errors` from worktree root (repo-root conftest handles paths) and `cd backend && ... tests/unit` as appropriate. Report exact counts (4 pre-existing env errors acceptable).

**Commits:** `feat(backend): SQLite WAL + ticks index`, `feat(backend): configurable signal stale TTL (default 60s)`, `test(quant): live prompt vs training livefmt format parity`.

**Report:** `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/ws-data-report.md`. Reply: status, commits, test counts, the livefmt status finding, concerns.
