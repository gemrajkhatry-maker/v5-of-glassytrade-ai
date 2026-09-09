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
from datetime import date, datetime, timedelta
from quant.amt.profile.gamma import compute_gamma_exposure
from quant.contracts.instrument_registry import DEFAULT_REGISTRY, UnknownInstrumentError
from quant.contracts.sync_boundary import ensure_sync_adapter_result, invoke_sync_or_async
from quant.contracts.timezones import IST, today_ist

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
    expected_roc: float = 0.0
    timesfm_edge: float = 0.0
    theta_viable: bool = True


class OptionScannerService:
    """Simple momentum-based contract selection for MCX/NSE."""

    _SCAN_NSE_UNDERLYINGS = DEFAULT_REGISTRY.nse_session_roots()
    _SCAN_MCX_UNDERLYINGS = DEFAULT_REGISTRY.mcx_roots()
    _STRIKE_INTERVALS = {
        s.root: int(s.strike_interval) for s in DEFAULT_REGISTRY.specs()
    }
    _MIN_OI = {s.root: s.min_oi for s in DEFAULT_REGISTRY.specs()}

    @staticmethod
    def dhan_exchange_for(underlying: str) -> str:
        """Dhan API exchange code (NFO/BFO/MCX). Unknown roots raise."""
        return DEFAULT_REGISTRY.resolve(underlying).dhan_exchange

    def __init__(self, broker, default_underlyings: list[str] | None = None) -> None:
        self._broker = broker
        self._default_underlyings = default_underlyings
        # Big-move mode: only trade when premium is cheap (IV low), enough
        # time to expiry, and in the scalping premium band. Env-driven so no
        # caller plumbing is needed. ponytail: straddle-% is the IV proxy we
        # can compute from the chain; no IV history exists to build a real IVR.
        self.big_move_mode = os.environ.get("SCANNER_BIG_MOVE", "").lower() in (
            "1",
            "true",
            "yes",
        )
        self.big_move_max_straddle_pct = float(
            os.environ.get("SCANNER_BIG_MOVE_MAX_STRADDLE_PCT", "0.02")
        )
        self.big_move_min_dte = int(os.environ.get("SCANNER_BIG_MOVE_MIN_DTE", "2"))

    def _fetch_historical_closes(self, symbol: str, limit: int = 32) -> list[float]:
        """Safely fetch historical candle close prices from broker (sync or async)."""
        if not hasattr(self._broker, "fetch_history"):
            return []
        try:
            result = invoke_sync_or_async(
                self._broker.fetch_history,
                symbol,
                interval="5m",
                limit=limit,
            )
            if result:
                closes = [
                    float(getattr(c, "close", 0.0) or getattr(c, "c", 0.0) or 0.0)
                    for c in result
                ]
                return [c for c in closes if c > 0]
        except Exception as e:
            logger.debug("History fetch for %s failed: %s", symbol, e)
        return []

    @staticmethod
    def _score_contract(
        strike, atm, interval, oi, vol, opt, ltp, bid, ask, underlying_upper,
        bias=None, opt_type=None, median_vol=1000, timesfm_forecast=None,
    ) -> tuple:
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

        # Momentum alignment (25 pts): CE with BULLISH bias, PE with BEARISH bias (-10 if opposing)
        if bias == "BULLISH":
            score += 25 if opt_type == "CE" else -10
        elif bias == "BEARISH":
            score += 25 if opt_type == "PE" else -10

        # Dynamic Spread Penalty (-20 pts max)
        if ltp > 0 and bid > 0 and ask > 0:
            spread_pct = (ask - bid) / ltp * 100
            if spread_pct > 0.5:
                score -= min(20, (spread_pct - 0.5) * 10)

        # TimesFM payoff simulation enrichment & model-driven scoring
        if timesfm_forecast is not None and ltp > 0:
            try:
                from quant.decision.timesfm_option_selector import simulate_contract_payoff
                dir_str = "LONG" if bias == "BULLISH" else ("SHORT" if bias == "BEARISH" else "FLAT")
                sim = simulate_contract_payoff(
                    opt=opt,
                    strike=strike,
                    option_type=opt_type or "CE",
                    underlying=underlying_upper,
                    expiry_str="",
                    forecast=timesfm_forecast,
                    direction=dir_str,
                )
                if sim is not None:
                    if not sim.is_theta_viable:
                        score -= 25
                    score += min(25.0, sim.timesfm_edge * 10.0)
                    score += min(20.0, max(0.0, sim.expected_roc * 50.0))
                    score += (sim.composite_score * 0.5)
                    try:
                        setattr(opt, "_timesfm_sim", sim)
                    except Exception:
                        pass
            except Exception as e:
                logger.debug("TimesFM payoff simulation scoring error: %s", e)

        return score, atm_dist, delta_val

    @staticmethod
    def _straddle_pct(chain, atm):
        """ATM straddle premium as a fraction of spot — cheap-IV proxy.

        Skip the whole chain when the market already prices in a large move
        (expensive premium); big-move scalps only pay off from a low base.
        """
        ce = chain.calls.get(float(atm))
        pe = chain.puts.get(float(atm))
        if not ce or not pe:
            return None
        premium = float(ce.ltp or 0) + float(pe.ltp or 0)
        spot = float(getattr(chain, "spot_price", 0) or chain.atm_strike or 0)
        if premium <= 0 or spot <= 0:
            return None
        return premium / spot

    def _process_contract(self, u, opt_type, strike, atm, interval, option_map,
                          bullish_only, bias, bias_reason, chain, is_mcx, median_vol=1000,
                          big_move_mode=False, timesfm_forecast=None):
        """Process a single option contract — applies filters, scores, returns ScanResult or None."""
        # Bullish-only filter: skip OTM
        if bullish_only:
            if opt_type == "CE" and strike > atm:
                return None
            if opt_type == "PE" and strike < atm:
                return None

        # Hard momentum filter: only trade aligned contracts
        # NEUTRAL = no directional edge = skip (will fall to fallback if needed)
        if bias == "NEUTRAL":
            return None

        # Direction alignment: don't buy puts when momentum is bullish
        if bias == "BULLISH" and opt_type == "PE":
            return None
        if bias == "BEARISH" and opt_type == "CE":
            return None

        opt = option_map.get(float(strike))
        if opt is None:
            return None

        ltp = float(opt.ltp or 0)
        # Scalping filter: premium in valid range
        mcx_min, mcx_max, nse_min, nse_max = 20, 50000, 20, 800
        if big_move_mode and not is_mcx:
            nse_min, nse_max = 25, 400
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
            timesfm_forecast=timesfm_forecast,
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

        if hasattr(chain.expiry, "date"):
            expiry_str = chain.expiry.date().isoformat()
        elif hasattr(chain.expiry, "isoformat"):
            expiry_str = chain.expiry.isoformat()
        else:
            expiry_str = str(chain.expiry)
        sim = getattr(opt, "_timesfm_sim", None)
        return ScanResult(
            symbol=opt.symbol, underlying=u, strike=strike,
            option_type=opt_type, expiry=expiry_str,
            ltp=ltp, oi=oi, volume=vol,
            spread=ask - bid if bid > 0 and ask > 0 else 0,
            score=score, bias=bias, bias_reason=bias_reason,
            delta=delta_val, iv=float(opt.iv or 0) if hasattr(opt, "iv") else 0,
            expected_roc=float(getattr(sim, "expected_roc", 0.0) or 0.0),
            timesfm_edge=float(getattr(sim, "timesfm_edge", 0.0) or 0.0),
            theta_viable=bool(getattr(sim, "is_theta_viable", True)),
        )

    def _scan_underlying_for_contracts(
        self,
        u: str,
        exchange: str | None,
        expiry_index: int,
        strikes_around_atm: int,
        bullish_only: bool,
        preferred_option_type: str | None = None,
        big_move_mode: bool = False,
        chains_out: dict[str, Any] | None = None,
        timesfm_forecast: Any | None = None,
    ) -> list[ScanResult]:
        """Fetch chain for one underlying and return scored contracts (CE+PE near ATM)."""
        out: list[ScanResult] = []
        u_upper = u.upper()
        try:
            _exchange = self.dhan_exchange_for(u_upper)
        except UnknownInstrumentError:
            logger.error("%s: unknown instrument root — refusing silent MCX default", u)
            return out

        effective_expiry_index = expiry_index
        chain = ensure_sync_adapter_result(
            "broker.get_option_chain",
            self._broker.get_option_chain,
            underlying=u,
            exchange=_exchange,
            expiry_index=effective_expiry_index,
        )
        while chain is not None:
            expiry_date = (
                chain.expiry.date()
                if hasattr(chain.expiry, "date")
                else (date.fromisoformat(chain.expiry) if isinstance(chain.expiry, str) else chain.expiry)
            )
            if expiry_date >= today_ist():
                break
            if effective_expiry_index >= 3:
                logger.info("%s: no live expiry up to index 3 — skipping", u)
                chain = None
                break
            effective_expiry_index += 1
            logger.info(
                "%s: exp %s is past — advancing to index %d",
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

        if chain is None:
            logger.info("%s: option chain returned None — skipping", u)
            return out

        try:
            lot_size = DEFAULT_REGISTRY.resolve(u).lot_size
        except Exception:
            lot_size = 1

        try:
            spot_val = float(getattr(chain, "spot_price", 0) or chain.atm_strike or 0)
            calls_oi = {float(k): getattr(v, "oi", 0) for k, v in getattr(chain, "calls", {}).items()}
            puts_oi = {float(k): getattr(v, "oi", 0) for k, v in getattr(chain, "puts", {}).items()}
            calls_iv = {float(k): getattr(v, "iv", 0.18) for k, v in getattr(chain, "calls", {}).items() if getattr(v, "iv", 0)}
            puts_iv = {float(k): getattr(v, "iv", 0.18) for k, v in getattr(chain, "puts", {}).items() if getattr(v, "iv", 0)}
            strikes = sorted(set(calls_oi.keys()) | set(puts_oi.keys()))
            chain.gex = compute_gamma_exposure(
                spot=spot_val,
                strikes=strikes,
                calls_oi=calls_oi,
                puts_oi=puts_oi,
                calls_iv=calls_iv,
                puts_iv=puts_iv,
                lot_size=lot_size,
            )
        except Exception:
            logger.debug("Failed computing GEX for %s", u, exc_info=True)
            chain.gex = None

        if chains_out is not None:
            chains_out[u] = chain

        atm = chain.atm_strike
        interval = self._STRIKE_INTERVALS.get(u.upper(), 50)
        listed = sorted(chain.calls.keys())
        if listed:
            # ponytail: snap to nearest listed strike — broker atm prints
            # (e.g. 23437) off the grid make every candidate lookup miss.
            atm = min(listed, key=lambda s: abs(s - atm))

        if big_move_mode:
            dte = (expiry_date - today_ist()).days
            if dte < self.big_move_min_dte:
                logger.info(
                    "%s: big-move skipped — DTE %d < %d",
                    u,
                    dte,
                    self.big_move_min_dte,
                )
                return out
            straddle_pct = self._straddle_pct(chain, atm)
            if straddle_pct is None or straddle_pct > self.big_move_max_straddle_pct:
                logger.info(
                    "%s: big-move skipped — ATM straddle %.2f%% of spot > %.2f%%",
                    u,
                    (straddle_pct or 0) * 100,
                    self.big_move_max_straddle_pct * 100,
                )
                return out

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

        effective_tfm_forecast = timesfm_forecast
        if effective_tfm_forecast is None:
            tfm_enabled = (
                os.getenv("TIMESFM_CONTRACT_SELECTION", "true").strip().lower() in ("1", "true", "yes")
                or os.getenv("TIMESFM_ADVISOR_ENABLED", "false").strip().lower() in ("1", "true", "yes")
            )
            if tfm_enabled:
                try:
                    from quant.decision.timesfm_engine import get_timesfm_model
                    from quant.decision.timesfm_agents import TimesFMForecast
                    import numpy as np

                    model = get_timesfm_model()
                    if model is not None:
                        prices: list[float] = []
                        fut_sym = None
                        if hasattr(self._broker, "get_nearest_futures"):
                            try:
                                fut_sym = self._broker.get_nearest_futures(u, exchange=_exchange)
                            except Exception:
                                fut_sym = None
                        if not fut_sym:
                            now = datetime.now(tz=IST)
                            month_str = now.strftime("%b").upper()
                            fut_sym = f"{u.upper()} {month_str} FUT"

                        prices = self._fetch_historical_closes(fut_sym, limit=32)
                        if len(prices) < 32:
                            root_prices = self._fetch_historical_closes(u, limit=32)
                            if len(root_prices) > len(prices):
                                prices = root_prices

                        if len(prices) < 32 and hasattr(self._broker, "get_broker"):
                            try:
                                raw_b = self._broker.get_broker()
                                if hasattr(raw_b, "get_historical") and hasattr(self._broker, "_make_instrument"):
                                    inst = self._broker._make_instrument(fut_sym or u)
                                    end_dt = datetime.now(tz=IST)
                                    start_dt = end_dt - timedelta(days=5)
                                    df = raw_b.get_historical(instrument=inst, from_date=start_dt, to_date=end_dt, interval="5")
                                    if df is not None and not df.empty and "close" in df.columns:
                                        prices = [float(c) for c in df["close"].tail(32)]
                            except Exception as e:
                                logger.debug("%s: raw_broker.get_historical skipped: %s", u, e)
                        if not prices and hasattr(self._broker, "get_quote"):
                            try:
                                q = self._broker.get_quote(u)
                                p = float(getattr(q, "ltp", 0.0) or getattr(q, "price", 0.0) or 0.0)
                                if p > 0:
                                    prices = [p] * 32
                            except Exception:
                                pass
                        if not prices and hasattr(chain, "spot_price") and chain.spot_price:
                            prices = [float(chain.spot_price)] * 32

                        if prices:
                            if len(prices) < 32:
                                prices = [prices[0]] * (32 - len(prices)) + prices
                            np_prices = np.array(prices[-32:], dtype=np.float32)
                            res = model.predict(context=np_prices, horizon=32, return_quantiles=True)
                            quantiles = getattr(res, "quantiles", None)
                            curr_price = float(np_prices[-1])
                            if quantiles is not None and len(quantiles) > 0:
                                p50 = quantiles[:, 4]
                                p10 = quantiles[:, 0]
                                p90 = quantiles[:, 8]
                                q_spread = float(np.mean(p90 - p10))
                            else:
                                p50 = np.full(32, curr_price)
                                p10 = np.full(32, curr_price * 0.998)
                                p90 = np.full(32, curr_price * 1.002)
                                q_spread = 0.0

                            mean_forecast = float(p50[-1])
                            pct_change = (mean_forecast - curr_price) / max(curr_price, 1e-4)
                            effective_tfm_forecast = TimesFMForecast(
                                horizon=32,
                                p50_path=p50,
                                p10_path=p10,
                                p90_path=p90,
                                q_spread=q_spread,
                                mean_forecast=mean_forecast,
                                pct_change=pct_change,
                                forecast_steps=["LONG" if p > curr_price else "SHORT" for p in p50],
                                curr_price=curr_price,
                                lat_ms=5.0,
                            )
                            logger.info("%s: TimesFM auto-forecasted (drift=%.2f%%, spread=%.2f, candles=%d)", u, pct_change * 100, q_spread, len(prices))
                except Exception as e:
                    logger.debug("%s: TimesFM auto-forecast skipped: %s", u, e)

        bias, bias_strength, bias_reason = self._detect_momentum(chain, atm, interval, timesfm_forecast=effective_tfm_forecast)
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
        is_mcx = u.upper() in DEFAULT_REGISTRY.mcx_roots()

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
                    big_move_mode=big_move_mode,
                    timesfm_forecast=effective_tfm_forecast,
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
        big_move_mode: bool | None = None,
        underlying_priority: list[str] | None = None,
        chains_out: dict[str, Any] | None = None,
        timesfm_forecasts: dict[str, Any] | None = None,
    ) -> list[ScanResult]:
        """Select top N contracts based on momentum and liquidity.

        Args:
            bullish_only: When True, only selects contracts aligned with a bullish thesis:
                - CE: ATM or ITM (strike <= ATM) — direct bullish bet
                - PE: ATM or ITM (strike >= ATM) — high-delta put, bullish if underlying rallies
            big_move_mode: When True (or SCANNER_BIG_MOVE env), only trade when
                premium is cheap: skip chains whose ATM straddle is a large % of
                spot (IV rich), require >= big_move_min_dte DTE, and cap NSE
                premium at 25-400 for scalping ROI.
            chains_out: Optional dict to receive fetched option chains for GEX / levels.
        """

        results: list[ScanResult] = []
        if big_move_mode is None:
            big_move_mode = self.big_move_mode

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

        cached_chains: dict[str, Any] = chains_out if chains_out is not None else {}
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
                        big_move_mode,
                        chains_out=cached_chains,
                        timesfm_forecast=timesfm_forecasts.get(u) if timesfm_forecasts else None,
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
                    tfm_fc = timesfm_forecasts.get(u) if timesfm_forecasts else None
                    results.extend(
                        self._scan_underlying_for_contracts(
                            u,
                            exchange,
                            expiry_index,
                            strikes_around_atm,
                            bullish_only,
                            preferred_option_type,
                            big_move_mode,
                            chains_out=cached_chains,
                            timesfm_forecast=tfm_fc,
                        )
                    )
                except Exception as e:
                    logger.error("scan_top_n failed for %s: %s", u, e)

        per_u = self._rank_per_underlying(results, preferred_option_type, top_per_underlying)

        # Ensure every underlying root has active contracts represented
        if not big_move_mode:
            for idx, u in enumerate(underlyings):
                if u not in per_u or not per_u[u]:
                    fb = self._fallback_atm([u], expiry_index, chains=cached_chains)
                    if fb:
                        cap = max(1, int(top_per_underlying))
                        if cap == 1 and idx % 2 == 1 and len(fb) > 1:
                            # Alternate CE/PE across roots when cap is 1
                            per_u[u] = [fb[1]]
                        else:
                            per_u[u] = fb[:cap]

        final = self._round_robin(n, per_u, underlying_priority)

        logger.info(
            "scan_top_n balanced: roots_with_chain=%s picked_roots=%s",
            sorted(per_u.keys()),
            [r.underlying for r in final],
        )

        # If still no contracts found, return ATM contracts for all underlyings
        if not final and not big_move_mode:
            final = self._fallback_atm(underlyings, expiry_index, chains=cached_chains)

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

    def _detect_momentum(self, chain, atm, interval, timesfm_forecast=None):
        """Momentum from TimesFM forecast when available, else near-ATM volume."""
        if timesfm_forecast is not None:
            pct = getattr(timesfm_forecast, "pct_change", 0.0)
            steps = getattr(timesfm_forecast, "forecast_steps", [])
            long_steps = sum(1 for s in steps if s == "LONG")
            short_steps = sum(1 for s in steps if s == "SHORT")
            total_steps = len(steps) or 1
            if pct > 0.0005 or (pct > 0.0002 and (long_steps / total_steps) >= 0.60):
                return "BULLISH", 4, f"TimesFM upward drift {pct * 100:.2f}%"
            elif pct < -0.0005 or (pct < -0.0002 and (short_steps / total_steps) >= 0.60):
                return "BEARISH", 4, f"TimesFM downward drift {pct * 100:.2f}%"

        interval = interval or 50
        near = {s for s in chain.calls if abs(s - atm) <= 2 * interval} | {
            s for s in chain.puts if abs(s - atm) <= 2 * interval
        }
        ce_vol = sum(int(chain.calls[s].volume or 0) for s in near if s in chain.calls)
        pe_vol = sum(int(chain.puts[s].volume or 0) for s in near if s in chain.puts)

        # OI-weighted tie-breaker: if vol is equal, check near-ATM OI
        if ce_vol == pe_vol == 0:
            ce_oi = sum(int(chain.calls[s].oi or 0) for s in near if s in chain.calls)
            pe_oi = sum(int(chain.puts[s].oi or 0) for s in near if s in chain.puts)
            ce_vol, pe_vol = ce_oi, pe_oi  # fall back to OI

        if ce_vol > pe_vol * 1.5:
            return "BULLISH", 3, f"Near-ATM CE vol {ce_vol} > PE vol {pe_vol}"
        elif pe_vol > ce_vol * 1.5:
            return "BEARISH", 3, f"Near-ATM PE vol {pe_vol} > CE vol {ce_vol}"
        return "NEUTRAL", 0, f"Balanced near-ATM CE={ce_vol} PE={pe_vol}"

    def _rank_per_underlying(
        self,
        results: list[ScanResult],
        preferred_option_type: str | None,
        top_per_underlying: int,
    ) -> dict[str, list[ScanResult]]:
        """Group results by underlying, rank within each, return top-per-underlying shortlists."""
        from collections import defaultdict

        grouped = defaultdict(list)
        for r in results:
            grouped[r.underlying].append(r)

        per_u: dict[str, list[ScanResult]] = {}
        cap = max(1, int(top_per_underlying))
        for u_name, u_results in grouped.items():
            if preferred_option_type:
                ranked = sorted(u_results, key=lambda r: -r.score)
            else:
                ce_list = sorted(
                    [r for r in u_results if r.option_type == "CE"],
                    key=lambda r: -r.score,
                )
                pe_list = sorted(
                    [r for r in u_results if r.option_type == "PE"],
                    key=lambda r: -r.score,
                )
                paired = []
                for i in range(max(len(ce_list), len(pe_list))):
                    if i < len(ce_list):
                        paired.append(ce_list[i])
                    if i < len(pe_list):
                        paired.append(pe_list[i])
                ranked = paired if paired else sorted(
                    u_results, key=lambda r: -r.score
                )
            per_u[u_name] = ranked[:cap]
        return per_u

    @staticmethod
    def _round_robin(
        n: int,
        per_u: dict[str, list[ScanResult]],
        underlying_priority: list[str] | None,
    ) -> list[ScanResult]:
        """Round-robin selection across underlyings, respecting priority order."""
        if underlying_priority:
            prio_idx = {str(u).upper(): i for i, u in enumerate(underlying_priority)}
            u_ranked = sorted(
                per_u.keys(),
                key=lambda u: (
                    prio_idx.get(str(u).upper(), len(prio_idx)),
                    -(per_u[u][0].score if per_u[u] else 0.0),
                ),
            )
        else:
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
        return final

    def _fallback_atm(
        self,
        underlyings: list[str],
        expiry_index: int,
        chains: dict[str, Any] | None = None,
    ) -> list[ScanResult]:
        """Fallback: select ATM CE+PE for monitoring when no momentum setups found."""
        final: list[ScanResult] = []
        if not underlyings:
            logger.error("scanner fallback has no underlyings — refusing hardcoded NSE/MCX lists")
            return final

        for u in underlyings:
            try:
                u_upper = u.upper()
                try:
                    _u_exchange = self.dhan_exchange_for(u_upper)
                except UnknownInstrumentError:
                    continue

                chain = (chains or {}).get(u)
                if chain is None:
                    chain = ensure_sync_adapter_result(
                        "broker.get_option_chain",
                        self._broker.get_option_chain,
                        underlying=u,
                        exchange=_u_exchange,
                        expiry_index=expiry_index,
                    )
                if chain is None:
                    continue
                _fb_exp = (
                    chain.expiry.date()
                    if hasattr(chain.expiry, "date")
                    else (date.fromisoformat(chain.expiry) if isinstance(chain.expiry, str) else chain.expiry)
                )
                if _fb_exp is not None and _fb_exp < today_ist():
                    continue
                atm = chain.atm_strike

                if hasattr(chain.expiry, "date"):
                    expiry_str = chain.expiry.date().isoformat()
                elif hasattr(chain.expiry, "isoformat"):
                    expiry_str = chain.expiry.isoformat()
                else:
                    expiry_str = str(chain.expiry)

                for opt_type, opt_map in [("CE", chain.calls), ("PE", chain.puts)]:
                    atm_opt = opt_map.get(float(atm))
                    if atm_opt and float(atm_opt.ltp or 0) > 0:
                        final.append(
                            ScanResult(
                                symbol=atm_opt.symbol,
                                underlying=u,
                                strike=int(atm),
                                option_type=opt_type,
                                expiry=expiry_str,
                                ltp=float(atm_opt.ltp),
                                oi=int(atm_opt.oi or 0),
                                volume=int(atm_opt.volume or 0),
                                spread=float(atm_opt.ask or 0) - float(atm_opt.bid or 0),
                                score=50,
                                bias="NEUTRAL",
                                bias_reason="Monitoring ATM (No strong momentum)",
                                delta=0.5,
                                iv=float(atm_opt.iv or 0) if hasattr(atm_opt, "iv") else 0.0,
                            )
                        )
                        logger.info("Fallback: Selected %s for monitoring", atm_opt.symbol)
            except Exception as e:
                logger.debug("Fallback scan failed for %s: %s", u, e)
                continue
        return final


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
        # Switch only if new contract is superior by > 15 pts
        if (new_score - self._current_score) > 15:
            self._current_contract = new_contract
            self._current_score = new_score
            self._last_score_time = current_time
            return True
        return False
