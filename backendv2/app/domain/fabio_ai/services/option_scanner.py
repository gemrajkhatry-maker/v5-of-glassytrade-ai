"""Momentum-based option scanning adapted for backendv2."""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.domain.shared.port.market_data import IMarketData

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
    bias: str = ""
    bias_reason: str = ""
    delta: float = 0.0
    iv: float = 0.0


@dataclass(frozen=True)
class ContractSwitchDecision:
    """Auditable scanner contract-switch decision."""

    accepted: bool
    reason: str
    current_contract: str | None
    candidate_contract: str
    current_score: float
    candidate_score: float
    score_delta: float
    cooldown_remaining: float = 0.0
    has_open_trade: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "reason": self.reason,
            "current_contract": self.current_contract,
            "candidate_contract": self.candidate_contract,
            "current_score": self.current_score,
            "candidate_score": self.candidate_score,
            "score_delta": self.score_delta,
            "cooldown_remaining": self.cooldown_remaining,
            "has_open_trade": self.has_open_trade,
        }


def _ensure_sync_result(label: str, fn: Any, *args: Any, **kwargs: Any) -> Any:
    result = fn(*args, **kwargs)
    if hasattr(result, "__await__"):
        raise TypeError(
            f"{label} returned awaitable. Wrap async broker calls with `run_in_executor` in adapter.",
        )
    return result


class OptionScannerService:
    """Simple momentum-based contract selection for MCX/NSE."""

    _SCAN_NSE_UNDERLYINGS = frozenset({"NIFTY", "BANKNIFTY", "FINNIFTY"})
    _SCAN_MCX_UNDERLYINGS = frozenset(
        {
            "CRUDEOIL",
            "NATURALGAS",
            "GOLD",
            "SILVER",
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
        "BANKNIFTY": 100_000,
        "FINNIFTY": 30_000,
        "CRUDEOIL": 10,
        "NATURALGAS": 500,
        "GOLD": 0,
        "GOLDM": 0,
        "SILVER": 0,
        "SILVERM": 0,
        "CRUDEOILM": 10,
    }

    def __init__(self, broker: IMarketData, default_underlyings: list[str] | None = None) -> None:
        self._broker = broker
        self._default_underlyings = default_underlyings
        self._ib_high = 0.0
        self._ib_low = 0.0
        self._session_vwap = 0.0
        self._session_poc = 0.0

    @staticmethod
    def _score_contract(strike, atm, interval, oi, vol, opt, ltp, bid, ask, underlying_upper, bias=None) -> tuple:
        atm_dist = abs(strike - atm) / interval if interval > 0 else 0
        delta_val = abs(float(opt.delta or 0.5))

        if vol <= 0:
            return 0, atm_dist, delta_val

        score = 0
        score += max(0, 40 - (atm_dist * 15))
        min_oi = OptionScannerService._MIN_OI.get(underlying_upper, 5000)
        if min_oi > 0:
            score += min(30, (oi / min_oi) * 10)
        else:
            score += 15
        score += min(20, (vol / 1000) * 5)
        if 0.40 <= delta_val <= 0.60:
            score += 10
        if ltp > 0 and bid > 0 and ask > 0:
            spread_pct = (ask - bid) / ltp * 100
            if spread_pct > 0.5:
                score -= min(20, (spread_pct - 0.5) * 10)
        return score, atm_dist, delta_val

    def _process_contract(
        self, u, opt_type, strike, atm, interval, option_map,
        bullish_only, bias, bias_reason, chain, is_mcx
    ):
        if bullish_only:
            if opt_type == "CE" and strike > atm:
                return None
            if opt_type == "PE" and strike < atm:
                return None

        opt = option_map.get(float(strike))
        if opt is None:
            return None

        ltp = float(opt.ltp or 0)
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

        score, _, delta_val = self._score_contract(
            strike, atm, interval, oi, vol, opt, ltp, bid, ask, u.upper(), bias
        )
        return ScanResult(
            symbol=opt.symbol,
            underlying=u,
            strike=strike,
            option_type=opt_type,
            expiry=chain.expiry.date().isoformat(),
            ltp=ltp,
            oi=oi,
            volume=vol,
            spread=ask - bid if bid > 0 and ask > 0 else 0,
            score=score,
            bias=bias,
            bias_reason=bias_reason,
            delta=delta_val,
            iv=float(opt.iv or 0) if hasattr(opt, "iv") else 0,
        )

    def _scan_underlying_for_contracts(
        self, u: str, exchange: str | None, expiry_index: int, strikes_around_atm: int, bullish_only: bool
    ) -> list[ScanResult]:
        out: list[ScanResult] = []
        u_upper = u.upper()
        if u_upper in self._SCAN_MCX_UNDERLYINGS:
            _exchange = "MCX"
        elif u_upper in self._SCAN_NSE_UNDERLYINGS:
            _exchange = "NFO"
        else:
            _exchange = exchange or "MCX"

        effective_expiry_index = expiry_index
        chain = _ensure_sync_result(
            "broker.get_option_chain",
            self._broker.get_option_chain,
            underlying=u,
            exchange=_exchange,
            expiry_index=effective_expiry_index,
        )
        while chain is not None and effective_expiry_index < 3:
            expiry_date = chain.expiry.date() if hasattr(chain.expiry, "date") else chain.expiry
            if expiry_date <= date.today():
                effective_expiry_index += 1
                chain = _ensure_sync_result(
                    "broker.get_option_chain",
                    self._broker.get_option_chain,
                    underlying=u,
                    exchange=_exchange,
                    expiry_index=effective_expiry_index,
                )
            else:
                break

        if chain is None:
            return out

        atm = chain.atm_strike
        interval = self._STRIKE_INTERVALS.get(u.upper(), 50)
        strikes = [atm + i * interval for i in range(-strikes_around_atm, strikes_around_atm + 1)]

        bias, _, bias_reason = self._detect_momentum(chain, atm, interval)
        is_mcx = u.upper() in (
            "CRUDEOIL", "CRUDEOILM", "GOLD", "GOLDM", "SILVER", "SILVERM", "NATURALGAS", "COPPER"
        )
        atm_checks: list[bool] = []
        for opt_type, option_map in [("CE", chain.calls), ("PE", chain.puts)]:
            if option_map.get(float(atm)) is None:
                continue
            atm_checks.append(
                self._process_contract(
                    u, opt_type, int(atm), atm, interval, option_map,
                    bullish_only, bias, bias_reason, chain, is_mcx=is_mcx
                ) is not None
            )
        if atm_checks and not any(atm_checks):
            return out
        for opt_type, option_map in [("CE", chain.calls), ("PE", chain.puts)]:
            for strike in strikes:
                result = self._process_contract(
                    u, opt_type, int(strike), atm, interval, option_map,
                    bullish_only, bias, bias_reason, chain, is_mcx=is_mcx
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
        bullish_only: bool = False,
    ) -> list[ScanResult]:
        results: list[ScanResult] = []
        explicit_underlyings = underlyings is not None
        if underlyings is None:
            underlyings = self._default_underlyings or []

        if not underlyings:
            if exchange == "MCX" or (not exchange and "MCX" in str(self._broker)):
                underlyings = ["CRUDEOIL", "NATURALGAS"]
            else:
                underlyings = ["NIFTY", "BANKNIFTY", "FINNIFTY"]

        if preferred_option_type is not None:
            if preferred_option_type == "PE":
                underlyings = ["BANKNIFTY"]
            elif preferred_option_type == "CE":
                underlyings = ["NIFTY"]

        parallel = os.environ.get("OPTION_SCANNER_PARALLEL_UNDERLYINGS", "").lower() in ("1", "true", "yes")
        max_workers = max(1, min(len(underlyings), int(os.environ.get("OPTION_SCANNER_MAX_WORKERS", "4"))))

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
                    ): u
                    for u in underlyings
                }
                for fut in as_completed(futures):
                    sym = futures[fut]
                    try:
                        merged.extend(fut.result())
                    except Exception as exc:
                        logger.error("scan_top_n failed for %s: %s", sym, exc, exc_info=True)
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
                        )
                    )
                except Exception as exc:
                    logger.error("scan_top_n failed for %s: %s", u, exc)

        grouped = defaultdict(list)
        for r in results:
            grouped[r.underlying].append(r)

        per_u: dict[str, list[ScanResult]] = {}
        for u_name, u_results in grouped.items():
            ranked = sorted(u_results, key=lambda r: -r.score)
            per_u[u_name] = ranked[:max(1, int(top_per_underlying))]

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

        if not final and not explicit_underlyings:
            if not underlyings:
                underlyings = ["NIFTY", "BANKNIFTY", "FINNIFTY"] if exchange != "MCX" else ["CRUDEOIL", "NATURALGAS"]
            _fb_exchange = exchange or ("MCX" if "MCX" in str(self._broker) else "NFO")
            _fb_underlyings = underlyings
            for u in _fb_underlyings:
                try:
                    u_upper = u.upper()
                    _u_exchange = _fb_exchange
                    if u_upper in self._SCAN_MCX_UNDERLYINGS:
                        _u_exchange = "MCX"
                    elif u_upper in self._SCAN_NSE_UNDERLYINGS:
                        _u_exchange = "NFO"

                    chain = _ensure_sync_result(
                        "broker.get_option_chain",
                        self._broker.get_option_chain,
                        underlying=u,
                        exchange=_u_exchange,
                        expiry_index=expiry_index,
                    )
                    if chain is None:
                        continue
                    atm = chain.atm_strike
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
                                    score=50,
                                    bias="NEUTRAL",
                                    bias_reason="Monitoring ATM (No strong momentum)",
                                    delta=0.5 if opt_type == "CE" else 0.5,
                                    iv=float(atm_opt.iv or 0) if hasattr(atm_opt, "iv") else 0.0,
                                )
                            )
                except Exception as exc:
                    logger.debug("fallback scan failed for %s: %s", u, exc)
                    continue

        return final[:n]

    @staticmethod
    def _detect_momentum(chain, atm, interval):
        ce_vol = sum(int(o.volume or 0) for o in chain.calls.values())
        pe_vol = sum(int(o.volume or 0) for o in chain.puts.values())
        if ce_vol > pe_vol * 1.5:
            return "BULLISH", 3, f"CE volume {ce_vol} > PE volume {pe_vol}"
        if pe_vol > ce_vol * 1.5:
            return "BEARISH", 3, f"PE volume {pe_vol} > CE volume {ce_vol}"
        return "NEUTRAL", 0, f"Balanced CE={ce_vol} PE={pe_vol}"

    def update_market_context(self, ib_high, ib_low, vwap, session_poc):
        self._ib_high = ib_high
        self._ib_low = ib_low
        self._session_vwap = vwap
        self._session_poc = session_poc


class ContractSwitchGuard:
    """Prevents switching contracts during open trades."""

    def __init__(self):
        self._current_contract = None
        self._current_score = 0.0
        self._last_score_time = 0.0
        self._has_open_trade = False

    @property
    def current_contract(self):
        return self._current_contract

    def set_open_trade(self, has_trade: bool):
        self._has_open_trade = has_trade

    def evaluate_switch(self, new_contract, new_score, current_time) -> ContractSwitchDecision:
        new_contract = str(new_contract)
        new_score = float(new_score)
        score_delta = abs(new_score - self._current_score)
        if self._has_open_trade:
            return ContractSwitchDecision(
                accepted=False,
                reason="open_trade_blocks_switch",
                current_contract=self._current_contract,
                candidate_contract=new_contract,
                current_score=self._current_score,
                candidate_score=new_score,
                score_delta=score_delta,
                has_open_trade=True,
            )
        if self._current_contract is None:
            return ContractSwitchDecision(
                accepted=True,
                reason="initial_contract",
                current_contract=None,
                candidate_contract=new_contract,
                current_score=self._current_score,
                candidate_score=new_score,
                score_delta=score_delta,
            )
        if new_contract == self._current_contract:
            return ContractSwitchDecision(
                accepted=False,
                reason="same_contract",
                current_contract=self._current_contract,
                candidate_contract=new_contract,
                current_score=self._current_score,
                candidate_score=new_score,
                score_delta=score_delta,
            )
        cooldown_remaining = max(0.0, 300 - (float(current_time) - self._last_score_time))
        if cooldown_remaining > 0:
            return ContractSwitchDecision(
                accepted=False,
                reason="cooldown_active",
                current_contract=self._current_contract,
                candidate_contract=new_contract,
                current_score=self._current_score,
                candidate_score=new_score,
                score_delta=score_delta,
                cooldown_remaining=cooldown_remaining,
            )
        if score_delta > 15:
            return ContractSwitchDecision(
                accepted=True,
                reason="score_delta_exceeded",
                current_contract=self._current_contract,
                candidate_contract=new_contract,
                current_score=self._current_score,
                candidate_score=new_score,
                score_delta=score_delta,
            )
        return ContractSwitchDecision(
            accepted=False,
            reason="score_delta_too_small",
            current_contract=self._current_contract,
            candidate_contract=new_contract,
            current_score=self._current_score,
            candidate_score=new_score,
            score_delta=score_delta,
        )

    def apply_switch(self, decision: ContractSwitchDecision, current_time: float) -> bool:
        if not decision.accepted:
            return False
        self._current_contract = decision.candidate_contract
        self._current_score = decision.candidate_score
        self._last_score_time = float(current_time)
        return True

    def should_switch(self, new_contract, new_score, current_time):
        decision = self.evaluate_switch(new_contract, new_score, current_time)
        return self.apply_switch(decision, current_time)

    def snapshot(self) -> dict[str, object]:
        return {
            "current_contract": self._current_contract,
            "current_score": self._current_score,
            "last_score_time": self._last_score_time,
            "has_open_trade": self._has_open_trade,
        }

