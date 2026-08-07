# WS-PT-DUP — Ponytail Audit: Dedup + Stdlib Swaps

**Worktree:** `/Users/apple/Documents/wt-pt-dup` (branch `migration/pt-dup`)
**Status:** COMPLETE — 3/4 tasks done, 1 reported (metrics left as-is)

## 1. async_boundary dedup — DONE
`backend/app/core/async_boundary.py` was byte-identical (`diff` clean) to
`quant/contracts/sync_boundary.py`; it defined no extra functions. Replaced with a
thin re-export:

```python
from quant.contracts.sync_boundary import *  # noqa: F401,F403
```

All 22 live consumers (`app.api.routers.*`, `app.application.*`, `app.domain.ops.*`,
`app.main.py`) import `ensure_sync_adapter_result` / `ensure_async_adapter_result`
by name and resolve through the re-export unchanged.

## 2. LLMCircuitBreaker → shared.resilience.CircuitBreaker — DONE
`backend/app/core/llm_circuit_breaker.py` re-implemented the breaker pattern
internally. Rewritten to delegate state/transition logic to
`shared.resilience.CircuitBreaker`, preserving the public API and all tests:

- Kept local `CircuitState(Enum)` and mapped `state` via `CircuitState(shared.value)`.
- Passed `success_threshold=1` to the shared breaker so a single success re-closes
  from HALF_OPEN — matches the historical one-success-close semantics (shared default
  of 3 would break `test_closes_on_success_from_half_open`).
- `should_allow_call()` → `shared.can_execute()` (identical CLOSED/HALF_OPEN allow logic).
- Shared breaker lacks `total_calls` / `total_failures` / `total_fallbacks`, so those
  metrics are tracked locally under a `threading.Lock` and merged in `get_metrics()`
  (preserves `failure_rate`). `record_failure(error=None)` accepts the error arg
  production callers pass (`llm_entry_handler.py`).
- `get_fallback_decision()` body kept verbatim (LLM-specific).

Production consumer `llm_entry_handler.py` untouched.

## 3. generative_ai OrderedDict+hashlib cache → functools.lru_cache — DONE
`quant/inference/generative_ai.py` hand-rolled an `OrderedDict` LRU keyed on
`hashlib.md5(prompt)` with `_CACHE_SIZE = 8`. Replaced with a per-instance
`lru_cache(maxsize=8)` wrapper:

```python
self._analyze_cached = lru_cache(maxsize=self._CACHE_SIZE)(self._analyze_uncached)
```

Semantics preserved:
- **LRU eviction, size 8** — identical.
- **Key** — prompt-only (replaces md5 with the raw string; no hash-collision risk).
  `market_state`/`aggression` are baked into `build_entry_prompt()`, so re-deriving
  them from `market_data` on a hit is value-identical. Keying only on the prompt also
  avoids `lru_cache` TypeError on unhashable `market_state`/`aggression` values.
- **Exceptions NOT cached** — the `try/except` lives in `analyze_market` outside the
  cached function, so failures still re-attempt the LLM (original skipped caching on
  the exception path).
- **Per-instance cache** — wrapper created in `__init__`, so services with different
  instructions/adapters don't share entries (original was per-instance too).
- `None`-response FLAT fallback still cached (as before).

## 4. metrics.py prometheus swap — REPORTED, NOT CHANGED
`backend/app/core/metrics.py` hand-rolls a Prometheus-style registry. `prometheus_client`
is **NOT installed** in `/Users/apple/miniconda3/envs/amt_313`:

```
ModuleNotFoundError: No module named 'prometheus_client'
```

Per instructions, left as-is; no dependency added. Swap deferred until the dep is
available.

## Verification

- `pytest tests/quant -q --tb=short` (worktree root): **1371 passed, 30 skipped, 0 failed, 0 errors**
- `cd backend && pytest tests/unit -q --tb=short --continue-on-collection-errors`:
  **1323 passed, 64 skipped, 0 failed, 0 errors**
- Focused: `tests/unit/core/test_llm_circuit_breaker.py` + `tests/unit/domain/test_generative_ai_service.py`
  → 43 passed; `tests/quant/inference` + `tests/quant/contracts` → 209 passed, 18 skipped.
- 1 pre-existing `RuntimeWarning` (coroutine never awaited) in `test_sync_boundary.py`,
  unrelated to these changes.

## Commits (branch `migration/pt-dup`)

| Commit | Message |
|---|---|
| `c75df93` | refactor(backend): async_boundary re-exports sync_boundary |
| `debd521` | refactor(backend): LLMCircuitBreaker delegates to shared CircuitBreaker |
| `276af85` | refactor(quant): generative_ai cache uses functools.lru_cache |

`.superpowers/`, `docs/superpowers/plans/`, `docs/*.md` were not committed.

## Concerns

1. **Metrics swap deferred** — `core/metrics.py` stays hand-rolled until
   `prometheus_client` is added to the env (do NOT add the dep per instructions).
2. **Per-instance lru_cache cycle** — `self._analyze_cached` wrapper → bound method →
   `self` is a reference cycle (GC-collectable, no `__del__`). Acceptable; services are
   long-lived singletons in the composition root.
3. **Cross-instance metric counters** — LLMCircuitBreaker's `total_calls`/`total_failures`
   are wrapper-local; the shared breaker's internal counters (`failure_count`,
   `last_failure_time`) are per-instance. No cross-instance sharing introduced.
4. **`import *` re-export** — re-exports `inspect`, `Any`, `Callable` too (no `__all__`
   in `sync_boundary`). Harmless; `# noqa` suppresses F401/F403.
