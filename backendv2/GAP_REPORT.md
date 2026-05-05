# BackendV2 Gap Report — Feature vs Backend

## Phase Status

| Phase | Status | Files | Tests |
|-------|--------|-------|-------|
| 0 — Foundation | ✅ COMPLETE | 20/20 | ~50 |
| 1 — Domain Models | ✅ COMPLETE | 6/6 | ~50 |
| 2 — AMT Pipeline | ✅ COMPLETE | 16/16 | ~80 |
| 3 — Trade Management | ⚠️ PARTIAL | 2/9 | ~15 |
| 4 — Risk Domain | ⚠️ PARTIAL | 1/6 | ~5 |
| 5 — App Orchestration | ❌ MISSING | 3/20 | ~20 |
| 6 — Infrastructure | ⚠️ PARTIAL | 6/15 | ~30 |
| 7 — API Layer | ⚠️ PARTIAL | 2/10 | ~5 |
| 8 — AI/ML | ❌ MISSING | 0/20 | 0 |

## Detailed Gap — What's Missing Per Phase

### Phase 3: Trade Management (2/9 files, 35%)

| File | Backend | Status | Impact |
|------|---------|--------|--------|
| exit_engine.py | 519L | ❌ | No exit orchestration |
| trail_engine.py | 460L | ❌ | No trailing stops |
| partition_exit_manager.py | 231L | ❌ | No P1/P2/P3 exits |
| pyramid_manager.py | 110L | ❌ | No pyramid adds |
| position_sizer.py | 136L | ❌ | No position sizing |
| structural_stop_engine.py | 335L | ❌ | No structural SL |
| loss_tracker.py | 528L | ❌ | No daily loss tracking |
| exit_models.py | — | ✅ | Done |
| exit_rules.py | 585L | ✅ | Basic done |

### Phase 4: Risk Domain (1/6 files, 17%)

| File | Backend | Status | Impact |
|------|---------|--------|--------|
| risk_manager.py | 257L | ❌ | No daily drawdown/kill switch |
| risk_tier_engine.py | 285L | ❌ | No tiered risk |
| flash_crash_protector.py | 123L | ❌ | No flash crash protection |
| self_healing.py | 216L | ❌ | No order rejection recovery |
| position_reconciliation.py | 163L | ❌ | No position sync |
| risk_sizing_engine.py | 668L | ✅ | Basic done |

### Phase 5: App Orchestration (3/23 files, 13%)

| File | Backend | Status | Impact |
|------|---------|--------|--------|
| trading_session.py | 868L | ❌ | **CORE ORCHESTRATOR** |
| session_state_manager.py | 444L | ❌ | No per-symbol state |
| session_cache.py | 360L | ❌ | No cached analysis |
| entry_coordinator.py | 295L | ❌ | No entry gating |
| exit_coordinator.py | 237L | ❌ | No exit coordination |
| signal_coordinator.py | 98L | ❌ | No signal coordination |
| state_broadcaster.py | 353L | ❌ | No frontend broadcast |
| state_snapshot_builder.py | 215L | ❌ | No state snapshots |
| tick_processor.py | 327L | ❌ | No tick pipeline |
| trade_journal.py | 907L | ❌ | No trade recording |
| engine_lifecycle.py | 492L | ❌ | No startup/shutdown |
| phase_manager.py | 175L | ❌ | No session phases |
| gap_detector.py | 340L | ❌ | No gap detection |
| update_tick_handler.py | — | ✅ | Done |
| evaluate_entry_handler.py | — | ✅ | Done |
| check_exit_handler.py | — | ✅ | Done |

### Phase 6: Infrastructure (6/17 files, 35%)

| File | Backend | Status | Impact |
|------|---------|--------|--------|
| database.py | 953L | ❌ | **MAIN PERSISTENCE** |
| mlx_inference_adapter.py | 750L | ❌ | No MLX inference |
| gguf_inference_adapter.py | 154L | ❌ | No GGUF inference |
| lgbm_probability_adapter.py | 166L | ❌ | No LGBM probability |
| paper_broker.py | 208L | ❌ | No paper trading |
| mcx_broker.py | ~200L | ❌ | No MCX broker |
| delta_profile_adapter.py | 142L | ❌ | No delta profile |
| npoc_adapter.py | 64L | ❌ | No NPOC adapter |
| null_notification_adapter.py | 16L | ❌ | Missing |
| serialization/schemas.py | ~300L | ❌ | No API schemas |
| config/ (YAML) | 6 files | ❌ | No config files |
| dhan_adapter.py | 507L | ✅ | Basic done |
| postgresql_adapter.py | — | ✅ | Done |
| infrastructure_adapters.py | — | ✅ | Done |
| redis_cache.py | — | ✅ | Done |
| alert_manager.py | — | ✅ | Done |
| event_bus.py (infra) | — | ✅ | Done |

### Phase 7: API Layer (2/10 files, 20%)

| File | Backend | Status | Impact |
|------|---------|--------|--------|
| ai.py | 271L | ❌ | No AI endpoints |
| health.py | 388L | ❌ | No health endpoints |
| market.py | 55L | ❌ | No market endpoints |
| trading.py | 103L | ❌ | No trading endpoints |
| rl.py | 201L | ❌ | No RL endpoints |
| alerts.py | 35L | ❌ | No alert endpoints |
| analysis.py | 63L | ❌ | No analysis endpoints |
| observability.py | 33L | ❌ | No observability |
| gameloop.py | 396L | ❌ | No WebSocket/SSE |
| main.py + metrics.py | — | ✅ | Basic done |

### Phase 8: AI/ML (0/20+ files, 0%)

| File | Backend | Status | Impact |
|------|---------|--------|--------|
| llm_entry_handler.py | 1208L | ❌ | **LLM ENTRY** |
| llm_overseer_handler.py | 541L | ❌ | No overseer |
| llm_decision_processor.py | 143L | ❌ | No decision processing |
| llm_worker.py | 54L | ❌ | No LLM worker |
| post_trade_analyst.py | 261L | ❌ | No post-trade analysis |
| entry_gate_coordinator.py | 233L | ❌ | No entry gates |
| prompt_builder.py | 807L | ❌ | No prompt building |
| generative_ai_service.py | 98L | ❌ | No AI service |
| mlx_compute.py | 301L | ❌ | No MLX compute |
| agent_pipeline.py | 989L | ❌ | No probability agent |
| + 10 more | ~2000L | ❌ | All missing |

## Critical Path to Trading

Can't trade without these, in order:

1. **Session orchestrator** (Phase 5) — ties everything together
2. **Session state manager** (Phase 5) — per-symbol state
3. **Tick processor** (Phase 5) — processes market data
4. **Exit engine** (Phase 3) — manages position exits
5. **Exit coordinator** (Phase 5) — exit orchestration
6. **Risk manager** (Phase 4) — drawdown/kill switch
7. **Entry coordinator** (Phase 5) — entry gating
8. **Position sizer** (Phase 3) — position sizing
9. **SQLite storage** (Phase 6) — persistence
10. **API routers** (Phase 7) — external interface
11. **L4 handlers** (Phase 5) — entry/exit/roWire
12. **LLM handlers** (Phase 8) — LLM integration
13. **MLX adapter** (Phase 6) — Apple Silicon inference
14. **Paper broker** (Phase 6) — simulation
15. **Dhan adapter** (Phase 6) — live trading

## Stats

| Metric | Backend | BackendV2 | Parity |
|--------|---------|-----------|--------|
| Source files | ~273 | 55 | 20% |
| Test files | 176 | 18 | 10% |
| API endpoints | ~50+ | ~5 | 10% |
| AMT services | 50+ | 16 | 32% |
| Domain models | 20+ | 26 | 130% ✅ |
| Infrastructure | 17 | 6 | 35% |
| Handlers | 15 | 3 | 20% |
| Config files | 12+ | 0 | 0% |
| DB persistence | 1 (953L) | 0 | 0% |

## Biggest Gaps (by impact)

1. **database.py** (953L) — no persistence at all
2. **trading_session.py** (868L) — no orchestrator
3. **llm_entry_handler.py** (1208L) — no LLM entry
4. **agent_pipeline.py** (989L) — no probability agent
5. **trade_journal.py** (907L) — no trade recording
6. **prompt_builder.py** (807L) — no prompts
7. **session_state_manager.py** (444L) — no per-symbol state
8. **exit_engine.py** (519L) — no exit management
9. **risk_manager.py** (257L) — no risk management
10. **API routers** (8 files) — no external interface
11. **Config system** (12 files) — no configuration
12. **MLX inference** (750L) — no ML inference
13. **paper_broker.py** (208L) — no simulation
14. **trail_engine.py** (460L) — no trailing stops
15. **SQLite storage** — no DB persistence
