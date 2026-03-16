"""OptionScannerService — momentum-optimized contract selection for scalping.

Designed for aggressive options scalping where we BUY options to ride
short-term momentum. Key principles:
  - Follow the momentum: detect which side (CE/PE) has live buying pressure
  - Maximize delta: ATM or 1-strike ITM for maximum P&L per underlying point
  - Tight spreads: slippage kills scalps — spread < 1% of premium mandatory
  - Volume > OI: live volume shows where momentum IS, OI is stale
  - Current-week expiry: highest gamma = fastest premium response
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import timezone, timedelta

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class ScanResult:
    symbol: str       # Broker-native symbol e.g. "NIFTY 24 FEB 25750 CALL"
    underlying: str
    strike: int
    option_type: str  # "CE" or "PE"
    expiry: str       # ISO date
    ltp: float
    oi: int
    volume: int
    spread: float
    score: float = 0.0
    bias: str = ""           # "BULLISH" | "BEARISH" | "NEUTRAL"
    bias_reason: str = ""
    delta: float = 0.0       # Option delta (0-1)
    iv: float = 0.0          # Implied volatility


class OptionScannerService:
    """Selects the optimal option contract for momentum scalping.

    Selection pipeline:
    1. Detect momentum direction from live chain signals
    2. Pick CE for bullish momentum, PE for bearish
    3. Score strikes: delta > volume > spread > OI
    4. Prefer ATM/1-ITM for maximum delta response
    """

    _STRIKE_INTERVALS = {"NIFTY": 50, "BANKNIFTY": 100, "FINNIFTY": 50,
                          "CRUDEOIL": 50, "NATURALGAS": 5, "GOLD": 100, "SILVER": 500}
    _MIN_OI = {"NIFTY": 500_000, "BANKNIFTY": 300_000, "FINNIFTY": 50_000,
               "CRUDEOIL": 5_000, "NATURALGAS": 5_000, "GOLD": 1_000, "SILVER": 1_000}

    # Scalping constraints
    MAX_SPREAD_PCT = 1.5     # Reject contracts with spread > 1.5% of LTP
    IV_WARN_MULTIPLE = 1.5   # Warn if IV > 1.5x of ATM baseline
    MIN_OI_SCAN_MULTIPLIER = 0.02     # Multiplier for _MIN_OI to get the hard OI floor (reject illiquid)
    MAX_PREMIUM = 1_500      # Reject options with LTP > this (capital safety)

    def __init__(self, broker) -> None:
        self._broker = broker

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan(
        self,
        underlying: str = "NIFTY",
        preferred_option_type: str | None = None,
        expiry_index: int = 0,
        exchange: str = "NFO",
    ) -> ScanResult | None:
        """Fetch option chain and select the best scalping contract.

        *preferred_option_type* is treated as a HINT, not override — if
        momentum clearly contradicts it, momentum wins.
        """
        try:
            logger.info("Scanning option chain for %s (expiry_index=%d)", underlying, expiry_index)
            chain = self._broker.get_option_chain(
                underlying=underlying,
                exchange=exchange,
                expiry_index=expiry_index,
            )
            if chain is None:
                logger.warning("No option chain returned for %s", underlying)
                return None

            expiry_date = chain.expiry.date().isoformat()
            atm = chain.atm_strike
            interval = self._STRIKE_INTERVALS.get(underlying.upper(), 50)

            logger.info("%s ATM=%.0f spot=%.0f expiry=%s strikes=%d",
                        underlying, atm, getattr(chain, 'spot_price', 0),
                        expiry_date, len(chain.strikes))

            # --- Step 1: Detect momentum direction ---
            bias, bias_strength, bias_reason = self._detect_momentum(chain, atm, interval)
            logger.info("Momentum: %s (strength=%d) — %s", bias, bias_strength, bias_reason)

            # Bias drives CE/PE — preference is only used when bias is weak
            if bias_strength >= 3:
                # Strong momentum — follow it regardless of preference
                opt_type = "CE" if bias == "BULLISH" else "PE"
                if preferred_option_type and preferred_option_type.upper() != opt_type:
                    logger.info("Overriding preference %s → %s (strong %s momentum)",
                                preferred_option_type, opt_type, bias)
            elif bias_strength >= 1:
                # Moderate momentum — follow it
                opt_type = "CE" if bias == "BULLISH" else "PE"
            elif preferred_option_type:
                # Weak/neutral — use preference as tiebreaker
                opt_type = preferred_option_type.upper()
            else:
                # No preference, no momentum — pick higher volume side
                ce_vol = sum(o.volume for o in chain.calls.values() if o.volume)
                pe_vol = sum(o.volume for o in chain.puts.values() if o.volume)
                opt_type = "CE" if ce_vol >= pe_vol else "PE"

            # --- Step 2: Score strikes with high volume + OI + momentum ---
            option_map = chain.calls if opt_type == "CE" else chain.puts
            # Scan wider range (±5 strikes) to find where the real action is
            strikes = [atm + i * interval for i in range(-5, 6)]

            scored: list[tuple[float, float, dict]] = []
            for strike in strikes:
                opt = option_map.get(float(strike))
                if opt is None:
                    continue
                sc, details = self._score_for_scalp(opt, atm, interval, underlying, opt_type)
                if sc > 0:
                    scored.append((strike, sc, details))

            if not scored:
                logger.warning("No valid scalping contracts for %s %s", underlying, opt_type)
                return None

            scored.sort(key=lambda x: x[1], reverse=True)
            # Log top candidates for transparency
            for rank, (st, sc, det) in enumerate(scored[:3], 1):
                o = option_map[float(st)]
                logger.info("  #%d Strike=%.0f  LTP=%.2f  Vol=%s  OI=%s  Score=%.1f  [%s]",
                            rank, st, float(o.ltp or 0),
                            f"{int(o.volume or 0):,}", f"{int(o.oi or 0):,}",
                            sc, ", ".join(f"{k}={v}" for k, v in det.items()))
            best_strike, best_score, best_details = scored[0]
            opt = option_map[float(best_strike)]

            ltp = float(opt.ltp or 0)
            oi = int(opt.oi or 0)
            volume = int(opt.volume or 0)
            bid = float(opt.bid or 0)
            ask = float(opt.ask or 0)
            spread = (ask - bid) if bid > 0 and ask > 0 else 0.0
            delta_val = float(opt.delta or 0) if hasattr(opt, 'delta') and opt.delta else 0.0
            iv_val = float(opt.iv or 0) if hasattr(opt, 'iv') and opt.iv else 0.0

            logger.info(
                "Selected: %s  LTP=%.2f  OI=%d  Vol=%d  Spread=%.2f  "
                "Delta=%.2f  IV=%.1f%%  Score=%.1f  Bias=%s  [%s]",
                opt.symbol, ltp, oi, volume, spread,
                delta_val, iv_val, best_score, bias,
                ", ".join(f"{k}={v}" for k, v in best_details.items()),
            )

            return ScanResult(
                symbol=opt.symbol,
                underlying=underlying,
                strike=int(best_strike),
                option_type=opt_type,
                expiry=expiry_date,
                ltp=ltp, oi=oi, volume=volume, spread=spread,
                score=best_score, bias=bias, bias_reason=bias_reason,
                delta=delta_val, iv=iv_val,
            )

        except Exception:
            logger.exception("OptionScannerService.scan() failed for %s", underlying)
            return None

    def scan_best(
        self,
        underlyings: list[str] | None = None,
        preferred_option_type: str | None = None,
    ) -> ScanResult | None:
        """Scan multiple underlyings, return highest-scored contract."""
        results = self.scan_top_n(n=1, underlyings=underlyings,
                                   preferred_option_type=preferred_option_type)
        return results[0] if results else None

    def scan_top_n(
        self,
        n: int = 10,
        underlyings: list[str] | None = None,
        preferred_option_type: str | None = None,
        top_per_underlying: int = 3,
        exchange: str | None = None,
        expiry_index: int = 0,
        strikes_around_atm: int = 2,
    ) -> list[ScanResult]:
        """Select option contracts by proximity to ATM strike.

        For each underlying, picks ATM ± *strikes_around_atm* strikes for
        both CE and PE.  This gives the highest-gamma contracts closest to
        spot — exactly what scalping needs.  No complex scoring for selection;
        the score is still computed for informational ranking but contracts
        are chosen purely by ATM distance.

        Example with strikes_around_atm=2, NIFTY ATM=24850:
          CE: 24750, 24800, 24850, 24900, 24950
          PE: 24750, 24800, 24850, 24900, 24950
          = 10 contracts for NIFTY alone
        """
        from app.config import settings
        _MCX_UNDERLYINGS = {"CRUDEOIL", "GOLD", "SILVER", "NATURALGAS", "GOLDM", "SILVERM", "CRUDEOILM", "COPPER", "ZINC", "ALUMINIUM", "LEAD", "NICKEL", "COTTONCANDY"}
        _default_exchange = exchange or settings.DEFAULT_EXCHANGE

        # Enforce SCANNER_MODE strict isolation
        active_underlyings = []
        for u in (underlyings or ["NIFTY", "BANKNIFTY"]):
            is_mcx = u.upper() in _MCX_UNDERLYINGS
            if settings.SCANNER_MODE == "nse_options" and is_mcx:
                logger.warning("SCANNER_MODE isolation: Dropping MCX underlying '%s' from NSE scan list.", u)
                continue
            if settings.SCANNER_MODE == "mcx_options" and not is_mcx:
                logger.warning("SCANNER_MODE isolation: Dropping NSE underlying '%s' from MCX scan list.", u)
                continue
            active_underlyings.append(u)

        if not active_underlyings:
            logger.warning("SCANNER_MODE '%s' filtered out all underlyings.", settings.SCANNER_MODE)
            return []

        results: list[ScanResult] = []
        for u in active_underlyings:
            _exchange = "MCX" if u.upper() in _MCX_UNDERLYINGS else _default_exchange
            try:
                chain = self._broker.get_option_chain(
                    underlying=u, exchange=_exchange, expiry_index=expiry_index,
                )
                if chain is None:
                    continue

                expiry_date = chain.expiry.date().isoformat()
                atm = chain.atm_strike
                interval = self._STRIKE_INTERVALS.get(u.upper(), 50)

                bias, bias_strength, bias_reason = self._detect_momentum(chain, atm, interval)

                # ATM-proximity selection: pick strikes closest to ATM
                strikes = [atm + i * interval for i in range(-strikes_around_atm, strikes_around_atm + 1)]

                for side in ("CE", "PE"):
                    option_map = chain.calls if side == "CE" else chain.puts
                    for strike in strikes:
                        opt = option_map.get(float(strike))
                        if opt is None:
                            continue

                        ltp = float(opt.ltp or 0)
                        if ltp <= 0:
                            continue  # Skip no-market contracts

                        oi = int(opt.oi or 0)
                        volume = int(opt.volume or 0)
                        bid = float(opt.bid or 0)
                        ask = float(opt.ask or 0)
                        spread = (ask - bid) if bid > 0 and ask > 0 else 0.0
                        delta_val = float(opt.delta or 0) if hasattr(opt, 'delta') and opt.delta else 0.0
                        iv_val = float(opt.iv or 0) if hasattr(opt, 'iv') and opt.iv else 0.0

                        # --- Hard filters (reject illiquid/unaffordable) ---
                        min_oi_scan = self._MIN_OI.get(u.upper(), 100_000) * self.MIN_OI_SCAN_MULTIPLIER
                        if oi < min_oi_scan:
                            continue  # Illiquid — no market depth
                        if ltp > self.MAX_PREMIUM:
                            continue  # Too expensive for scalping capital
                        if bid > 0 and ask > 0 and ltp > 0:
                            spread_pct = (ask - bid) / ltp * 100
                            if spread_pct > self.MAX_SPREAD_PCT:
                                continue  # Spread too wide — slippage kills scalps

                        # Distance from ATM (0 = ATM, 1 = 1-strike away, etc.)
                        atm_dist = abs(strike - atm) / interval if interval > 0 else 0

                        # Informational score (still useful for ranking within same distance)
                        sc, _details = self._score_for_scalp(opt, atm, interval, u, side)

                        results.append(ScanResult(
                            symbol=opt.symbol,
                            underlying=u,
                            strike=int(strike),
                            option_type=side,
                            expiry=expiry_date,
                            ltp=ltp, oi=oi, volume=volume, spread=spread,
                            score=sc, bias=bias, bias_reason=bias_reason,
                            delta=delta_val, iv=iv_val,
                        ))

            except Exception:
                logger.exception("scan_top_n: failed for %s", u)

        # Sort by: Score (momentum/volume) first, then ATM distance (tie breaker)
        def _sort_key(r: ScanResult) -> tuple:
            interval = self._STRIKE_INTERVALS.get(r.underlying.upper(), 50)
            return (-r.score, abs(r.strike - r.strike) / interval)

        # Group by underlying, then interleave for diversity
        by_underlying: dict[str, list[ScanResult]] = {}
        for r in results:
            by_underlying.setdefault(r.underlying, []).append(r)

        # Within each underlying, sort by SCORE (highest momentum/volume first)
        for u_name, u_results in by_underlying.items():
            interval = self._STRIKE_INTERVALS.get(u_name.upper(), 50)
            # Find actual ATM for this underlying (strike with smallest distance to median)
            all_strikes = [r.strike for r in u_results]
            if all_strikes:
                median_strike = sorted(all_strikes)[len(all_strikes) // 2]
            else:
                median_strike = 0
            u_results.sort(key=lambda r: (-r.score, abs(r.strike - median_strike) / interval))

        # Round-robin interleave: 1 from each underlying in turn
        # Apply top_per_underlying cap AFTER sorting so we take the best-ranked contracts
        final: list[ScanResult] = []
        iters = {u: iter(lst[:top_per_underlying]) for u, lst in by_underlying.items()}
        while len(final) < n and iters:
            exhausted = []
            for u_name in list(iters.keys()):
                if len(final) >= n:
                    break
                try:
                    final.append(next(iters[u_name]))
                except StopIteration:
                    exhausted.append(u_name)
            for u_name in exhausted:
                del iters[u_name]

        logger.info("scan_top_n: %d ATM-proximity contracts across %s, returning %d",
                     len(results), active_underlyings, len(final))
        for i, r in enumerate(final, 1):
            logger.info("  #%d %s  Strike=%d  LTP=%.2f  Delta=%.3f  OI=%s  Score=%.1f  Bias=%s",
                        i, r.symbol, r.strike, r.ltp, r.delta,
                        f"{r.oi:,}", r.score, r.bias)
        return final

    # ------------------------------------------------------------------
    # Momentum detection (scalping-optimized)
    # ------------------------------------------------------------------

    def _detect_momentum(self, chain, atm: float, interval: float) -> tuple[str, int, str]:
        """Detect momentum direction from live chain signals.

        Returns (bias, strength 0-6, reason).

        For BUYING options to scalp momentum:
        - Heavy CE volume + rising CE premium = bullish momentum → buy CE
        - Heavy PE volume + rising PE premium = bearish momentum → buy PE
        - High PCR (put writers active) = support = bullish
        - OI unwinding on one side = short covering = momentum that side
        """
        reasons: list[str] = []
        bull = 0
        bear = 0
        spot = getattr(chain, 'spot_price', 0) or atm

        # --- 1. PCR (Put-Call Ratio by OI) ---
        total_call_oi = sum(o.oi for o in chain.calls.values() if o.oi > 0)
        total_put_oi = sum(o.oi for o in chain.puts.values() if o.oi > 0)
        pcr = total_put_oi / total_call_oi if total_call_oi > 0 else 1.0

        if pcr > 1.2:
            bull += 1
            reasons.append(f"PCR={pcr:.2f} (put support → bullish)")
        elif pcr < 0.7:
            bear += 1
            reasons.append(f"PCR={pcr:.2f} (weak put support → bearish)")
        else:
            reasons.append(f"PCR={pcr:.2f} (neutral)")

        # --- 2. Live volume near ATM: where are scalpers active? ---
        # For BUYING: CE volume surge = buyers rushing in = bullish momentum
        # PE volume surge = sellers rushing in = bearish momentum
        ce_vol_atm = 0
        pe_vol_atm = 0
        for i in range(-2, 3):
            s = atm + i * interval
            ce = chain.calls.get(float(s))
            pe = chain.puts.get(float(s))
            if ce and ce.volume:
                ce_vol_atm += ce.volume
            if pe and pe.volume:
                pe_vol_atm += pe.volume

        total_vol = ce_vol_atm + pe_vol_atm
        if total_vol > 0:
            ce_ratio = ce_vol_atm / total_vol
            if ce_ratio > 0.60:
                bull += 2
                reasons.append(f"CE vol dominance {ce_ratio:.0%} near ATM ({ce_vol_atm:,} vs PE {pe_vol_atm:,})")
            elif ce_ratio < 0.40:
                bear += 2
                reasons.append(f"PE vol dominance {1 - ce_ratio:.0%} near ATM (PE {pe_vol_atm:,} vs CE {ce_vol_atm:,})")
            else:
                reasons.append(f"Vol balanced near ATM (CE {ce_ratio:.0%})")

        # --- 3. OI change: fresh buildup vs unwinding ---
        ce_oi_chg = 0
        pe_oi_chg = 0
        for i in range(-3, 4):
            s = atm + i * interval
            ce = chain.calls.get(float(s))
            pe = chain.puts.get(float(s))
            if ce and ce.prev_oi is not None and ce.oi:
                ce_oi_chg += ce.oi - ce.prev_oi
            if pe and pe.prev_oi is not None and pe.oi:
                pe_oi_chg += pe.oi - pe.prev_oi

        # For scalping: CE unwinding (shorts covering) + PE buildup = bullish
        # PE unwinding (shorts covering) + CE buildup = bearish
        if ce_oi_chg < 0 and pe_oi_chg > 0:
            bull += 1
            reasons.append(f"CE unwinding {ce_oi_chg:,} + PE buildup +{pe_oi_chg:,} (bullish)")
        elif pe_oi_chg < 0 and ce_oi_chg > 0:
            bear += 1
            reasons.append(f"PE unwinding {pe_oi_chg:,} + CE buildup +{ce_oi_chg:,} (bearish)")
        elif pe_oi_chg > ce_oi_chg * 2 and pe_oi_chg > 0:
            # Heavy PE writing = strong support = bullish
            bull += 1
            reasons.append(f"Heavy PE writing +{pe_oi_chg:,} (support building)")
        elif ce_oi_chg > pe_oi_chg * 2 and ce_oi_chg > 0:
            # Heavy CE writing = strong resistance = bearish
            bear += 1
            reasons.append(f"Heavy CE writing +{ce_oi_chg:,} (resistance building)")

        # --- 4. Max pain drift ---
        max_pain = self._calc_max_pain(chain)
        if max_pain and spot > 0:
            mp_dist_pct = (spot - max_pain) / spot * 100
            if mp_dist_pct > 0.3:
                bull += 1
                reasons.append(f"Spot {spot:.0f} above max_pain {max_pain:.0f} (+{mp_dist_pct:.1f}%)")
            elif mp_dist_pct < -0.3:
                bear += 1
                reasons.append(f"Spot {spot:.0f} below max_pain {max_pain:.0f} ({mp_dist_pct:.1f}%)")

        # --- Verdict ---
        strength = abs(bull - bear)
        if bull > bear:
            return "BULLISH", strength, "; ".join(reasons)
        elif bear > bull:
            return "BEARISH", strength, "; ".join(reasons)
        return "NEUTRAL", 0, "; ".join(reasons)

    # ------------------------------------------------------------------
    # Scalping-optimized contract scoring
    # ------------------------------------------------------------------

    def _score_for_scalp(
        self, opt, atm: float, interval: float, underlying: str, opt_type: str,
    ) -> tuple[float, dict]:
        """Score contract for scalping: gamma-first, then volume and momentum.

        Priority: Volume(25) > Gamma(20) > Momentum(20) > Delta(15) > Spread(10) > OI(10)
        Total: 100 pts.  Gamma added as key scalping metric — determines how
        fast delta grows on small underlying moves (the scalper's core edge).
        Returns (score, breakdown_dict).
        """
        score = 0.0
        details: dict[str, str] = {}
        ltp = float(opt.ltp or 0)
        oi = int(opt.oi or 0)
        vol = int(opt.volume or 0)
        bid = float(opt.bid or 0)
        ask = float(opt.ask or 0)
        strike = float(opt.strike)

        # --- Spread gate: reject illiquid contracts ---
        if bid > 0 and ask > 0 and ltp > 0:
            spread_pct = (ask - bid) / ltp * 100
            if spread_pct > self.MAX_SPREAD_PCT:
                details["rejected"] = f"spread {spread_pct:.1f}%"
                return 0.0, details
        elif ltp <= 0:
            return 0.0, {"rejected": "no LTP"}

        # --- 1. Volume — where the action is (25 pts) ---
        if vol > 0:
            v_score = min(25, 25 * math.log1p(vol) / math.log1p(5_000_000))
        else:
            v_score = 0
        score += v_score
        details["vol"] = f"{vol:,}→{v_score:.0f}pts"

        # --- 2. Gamma — delta acceleration for scalping (20 pts) ---
        gamma_val = float(opt.gamma or 0) if hasattr(opt, 'gamma') and opt.gamma else None
        if gamma_val is not None and gamma_val > 0:
            # Gamma is highest ATM; normalize relative to ATM gamma
            # Typical NIFTY ATM gamma ~0.001-0.005, BNF ~0.0005-0.002
            # Score linearly: higher gamma = better for scalping
            dist_from_atm = abs(strike - atm) / interval if interval > 0 else 0
            # ATM gamma bonus: strikes at ATM get full 20, decays with distance
            if dist_from_atm <= 0.5:
                g_score = 20
            elif dist_from_atm <= 1.5:
                g_score = 14
            elif dist_from_atm <= 2.5:
                g_score = 8
            else:
                g_score = 3
            # Boost if gamma is actually high (chain has greeks)
            # gamma × interval gives approximate delta change per strike move
            gamma_impact = gamma_val * interval
            if gamma_impact > 0.10:   # >10% delta change per strike
                g_score = min(20, g_score + 4)
            elif gamma_impact > 0.05:
                g_score = min(20, g_score + 2)
            details["gamma"] = f"{gamma_val:.4f}→{g_score}pts"
        else:
            # Fallback: use distance from ATM as gamma proxy
            dist = abs(strike - atm) / interval if interval > 0 else 0
            if dist <= 0.5:
                g_score = 20
            elif dist <= 1.5:
                g_score = 14
            elif dist <= 2.5:
                g_score = 8
            else:
                g_score = 3
            details["gamma_proxy"] = f"dist={dist:.1f}→{g_score}pts"
        score += g_score

        # --- 3. Momentum — fresh buildup + vol/OI activity (20 pts) ---
        m_score = 0.0
        if hasattr(opt, 'prev_oi') and opt.prev_oi is not None and oi > 0:
            oi_chg = oi - opt.prev_oi
            if oi_chg > 0 and opt.prev_oi > 0:
                chg_pct = oi_chg / opt.prev_oi
                m_score += min(10, 10 * min(chg_pct / 0.10, 1.0))
            elif oi_chg < 0:
                m_score -= 3

        if oi > 0 and vol > 0:
            vol_oi = vol / oi
            if vol_oi > 1.5:
                m_score += 10
            elif vol_oi > 1.0:
                m_score += 7
            elif vol_oi > 0.5:
                m_score += 4
            elif vol_oi > 0.2:
                m_score += 2

        m_score = max(0, min(20, m_score))
        score += m_score
        details["momentum"] = f"{m_score:.0f}pts"

        # --- 4. Delta / moneyness — scalping sweet spot 0.45-0.60 (15 pts) ---
        delta_val = float(opt.delta or 0) if hasattr(opt, 'delta') and opt.delta else None
        if delta_val is not None:
            abs_delta = abs(delta_val)
            if 0.45 <= abs_delta <= 0.60:
                d_score = 15  # Sweet spot for scalping
            elif 0.40 <= abs_delta <= 0.65:
                d_score = 12
            elif 0.35 <= abs_delta <= 0.70:
                d_score = 8
            elif 0.25 <= abs_delta <= 0.80:
                d_score = 4
            else:
                d_score = 1
            details["delta"] = f"{delta_val:.2f}→{d_score}pts"
        else:
            dist = abs(strike - atm) / interval if interval > 0 else 0
            if dist <= 0.5:
                d_score = 15
            elif dist <= 1.5:
                d_score = 10
            elif dist <= 2.5:
                d_score = 5
            else:
                d_score = 1
            details["moneyness"] = f"dist={dist:.1f}→{d_score}pts"
        score += d_score

        # --- 5. Spread tightness (10 pts) ---
        if bid > 0 and ask > 0 and ltp > 0:
            spread_pct = (ask - bid) / ltp * 100
            if spread_pct < 0.3:
                s_score = 10
            elif spread_pct < 0.5:
                s_score = 8
            elif spread_pct < 0.8:
                s_score = 5
            elif spread_pct < 1.0:
                s_score = 3
            else:
                s_score = 1
            details["spread"] = f"{spread_pct:.2f}%→{s_score}pts"
        else:
            s_score = 0
            details["spread"] = "no bid/ask"
        score += s_score

        # --- 6. OI — liquidity pool (10 pts, reduced from 25) ---
        min_oi = self._MIN_OI.get(underlying.upper(), 100_000)
        if oi > 0:
            o_score = min(10, 10 * math.log1p(oi) / math.log1p(min_oi * 5))
        else:
            o_score = 0
        score += o_score
        details["oi"] = f"{oi:,}→{o_score:.0f}pts"

        # --- IV (informational) ---
        iv_val = float(opt.iv or 0) if hasattr(opt, 'iv') and opt.iv else 0
        if iv_val > 0:
            details["iv"] = f"{iv_val:.1f}%"

        return round(score, 1), details

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _calc_max_pain(chain) -> float | None:
        """Calculate max pain strike."""
        if not chain.strikes:
            return None
        min_loss = float("inf")
        max_pain = None
        for strike in chain.strikes:
            total_loss = 0
            for cs, co in chain.calls.items():
                if co.oi > 0 and strike > cs:
                    total_loss += (strike - cs) * co.oi
            for ps, po in chain.puts.items():
                if po.oi > 0 and strike < ps:
                    total_loss += (ps - strike) * po.oi
            if total_loss < min_loss:
                min_loss = total_loss
                max_pain = strike
        return max_pain


class _NullOpt:
    """Sentinel for missing option in chain lookups."""
    volume = 0
    oi = 0
    ltp = 0
    bid = None
    ask = None
    prev_oi = None
    delta = None
    iv = None
    strike = 0
