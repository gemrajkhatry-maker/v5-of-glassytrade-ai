# WS-TTL — Reconcile SignalValidator TTL with the new 60s default

**Worktree:** `/Users/apple/Documents/wt-ws-ttl` (branch `migration/ws-ttl`). Work ONLY there.

**Context:** WS-DATA made the runtime signal stale-TTL configurable with a **60s default** (settings `SIGNAL_STALE_SECONDS`, used in `trading_session.py`/`session_event_router.py`). But the quant-side validator still hardcodes **600**:
- `quant/contracts/constants.py:125` → `SIGNAL_TTL_SECONDS = 600`
- `quant/execution/signal_validator.py:19,37` → imports it and uses it as `validate_staleness(max_age_seconds=SIGNAL_TTL_SECONDS)` default.

The two defaults now disagree (60s in the backend settings vs 600s in `SignalValidator`), so a signal can pass the quant validator while the session considers it stale — or vice versa. Reconcile them.

**Task:**
1. Change `SIGNAL_TTL_SECONDS` in `quant/contracts/constants.py` from `600` to `60` (aligning with the new default), with a comment `# 60s scalar-session default; runtime override via SIGNAL_STALE_SECONDS setting`.
2. Ensure `validate_staleness` remains overridable (`max_age_seconds` param already exists) and that callers who need the longer window pass it explicitly.
3. Search the whole repo for other uses of `SIGNAL_TTL_SECONDS` or a literal `600` that means the stale window; update any that should follow the 60s default. If a caller genuinely needs 600, change it to pass `max_age_seconds=600` explicitly with a comment — do NOT silently change real behavior beyond the reconciliation.
4. Add/extend a test in `tests/quant/execution/test_signal_validator*.py` asserting `validate_staleness` default rejects a signal older than 60s and accepts one younger (adjust any existing test that asserted the 600s boundary).

**Verify:** `/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant -q --tb=short` (worktree root). Report exact counts.

**Commits:** `fix(quant): align SignalValidator TTL default with 60s runtime setting`.

**Report:** `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/ws-ttl-report.md`. Reply: status, commits, test counts, concerns.
