# WS-METRICS — Migration Report

**Status: DONE**

Worktree: `/Users/apple/Documents/wt-ws-metrics` (branch `migration/ws-metrics`).
Commit: `a53b720` — `refactor(backend): metrics registry uses prometheus_client`

## What changed

- **`backend/app/core/metrics.py`** — replaced the hand-rolled registry with a thin wrapper over `prometheus_client` (v0.26.0). Public surface preserved exactly: `metrics` singleton, `MetricsRegistry` (`counter`/`histogram`/`gauge`/`to_prometheus`/`_metrics`/`_metric_key`), wrapper classes `Metric`/`Counter`/`Histogram`/`Gauge`, and the module-level convenience objects (`ticks_processed`, `amt_duration`, `signals_generated`, `errors_total`, `active_positions`). Consumers (`app/api/routers/observability.py`, `app/core/startup_telemetry.py`) were NOT modified.
- **`backend/requirements.txt`** — added `prometheus_client>=0.26.0`.
- **`backend/tests/unit/core/test_metrics.py`** — new, 16 tests covering counter/gauge/histogram semantics, label handling, the `_metrics` dict keys, `to_prometheus()` text output, and the public module surface.

## Design notes

- Each metric family gets a private `CollectorRegistry`, so same-name collectors with different label sets (e.g. `startup_crash_count_total` created both unlabeled and with `category=`) coexist exactly like the old code, and nothing pollutes the global `REGISTRY`.
- Histogram buckets explicitly set to the old boundaries `(0.005 … 10, +Inf)` — not the prometheus_client defaults.
- `disable_created_metrics()` called at import so the exposition surface matches the old output (no `_created` series).
- `.value`/`.count`/`.sum_val` read via the public `collect()` API (0.26.0 removed the old public `.value`/`.count`/`.sum` properties).
- Label values are now quoted in exposition (e.g. `{category="config"}`) — the old output wrote them unquoted; the new form is valid Prometheus text format.

## Verification (amt_313 interpreter)

- `python -m pytest tests/unit -q --tb=short --continue-on-collection-errors` (from `backend/`): **1327 passed, 64 skipped, 0 failed, 0 errors** (new file: 16 passed).
- `PYTHONPATH=.../backend python -c "import app.main"` (from repo root): **SMOKE OK**.

## Concerns

1. `startup_crash_count_total` renders as two separate `# HELP`/`# TYPE` blocks (unlabeled `0.0` plus per-`category` samples) — same as before, harmless, but slightly non-idiomatic Prometheus. Left as-is to avoid touching consumers.
2. `disable_created_metrics()` is a process-global prometheus_client switch; currently the only consumer of the library, so safe.
3. Wrapper value reads rely on `collect()`, which allocates; only used on the `/metrics/summary` endpoint and tests, not hot paths.
