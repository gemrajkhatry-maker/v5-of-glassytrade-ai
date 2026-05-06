# BackendV2 Deployment Hardening Checklist

## 1) Containerization

TODO:
- [ ] Add/verify `Dockerfile` for backendv2 service
- [ ] Add compose file(s) for app + storage + observability
- [ ] Pin base images and runtime dependencies
- [ ] Add multi-stage build and non-root runtime user

## 2) Security and Secrets

TODO:
- [ ] Remove hard-coded credentials from code
- [ ] Integrate secret manager (or environment-injected secret layer)
- [ ] Validate `.env` variable validation and masking in logs
- [ ] Confirm TLS termination and strict CORS allowlist strategy

## 3) Health, readiness, and startup behavior

TODO:
- [ ] Verify `/health` returns liveness signals in deploy
- [ ] Add readiness checks for required dependencies (DB, broker, feed)
- [ ] Configure startup timeout and circuit-breaker on feed warmup
- [ ] Verify graceful teardown path closes orchestrators and storage handles

## 4) Horizontal scaling and runbook behavior

TODO:
- [ ] Define single-writer/session placement strategy
- [ ] Verify orchestration affinity for symbol-to-runtime mapping
- [ ] Add graceful rolling update/runbook steps
- [ ] Add queue/backpressure handling for tick bursts

## 5) Logs, telemetry, and alerts

TODO:
- [ ] Standardize structured logging and retention policy
- [ ] Export Prometheus metrics endpoints and scrape config
- [ ] Configure alert thresholds for:
  - processing lag
  - prediction failures
  - daily loss / risk halts
  - websocket disconnect rates
- [ ] Wire error budgets and incident notification

## 6) RL lifecycle operations

TODO:
- [ ] Verify model artifact storage versioning and rollback
- [ ] Verify training job parity with live symbol config
- [ ] Validate checkpoint signing/checksum verification
- [ ] Document model promotion and rollback procedure
