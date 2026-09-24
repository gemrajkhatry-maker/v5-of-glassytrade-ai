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
from quant.decision.data_quality import DataQuality, normalize_data_quality, normalize_evidence_provenance
from quant.amt.snapshot import derive_stacked_imbalance


def _derive_stacked_imbalance(footprints: dict) -> tuple[str, int, float, float]:
    """WS adapter wrapper — logic lives in ``derive_stacked_imbalance``."""
    return derive_stacked_imbalance(footprints)


class CVDStateDict(dict):
    @property
    def value(self) -> float:
        return float(self.get("value", 0.0))

    @property
    def slope(self) -> float:
        return float(self.get("slope", 0.0))

    @property
    def has_divergence(self) -> bool:
        return bool(self.get("hasDivergence", False))

    @property
    def divergence_type(self) -> str:
        return str(self.get("divergenceType", "NONE"))

    @property
    def z_score(self) -> float:
        return float(self.get("zScore", 0.0))


class OFIResultDict(dict):
    @property
    def ofi(self) -> float:
        return float(self.get("ofi", 0.0))

    @property
    def window(self) -> int:
        return int(self.get("window", 0))


def _to_cvd_state_dto(cs: object) -> CVDStateDict | None:
    if cs is None:
        return None
    if isinstance(cs, CVDStateDict):
        return cs
    if isinstance(cs, dict):
        return CVDStateDict(
            value=float(cs.get("value", 0.0)),
            slope=float(cs.get("slope", 0.0)),
            hasDivergence=bool(cs.get("hasDivergence") or cs.get("has_divergence", False)),
            divergenceType=str(cs.get("divergenceType") or cs.get("divergence_type", "NONE")),
            zScore=float(cs.get("zScore") or cs.get("z_score", 0.0)),
        )
    return CVDStateDict(
        value=float(getattr(cs, "value", 0.0)),
        slope=float(getattr(cs, "slope", 0.0)),
        hasDivergence=bool(getattr(cs, "has_divergence", False)),
        divergenceType=str(getattr(cs, "divergence_type", "NONE")),
        zScore=float(getattr(cs, "z_score", 0.0)),
    )


def _cvd_agrees(r) -> bool:
    """Auction scoring flag: CVD slope sign agrees with the break direction.

    Defaults False (same as ``bool(dto.get("cvdAgrees"))`` on a missing key)
    when either side is unavailable, so no trading behavior changes for
    absent CVD or absent break.
    """
    slope = getattr(r, "cvd_slope", 0.0) or 0.0
    direction = str(getattr(r, "break_direction", "") or "").upper()
    if not direction or not slope:
        return False
    if direction == "UP":
        return slope > 0
    if direction == "DOWN":
        return slope < 0
    return False


def _to_ofi_result_dto(o: object) -> OFIResultDict | None:
    if o is None:
        return None
    if isinstance(o, OFIResultDict):
        return o
    if isinstance(o, dict):
        return OFIResultDict(
            ofi=float(o.get("ofi", 0.0)),
            window=int(o.get("window", 0)),
        )
    return OFIResultDict(
        ofi=float(getattr(o, "ofi", 0.0)),
        window=int(getattr(o, "window", 0)),
    )


def amt_result_to_dto(r) -> dict:
    """Convert a domain AMTResult to the camelCase WS DTO dict."""
    quality = normalize_data_quality(getattr(r, "data_quality", ""))
    if quality is DataQuality.UNAVAILABLE and not getattr(r, "data_quality", ""):
        # Fabio live-safety spec: ``CANDLE_DISTRIBUTED`` "is not upgraded to
        # TICK_EXACT merely because a footprint object exists" (2026-09-18
        # live-safety remediation, step 7). The accumulator gate that earns
        # TICK_EXACT lives in AMTAnalyzer._build_result, which sees the live
        # ``TickFootprintAccumulator``; this fallback only binds when the
        # analyzer declined to classify, so a bare footprint object must not
        # promote the quality here.
        quality = (
            DataQuality.CANDLE_DISTRIBUTED
            if getattr(r, "cvd_source", "") in ("underlying", "option")
            else DataQuality.CANDLE_GAUSSIAN
        )
    si_dir, si_mag, si_low, si_high = _derive_stacked_imbalance(getattr(r, "footprints", {}) or {})
    leg_lvns = getattr(r, "leg_lvns", ()) or ()
    footprint_keys = tuple(getattr(r, "footprints", {}) or ())
    raw_drive_number = getattr(r, "drive_number", 0)
    try:
        drive_number = int(raw_drive_number)
    except (TypeError, ValueError):
        drive_number = 0
    return {
        "marketState": r.market_state,
        "time": _epoch_to_iso(max(footprint_keys)) if footprint_keys else "",
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
        "dataQuality": quality.value,
        "evidenceProvenance": {
            key: value.value
            for key, value in normalize_evidence_provenance(
                getattr(r, "evidence_provenance", None)
            ).items()
        },
        "cvdDivergence": r.cvd_divergence,
        # Session probe extremes (Fabio failed-breakout rule; review finding C2):
        # consumed by va_fade so the stop sits beyond the FULL session probe.
        "sessionExtremeLow": r.session_extreme_low,
        "sessionExtremeHigh": r.session_extreme_high,
        "profileShape": r.profile_shape,
        "profileType": r.profile_type,
        "sessionVwap": r.session_vwap,
        "vwap": r.session_vwap,
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
        "driveEntryValid": bool(getattr(r, "drive_entry_valid", False)),
        # Departure is a distinct tracker observation (not an alias of the
        # entry-valid bool): DriveTracker only advances drive_count past D1
        # after an observe()d leave-and-return, so drive_number >= 2 IS
        # "departed and re-approached". SetupEvidence reads this key instead
        # of re-asking isSecondDrive / driveEntryValid.
        "departed": drive_number >= 2,
        # Phase 4: context_builder.py's drive-exhaustion guard reads
        # "driveNumber" but this key was never emitted here, so
        # gates_edge.py's "3+ drives -> exhausted" guard could never fire —
        # AMTResult.drive_number is real, already-tracked state (analyzer.py
        # _track_drives), it just never reached the wire.
        "driveNumber": drive_number,
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
        # Layer 2 Compression Box (spec §5.2): micro-profile in tight balance
        "compressionBoxPoc": float(getattr(r, "compression_box_poc", 0.0)),
        "compressionBoxVah": float(getattr(r, "compression_box_vah", 0.0)),
        "compressionBoxVal": float(getattr(r, "compression_box_val", 0.0)),
        "compressionBoxBars": int(getattr(r, "compression_box_bars", 0)),
        # Layer 4 Gap Profile (spec §5.2): gap-POC/VAH/VAL
        "gapProfilePoc": float(getattr(r, "gap_profile_poc", 0.0)),
        "gapProfileVah": float(getattr(r, "gap_profile_vah", 0.0)),
        "gapProfileVal": float(getattr(r, "gap_profile_val", 0.0)),
        # Raw aggression components for direction-gated re-scoring
        "aggressionComponents": getattr(r, "aggression_components", {}),
        "cvdState": _to_cvd_state_dto(getattr(r, "cvd_state", None)),
        "ofiResult": _to_ofi_result_dto(getattr(r, "ofi_result", None)),
        "normDelta": getattr(r, "norm_delta", 0.0),
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
        "legLvn": float(leg_lvns[0]) if leg_lvns else 0.0,
        # Keys the decision layer reads (test_amt_dto_contract); absent keys
        # silently zero/default in submission_handler / context_builder.
        # AMTResult carries no top-of-book fields — bid/ask stay 0.0 ("no
        # book"), which readers already treat as unknown/neutral.
        "optionDelta": (
            float(r.delta_normalized_option)
            if getattr(r, "delta_normalized_option", 0.0)
            else None
        ),
        "bid": float(getattr(r, "best_bid", 0.0) or 0.0),
        "ask": float(getattr(r, "best_ask", 0.0) or 0.0),
        "nearestLegLvn": float(leg_lvns[0]) if leg_lvns else 0.0,
        "cvdAgrees": _cvd_agrees(r),
        "stackedImbalanceDirection": si_dir,
        "stackedImbalanceMagnitude": si_mag,
        "stackedImbalancePriceLow": si_low,
        "stackedImbalancePriceHigh": si_high,
        "stacked_imbalance_direction": si_dir,
        "stacked_imbalance_magnitude": si_mag,
        "stacked_imbalance_price_low": si_low,
        "stacked_imbalance_price_high": si_high,
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
