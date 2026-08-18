# Hardcoded Constants - Quick Summary

## Architecture Assessment

**Excellent:** YAML-based config hierarchy for all trading parameters
**Acceptable:** Dhan broker API constants (API contracts)
**Needs Review:** Frontend local magic numbers

---

## Key Hardcoded Values That Should Be Externalized

### Frontend Components (Magic Numbers)

| File | Line | Value | Purpose | Config Key Suggestion |
|------|------|-------|---------|----------------------|
| `DiagnosticsPanel.tsx` | 120 | `0.3` | VWAP cross threshold (%) | `diagnostics.vwapCrossThreshold` |
| `DiagnosticsPanel.tsx` | 214 | `0.25` | Distance threshold | `diagnostics.distThreshold` |
| `DiagnosticsPanel.tsx` | 218 | `3` | Total rules count | `diagnostics.ruleCount` |
| `EquityPanel.tsx` | 16 | `20000` | Daily P&L target (₹) | `equity.dailyTarget` |
| `profileInfo.ts` | 39-40 | `0.001`, `0.005` | Confluence/divergence (%) | `profile.confluencePct`, `profile.divergencePct` |
| `OrderFlowCard.tsx` | 176 | `5`, `15` | Spread thresholds (bps) | `orderFlow.spreadGreenBps`, `orderFlow.spreadYellowBps` |
| `AbsorptionCard.tsx` | 73 | `100` | Swing delta threshold | `absorption.swingDeltaThreshold` |
| `VaFreezeCard.tsx` | 89 | `2` | Min VA snapshots | `vaFreeze.minSnapshots` |
| `threeA.ts` | 24-25 | `2.0`, `2.0` | Min aggression/CVD slope | Already in YAML |
| `useServerTradingSystem.ts` | 106 | `10` | RAF queue size | `performance.maxRafQueue` |
| `useServerTradingSystem.ts` | 175 | `180000` | Config timeout (ms) | `network.configTimeoutMs` |

### Frontend Chart Config (Theme Defaults)

| File | Value | Purpose |
|------|-------|---------|
| `constants.ts` | `#00c896` | Bull color |
| `constants.ts` | `#ff4757` | Bear color |
| `constants.ts` | `0.1` | Glass roughness |
| `constants.ts` | `0.95` | Transmission |
| `constants.ts` | `19800` | IST offset (fixed, OK) |
| `constants.ts` | `5m` | Default interval |

### Dhan Broker Constants (API Contracts - Acceptable)

These represent Dhan API contracts and should remain:
- API URLs, endpoints
- Exchange segment IDs (1-12)
- Order status codes ("PENDING", "TRANSIT", "TRADED", etc.)
- Product types ("I", "M", "C", "CO", "BO")
- WebSocket feed types (15, 17, 21, 20)
- Rate limits (10, 5, 0.33 req/sec)
- Error codes (DH-1001 through DH-5003)
- Historical max days (90)

### Backend Hardcoded Fallback Defaults

When YAML config fails, SettingsAdapter uses these fallbacks:
- Scanner mode: `"mcx_options"`
- Default exchange: `"MCX"`
- DHAN symbols: `"CRUDEOIL,NATURALGAS"`
- Scanner top N: `4`
- LLM timeout: `60` seconds
- Capital: `5000000`
- Tick poll: `5.0` seconds
- Signal stale: `60` seconds
- Gap fill interval: `300` seconds

---

## Config Loading Order

```
GLASSYTRADE_ENV env var
    ↓
backend/config/environments/{env}.yaml
    ↓
GLASSYTRADE_STRATEGY env var  
    ↓
backend/config/strategies/{strategy}.yaml
    ↓
backend/config/base.yaml (defaults)
    ↓
backend/config/feature_flags.yaml
    ↓
SystemConfig (frozen dataclass)
```

---

## Lot Sizes (Exchange-Authoritative, Current Series Aug 2026)

| Symbol | Lot Size | Source |
|--------|----------|--------|
| NIFTY | 65 | NSE current series |
| BANKNIFTY | 30 | NSE current series |
| FINNIFTY | 60 | NSE current series |
| MIDCPNIFTY | 120 | NSE current series |
| SENSEX | 20 | BSE current series |

These are correctly configured in both `base.yaml` and `constants.py`.
