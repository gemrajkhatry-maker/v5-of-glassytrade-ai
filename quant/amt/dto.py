"""AMTResult -> frontend ``amt`` WS DTO (pure, camelCase).

Ported from the legacy ``backend/app/infrastructure/serialization/schemas.py``
``amt_result_to_dto`` (deleted pipeline) so the quant layer stays pure and the
frontend ``AMTAnalysis`` contract is fully satisfied: the volume-profile
histogram (``profile``/``legProfile``), market state, VWAP bands, LVNs/HVNs,
aggressive prints, absorption and displacement context — every field the old
AMTHandler produced per bar.

``AMTResult`` is a frozen dataclass with defaults, so every attribute access
is safe.
"""

from __future__ import annotations
from quant.contracts.enums import MarketState
from quant.state import _epoch_to_iso


def amt_result_to_dto(r) -> dict:
    """Convert a domain AMTResult to the camelCase WS DTO dict."""
    return {
        "marketState": r.market_state,
        "poc": r.poc,
        "valueAreaHigh": r.value_area_high,
        "valueAreaLow": r.value_area_low,
        "lvns": list(r.lvns),
        "hvns": list(r.hvns),
        "aggression": r.aggression,
        "signal": None,  # signals now generated exclusively by the decision pipeline
        "setup": r.setup,
        "profile": [
            {
                "price": p.price,
                "volume": p.volume,
                "buyVolume": p.buy_volume,
                "sellVolume": p.sell_volume,
            }
            for p in r.profile
        ],
        "aggressivePrints": [
            {
                "price": ap.price,
                "time": ap.time,
                "volume": ap.volume,
                "delta": ap.delta,
                "side": ap.side,
            }
            for ap in r.aggressive_prints
        ],
        "cvdSlope": r.cvd_slope,
        # Canonical provenance: exact tick footprint when available, otherwise
        # preserve the analyzer's explicit candle/proxy source.
        "dataQuality": (
            "TICK_EXACT" if r.footprints else
            "CANDLE_DISTRIBUTED" if getattr(r, "cvd_source", "") in ("underlying", "option") else
            "CANDLE_GAUSSIAN"
        ),
        "cvdDivergence": r.cvd_divergence,
        "profileShape": r.profile_shape,
        "profileType": r.profile_type,
        "sessionVwap": r.session_vwap,
        "vwapUpper1": r.vwap_upper_1,
        "vwapLower1": r.vwap_lower_1,
        "vwapUpper2": r.vwap_upper_2,
        "vwapLower2": r.vwap_lower_2,
        "vwapDeviationSigmas": r.vwap_deviation_sigmas,
        "isExtremeDeviation": r.is_extreme_deviation,
        "balanceRatio": r.balance_ratio,
        "valueMigration": {
            "direction": r.value_migration.direction,
            "pocDrift": r.value_migration.poc_drift,
            "vahDrift": r.value_migration.vah_drift,
            "valDrift": r.value_migration.val_drift,
            "windowLabel": r.value_migration.window_label,
            "hasMigration": r.value_migration.has_migration,
        },
        "npocAbove": float(r.npoc_above or 0.0),
        "npocBelow": float(r.npoc_below or 0.0),
        "legProfile": [
            {
                "price": p.price,
                "volume": p.volume,
                "buyVolume": p.buy_volume,
                "sellVolume": p.sell_volume,
            }
            for p in r.leg_profile
        ],
        "legLvns": list(r.leg_lvns),
        "legProfileSource": r.leg_profile_source,
        "legBucketCount": r.leg_bucket_count,
        "legLvnAvailable": bool(r.leg_lvns),
        "legLvnUnavailableReason": r.leg_lvn_unavailable_reason,
        "legPoc": r.leg_poc,
        "legVah": r.leg_vah,
        "legVal": r.leg_val,
        "hasDisplacement": r.has_displacement,
        "ofi": r.ofi,
        "obi": r.obi,
        # Market structure
        "marketStructure": r.market_structure,
        "structureConfidence": r.structure_confidence,
        # Initial Balance
        "ibHigh": r.ib_high,
        "ibLow": r.ib_low,
        "ibComplete": r.ib_complete,
        "ibPoc": r.ib_poc,
        "ibVah": r.ib_vah,
        "ibVal": r.ib_val,
        # Prior day levels
        "priorPoc": r.prior_poc,
        "priorVah": r.prior_vah,
        "priorVal": r.prior_val,
        "gapType": r.gap_type,
        "openingBias": r.opening_bias,
        "squeezeDirection": getattr(r, "squeeze_direction", ""),
        "squeezeTrappedLevel": float(getattr(r, "squeeze_trapped_level", 0.0)),
        # Acceptance / Rejection
        "acceptanceAbove": r.acceptance_above,
        "acceptanceBelow": r.acceptance_below,
        "rejectionAtHigh": r.rejection_at_high,
        "rejectionAtLow": r.rejection_at_low,
        "priceVelocity": r.price_velocity,
        # Break detection
        "breakDirection": r.break_direction,
        "breakType": r.break_type,
        "breakLevel": r.break_level,
        # POC migration + LVN play
        "pocSignal": r.poc_signal,
        "pocVsPrice": r.poc_vs_price,
        "lvnPlay": r.lvn_play,
        "isSecondDrive": r.drive_entry_valid,
        # Phase 4: context_builder.py's drive-exhaustion guard reads
        # "driveNumber" but this key was never emitted here, so
        # gates_edge.py's "3+ drives -> exhausted" guard could never fire —
        # AMTResult.drive_number is real, already-tracked state (analyzer.py
        # _track_drives), it just never reached the wire.
        "driveNumber": r.drive_number,
        # Higher Timeframe Levels
        "dailyVah": r.daily_vah,
        "dailyVal": r.daily_val,
        "dailyPoc": r.daily_poc,
        "hourlyPoc": r.hourly_poc,
        # Absorption context
        "absorptionSide": r.absorption_side,
        "absorptionRangeRatio": r.absorption_range_ratio,
        "absorptionVolRatio": r.absorption_vol_ratio,
        "tripleAPhase": getattr(r, "triple_a_phase", "WAITING"),
        "tripleASignal": getattr(r, "triple_a_signal", ""),
        "absorptionClusterHigh": getattr(r, "absorption_cluster_high", 0.0),
        "absorptionClusterLow": getattr(r, "absorption_cluster_low", 0.0),
        # Displacement
        "swingDelta": r.swing_delta,
        # Per-symbol delta (isolated per option contract)
        "deltaNormalizedOption": r.delta_normalized_option,
        "contestedZone": r.contested_zone,
        "gex": {
            "netGexCrores": getattr(r.gex, "net_gex_crores", 0.0) if getattr(r, "gex", None) else 0.0,
            "regime": getattr(r.gex, "regime", "NEUTRAL_GAMMA") if getattr(r, "gex", None) else "NEUTRAL_GAMMA",
            "zeroFlipLevel": getattr(r.gex, "zero_flip_level", 0.0) if getattr(r, "gex", None) else 0.0,
            "callWallStrike": getattr(r.gex, "call_wall_strike", 0.0) if getattr(r, "gex", None) else 0.0,
            "putWallStrike": getattr(r.gex, "put_wall_strike", 0.0) if getattr(r, "gex", None) else 0.0,
            "gammaPinStrike": getattr(r.gex, "gamma_pin_strike", 0.0) if getattr(r, "gex", None) else 0.0,
            "strikeGex": [
                {
                    "strike": s.strike,
                    "callGex": s.call_gex,
                    "putGex": s.put_gex,
                    "netGex": s.net_gex,
                }
                for s in getattr(r.gex, "strike_gex", ())
            ] if getattr(r, "gex", None) else [],
        },
        "vars": {
            "bullishReclaimCva": getattr(r.vars_result, "bullish_reclaim_cva", False) if getattr(r, "vars_result", None) else False,
            "bearishReclaimCva": getattr(r.vars_result, "bearish_reclaim_cva", False) if getattr(r, "vars_result", None) else False,
            "bullishReclaimPva": getattr(r.vars_result, "bullish_reclaim_pva", False) if getattr(r, "vars_result", None) else False,
            "bearishReclaimPva": getattr(r.vars_result, "bearish_reclaim_pva", False) if getattr(r, "vars_result", None) else False,
            "bullishReclaim": getattr(r.vars_result, "bullish_reclaim", False) if getattr(r, "vars_result", None) else False,
            "bearishReclaim": getattr(r.vars_result, "bearish_reclaim", False) if getattr(r, "vars_result", None) else False,
            "signalSource": getattr(r.vars_result, "signal_source", "") if getattr(r, "vars_result", None) else "",
        },
        # HalfTrend indicator — display-only line + Buy/Sell labels.
        # The bar time is normalized to the same ISO-8601 IST string the WS
        # candle tick carries (state._bar_to_tick) and the REST /halftrend rows
        # (fetch_history already ISO). The frontend merges live points into the
        # REST series by raw timestamp equality — an epoch-string live row never
        # matched an ISO history row, so the live HalfTrend tail was silently
        # dropped (and toISTTimestamp(epoch) == 0, so the chart skipped it).
        "halfTrend": {
            "time": _epoch_to_iso(getattr(r.half_trend_result, "time", "")) if getattr(r, "half_trend_result", None) else "",
            "trend": int(getattr(r.half_trend_result, "trend", 0)) if getattr(r, "half_trend_result", None) else 0,
            "ht": float(getattr(r.half_trend_result, "ht", 0.0)) if getattr(r, "half_trend_result", None) else 0.0,
            # ATR channel is null until ATR(period) warms up (~100 bars) —
            # emit JSON null, never 0.0, so the frontend skips the rail.
            "atrHigh": (getattr(r.half_trend_result, "atr_high", None)) if getattr(r, "half_trend_result", None) else None,
            "atrLow": (getattr(r.half_trend_result, "atr_low", None)) if getattr(r, "half_trend_result", None) else None,
            "buySignal": bool(getattr(r.half_trend_result, "buy_signal", False)) if getattr(r, "half_trend_result", None) else False,
            "sellSignal": bool(getattr(r.half_trend_result, "sell_signal", False)) if getattr(r, "half_trend_result", None) else False,
        },
        "footprints": {
            k: {
                "time": v.time,
                "levels": [
                    {
                        "price": lvl.price,
                        "bid": lvl.bid,
                        "ask": lvl.ask,
                        "delta": lvl.delta,
                        "imbalance": lvl.imbalance,
                        "stacked": lvl.stacked,
                    }
                    for lvl in v.levels
                ],
                "pocPrice": v.poc_price,
                "totalDelta": v.total_delta,
                "stepPrice": v.step_price,
            }
            for k, v in r.footprints.items()
        },
    }


def empty_amt_dto() -> dict:
    """Full-shape DTO for an empty analysis (insufficient candles / error).

    Keeps every key present so the frontend renders the contract instead of
    falling back to the old 4-field stub shape.
    """
    from quant.contracts.value_objects import AMTResult

    return amt_result_to_dto(
        AMTResult(market_state=MarketState.BALANCED, poc=0.0, value_area_high=0.0,
                  value_area_low=0.0)
    )
