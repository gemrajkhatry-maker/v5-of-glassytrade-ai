# WS-ACCEPT report — acceptance-gate tool + honest verdict

**Branch:** `migration/ws-accept` (worktree `/Users/apple/Documents/wt-ws-accept`)
**Date:** 2026-08-07

## Status: DONE (tool + tests committed; docs report uncommitted as required)

## Commits (worktree `migration/ws-accept`)

- `3b98767` `feat(scripts): acceptance-gate report tool (backtest metrics)` — `backend/scripts/acceptance_gate.py`
- `0aa63c1` `test(scripts): acceptance-gate unit tests` — `backend/tests/unit/scripts/test_acceptance_gate.py`

**Not committed** (per brief): `docs/ACCEPTANCE_GATE_REPORT.md` (untracked in the
worktree, not covered by `.gitignore`); nothing else touched. The journals were
copied into the worktree's `backend/live_trading_logs/` (already `.gitignore`d)
so the tool could run on real data.

## Verification

- `pytest tests/unit/scripts -q --tb=short` → **13 passed** (5 new + 8 existing).
- Tool run on real journals: `python backend/scripts/acceptance_gate.py backend/live_trading_logs/journal_*.jsonl` → exit code 1 (gate not passed).

## Gate verdict: UNMET / INCONCLUSIVE

**All 304 recorded EXITs are synthetic-harness artifacts; there are zero real
trades.** The gate cannot be assessed — and the recorded exits would fail it
outright (0% win rate, 100% stop-loss, ~101.3 trades/session).

### Tool's real-journal output (2026-08-07)

```
========================================================================
 ACCEPTANCE GATE (§5.4) - journal metric report
========================================================================
 EXIT events (trades):   304
 Records parsed:         5,246  (SIGNAL_GENERATED=2,076, ENTRY_REJECTED=2,864)
 Malformed lines:        0
 Sessions (calendar d.): 3

 HARNESS-ARTIFACT DETECTION
   R1 underlying symbol (no expiry/strike):    300
   R2 repeated run_id (>1 EXIT):               297
   R3 impossible time-in-trade (<0 or >7d):    304
   Flagged exits (union):                      304  (100.0% of exits)
   Clean (real) exits:                           0

 METRICS - ALL EXITS
   trades                       304
   wins / losses                0 / 304
   win rate                     0.00%
   total PnL                    -116,299.50
   avg win                      0.00
   avg loss (magnitude)         382.56
   avg R:R (avg win/avg loss)   0.00
   max drawdown                 116,299.50  (1.1630% of equity)
   Sharpe (annualized, rfr=0)   -0.000
   trades / session             101.33
   exit reasons                 {'STOP_LOSS': 4, 'WATCHDOG_Stop Loss': 300}

 METRICS - CLEAN (harness-flagged excluded): no real trades recorded.

 PER-SYMBOL BREAKDOWN (all exits)
   symbol                              n wins  loss    win%    total PnL
   CRUDEOIL 17 AUG 7200 CALL          4    0     4    0.0   -99,457.20
   NIFTY                            300    0   300    0.0   -16,842.30 *
   (* = harness-flagged underlying symbol)

 GATE CHECK (on clean, harness-excluded trades)
   metric                            value  threshold   result
   win rate                            n/a     >= 55%    UNMET
   avg R:R                             n/a     >= 1.5    UNMET
   max DD % of equity                  n/a     <= 10%    UNMET
   Sharpe (annualized)                 n/a     >= 1.0    UNMET
   trades / session                    n/a      3 - 8    UNMET

========================================================================
 VERDICT: INCONCLUSIVE - no real (non-harness) trades recorded.
          All recorded EXITs are synthetic-harness artifacts; the
          gate cannot be assessed until real paper-week-1 data exists
          (QUANT_EXECUTION_MODE=paper, architecture §5.5).
========================================================================
```

Exit code `1`. (Full report incl. what's needed to satisfy the gate:
`/Users/apple/Documents/wt-ws-accept/docs/ACCEPTANCE_GATE_REPORT.md`.)

## Deliverables

1. `backend/scripts/acceptance_gate.py` — reusable CLI. Computes trades, win
   rate, avg win/loss, avg R:R, max drawdown (cumulative-PnL equity curve, % of
   `--capital`, default 10M), annualized Sharpe on per-trade returns (rfr=0),
   trades/session (calendar-day sessions), exit-reason distribution, per-symbol
   breakdown. Robust to string/`None` numerics (`_num`). Harness detection:
   R1 underlying symbol w/o expiry/strike, R2 repeated run_id, R3 impossible
   time-in-trade (<0 or >7 d); reports metrics with and without flagged trades;
   `--json` for machine output; exit 0 on PASS, 1 otherwise.
2. `docs/ACCEPTANCE_GATE_REPORT.md` — honest report (uncommitted), path above.
3. `backend/tests/unit/scripts/test_acceptance_gate.py` — synthetic fixture (4
   real: 2 win/2 loss + 3 harness exits sharing a run_id); asserts clean win
   rate 50%, avg R:R 2.0, max DD 75.0 (exact equity-curve math), string-pnl
   parsing, and that harness-flagged records are excluded from clean numbers.

## Concerns

- **Brief's numbers vs. actual data:** the brief said "300 identical
  NIFTY/LONG stop-losses at −24,864 each". Real journals show the −24,864
  belongs to 4 `CRUDEOIL 17 AUG 7200 CALL` STOP_LOSSes; the 300 NIFTY exits are
  at **−56.141** (entry 100.00 → exit 93.859, ~203-day time-in-trade). The
  substantive finding (all synthetic) is unchanged; the report states this
  correction explicitly rather than repeating the brief verbatim.
- **R3 heuristic added beyond the brief's two rules:** the 4 CRUDEOIL exits
  carry contract symbols (miss R1) and 1 of 4 has a unique run_id (misses R2),
  yet are identically-priced, negative-time-in-trade replays. The
  impossible-time rule is what forces clean = 0; without it, clean would be 1
  synthetic CRUDEOIL trade (still 0% win → UNMET, but misleadingly "real").
  R3 is documented in the tool docstring.
- **Sharpe approximation:** annualized from per-trade returns assuming
  `trades/session × 252` trades/yr (rfr=0). Fine for a pass/fail signal; not a
  rigorous time-series Sharpe. With identical harness PnL the std collapses to
  ~0 and Sharpe ≈ 0.
- **No real data exists yet** — verdict is INCONCLUSIVE by design; the tool and
  report must be re-run after real paper-week-1 data via
  `QUANT_EXECUTION_MODE=paper` (§5.5). Nothing was fabricated to force a pass.
