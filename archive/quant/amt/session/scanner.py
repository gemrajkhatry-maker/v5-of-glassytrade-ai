"""OptionScannerService — Simple momentum-based contract selection.

Selects contracts based on:
1. Momentum direction (CE for bullish, PE for bearish)
2. Basic liquidity (OI, volume)
3. ATM proximity (gamma optimization)

No complex scoring — just follow the momentum with liquid contracts.
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from quant.contracts.sync_boundary import ensure_sync_adapter_result

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    symbol: str
    underlying: str
    strike: int
    option_type: str  # "CE" or "PE"
    expiry: str
    ltp: float
    oi: int
    volume: int
    spread: float
    score: float = 0.0
    bias: str = ""  # "BULLISH" | "BEARISH" | "NEUTRAL"
    bias_reason: str = ""
    delta: float = 0.0
    iv: float = 0.0


class OptionScannerService:
    """Simple momentum-based contract selection for MCX/NSE."""

    _SCAN_NSE_UNDERLYINGS = frozenset({"NIFTY", "BANKNIFTY", "FINNIFTY"})
    _SCAN_MCX_UNDERLYINGS = frozenset(
        {
            "CRUDEOIL",
            "NATURALGAS",
            "GOLD",
            "SILVER",
            # MCX mini / alternate roots (Dhan chain is per root; SILVER ≠ SILVERM)
            "GOLDM",
            "SILVERM",
            "CRUDEOILM",
        }
    )

    _STRIKE_INTERVALS = {
        "NIFTY": 50,
        "BANKNIFTY": 100,
        "FINNIFTY": 50,
        "CRUDEOIL": 50,
        "NATURALGAS": 5,
        "GOLD": 100,
        "GOLDM": 100,
        "SILVER": 500,
        "SILVERM": 500,
        "CRUDEOILM": 50,
    }

    _MIN_OI = {
        "NIFTY": 50_000,
        "BANKNIFTY": 150_000,
        "FINNIFTY": 30_000,
        "CRUDEOIL": 10,
        "NATURALGAS": 500,
        "GOLD": 0,
        "GOLDM": 0,
        "SILVER": 0,
        "SILVERM": 0,
        "CRUDEOILM": 10,
    }

    def __init__(self, broker, default_underlyings: list[str] | None = None) -> None:
        self._broker = broker
        self._default_underlyings = default_underlyings

    @staticmethod
    def _score_contract(strike, atm, interval, oi, vol, opt, ltp, bid, ask, underlying_upper, bias=None, opt_type=None, median_vol=1000) -> tuple:
        """Score an option contract based on ATM proximity, liquidity, and momentum.
        
        Returns (score, atm_dist, delta_val).
        """
        atm_dist = abs(strike - atm) / interval if interval > 0 else 0
        delta_val = abs(float(opt.delta or 0.5))

        # DEAD market check
        if vol <= 0:
            return 0, atm_dist, delta_val

        score = 0
        # ATM proximity (40 pts max)
        score += max(0, 40 - (atm_dist * 15))
        # OI liquidity scaling (30 pts max)
        min_oi = OptionScannerService._MIN_OI.get(underlying_upper, 5000)
        if min_oi > 0:
            score += min(30, (oi / min_oi) * 10)
        else:
            score += 15
        # Volume momentum scaling (20 pts max) — relative to chain median, not absolute
        if median_vol > 0:
            score += min(20, (vol / median_vol) * 5)

        # Delta sweet spot +10 pts
        if 0.40 <= delta_val <= 0.60:
            score += 10

        # Momentum alignment (15 pts): CE with BULLISH bias, PE with BEARISH bias
        if bias == "BULLISH":
            score += 15 if opt_type == "CE" else -5
        elif bias == "BEARISH":
            score += 15 if opt_type == "PE" else -5

        # Dynamic Spread Penalty (-20 pts max)
        if ltp > 0 and bid > 0 and ask > 0:
            spread_pct = (ask - bid) / ltp * 100
            if spread_pct > 0.5:
                score -= min(20, (spread_pct - 0.5) * 10)

        return score, atm_dist, delta_val

    def _process_contract(self, u, opt_type, strike, atm, interval, option_map,
                          bullish_only, bias, bias_reason, chain, is_mcx, median_vol=1000):
        """Process a single option contract — applies filters, scores, returns ScanResult or None."""
        # Bullish-only filter: skip OTM
        if bullish_only:
            if opt_type == "CE" and strike > atm:
                return None
            if opt_type == "PE" and strike < atm:
                return None

        opt = option_map.get(float(strike))
        if opt is None:
            return None

        ltp = float(opt.ltp or 0)
        # Scalping filter: premium in valid range
        mcx_min, mcx_max, nse_min, nse_max = 20, 50000, 20, 800
        ltp_min, ltp_max = (mcx_min, mcx_max) if is_mcx else (nse_min, nse_max)
        if not (ltp_min <= ltp <= ltp_max):
            return None

        vol = int(opt.volume or 0)
        oi = int(opt.oi or 0)
        min_oi = self._MIN_OI.get(u.upper(), 5000)
        if oi < min_oi:
            return None

        bid = float(opt.bid or 0)
        ask = float(opt.ask or 0)
        if bid > 0 and ask > 0 and ltp > 0:
            spread_pct = (ask - bid) / ltp * 100
            if spread_pct > 4.0:
                return None

        # Score
        score, _, delta_val = self._score_contract(
            strike, atm, interval, oi, vol,
            opt, ltp, bid, ask, u.upper(), bias,
            opt_type=opt_type, median_vol=median_vol,
        )
        logger.debug(
            "SCORED: %s %s %d: ltp=%.2f oi=%d vol=%d score=%.0f sym=%s",
            u,
            opt_type,
            strike,
            ltp,
            oi,
            vol,
            score,
            opt.symbol,
        )

        return ScanResult(
            symbol=opt.symbol, underlying=u, strike=strike,
            option_type=opt_type, expiry=chain.expiry.date().isoformat(),
            ltp=ltp, oi=oi, volume=vol,
            spread=ask - bid if bid > 0 and ask > 0 else 0,
            score=score, bias=bias, bias_reason=bias_reason,
            delta=delta_val, iv=float(opt.iv or 0) if hasattr(opt, "iv") else 0,
        )

    def _scan_underlying_for_contracts(
        self,
        u: str,
        exchange: str | None,
        expiry_index: int,
        strikes_around_atm: int,
        bullish_only: bool,
        preferred_option_type: str | None = None,
    ) -> list[ScanResult]:
        """Fetch chain for one underlying and return scored contracts (CE+PE near ATM)."""
        out: list[ScanResult] = []
        u_upper = u.upper()
        if u_upper in self._SCAN_MCX_UNDERLYINGS:
            _exchange = "MCX"
        elif u_upper in self._SCAN_NSE_UNDERLYINGS:
            _exchange = "NFO"
        else:
            _exchange = exchange or "MCX"

        effective_expiry_index = expiry_index
        chain = ensure_sync_adapter_result(
            "broker.get_option_chain",
            self._broker.get_option_chain,
            underlying=u,
            exchange=_exchange,
            expiry_index=effective_expiry_index,
        )
        while chain is not None and effective_expiry_index < 3:
            expiry_date = (
                chain.expiry.date()
                if hasattr(chain.expiry, "date")
                else chain.expiry
            )
            if expiry_date <= date.today():
                effective_expiry_index += 1
                logger.info(
                    "%s: exp %s is today/past — advancing to index %d",
                    u,
                    expiry_date,
                    effective_expiry_index,
                )
                chain = ensure_sync_adapter_result(
                    "broker.get_option_chain",
                    self._broker.get_option_chain,
                    underlying=u,
                    exchange=_exchange,
                    expiry_index=effective_expiry_index,
                )
            else:
                break

        if chain is None:
            logger.info("%s: option chain returned None — skipping", u)
            return out

        atm = chain.atm_strike
        interval = self._STRIKE_INTERVALS.get(u.upper(), 50)

        all_strikes = sorted(chain.calls.keys())
        near_atm = [s for s in all_strikes if abs(s - atm) <= interval * 3]
        logger.info(
            "%s: chain OK — spot=%.0f atm=%.0f step=%.0f strikes_near_atm=%s",
            u,
            chain.spot_price,
            atm,
            interval,
            near_atm[:10],
        )

        bias, bias_strength, bias_reason = self._detect_momentum(chain, atm, interval)
        logger.info(
            "MOMENTUM: %s — %s (strength=%d) [calls=%d puts=%d atm=%.0f]",
            u,
            bias,
            bias_strength,
            len(chain.calls),
            len(chain.puts),
            atm,
        )
        strikes = [
            atm + i * interval
            for i in range(-strikes_around_atm, strikes_around_atm + 1)
        ]
        is_mcx = u.upper() in (
            "CRUDEOIL",
            "CRUDEOILM",
            "GOLD",
            "GOLDM",
            "SILVER",
            "SILVERM",
            "NATURALGAS",
            "COPPER",
        )

        # ponytail: relative liquidity — normalize vol against chain median so
        # BANKNIFTY's naturally larger volumes don't outrank FINNIFTY. Compute
        # median once per chain instead of scoring absolute volume.
        all_vols = sorted(
            int(o.volume or 0)
            for opt_map in (chain.calls, chain.puts)
            for o in opt_map.values()
            if (o.volume or 0) > 0
        )
        median_vol = all_vols[len(all_vols) // 2] if all_vols else 1000

        option_types = [("CE", chain.calls), ("PE", chain.puts)]
        if preferred_option_type:
            pref = preferred_option_type.upper()
            option_types = [t for t in option_types if t[0] == pref]

        for opt_type, option_map in option_types:
            for strike in strikes:
                result = self._process_contract(
                    u,
                    opt_type,
                    int(strike),
                    atm,
                    interval,
                    option_map,
                    bullish_only,
                    bias,
                    bias_reason,
                    chain,
                    is_mcx=is_mcx,
                    median_vol=median_vol,
                )
                if result:
                    out.append(result)
        return out

    def scan_top_n(
        self,
        n: int = 3,
        underlyings: list[str] | None = None,
        preferred_option_type: str | None = None,
        top_per_underlying: int = 3,
        exchange: str | None = None,
        expiry_index: int = 0,
        strikes_around_atm: int = 2,
        bullish_only: bool = False,  # Allow both CE and PE by default
    ) -> list[ScanResult]:
        """Select top N contracts based on momentum and liquidity.

        Args:
            bullish_only: When True, only selects contracts aligned with a bullish thesis:
                - CE: ATM or ITM (strike <= ATM) — direct bullish bet
                - PE: ATM or ITM (strike >= ATM) — high-delta put, bullish if underlying rallies
        """

        results: list[ScanResult] = []

        # Use injected default underlyings if not specified
        if underlyings is None:
            underlyings = self._default_underlyings or []

        if not underlyings:
            if exchange == "MCX" or (not exchange and "MCX" in str(self._broker)):
                underlyings = ["CRUDEOIL", "NATURALGAS"]
            else:
                underlyings = ["NIFTY", "BANKNIFTY", "FINNIFTY"]

        parallel = os.environ.get("OPTION_SCANNER_PARALLEL_UNDERLYINGS", "").lower() in (
            "1",
            "true",
            "yes",
        )
        max_workers = max(
            1,
            min(
                len(underlyings),
                int(os.environ.get("OPTION_SCANNER_MAX_WORKERS", "4")),
            ),
        )

        if parallel and len(underlyings) > 1:
            merged: list[ScanResult] = []
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {
                    pool.submit(
                        self._scan_underlying_for_contracts,
                        u,
                        exchange,
                        expiry_index,
                        strikes_around_atm,
                        bullish_only,
                        preferred_option_type,
                    ): u
                    for u in underlyings
                }
                for fut in as_completed(futures):
                    sym = futures[fut]
                    try:
                        merged.extend(fut.result())
                    except Exception as e:
                        logger.error(
                            "scan_top_n failed for %s: %s", sym, e, exc_info=True
                        )
            results = merged
        else:
            for u in underlyings:
                try:
                    results.extend(
                        self._scan_underlying_for_contracts(
                            u,
                            exchange,
                            expiry_index,
                            strikes_around_atm,
                            bullish_only,
                            preferred_option_type,
                        )
                    )
                except Exception as e:
                    logger.error("scan_top_n failed for %s: %s", u, e)

        # Group by underlying and take top N per underlying first
        from collections import defaultdict

        grouped = defaultdict(list)
        for r in results:
            grouped[r.underlying].append(r)

        # Per-underlying shortlists (best contracts first within each root).
        per_u: dict[str, list[ScanResult]] = {}
        for u_name, u_results in grouped.items():
            ranked = sorted(u_results, key=lambda r: -r.score)
            cap = max(1, int(top_per_underlying))
            per_u[u_name] = ranked[:cap]

        # Round-robin across roots ordered by *best* score on that root.
        # Pure global sort by score used to drop entire underlyings (e.g. GOLDM) when
        # CRUDEOIL/NATURALGAS dominated the top-N — mini metals never got a slot even
        # with a healthy chain.
        u_ranked = sorted(
            per_u.keys(),
            key=lambda u: per_u[u][0].score if per_u[u] else -1.0,
            reverse=True,
        )
        final: list[ScanResult] = []
        round_idx = 0
        while len(final) < n and per_u:
            took_any = False
            for u in u_ranked:
                if len(final) >= n:
                    break
                lst = per_u.get(u, [])
                if round_idx < len(lst):
                    final.append(lst[round_idx])
                    took_any = True
            if not took_any:
                break
            round_idx += 1

        logger.info(
            "scan_top_n balanced: roots_with_chain=%s picked_roots=%s",
            sorted(grouped.keys()),
            [r.underlying for r in final],
        )

        # If no contracts found (no momentum), return ATM contracts for monitoring
        if not final:
            logger.info("No momentum setups — selecting ATM contracts for monitoring")
            
            # Determine exchange for fallback
            _fb_exchange = exchange or ("MCX" if "MCX" in str(self._broker) else "NFO")
            
            # Use provided underlyings or detect from exchange
            if not underlyings:
                if _fb_exchange == "MCX":
                    _fb_underlyings = [
                        "CRUDEOIL",
                        "NATURALGAS",
                        "GOLD",
                        "GOLDM",
                        "SILVER",
                        "SILVERM",
                    ]
                else:
                    _fb_underlyings = ["NIFTY", "BANKNIFTY", "FINNIFTY"]
            else:
                _fb_underlyings = underlyings

            for u in _fb_underlyings:
                try:
                    # Auto-detect exchange for this underlying
                    u_upper = u.upper()
                    _u_exchange = _fb_exchange
                    if u_upper in self._SCAN_MCX_UNDERLYINGS:
                        _u_exchange = "MCX"
                    elif u_upper in self._SCAN_NSE_UNDERLYINGS:
                        _u_exchange = "NFO"

                    chain = ensure_sync_adapter_result(
                        "broker.get_option_chain",
                        self._broker.get_option_chain,
                        underlying=u,
                        exchange=_u_exchange,
                        expiry_index=expiry_index,
                    )
                    if chain is None:
                        continue
                    atm = chain.atm_strike
                    
                    # Get BOTH CE and PE for a balanced view in neutral markets
                    for opt_type, opt_map in [("CE", chain.calls), ("PE", chain.puts)]:
                        atm_opt = opt_map.get(float(atm))
                        if atm_opt and float(atm_opt.ltp or 0) > 0:
                            final.append(
                                ScanResult(
                                    symbol=atm_opt.symbol,
                                    underlying=u,
                                    strike=int(atm),
                                    option_type=opt_type,
                                    expiry=chain.expiry.date().isoformat()
                                    if hasattr(chain.expiry, "date")
                                    else "",
                                    ltp=float(atm_opt.ltp),
                                    oi=int(atm_opt.oi or 0),
                                    volume=int(atm_opt.volume or 0),
                                    spread=float(atm_opt.ask or 0) - float(atm_opt.bid or 0),
                                    score=50,  # Neutral score
                                    bias="NEUTRAL",
                                    bias_reason="Monitoring ATM (No strong momentum)",
                                    delta=0.5 if opt_type == "CE" else 0.5,
                                    iv=float(atm_opt.iv or 0) if hasattr(atm_opt, "iv") else 0.0,
                                )
                            )
                            logger.info("Fallback: Selected %s for monitoring", atm_opt.symbol)
                except Exception as e:
                    logger.debug("Fallback scan failed for %s: %s", u, e)
                    continue

        logger.info(
            "scan_top_n: %d contracts found, returning %d",
            len(results) + len(final),
            len(final),
        )
        for i, r in enumerate(final, 1):
            logger.info(
                "  #%d %s Strike=%d LTP=%.2f Score=%.0f",
                i,
                r.symbol,
                r.strike,
                r.ltp,
                r.score,
            )

        return final

    def _detect_momentum(self, chain, atm, interval):
        """Simple momentum detection from option chain."""
        # CE vs PE volume ratio near ATM
        ce_vol = sum(int(o.volume or 0) for o in chain.calls.values())
        pe_vol = sum(int(o.volume or 0) for o in chain.puts.values())

        if ce_vol > pe_vol * 1.5:
            return "BULLISH", 3, f"CE volume {ce_vol} > PE volume {pe_vol}"
        elif pe_vol > ce_vol * 1.5:
            return "BEARISH", 3, f"PE volume {pe_vol} > CE volume {ce_vol}"
        else:
            return "NEUTRAL", 0, f"Balanced CE={ce_vol} PE={pe_vol}"


class ContractSwitchGuard:
    """Prevents switching contracts during open trades."""

    def __init__(self):
        self._current_contract = None
        self._current_score = 0.0
        self._last_score_time = 0.0
        self._has_open_trade = False

    def set_open_trade(self, has_trade: bool):
        self._has_open_trade = has_trade

    def should_switch(self, new_contract, new_score, current_time):
        if self._has_open_trade:
            return False  # NEVER switch during open trade
        if self._current_contract is None:
            self._current_contract = new_contract
            self._current_score = new_score
            self._last_score_time = current_time
            return True
        if new_contract == self._current_contract:
            return False
        if current_time - self._last_score_time < 300:  # 5 min cooldown
            return False
        # Switch only if score delta > 15 pts
        if abs(new_score - self._current_score) > 15:
            self._current_contract = new_contract
            self._current_score = new_score
            self._last_score_time = current_time
            return True
        return False
