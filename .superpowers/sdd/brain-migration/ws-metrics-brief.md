# WS-METRICS — Swap hand-rolled metrics registry for prometheus_client

**Worktree:** `/Users/apple/Documents/wt-ws-metrics` (branch `migration/ws-metrics`). Work ONLY there.

**Context:** PT-DUP deferred swapping `backend/app/core/metrics.py`'s hand-rolled Prometheus registry to `prometheus_client` because the dep wasn't installed. It IS now installed in the `amt_313` env (v0.26.0). Complete the swap.

**Task:**
1. Read `backend/app/core/metrics.py` (hand-rolled registry: counters, gauges, histograms, `generate_latest`-style rendering). Read its consumers (`grep -rn "core.metrics\|from app.core.metrics\|metrics\." backend/app --include="*.py"`) to preserve the PUBLIC API exactly (the consumers must not change).
2. Reimplement the same public surface on top of `prometheus_client` (`Counter`, `Gauge`, `Histogram`, `generate_latest`, `CONTENT_TYPE_LATEST`). Preserve metric names/labels so any Prometheus scrapes keep working. Keep the module's public function/class names identical.
3. `prometheus_client` is now a runtime dependency — add it to `backend/requirements.txt` (and note it).
4. Update/add tests for the metrics module (test the counters/gauges render into the text format via `generate_latest`).

**Verify:** `/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/unit -q --tb=short --continue-on-collection-errors` (worktree root, from its `backend/`) → 0 failed / 0 errors. Plus `PYTHONPATH=/Users/apple/Documents/wt-ws-metrics/backend /Users/apple/miniconda3/envs/amt_313/bin/python -c "import app.main"` smoke (run from repo root so `quant` resolves).

**Commits:** `refactor(backend): metrics registry uses prometheus_client`.

**Report:** `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/ws-metrics-report.md`. Reply: status, commits, test counts, concerns.
