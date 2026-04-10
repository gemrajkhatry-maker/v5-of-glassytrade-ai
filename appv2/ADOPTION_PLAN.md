# ADVANCED VERSION ADOPTION PLAN
## appv2 → Full Parity + Improvements over Original Backend

**Date:** 2026-04-09
**Source:** Live analysis of original backend (port 9090) + code audit
**Goal:** Build production-grade v2 that exceeds original backend capabilities

---

## MASTER FEATURE GAP ANALYSIS

Based on live session analysis and code audit of `/Users/apple/Downloads/v5-of-glassytrade-ai/backend/`:

### CRITICAL (Blocks Live Trading)

| # | Feature | Original Backend | appv2 | Impact | Effort |
|---|---------|-----------------|-------|--------|--------|
| 1 | Throttled processing (500ms) | ✅ 500ms throttle per symbol | ❌ None | Performance + correctness | 2h |
| 2 | Underlying futures dual-feed | ✅ Separate aggregation | ⚠️ Router exists, not wired | AMT accuracy on options | 2h |
| 3 | Footprint accumulation | ✅ Full delta-colored profiles | ⚠️ Simplified | Order flow visibility | 3h |
| 4 | Range bar backfill | ✅ Backfills from history | ❌ None | Range bar accuracy | 1h |

### HIGH (Production Quality)

| # | Feature | Original Backend | appv2 | Impact | Effort |
|---|---------|-----------------|-------|--------|--------|
| 5 | Opening type classifier | ✅ Open Drive/Test/Rejection | ❌ None | Entry timing | 2h |
| 6 | Regime detector | ✅ Volatility regimes | ❌ None | Strategy adaptation | 2h |
| 7 | Market structure classifier | ✅ 5-state with hysteresis | ❌ None | State accuracy | 2h |
| 8 | Partition exit manager | ✅ Scale-out management | ❌ None | Position management | 2h |
| 9 | Structural stop engine | ✅ Beyond aggressive prints | ❌ None | SL precision | 2h |
| 10 | Drive decay tracker | ✅ D3+ exhaustion | ⚠️ Basic | Drive awareness | 1h |
| 11 | Latency metrics (p50/p95/p99) | ✅ Tracked per symbol | ❌ None | Performance monitoring | 2h |
| 12 | Gate rejection metrics | ✅ Full tracking | ❌ None | Pipeline diagnostics | 2h |

### MEDIUM (Advanced Features)

| # | Feature | Original Backend | appv2 | Impact | Effort |
|---|---------|-----------------|-------|--------|--------|
| 13 | Playbook guard (3-reject max) | ✅ Per-session | ❌ None | Overtrading prevention | 1h |
| 14 | Session risk tiers | ✅ 5 tiers | ❌ Binary | Dynamic risk mgmt | 2h |
| 15 | Capital ladder tracking | ✅ Cumulative | ❌ None | Position sizing | 1h |
| 16 | Volatility features | ✅ Regime detection | ❌ None | Strategy selection | 2h |
| 17 | One-minute bar engine | ✅ Separate processing | ❌ None | Scalping precision | 3h |
| 18 | State snapshot builder | ✅ For broadcast | ⚠️ Basic | Frontend quality | 1h |
| 19 | Session cache | ✅ Session-level caching | ❌ None | Performance | 1h |
| 20 | Event router | ✅ Delegates handler calls | ❌ None | Code organization | 1h |

### SEPARATE SKILL DOMAIN (Deferred)

| # | Feature | Original Backend | appv2 | Notes |
|---|---------|-----------------|-------|-------|
| 21 | LLM integration | ✅ Qwen-MLX + prompts | ❌ None | Use `/design-trading-strategies` skill |
| 22 | Probability engine | ✅ LightGBM 42 features | ❌ None | Requires model training |
| 23 | RL training loop | ✅ Present | ❌ None | Requires training infrastructure |
| 24 | Pre-candle advisory | ✅ T-60s LLM advisory | ❌ None | LLM-dependent |
| 25 | Overseer handler | ✅ Position monitoring | ❌ None | LLM-dependent |

---

## IMPLEMENTATION PLAN

### Phase 1: Core Pipeline Upgrades (4 hours)
- [ ] 1. Throttle mechanism (500ms per symbol)
- [ ] 2. Footprint accumulator (delta-colored profiles)
- [ ] 3. Range bar backfill from historical data
- [ ] 4. Underlying futures dual-feed wiring

### Phase 2: Advanced AMT Services (6 hours)
- [ ] 5. Opening type classifier
- [ ] 6. Regime detector
- [ ] 7. Market structure classifier (5-state)
- [ ] 10. Drive decay tracker

### Phase 3: Advanced Exit System (6 hours)
- [ ] 8. Partition exit manager (scale-out)
- [ ] 9. Structural stop engine
- [ ] 16. Volatility features

### Phase 4: Metrics & Observability (6 hours)
- [ ] 11. Latency tracker (p50/p95/p99)
- [ ] 12. Gate rejection tracker
- [ ] 13. Playbook guard
- [ ] 18. State snapshot builder

### Phase 5: Risk Tiers & Capital (4 hours)
- [ ] 14. Session risk tiers (5 tiers)
- [ ] 15. Capital ladder
- [ ] 19. Session cache

### Phase 6: Integration & Wiring (4 hours)
- [ ] Wire all services into TradingEngine v2
- [ ] Add comprehensive tests
- [ ] Live verification with market data

**Total Estimated Effort: ~30 hours**

---

## PRIORITY ORDER (Based on Live Impact)

1. **Throttle mechanism** — Without it, appv2 processes every tick which may cause duplicate signals
2. **Footprint accumulator** — Fabio uses this for aggression confirmation
3. **Opening classifier** — Critical for Phase 1 (opening noise) detection
4. **Latency metrics** — Needed to verify system performance
5. **Gate rejection metrics** — Needed to tune the pipeline
6. **Structural stops** — Fabio's SL placement is based on aggressive prints
7. **Partition exit manager** — Fabio scales out at +1R
8. **Session risk tiers** — Dynamic risk adjustment per session conditions

---

## ARCHITECTURAL DECISIONS

### Throttling Pattern
Original backend throttles `process_tick` to 500ms max per symbol. We'll adopt this:
```python
# Per-symbol throttle
if now - last_process < 0.5:
    return  # Skip, too frequent
```

### Footprint Pattern
Original uses `CandleAggregator.update_footprint()` with delta-colored profiles.
We'll build a proper footprint accumulator that tracks bid/ask volume at each price level.

### Dual-Feed Pattern
Original aggregates option ticks AND underlying futures ticks separately, then passes underlying tick to AMT analysis. We already have `UnderlyingRouter` — just need to wire it.

### State Broadcast Pattern
Original uses `StateBroadcaster` with delta compression and generation tracking.
Our `GameStateBroadcaster` already implements this — just needs enhancement.

---

## SUCCESS CRITERIA

| Metric | Target | Verification |
|--------|--------|--------------|
| Latency p50 | < 15ms | Metrics endpoint |
| Latency p95 | < 30ms | Metrics endpoint |
| Tick processing | ≤ 2 per second per symbol | Throttle verification |
| Gate rejection rate | Tracked and visible | Metrics endpoint |
| Footprint accuracy | Matches original backend | Side-by-side comparison |
| Test coverage | > 90% for new services | pytest --cov |
| Live data verification | Processes real ticks during market hours | Live session |

---

*Plan prepared from live analysis of original backend running on port 9090*
