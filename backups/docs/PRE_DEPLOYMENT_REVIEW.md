# PRE-DEPLOYMENT SYSTEM REVIEW
## Principal Engineer Assessment — GlassyTrade AI
### Date: 2026-03-16

---

## EXECUTIVE SUMMARY

**Deployment Status: CONDITIONALLY APPROVED**

The system demonstrates solid AMT-aligned trading logic with proper gate enforcement. However, critical architectural issues must be resolved before production deployment.

**Critical Issues Found:**
1. Duplicate execution paths (pipeline + legacy handler)
2. Pre-LLM filter in wrong location (should be in gate, not handler)
3. Some dead code paths

**Score: 75/100** — Deployable after architectural cleanup

---

## STEP 1: MODULE MAP

### Active Modules (Production Path):

```
┌─────────────────────────────────────────────────────────────────┐
│  PRIMARY PIPELINE (Active)                                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ingest.py (224 lines)                                          │
│    └── Dhan WS/REST → RawTickMessage                           │
│                                                                 │
│  candle.py (340 lines)                                          │
│    └── RawTick → CandleMessage (5m OHLCV + delta)              │
│                                                                 │
│  analysis.py (257 lines)                                        │
│    └── Candle → AMTResultPayload (wraps AMTHandler)            │
│                                                                 │
│  gate.py (485 lines) ✅ PRIMARY GATE                            │
│    └── AMT → SignalGatePayload (3-align gate)                  │
│    └── Session enforcement                                      │
│    └── CVD hard block                                           │
│                                                                 │
│  llm_entry.py (395 lines)                                       │
│    └── Gate → LLMDecisionPayload (LLM inference)               │
│                                                                 │
│  overseer.py (245 lines)                                        │
│    └── LLMDecision → OverseerDecision (position mgmt)          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Domain Modules (Used by Pipeline):

```
┌─────────────────────────────────────────────────────────────────┐
│  CORE AMT (AUTHORITATIVE)                                       │
├─────────────────────────────────────────────────────────────────┤
│  amt_analyzer.py (1745 lines)     → VP + market state           │
│  entry_gate.py (877 lines)        → Gate logic + signal build   │
│  cvd_tracker.py (115 lines)       → CVD slope + divergence      │
│  profile_classifier.py (139 lines) → P/b/D/B shape detection    │
│  market_structure_classifier.py   → 5-state classifier           │
│  footprint_analyzer.py (341 lines) → Order flow analysis         │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  RISK & SESSION (AUTHORITATIVE)                                 │
├─────────────────────────────────────────────────────────────────┤
│  session_context.py (405 lines)   → Session phases              │
│  session_risk_manager.py (167)    → Risk tiers + circuit breaker │
│  trade_manager.py (1332 lines)    → Mechanical exits             │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  LLM/ML (AUTHORITATIVE)                                         │
├─────────────────────────────────────────────────────────────────┤
│  prompt_builder.py (525 lines)    → AMT narrative prompt        │
│  llm_contract.py (47 lines)       → JSON schema contract        │
└─────────────────────────────────────────────────────────────────┘
```

### Orchestration:

```
┌─────────────────────────────────────────────────────────────────┐
│  ORCHESTRATION LAYER                                            │
├─────────────────────────────────────────────────────────────────┤
│  engine.py              → Main trading engine                   │
│  trading_session.py     → Session lifecycle, signal routing     │
│  dependencies.py        → Service wiring                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## STEP 2: EXECUTION FLOW VALIDATION

### Full Execution Trace:

```
1. Dhan WS sends tick for "NATURALGAS 24 MAR 290 PUT"
   ↓
2. ingest.py: DhanWsIngestor receives tick
   → Creates RawTickPayload(ltp=17.30, volume=500, ...)
   → Sends RawTickMessage to "raw_ticks" channel
   ↓
3. candle.py: CandleBuilderProcessor
   → Aggregates ticks into 5m OHLCV candles
   → When candle closes, sends CandleMessage to "candles" channel
   ↓
4. analysis.py: AMTAnalysisProcessor
   → Calls AMTHandler.analyze(ohlc_list)
   → Computes: VP, POC, VAH, VAL, LVNs, CVD, market state
   → Sends AMTResultPayload to "amt_results" channel
   ↓
5. gate.py: SignalGateProcessor
   → Gets session context (NSE_AFTERNOON = allows entry)
   → Checks CVD hard block (|slope| < 100 = PASS)
   → Calls three_align_check():
     • Market State: BALANCED ✓
     • Location: price near VAL ✓
     • Aggression: volume impulse + delta ✓
   → Sends SignalGatePayload(passed=True) to "signal_gates" channel
   ↓
6. llm_entry.py: LLMEntryProcessor
   → Gate passed, build prompt with full AMT context
   → Call LLM inference (Qwen-MLX)
   → LLM returns: {"direction": "LONG", "confidence": "Medium"}
   → Sends LLMDecisionPayload to "llm_decisions" channel
   ↓
7. overseer.py: OverseerProcessor
   → Decision is LONG, check if position management needed
   → Sends OverseerDecisionPayload downstream
   ↓
8. Execution layer: Create order, manage position mechanically
```

### Data Contract Validation:

| Stage | Input Type | Output Type | Validated |
|-------|-----------|-------------|-----------|
| ingest | WS tick | RawTickMessage | ✅ |
| candle | RawTick | CandleMessage | ✅ |
| analysis | Candle | AMTResultMessage | ✅ |
| gate | AMTResult | SignalGateMessage | ✅ |
| llm_entry | SignalGate | LLMDecisionMessage | ✅ |
| overseer | LLMDecision | OverseerDecisionMessage | ✅ |

---

## STEP 3: SHOTGUN SURGERY DETECTION

### Single-Change-Impacts-Multiple-Files:

| Change | Files Affected | Root Cause |
|--------|---------------|------------|
| Gate logic | `gate.py`, `entry_gate.py`, `llm_entry_handler.py` | Duplicate paths |
| Session rules | `gate.py`, `llm_entry_handler.py`, `session_context.py` | Legacy handler duplication |
| Pre-LLM filter | `llm_entry_handler.py` (should be in `gate.py`) | Wrong ownership |
| Market state | `amt_analyzer.py`, `market_structure_classifier.py`, `regime_detector.py` | Overlapping concerns |

### Design Fix:

```
BEFORE: Gate logic in 3 places
AFTER:  Gate logic ONLY in gate.py → entry_gate.py

BEFORE: Pre-LLM filter in llm_entry_handler.py  
AFTER:  Pre-LLM filter in gate.py (it's a gate function)

BEFORE: Two execution paths (pipeline + legacy)
AFTER:  Single pipeline path (deprecate legacy)
```

---

## STEP 4: CODE ELIMINATION PASS

### Code to DELETE:

| File | Reason |
|------|--------|
| `llm_entry_handler.py` | Legacy path, duplicates pipeline logic |
| `regime_detector.py` | Duplicates `market_structure_classifier.py` |
| `learning_engine.py` | Not in active trading path |
| `prediction_engine.py` | Replaced by pipeline architecture |
| `rl/` directory | RL training, not live trading |

### Code to MERGE:

| From | Into | Reason |
|------|------|--------|
| `llm_entry_handler.py` pre-LLM filter | `gate.py` | Gate function, not handler |
| `entry_gate.py` gate checks | `gate.py` | Single gate authority |
| `regime_detector.py` logic | `market_structure_classifier.py` | Single state detector |

### Code to KEEP:

| File | Reason |
|------|--------|
| `amt_analyzer.py` | Core AMT logic |
| `entry_gate.py` | Signal building + SL logic |
| `cvd_tracker.py` | CVD tracking |
| `trade_manager.py` | Mechanical exits |
| `session_context.py` | Session phases |
| `session_risk_manager.py` | Risk management |
| `prompt_builder.py` | LLM prompts |
| `gate.py` | Primary gate (now authoritative) |
| `llm_entry.py` | LLM inference |
| `option_scanner.py` | Contract selection |

---

## STEP 5: INTEGRATION & BOUNDARY REVIEW

### Critical Integration Points:

```
1. Dhan → ingest.py
   Input: WebSocket tick data
   Output: RawTickMessage
   Failure: REST polling fallback ✅
   Risk: Rate limiting (HTTP 429) — handled ✅

2. analysis.py → AMTHandler
   Input: OHLC list
   Output: AMTResult
   Failure: Returns empty result ✅
   Risk: VP rebuild on range overflow — handled ✅

3. gate.py → entry_gate.three_align_check()
   Input: AMTResult + tick
   Output: (gate_passed, confirmation, is_second_drive)
   Failure: Returns (False, False, False) ✅
   Risk: None — pure function ✅

4. llm_entry.py → LLM inference
   Input: SignalGatePayload (now with full AMT context)
   Output: LLMDecisionPayload
   Failure: Timeout → FLAT ✅
   Risk: LLM hallucination — mitigated by gates ✅
```

### Silent Failure Risks:

| Risk | Mitigation | Status |
|------|-----------|--------|
| LLM returns invalid JSON | Keyword fallback parser | ✅ |
| LLM timeout | FLAT decision emitted | ✅ |
| VP range overflow | Full rebuild triggered | ✅ |
| Session boundary | VP reset on new day | ✅ |
| Circuit breaker | 3-loss halt | ✅ |

---

## STEP 6: TEST & DEPLOY READINESS

### Critical Tests Required:

```
1. Pipeline Tests (MUST PASS)
   ✅ test_candle_builder.py — OHLCV construction
   ✅ test_analysis_processors.py — AMT analysis
   ✅ test_llm_processors.py — LLM inference
   ✅ test_gate_processor — Gate logic

2. Domain Tests (MUST PASS)
   ✅ test_entry_gate.py — Three-align gate
   ✅ test_amt_analyzer.py — VP construction
   ✅ test_trade_manager.py — Exit logic

3. Integration Tests (SHOULD PASS)
   ⚠️ test_e2e_trading_lifecycle.py — Full pipeline
   ⚠️ test_trading_pipeline.py — End-to-end
```

### Current Test Status:
```
Pipeline tests: 61/61 PASSING ✅
Fabio alignment tests: 16/16 PASSING ✅
Validation tests: 13/13 PASSING ✅
Total: 90/90 PASSING ✅
```

### Observable State Transitions:

```
✅ Market state changes logged (BALANCED ↔ IMBALANCED)
✅ Gate decisions logged (passed/blocked + reason)
✅ LLM decisions logged (direction + confidence)
✅ Circuit breaker state logged (halted/resumed)
✅ Session phase transitions logged
```

---

## FINAL RECOMMENDATIONS

### Before Deployment:

1. **CRITICAL**: Remove `llm_entry_handler.py` duplicate logic
   - Move pre-LLM filter to `gate.py`
   - Use pipeline path exclusively

2. **IMPORTANT**: Consolidate regime detection
   - Merge `regime_detector.py` into `market_structure_classifier.py`

3. **NICE-TO-HAVE**: Clean dead code
   - Move `learning_engine.py`, `prediction_engine.py` to `/archive`
   - Move `rl/` directory to `/archive`

### Architecture After Cleanup:

```
Clean Pipeline (Single Path):
┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐
│ ingest  │──►│ candle  │──►│analysis │──►│  gate   │──►│llm_entry│
└─────────┘   └─────────┘   └─────────┘   └─────────┘   └─────────┘
                                        │
                                        ├── Pre-LLM filter (HERE)
                                        ├── Session enforcement
                                        ├── CVD hard block
                                        └── 3-align gate

Single Gate Authority: gate.py → entry_gate.py
Single State Detector: market_structure_classifier.py
Single Exit Manager: trade_manager.py
```

---

## VERDICT

**Score: 75/100** — CONDITIONALLY APPROVED

**Strengths:**
- Core AMT logic is correct and well-tested
- Gate enforcement is comprehensive
- LLM integration is explainable
- Risk management is institutional-grade

**Weaknesses:**
- Duplicate execution paths (pipeline + legacy)
- Pre-LLM filter in wrong location
- Some dead code paths

**Recommendation:** Deploy after Step 4 cleanup (estimated 2-3 hours of work).

---

*Reviewed by: Principal Engineer*
*Date: 2026-03-16*
