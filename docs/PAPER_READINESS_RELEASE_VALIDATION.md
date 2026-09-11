# Paper Readiness Release Validation

## Decision

**PAPER READY** means the deterministic paper workflow passes the validation gates below.
**LIVE: NO-GO.** This branch does not authorize live trading, broker execution, credentials,
or production deployment. Live execution remains explicitly blocked until a separately
approved release changes this decision and completes live-specific review.

## Required validation gates

Run from the repository root:

```bash
PYTHONPATH=. pytest -q \
  tests/release/test_paper_readiness_release.py \
  tests/architecture \
  tests/system/test_paper_protocol.py \
  tests/quant/test_golden_replay.py \
  tests/quant/execution/test_readiness.py
```

The release evidence must show:

1. **Readiness:** coordinator state, crashes, quarantine, and paper degradation are
   represented truthfully. A degraded or not-ready state cannot be reported as ready.
2. **Architecture:** the architecture suite passes, including layer boundaries and
   no-bypass rules. New dependencies require architecture review.
3. **Replay parity:** golden replay scenarios are deterministic and preserve event
   ordering and outcomes across repeated runs.
4. **Paper protocol:** no-trade-without-approved-decision, non-fabricated market data,
   fill conventions, and idempotent exits pass against deterministic paper input.

## Protected boundaries

This validation work is documentation and tests only. It **must not change** broker
execution or `brokers/broker/dhan/infrastructure/symbol_mapper.py`. Any diff to either
boundary invalidates this scoped release evidence and requires a new review.

## Release record

Record the exact commit hash, command, date, and pass/fail counts with the release
artifact. A failing or unavailable gate is a paper **NO-GO**, not a warning.

## Explicit live stop

Do not set live mode, submit broker orders, use live credentials, or infer live readiness
from paper replay parity. The result of this validation is paper-only: **LIVE: NO-GO**.
