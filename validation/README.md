# GlassyTrade AI — Validation Suite

Tests/validation suite built against Fabio Valentini's exact Auction Market Theory scalping playbook.

## Folder Structure

```
tests/validation/
├── scenarios/                    ← 15 scenario JSON files (ground truth)
│   ├── S001_BALANCED_NO_BREAK_NO_AGGRESSION.json
│   ├── S002_OOB_AT_LVN_STRONG_AGGRESSION_LONG.json
│   ├── S003_BALANCED_FAILED_BREAKOUT_SHORT_REVERSION.json
│   ├── S004_OOB_AT_LVN_ZERO_AGGRESSION_FLAT.json
│   ├── S005_OOB_ALL_GATES_PASS_BUT_PRIOR_POC_NULL.json
│   ├── S006_KELLY_NEVER_EXCEEDS_0_5_PCT.json
│   ├── S007_BALANCED_IB_BREAK_NOT_YET_FAILED_WAIT.json
│   ├── S008_CVD_IS_TRADE_MANAGEMENT_NOT_ENTRY.json
│   ├── S009_PROFILE_MUST_MATCH_OPTION_PREMIUM_RANGE.json
│   ├── S010_SIGNAL_AND_RATIONALE_MUST_MATCH.json
│   ├── S011_NO_RAPID_FIRE_IN_BALANCED_STATE.json
│   ├── S012_STOP_LOSS_AT_AGGRESSION_PRINT_NOT_MULTIPLIER.json
│   ├── S013_FULL_EXIT_AT_PRIOR_SESSION_POC.json
│   ├── S014_BREAKEVEN_TRIGGERED_BY_CVD_PRESSURE.json
│   └── S015_IB_BREAK_MANDATORY_FOR_MODEL1.json
├── fixtures/
│   ├── synthetic_data_generator.py   ← generates candle series
│   └── candle_data/                  ← auto-generated session files
├── results/
│   └── last_run.json                 ← auto-written after each run
├── run_validation.py                 ← main test runner
└── live_market_checklist.py          ← daily pre-market checklist
```

## Usage

### Step 1 — Generate synthetic candle data
```bash
python tests/validation/fixtures/synthetic_data_generator.py
```

### Step 2 — Run all 15 validation scenarios
```bash
python tests/validation/run_validation.py
```
- Exit 0 = 15/15 pass → safe for paper trading
- Exit 1 = failures → fix engine before trading

### Step 3 — Run before every market session
```bash
python tests/validation/live_market_checklist.py
```
All 10 live checks must pass before enabling signals.

## Gate Logic (Fabio's 3 Hard AND Gates)

| Gate | Model 1 (Trend) | Model 2 (Mean Reversion) |
|------|----------------|--------------------------|
| State | OUT_OF_BALANCE required | BALANCED required |
| IB Break | Confirmed break + direction | Break occurred + FAILED |
| Aggression | delta_score > 0 at LVN | delta_score > 0 at reclaim LVN |
| Target | prior_poc must be non-null | session_poc must be non-null |

If ANY gate fails → signal = FLAT. No exceptions.

## Key Rules Encoded (Fabio Valentini Playbook)

- Never trade in BALANCED state with Model 1 (S001, S011)
- Delta score = 0.00 → always FLAT (S004)
- No prior POC → always FLAT (S005)
- Kelly max = 0.5%; 0.25% when win_rate_sample < 30 (S006)
- Do NOT take first IB breakout — wait for fail (S007)
- CVD is break-even management only, NOT entry (S008, S014)
- Profile must compute on option premium, not futures (S009)
- Badge and JSON signal must always match (S010)
- SL = swing_low + (2 ticks buffer), never a multiplier (S012)
- Target = prior session POC, full position exit only (S013)
- IB break is a mandatory prerequisite for Model 1 (S015)
