"""Cost tracking service for trading operations.

Tracks LLM token usage, broker API calls, trade costs, and provides
aggregated cost summaries for session-level spending visibility.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any


@dataclass
class TokenUsage:
    """Token usage for a single LLM call."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""
    is_cloud: bool = False


@dataclass
class APICallRecord:
    """Record of a broker API call."""
    endpoint: str = ""
    symbol: str = ""
    latency_ms: float = 0.0
    status: str = "ok"  # ok, error, rate_limited


@dataclass
class TradeCostRecord:
    """Cost breakdown for a trade."""
    symbol: str = ""
    notional: float = 0.0
    brokerage: float = 0.0
    stt: float = 0.0
    exchange_fee: float = 0.0
    gst: float = 0.0
    sebi: float = 0.0
    slippage: float = 0.0
    total: float = 0.0


class CostTracker:
    """Centralized cost tracking for LLM, broker API, and trades.

    Thread-safe singleton-style tracker. Collects usage metrics without
    affecting the trading pipeline performance.
    """

    # Indian market cost constants
    STT_PCT = 0.000625  # 0.0625% on sell only
    EXCHANGE_FEE_PCT = 0.000495  # 0.0495% per side
    BROKERAGE_PER_ORDER = 20.0  # Rs. 20 per order
    GST_PCT = 0.18  # 18% on brokerage
    SEBI_PCT = 0.000001  # 0.0001% per side

    def __init__(self):
        self._lock = threading.Lock()

        # LLM tracking
        self._total_prompt_tokens: int = 0
        self._total_completion_tokens: int = 0
        self._total_cloud_calls: int = 0
        self._total_local_calls: int = 0
        self._cloud_429_count: int = 0
        self._token_history: list[TokenUsage] = []

        # Broker API tracking
        self._api_call_counts: dict[str, int] = {}
        self._api_errors: dict[str, int] = {}
        self._api_latencies: dict[str, list[float]] = {}
        self._rate_limit_hits: int = 0

        # Trade cost tracking
        self._trade_costs: list[TradeCostRecord] = []
        self._total_brokerage: float = 0.0
        self._total_stt: float = 0.0
        self._total_exchange_fee: float = 0.0
        self._total_gst: float = 0.0
        self._total_sebi: float = 0.0
        self._total_slippage: float = 0.0

    # -- LLM Token Tracking --

    def record_llm_call(self, usage: TokenUsage) -> None:
        """Record token usage from an LLM inference call."""
        with self._lock:
            self._total_prompt_tokens += usage.prompt_tokens
            self._total_completion_tokens += usage.completion_tokens
            self._token_history.append(usage)
            # Keep only last 100 for memory
            if len(self._token_history) > 100:
                self._token_history = self._token_history[-100:]
            if usage.is_cloud:
                self._total_cloud_calls += 1
            else:
                self._total_local_calls += 1

    def record_cloud_429(self) -> None:
        """Record a rate limit hit from cloud provider."""
        with self._lock:
            self._cloud_429_count += 1

    # -- Broker API Tracking --

    def record_api_call(self, endpoint: str, symbol: str = "", latency_ms: float = 0.0, status: str = "ok") -> None:
        """Record a broker API call."""
        with self._lock:
            self._api_call_counts[endpoint] = self._api_call_counts.get(endpoint, 0) + 1
            if status != "ok":
                self._api_errors[endpoint] = self._api_errors.get(endpoint, 0) + 1
            if status == "rate_limited":
                self._rate_limit_hits += 1
            if endpoint not in self._api_latencies:
                self._api_latencies[endpoint] = []
            self._api_latencies[endpoint].append(latency_ms)
            # Keep last 100 latencies per endpoint
            if len(self._api_latencies[endpoint]) > 100:
                self._api_latencies[endpoint] = self._api_latencies[endpoint][-100:]

    # -- Trade Cost Tracking --

    def record_trade_cost(self, symbol: str, notional: float, slippage_bps: float = 15.0, is_sell: bool = False) -> TradeCostRecord:
        """Compute and record costs for a trade round-trip.

        Returns the computed cost record.
        """
        slippage = notional * slippage_bps / 10000.0
        stt = notional * self.STT_PCT if is_sell else 0.0
        exchange_fee = notional * self.EXCHANGE_FEE_PCT * 2  # Both sides
        brokerage = self.BROKERAGE_PER_ORDER * 2  # Entry + exit
        gst = brokerage * self.GST_PCT
        sebi = notional * self.SEBI_PCT * 2  # Both sides
        total = slippage + stt + exchange_fee + brokerage + gst + sebi

        record = TradeCostRecord(
            symbol=symbol,
            notional=notional,
            brokerage=brokerage,
            stt=stt,
            exchange_fee=exchange_fee,
            gst=gst,
            sebi=sebi,
            slippage=slippage,
            total=total,
        )

        with self._lock:
            self._trade_costs.append(record)
            self._total_brokerage += brokerage
            self._total_stt += stt
            self._total_exchange_fee += exchange_fee
            self._total_gst += gst
            self._total_sebi += sebi
            self._total_slippage += slippage

        return record

    # -- Snapshot --

    def snapshot(self) -> dict[str, Any]:
        """Return current cost snapshot for metrics/dashboard."""
        with self._lock:
            total_tokens = self._total_prompt_tokens + self._total_completion_tokens
            trade_count = len(self._trade_costs)
            total_trade_cost = (
                self._total_brokerage
                + self._total_stt
                + self._total_exchange_fee
                + self._total_gst
                + self._total_sebi
                + self._total_slippage
            )

            # API latency averages
            api_latency_avg = {}
            for endpoint, latencies in self._api_latencies.items():
                if latencies:
                    api_latency_avg[endpoint] = round(sum(latencies) / len(latencies), 1)

            return {
                "llm": {
                    "total_tokens": total_tokens,
                    "prompt_tokens": self._total_prompt_tokens,
                    "completion_tokens": self._total_completion_tokens,
                    "local_calls": self._total_local_calls,
                    "cloud_calls": self._total_cloud_calls,
                    "cloud_429s": self._cloud_429_count,
                    "avg_tokens_per_call": round(total_tokens / max(1, self._total_local_calls + self._total_cloud_calls)),
                },
                "broker_api": {
                    "total_calls": sum(self._api_call_counts.values()),
                    "by_endpoint": dict(self._api_call_counts),
                    "errors": dict(self._api_errors),
                    "rate_limit_hits": self._rate_limit_hits,
                    "avg_latency_ms": api_latency_avg,
                },
                "trades": {
                    "count": trade_count,
                    "total_cost_rs": round(total_trade_cost, 2),
                    "breakdown": {
                        "brokerage": round(self._total_brokerage, 2),
                        "stt": round(self._total_stt, 2),
                        "exchange_fee": round(self._total_exchange_fee, 2),
                        "gst": round(self._total_gst, 2),
                        "sebi": round(self._total_sebi, 2),
                        "slippage": round(self._total_slippage, 2),
                    },
                    "avg_cost_per_trade": round(total_trade_cost / max(1, trade_count), 2),
                },
            }

    def reset(self) -> None:
        """Reset all counters (for session restarts)."""
        with self._lock:
            self.__init__()


# Global singleton
_cost_tracker: CostTracker | None = None
_tracker_lock = threading.Lock()


def get_cost_tracker() -> CostTracker:
    """Get the global cost tracker singleton."""
    global _cost_tracker
    if _cost_tracker is None:
        with _tracker_lock:
            if _cost_tracker is None:
                _cost_tracker = CostTracker()
    return _cost_tracker


def reset_cost_tracker() -> None:
    """Reset the global cost tracker (for testing)."""
    global _cost_tracker
    with _tracker_lock:
        _cost_tracker = None
