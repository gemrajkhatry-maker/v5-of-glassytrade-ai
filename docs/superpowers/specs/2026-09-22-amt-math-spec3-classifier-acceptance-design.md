# AMT Math Spec 3 — Classifier and Acceptance Design

Date: 2026-09-22

## System intent

Market state describes the current auction from price location and effective
displacement. Acceptance describes confirmed time and volume beyond one current
Value Area boundary. Historical balance and acceptance timers provide context;
they do not override the current bar's location.

## Expected behavior contract

Inputs:
- Current close and session VAH/VAL.
- Effective displacement after rejected-probe suppression.
- Rolling balance ratio.
- Per-side elapsed time outside value and current-bar volume.

Outputs:
- `IMBALANCED` only when close is outside session value or effective
  displacement is active.
- `BALANCED` when close is inside value without effective displacement.
- At most one acceptance side, matching the boundary beyond which the current
  close remains.
- No acceptance side when the current close is inside value.

Timing and state:
- Outside-value timers accumulate from real bar timestamps.
- A same-timestamp repeat adds no time.
- Prior-side timers may decay for continuity, but cannot publish acceptance
  unless the current close is still on that side.

Failure behavior:
- Missing/zero volume baseline cannot confirm acceptance.
- A wick through value may publish rejection/sweep, never close-based
  acceptance by itself.

## Current flow and mismatch

`AMTAnalyzer` computes Value Area, displacement, rolling balance ratio, and the
acceptance/rejection result. It ORs the two acceptance flags into
`has_acceptance`, then calls `detect_market_state`.

Two silent mismatches existed:
1. Low balance ratio was a third state-transition OR, allowing an inside-value
   close with no displacement to become `IMBALANCED`.
2. Decaying side timers directly drove acceptance flags, so stale acceptance
   remained visible inside value and both sides could be true after a fast
   cross.

## Runtime cycle

Assume VAH=105, VAL=95, acceptance threshold=50 seconds:
1. Close 106.5 for 120 seconds: above timer=120; only `acceptance_above=true`.
2. Next close 93.5 for 60 seconds: below timer=60 and above timer decays to 90;
   only `acceptance_below=true`, because the close is currently below value.
3. Next close 100: both timers decay, but both acceptance flags are false.
4. With no effective displacement, step 3 classifies `BALANCED` regardless of a
   low rolling balance ratio. The ratio only affects confidence and trigger
   context.

## B-shape decision

The working analyzer no longer overrides `IMBALANCED` to `BALANCED` for a
B-shaped profile. Shape remains descriptive through
`effective_profile_shape = shape.shape`. No classifier change is required; the
debt item is obsolete. The existing removal is preserved without introducing a
new playbook interpretation.

## Correct ownership

- `AcceptanceRejectionEngine` owns truthfulness and mutual exclusion of its
  side flags.
- `detect_market_state` owns state transition criteria.
- `AMTAnalyzer` may continue OR-ing the now-honest acceptance flags.

This keeps replay, backtest, and live paths on the same shared implementation.
