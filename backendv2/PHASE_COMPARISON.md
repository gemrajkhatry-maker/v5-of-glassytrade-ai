# Phase 1-4 In-Depth Comparison: BackendV2 vs Existing Backend

## Phase 1: CVDTracker + Enhanced Absorption

### Existing Backend (`cvd_tracker.py`)
| Feature | Implementation |
|---------|---------------|
| CVD State | `CVDState` frozen dataclass with `value`, `slope`, `has_divergence`, `divergence_type`, `z_score` |
| History | `_MAX_HISTORY = 500` limit with automatic trimming |
| Slope Calculation | `_compute_slope()` using linear regression |
| Divergence Detection | `_detect_divergence()` - price vs CVD divergence with direction |
| Session Boundary | Auto-reset when time goes backwards (new session) |
| State Persistence | Full `reset()`, `update()`, `state()` methods |

### BackendV2 Implementation
| Feature | Status | Gap |
|---------|--------|-----|
| CVDState | ✅ Has `CVDPoint` and `CVDSnapshot` | Missing `z_score`, `divergence_type` |
| History | ✅ 100-point window | No explicit max limit |
| Slope | ✅ `get_slope()` method | Returns single value |
| Divergence | ❌ Not implemented | No divergence detection |
| Session Boundary | ❌ Not implemented | No auto-reset |
| Update API | ✅ `update()` returns `CVDSnapshot` | Simpler interface |

**Gap Assessment**: BackendV2 has basic CVD tracking but missing:
- Divergence detection (critical for absorption signals)
- Session boundary handling
- Z-score calculation
- Slope persistence filter

---

## Phase 2: Acceptance/Rejection Engine

### Existing Backend (`acceptance_rejection.py`)
| Feature | Implementation |
|---------|---------------|
| ARResult | Frozen dataclass with `acceptance_above`, `acceptance_below`, `rejection_at_high`, `rejection_at_low`, `liquidity_sweep`, `price_velocity` |
| Time Threshold | 120 seconds default |
| Volume Ratio | 1.2x baseline |
| Velocity Calculation | Using candle body / duration |
| Liquidity Sweep | Detects upper/lower wick sweeps with volume spike |
| Wick Analysis | Upper wick > body size detection |

### BackendV2 Implementation
| Feature | Status | Gap |
|---------|--------|-----|
| ARResult | ✅ Has `AcceptanceResult` | Missing `price_velocity` |
| Time Tracking | ❌ Not implemented | No time accumulation |
| Volume Ratio | ✅ Has `volume_check` | Fixed threshold |
| Velocity | ❌ Not implemented | No price velocity |
| Liquidity Sweep | ✅ `liquidity_sweep` flag | Basic detection |
| Wick Analysis | ❌ Not implemented | No wick analysis |

**Gap Assessment**: BackendV2 is missing critical AR features:
- Time-based accumulation (core to AR detection)
- Velocity calculation
- Sophisticated wick analysis
- Price velocity tracking

---

## Phase 3: LVN/HVN Detection

### Existing Backend (`lvn_detector.py`)
| Feature | Implementation |
|---------|---------------|
| LVN Level | `LVNLevel` dataclass with `price`, `strength`, `bucket_index` |
| HVN Level | `HVNLevel` dataclass with `price`, `strength`, `bucket_index` |
| Percentile Method | `lvn_percentile=25%`, `hvn_percentile=75%` |
| Smoothing | `_smooth_array()` centered moving average |
| Clustering | `_cluster_nodes()` with `min_separation` parameter |
| Persistence Tracker | `LVNPersistenceTracker` for cross-bar tracking |

### BackendV2 Implementation
| Feature | Status | Gap |
|---------|--------|-----|
| LVN Level | ✅ `VolumeNode` with `price`, `volume`, `node_type`, `strength` | No `bucket_index` |
| HVN Level | ✅ Same model | Combined model |
| Percentile | ❌ Uses absolute ratio | Not percentile-based |
| Smoothing | ❌ Not implemented | No histogram smoothing |
| Clustering | ✅ `min_separation` parameter | Basic implementation |
| Persistence | ❌ Not implemented | No cross-bar tracking |

**Gap Assessment**: BackendV2 LVN/HVN is simplified:
- Uses absolute ratio vs percentile (less adaptive)
- No histogram smoothing
- No persistence tracking
- Combined model loses specificity

---

## Phase 4: Aggression Scoring

### Existing Backend (`aggression_scorer.py`)
| Feature | Implementation |
|---------|---------------|
| Multiple Signals | 7-component additive scoring (max 4.5) |
| Footprint | ≥40% cells at ≥3:1 ratio → +1.0 |
| CVD Confirmation | Slope OR divergence → +1.0 |
| Big Trade | 3+ prints ≥5× avg within 2 ticks → +1.0 |
| Absorption | Range < ATR×0.3 AND vol > avg×2 → +0.5 |
| OFI Aligned | >+0.10 LONG, <-0.10 SHORT → +0.5 |
| Confluence | LVN near session level → +0.5 |
| Volume Bubble | Within 3 ticks of entry → +0.5 |
| Confidence | HIGH (≥3.0), MEDIUM (≥2.0), LOW (<2.0) |

### BackendV2 Implementation
| Feature | Status | Gap |
|---------|--------|-----|
| Multiple Signals | ❌ Single value scoring | No additive model |
| Footprint | ❌ Not implemented | Missing entirely |
| CVD Confirmation | ❌ Not implemented | Missing entirely |
| Big Trade | ❌ Not implemented | Missing entirely |
| Absorption | ✅ Basic 2.5σ filter | Different approach |
| OFI | ❌ Not implemented | Missing entirely |
| Confluence | ❌ Not implemented | Missing entirely |
| Volume Bubble | ❌ Not implemented | Missing entirely |
| Multi-signal | ❌ Not implemented | Single dimension |

**Gap Assessment**: BackendV2 aggression scoring is fundamentally different:
- No multi-signal additive model
- Missing 6 of 7 core signals
- Different purpose (simple outlier detection vs trade confirmation)

---

## Summary: Critical Gaps to Address

| Priority | Component | Missing Critical Features |
|----------|-----------|---------------------------|
| CRITICAL | CVDTracker | Divergence detection, session boundaries |
| CRITICAL | Acceptance/Rejection | Time accumulation, velocity, wick analysis |
| HIGH | LVN/HVN | Percentile method, smoothing, persistence |
| HIGH | AggressionScorer | Multi-signal model (6 of 7 missing) |

## Recommendation

The current BackendV2 implementations are **simplified versions** that capture basic functionality but miss the sophisticated multi-dimensional analysis that makes the existing backend professional-grade. To achieve true parity, each component needs significant enhancement.