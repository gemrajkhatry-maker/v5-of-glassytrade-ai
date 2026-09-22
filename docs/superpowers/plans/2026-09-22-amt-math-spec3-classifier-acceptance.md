# AMT Math Spec 3 — Classifier and Acceptance Plan

Date: 2026-09-22

1. Lock the contracts with regressions:
   - An inside-VA close with low balance ratio remains `BALANCED`.
   - A boundary cross publishes only the current close's acceptance side.
   - An inside-VA close publishes neither acceptance side.
2. Remove balance ratio from the market-state transition predicate while
   retaining its confidence and trigger contribution.
3. Gate acceptance publication by the current close's mutually exclusive side
   in `AcceptanceRejectionEngine`; retain timer decay and wick/sweep behavior.
4. Verify the analyzer has no B-shape state override. Record the already-absent
   override as obsolete and leave shape reporting intact.
5. Run focused market tests, then the required architecture/AMT/decision/
   execution/runtime merge gate.

No money-path, auction, TimesFM, options, or Gate1–4 logic is changed.
