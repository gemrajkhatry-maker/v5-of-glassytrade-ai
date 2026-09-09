# Golden Snapshot Nondeterminism Isolation Plan

**Date:** 2026-09-09
**Scope:** `tests/quant/runtime/test_decide_golden.py::test_decide_golden_matches_committed_snapshot`
**Status:** Investigation plan

## Evidence currently established

- The golden test passes repeatedly in isolation.
- The complete ordered quant suite fails after roughly 1,430 passing tests.
- The failure is a trace-content mismatch, not a missing file or collection error.
- Actual and expected traces both contain 307 decisions and no approved signals.
- TimesFM is unavailable in the environment and emits fallback warnings, but the isolated golden trace remains stable.
- No snapshot regeneration is justified.
- Candidate shared state includes AMT seed cache, model cache, hotpath tracer/subscriber state, SessionRisk persistence, module-level caches, environment variables, and mutable test fixtures.

## Root-cause strategy

### 1. Freeze the acceptance seam

Run only the golden file and confirm:

```bash
pytest -q tests/quant/runtime/test_decide_golden.py
```

Capture a normalized trace fingerprint containing:

- decision count
- SHA-256 of canonical JSON trace
- first differing decision index
- risk state before engine construction
- relevant environment flags
- AMT seed-cache keys
- TimesFM model-cache state

Do not modify the committed snapshot.

### 2. Produce the exact ordered prefix

Use pytest collection output to record the test IDs in execution order. Build a small diagnostic runner that executes pytest in subprocesses with a selected prefix and then runs the golden test. The subprocess boundary prevents one diagnostic attempt from contaminating the next.

For each prefix, record:

```text
prefix length
prefix last test
exit status
first differing decision index
trace fingerprint
```

The predicate is:

```text
prefix + golden test fails
```

Binary-search the ordered prefix until the smallest triggering prefix is found.

### 3. Bisect candidate state owners

After identifying the smallest prefix, classify the final test and inspect only its reachable shared state:

- `AMTEngine` and `_SEED_CACHE`
- `SessionRisk` date/storage state
- `TimesFMEngine` model and price buffers
- `LLMAdvisor._MODEL_CACHE`
- `HotPathSubscriber` and tracer state
- `os.environ` mutations
- module-level singleton registries
- global random/time state

Run the golden test after each candidate test alone and after each candidate plus the smallest prefix. A candidate is causal only if it reproduces the mismatch in a fresh subprocess.

### 4. Add a failing regression test at the public seam

Do not test private globals directly as the final regression. Add a public-flow test that runs:

```text
candidate setup → QuantEngine public run() → DecisionProduced trace
```

and asserts the trace is identical to a fresh run. Diagnostics may inspect internals, but the retained test must observe the engine/event boundary.

### 5. Fix ownership, not symptoms

Apply the smallest fix according to the proven owner:

- Cache: add explicit lifecycle/reset or scope cache by immutable session identity.
- Persistence: inject memory-only storage into tests and reset through the owning risk boundary.
- Environment: use a fixture that restores all affected variables and global caches.
- Randomness/time: inject deterministic clock/random source; do not patch expected output.
- Event subscribers: make subscription idempotent per bus and lifecycle-bound.

Do not add a blanket `autouse` reset fixture before identifying the owner.

### 6. Validation gates

The fix is accepted only if:

1. The new regression fails before the fix.
2. It passes after the fix.
3. The golden file passes five isolated runs.
4. The golden file passes after the previously triggering prefix.
5. The full quant suite passes twice in the isolated dependency environment.
6. Backend, frontend, broker-boundary, chaos, and replay suites remain green.
7. No snapshot is changed unless an intentional behavior change is independently reviewed.
8. No production global reset is introduced solely for tests.

## Stop conditions

Stop and report rather than patch if:

- The failure cannot be reproduced in a fresh subprocess.
- The minimal trigger changes between runs.
- The mismatch is caused by an intentional uncommitted user change.
- Fixing the issue requires changing trading behavior rather than lifecycle ownership.
- Full-suite execution exceeds the available validation budget without narrowing the trigger.

## Expected deliverables

- Root-cause note with the minimal triggering test/prefix.
- One regression test at the engine/event seam.
- One minimal ownership-correct fix.
- Repeated full-suite evidence.
- Updated architecture risk register if the owner is production state rather than test-only state.
