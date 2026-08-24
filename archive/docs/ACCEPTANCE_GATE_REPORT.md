# Acceptance Gate Report (§5.4)

**Tool:** `backend/scripts/acceptance_gate.py`
**Data:** `backend/live_trading_logs/journal_2026-08-{05,06,07}.jsonl` (5,246 records)
**Date:** 2026-08-07

## Verdict: UNMET / INCONCLUSIVE

The only recorded trade evidence is **synthetic-harness output**, not live or
paper trading. The §5.4 acceptance gate cannot be honestly assessed — and the
recorded "trades" would fail it outright (0% win rate, all stop-losses).

## What the journals actually contain

| Source | Count | Details |
| --- | --- | --- |
| `SIGNAL_GENERATED` | 2,076 | synthetic/determinism-run signals |
| `ENTRY_REJECTED` | 2,864 | rejected entries (mostly `THESIS_MISSING_STATE`) |
| `EXIT` | 304 | **all** detected as harness artifacts (see below) |
| other (`ENTRY_EXECUTED`, `BREAK_EVEN_TRIGGERED`) | 2 | — |

The 304 EXITs decompose as:

- **300 × `NIFTY/LONG` `WATCHDOG_Stop Loss` at PnL −56.141** each — identical
  prices (entry 100.00 → exit 93.859), `time_in_trade_s = 17,568,448` (~203
  days, impossible), spread across many determinism run_ids. Underlying symbol
  with no expiry/strike.
- **4 × `CRUDEOIL 17 AUG 7200 CALL` `STOP_LOSS` at PnL −24,864.30** each —
  identical entry/exit prices (100.1500 → 93.06020), negative `time_in_trade_s`
  (−18,663,300 s), three of four from the same `…-774574ff9f83` determinism
  fingerprint. Same synthetic replay, despite carrying a contract symbol.

Note: the coordinator's brief described "300 identical stop-losses at −24,864".
The tool's real output shows the −24,864 value belongs to the 4 CRUDEOIL
exits, and the 300 NIFTY exits are at −56.141. The substantive finding is
unchanged: **all 304 recorded EXITs are synthetic-harness artifacts, zero wins,
100% stop-loss.**

## Harness-artifact detection (per tool)

- R1 underlying symbol (no expiry/strike): **300**
- R2 repeated run_id (>1 EXIT): **297**
- R3 impossible time-in-trade (<0 s or >7 days): **304**
- Flagged (union): **304 / 304 (100%)**
- Clean (real) exits: **0**

## Gate check on clean data

With zero real trades the gate is INCONCLUSIVE:

| Metric | Value | Threshold | Result |
| --- | --- | --- | --- |
| win rate | n/a | ≥ 55% | UNMET |
| avg R:R | n/a | ≥ 1.5 | UNMET |
| max DD % of equity | n/a | ≤ 10% | UNMET |
| Sharpe (annualized) | n/a | ≥ 1.0 | UNMET |
| trades / session | n/a | 3–8 | UNMET |

Even treating all 304 exits as "real": 0% win rate, avg R:R 0.00,
Sharpe ≈ 0.0, ~101.3 trades/session (harness noise, outside 3–8).

## What is needed to satisfy the gate

1. Run real paper trading week 1 via `QUANT_EXECUTION_MODE=paper` (§5.5) so the
   journals contain genuine contract entries/exits (dated/struck symbols,
   real positions, positive session-consistent `time_in_trade_s`).
2. Re-run:
   ```
   python scripts/acceptance_gate.py backend/live_trading_logs/journal_*.jsonl
   ```
   The gate passes only when the clean (harness-excluded) metrics meet all
   §5.4 thresholds: win rate ≥ 55%, avg R:R ≥ 1.5, max DD ≤ 10% of equity,
   Sharpe ≥ 1.0, trades/session 3–8.

## Tool output (run on the real journals, 2026-08-07)

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

Exit code: `1` (gate not passed).
