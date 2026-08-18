# Frontend Config Externalization - Complete

## Summary

Successfully externalized all hardcoded frontend magic numbers into a centralized `frontend/config.ts` configuration file.

## Files Created

### `frontend/config.ts` (new)
Centralized configuration with the following sections:

| Section | Config Object | Purpose |
|---------|--------------|---------|
| Time | `IST_OFFSET_SECONDS`, `ONE_DAY_MS` | Time constants |
| Chart | `DEFAULT_CHART_CONFIG` | Chart appearance (colors, opacity, etc.) |
| Equity | `EQUITY_PANEL` | Daily P&L circuit breaker (-₹10,000) and target (₹20,000) |
| Diagnostics | `DIAGNOSTICS_CONFIG` | VWAP threshold (0.3%), distance threshold (0.25), confidence gates |
| Three-A | `THREE_A_CONFIG` | Aggression min (2.0), CVD slope min (2.0) |
| Profile | `PROFILE_CONFIG` | Confluence (0.1%) / divergence (0.5%) thresholds |
| Order Flow | `ORDER_FLOW_CONFIG` | Format thresholds, spread colors (5/15 bps), divergence detection |
| Absorption | `ABSORPTION_CONFIG` | Swing delta threshold (100), large print K threshold (1000) |
| VA Freeze | `VA_FREEZE_CONFIG` | Min snapshots required (2) |
| Network | `NETWORK_CONFIG` | Reconnect delay, max attempts, ping interval, config timeout (180s), RAF queue size (10) |

## Files Modified

### `frontend/constants.ts`
- Moved `DEFAULT_CONFIG` to re-export from `config.ts`
- Added `DEFAULT_CONFIG` alias for backward compatibility

### `frontend/types.ts`
- Exported `VaSnapshot` interface (was previously inline in `AuctionAnalysis`)

### `frontend/components/ai/DiagnosticsPanel.tsx`
- Replaced hardcoded `70`, `40`, `80` confidence thresholds with `DIAGNOSTICS_CONFIG.structureConfidence`
- Replaced `0.3` VWAP threshold with `DIAGNOSTICS_CONFIG.vwapCrossThreshold`
- Replaced `0.25` distance threshold with `DIAGNOSTICS_CONFIG.distThreshold`
- Replaced `3` rule count with `DIAGNOSTICS_CONFIG.ruleCount`

### `frontend/components/ai/EquityPanel.tsx`
- Replaced `20000` target with `EQUITY_PANEL.dailyTarget`
- Replaced `-10000` circuit breaker with `EQUITY_PANEL.circuitBreaker`

### `frontend/utils/profileInfo.ts`
- Replaced `0.001` confluence threshold with `PROFILE_CONFIG.confluenceThreshold`
- Replaced `0.005` divergence threshold with `PROFILE_CONFIG.divergenceThreshold`

### `frontend/utils/threeA.ts`
- Replaced `AGGRESSION_MIN = 2.0` with `THREE_A_CONFIG.aggressionMin`
- Replaced `CVD_SLOPE_MIN = 2.0` with `THREE_A_CONFIG.cvdSlopeMin`

### `frontend/components/ai/OrderFlowCard.tsx`
- Replaced format thresholds with `ORDER_FLOW_CONFIG.format`
- Replaced spread thresholds (`5`, `15`) with `ORDER_FLOW_CONFIG.spread`

### `frontend/components/ai/AbsorptionCard.tsx`
- Replaced `100` swing delta threshold with `ABSORPTION_CONFIG.swingDeltaThreshold`
- Replaced `1000` large print threshold with `ABSORPTION_CONFIG.largePrintKThreshold`

### `frontend/components/ai/VaFreezeCard.tsx`
- Replaced `2` min snapshots with `VA_FREEZE_CONFIG.minSnapshots`

### `frontend/hooks/useServerTradingSystem.ts`
- Replaced `10` RAF queue size with `NETWORK_CONFIG.maxRafQueueSize`
- Replaced `180000` config timeout with `NETWORK_CONFIG.configTimeoutMs`

## Verification

✅ Frontend builds successfully (1739 modules transformed)
✅ Main source files compile without TypeScript errors
⚠️ Test files have pre-existing errors unrelated to this change

## Architecture Notes

The new `config.ts` follows a similar pattern to the backend's YAML-based configuration:
- Typed configuration objects with explicit defaults
- Grouped by domain (equity, diagnostics, order flow, etc.)
- Easy to override per-environment or per-user
- Can be extended to support localStorage persistence or admin settings

## Next Steps (Optional)

1. Add runtime config loading from backend API
2. Add localStorage persistence for user preferences
3. Add admin UI for adjusting thresholds
4. Add validation for config values (min/max ranges)
