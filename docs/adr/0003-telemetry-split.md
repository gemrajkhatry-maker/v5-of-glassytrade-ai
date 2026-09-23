# ADR-0003: Telemetry Split Dispositions

Date: 2026-09-03 (Plan E Task 4, Half B). Status: **Accepted**.

## Context

The audit program left four telemetry items open: whether the two metrics
sinks should merge, which logging API new code should use, whether
`shared/conversion.py` still earns its keep next to `shared.money`, and
whether the frontend `NETWORK_CONFIG` mirror should be generated. Plan D
pinned the sink contracts; this record locks the dispositions.

## Decision

1. **Metrics: KEEP SPLIT.** Originally `backend/app/infrastructure/metrics.py`
   (`MetricsCollector`, a thread-safe singleton emitting a business-KPI dict
   for `GET /api/v1/metrics`: ticks, signals, PnL, cache hit-rate, regime
   changes, uptime) and `backend/app/core/metrics.py` (`MetricsRegistry`,
   Prometheus counters/gauges/histograms for infra observability) served
   different consumers with different shapes. **Amendment 2026-09-23
   (predeploy remediation Task 9 / D7):** `MetricsCollector` /
   `infrastructure/metrics.py` was deleted (zero live importers after dead
   counters were removed); business-KPI values that remain are served by
   `MetricsRegistry` via `observability.py` (`/api/metrics/summary`) with
   canary increments (ticks/decisions/trades). The **split disposition
   stands**: do not merge a second sink; if a business-KPI dict shape is
   reintroduced, add it as a separate consumer of `MetricsRegistry`, not a
   resurrected singleton. `shared/conversion.py` already deleted (item 3).
   Close.
2. **Logging: facade for new code, grandfather the rest.** New code uses the
   facades — `brokers/broker/logging.get_logger` (named + correlation) and
   `backend/app/core/logging.get_logger` (correlation-ID adapter) — never raw
   `logging.getLogger(__name__)`, and never bare `except Exception`. The ~245
   existing `logging.getLogger` call sites stay as-is (no mass migration —
   YAGNI; a bulk rewrite risks log-pipeline regressions for zero behavior
   gain). Enforced for Plan A–E files only by
   `test_new_code_logging_hygiene` in
   `tests/architecture/test_no_layer_bypass.py` (hardcoded file list —
   explicit > clever). Close.
3. **`shared/conversion.py`: DELETE.** Inventory 2026-09-03: exactly one
   live non-test importer —
   `backend/app/infrastructure/storage/database.py`
   (`to_float`, 13 single-arg call sites). `conversion.to_float` is
   behaviorally identical to `shared.money.to_float` for those calls, so the
   import was re-pointed (trivial same-name swap, zero logic change) and the
   file deleted. `to_decimal`/`safe_decimal_operation` had zero importers;
   `decimal_add/subtract/multiply/divide` had zero importers. Close.
4. **`NETWORK_CONFIG`: KEEP MIRROR.** `frontend/config.ts`
   (`reconnectDelaySeconds`, `maxReconnectAttempts`, `pingIntervalSeconds`,
   `configTimeoutMs`, `maxRafQueueSize`) mirrors `shared/net_policy.py`
   conceptually, not 1:1 (comment at the site says so). Generating it from
   the backend would add a startup fetch dependency to a pure renderer for
   values that change rarely — YAGNI rejected codegen. On change: update
   both, keep the comment. Close.

## Consequences

- New crossings (a third metrics sink, raw `getLogger` in new modules) fail
  review via the ratchet tests.
- If a future product decision unifies observability backends, revisit (1)
  explicitly — the contracts make the seam visible.
