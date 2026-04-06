# DEEP SYSTEM AUDIT — GlassyTrade AI
## Principal Engineer Code Review
### Date: 2026-03-16 | Files: 126 Python files | Lines: 29,551

---

## 1. ARCHITECTURE AUDIT

### 1.1 Execution Paths — CRITICAL FINDING

```
TWO PARALLEL SYSTEMS DETECTED:
┌─────────────────────────────────────────────────────────────────┐
│  PATH A: ACTIVE (trading_session.py → llm_entry_handler.py)    │
│  • This is what actually runs                                   │
│  • 1,636 + 1,245 = 2,881 lines of active code                  │
│  • Direct function calls, no pipeline abstraction               │
│                                                                 │
│  PATH B: UNUSED (pipeline/processors/)                          │
│  • NiFi-style pipeline architecture                             │
│  • 1,946 lines of UNUSED code                                   │
│  • Never wired into the main engine                             │
│  • SHOULD BE REMOVED OR DOCUMENTED AS FUTURE                    │
└─────────────────────────────────────────────────────────────────┘
```

**RECOMMENDATION:** Document pipeline/ as "future migration path" or remove.

### 1.2 Module Ownership Map

```
DOMAIN LAYER (Pure logic, no I/O):
├── entry_gate.py (889 lines)        → AUTHORITY: Gate logic
├── amt_analyzer.py (1745 lines)     → AUTHORITY: Volume profile + market state
├── trade_manager.py (1332 lines)    → AUTHORITY: Exit mechanics
├── prompt_builder.py (556 lines)    → AUTHORITY: LLM prompts
├── session_context.py (534 lines)   → AUTHORITY: Session phases
└── option_scanner.py (928 lines)    → AUTHORITY: Contract selection

APPLICATION LAYER (Orchestration):
├── trading_session.py (1636 lines)  → MAIN: Session lifecycle
├── llm_entry_handler.py (1245 lines)→ MAIN: LLM decisions
├── engine.py (875 lines)            → MAIN: Engine orchestration
└── amt_handler.py (180 lines)       → ADAPTER: AMT to pipeline

INFRASTRUCTURE:
├── dhan_adapter.py (368 lines)      → BROKER: Market data
├── database.py (559 lines)          → STORAGE: SQLite
└── event_bus.py (56 lines)          → EVENTS: Pub/sub
```

---

## 2. DUPLICATE LOGIC DETECTION

### 2.1 Gate Logic — Found in 2 Places

```
LOCATION 1: entry_gate.py (line 156)
  three_align_check() — AUTHORITATIVE source
  
LOCATION 2: llm_entry_handler.py (line 188)
  Calls three_align_check() — CORRECT (caller, not duplicate)
  
VERDICT: ✅ No duplication — proper delegation
```

### 2.2 Session Context — Found in 2 Places

```
LOCATION 1: session_context.py (line 230)
  get_session_info() — AUTHORITATIVE source
  
LOCATION 2: trading_session.py (line 179)
  Calls get_session_info() — CORRECT
  
LOCATION 3: gate.py (line 156)
  Calls get_session_info() — CORRECT
  
VERDICT: ✅ No duplication — proper delegation
```

### 2.3 Market State Detection — Found in 2 Places

```
LOCATION 1: market_structure_classifier.py
  5-state classifier with hysteresis
  
LOCATION 2: amt_analyzer.py (line 1100)
  ALSO computes market_state using displacement + acceptance
  
CONFLICT: Two different market state computations!
  • market_structure_classifier: BALANCE/IMBALANCE/TRANSITION/EXPANSION/CHOP
  • amt_analyzer: BALANCED/IMBALANCED (simpler)
  
VERDICT: ⚠️ DUPLICATION — Pick one authoritative source
```

### 2.4 CVD Thresholds — Found in 3 Places

```
LOCATION 1: entry_gate.py (line 205)
  CVD_EXTREME_THRESHOLD = 100 (options)
  
LOCATION 2: llm_entry_handler.py (line 536)
  abs(cvd_slope) > 150 → safety block
  
LOCATION 3: entry_gate.py (line 795)
  cvd_slope < -50 → grade penalty
  
ISSUE: Three different thresholds! (50, 100, 150)
RECOMMENDATION: Single constant CVD_EXTREME_THRESHOLD = 100
```

---

## 3. CODE SMELLS FOUND

### 3.1 Bare Exception Clauses (20+ instances)

```
trading_session.py:     20 bare except clauses
engine.py:              12 bare except clauses
database.py:            11 bare except clauses
llm_entry_handler.py:    7 bare except clauses
main.py:                 5 bare except clauses

RISK: Silent failures — errors swallowed without proper handling
RECOMMENDATION: Use specific exception types or at minimum log.error()
```

### 3.2 Large File Sizes

```
trading_session.py:    1,636 lines → SHOULD BE SPLIT
llm_entry_handler.py:  1,245 lines → SHOULD BE SPLIT
trade_manager.py:      1,332 lines → ACCEPTABLE (single responsibility)
amt_analyzer.py:       1,745 lines → ACCEPTABLE (complex domain)
```

### 3.3 Magic Numbers

```
entry_gate.py:50     LVN_THRESHOLD = 0.40
entry_gate.py:63     MAX_SPREAD_PCT = 2.5
llm_entry_handler:   150 (CVD threshold)
entry_gate.py:       100 (CVD threshold)
trade_manager.py:    0.50 (trail activation)
```

**RECOMMENDATION:** Move all thresholds to config.py or constants.py

---

## 4. MISSING FUNCTIONALITY

### 4.1 No Squeeze Detection
```
Status: Components exist but not connected
Impact: Missing highest-conviction Fabio setup
Effort: 2-3 hours
```

### 4.2 No VWAP Trailing
```
Status: VWAP bands computed but not used for trailing
Impact: Giving back profits on options (theta decay)
Effort: 1-2 hours
```

### 4.3 No Cross-Index Correlation
```
Status: BANKNIFTY/NIFTY treated independently
Impact: Missing BANKNIFTY lead signal (5-30 seconds)
Effort: 3-4 hours
```

### 4.4 No IV Regime Adaptation
```
Status: IV tracked but not used for strike selection
Impact: Wrong strike selection in high IV environments
Effort: 2-3 hours
```

---

## 5. PERFORMANCE ANALYSIS

### 5.1 LLM Inference Latency
```
Average: 0.8-1.2 seconds per call
Acceptable for scalping? YES (entries are not sub-second)
```

### 5.2 Probability Engine Latency
```
Average: 0.001-0.01 seconds (1-10ms)
Acceptable? YES (very fast)
```

### 5.3 Memory Usage
```
Not measured — recommend adding memory monitoring
```

---

## 6. SECURITY CONCERNS

### 6.1 Credentials in .env
```
⚠️ DHAN_ACCESS_TOKEN in plaintext
⚠️ API_KEY, API_SECRET in plaintext
RECOMMENDATION: Use environment variables or secret manager
```

### 6.2 No Rate Limiting on API
```
No rate limiting on /api/ endpoints
RECOMMENDATION: Add rate limiting middleware
```

---

## 7. TEST COVERAGE ANALYSIS

### 7.1 What's Tested:
```
✅ Pipeline processors (61 tests)
✅ AMT analyzer (38 tests)
✅ Entry gate logic
✅ Session management
✅ Trade manager exits
```

### 7.2 What's NOT Tested:
```
❌ End-to-end with real market data
❌ LLM decision quality
❌ Squeeze detection
❌ VWAP trailing
❌ Cross-index correlation
```

### 7.3 Test Quality:
```
Unit tests: GOOD
Integration tests: MINIMAL
E2E tests: NONE (only synthetic)
RECOMMENDATION: Add E2E tests with real MCX/NSE data
```

---

## 8. FINAL VERDICT

### Production Readiness Score: 78/100

| Category | Score | Notes |
|----------|-------|-------|
| Architecture | 8/10 | Two parallel paths (unused pipeline) |
| Core Logic | 9/10 | AMT correctly implemented |
| LLM Integration | 8/10 | Good but could be tighter |
| Risk Management | 9/10 | Comprehensive |
| Test Coverage | 7/10 | Good unit, weak integration |
| Performance | 8/10 | Acceptable for scalping |
| Security | 6/10 | Credentials in plaintext |
| Maintainability | 7/10 | Some large files, magic numbers |

### Critical Path Forward:
1. **Merge duplicate market state logic** (amt_analyzer vs classifier)
2. **Unify CVD thresholds** (single constant)
3. **Add bare except logging** (prevent silent failures)
4. **Document pipeline/ as future path** (or remove)
5. **Add E2E tests** with real data

---

*Audited by: Principal Engineer*
*Date: 2026-03-16*
