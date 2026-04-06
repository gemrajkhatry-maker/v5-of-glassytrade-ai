"""
Prometheus metrics for observability.

Tracks trade count, PnL, latency, and system health.
"""

from prometheus_client import Counter, Gauge, Histogram, Info

# Trade metrics
TRADES_TOTAL = Counter(
    "glassytrade_trades_total",
    "Total number of trades executed",
    ["symbol", "direction", "result"]  # result: win/loss
)

TRADES_PNL = Gauge(
    "glassytrade_trades_pnl",
    "Current session PnL",
    ["symbol"]
)

TRADES_PNL_TOTAL = Counter(
    "glassytrade_trades_pnl_total",
    "Cumulative PnL",
    ["symbol"]
)

# Signal metrics
SIGNALS_TOTAL = Counter(
    "glassytrade_signals_total",
    "Total signals generated",
    ["symbol", "direction", "confidence"]
)

SIGNALS_BLOCKED = Counter(
    "glassytrade_signals_blocked",
    "Signals blocked by gates",
    ["symbol", "gate", "reason"]
)

# Aggression metrics
AGGRESSION_SCORE = Histogram(
    "glassytrade_aggression_score",
    "Aggression score distribution",
    ["symbol"],
    buckets=[0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5]
)

# Risk metrics
RISK_DAILY_PNL = Gauge(
    "glassytrade_risk_daily_pnl",
    "Daily PnL percentage",
    ["symbol"]
)

RISK_DRAWDOWN = Gauge(
    "glassytrade_risk_drawdown",
    "Current drawdown percentage",
    ["symbol"]
)

RISK_CONSECUTIVE_LOSSES = Gauge(
    "glassytrade_risk_consecutive_losses",
    "Current consecutive losses",
    ["symbol"]
)

RISK_HALTED = Gauge(
    "glassytrade_risk_halted",
    "Whether trading is halted (1=halted, 0=active)",
    ["symbol"]
)

# Latency metrics
TICK_PROCESSING_LATENCY = Histogram(
    "glassytrade_tick_processing_latency_seconds",
    "Tick processing latency",
    ["symbol"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0]
)

SIGNAL_GENERATION_LATENCY = Histogram(
    "glassytrade_signal_generation_latency_seconds",
    "Signal generation latency",
    ["symbol"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0]
)

# Connection metrics
WS_CONNECTION_STATUS = Gauge(
    "glassytrade_ws_connection_status",
    "WebSocket connection status (1=connected, 0=disconnected)",
    ["symbol"]
)

WS_RECONNECT_TOTAL = Counter(
    "glassytrade_ws_reconnect_total",
    "Total WebSocket reconnections",
    ["symbol"]
)

# Profile metrics
PROFILE_UPDATES_TOTAL = Counter(
    "glassytrade_profile_updates_total",
    "Total profile updates",
    ["symbol"]
)

VOLUME_PROFILE_POC = Gauge(
    "glassytrade_volume_profile_poc",
    "Current POC price",
    ["symbol"]
)

# System info
SYSTEM_INFO = Info(
    "glassytrade_system",
    "System information"
)


def init_metrics(version: str = "2.0.0") -> None:
    """Initialize system metrics."""
    SYSTEM_INFO.info({
        "version": version,
        "engine": "AMT Order Flow",
        "methodology": "Fabio Valentini"
    })


def record_trade(symbol: str, direction: str, pnl: float) -> None:
    """Record a trade execution."""
    result = "win" if pnl > 0 else "loss"
    TRADES_TOTAL.labels(symbol=symbol, direction=direction, result=result).inc()
    TRADES_PNL_TOTAL.labels(symbol=symbol).inc(pnl)


def update_session_pnl(symbol: str, pnl: float) -> None:
    """Update session PnL."""
    TRADES_PNL.labels(symbol=symbol).set(pnl)


def record_signal(symbol: str, direction: str, confidence: str) -> None:
    """Record a signal generation."""
    SIGNALS_TOTAL.labels(symbol=symbol, direction=direction, confidence=confidence).inc()


def record_blocked_signal(symbol: str, gate: int, reason: str) -> None:
    """Record a blocked signal."""
    SIGNALS_BLOCKED.labels(symbol=symbol, gate=str(gate), reason=reason).inc()


def record_aggression_score(symbol: str, score: float) -> None:
    """Record aggression score."""
    AGGRESSION_SCORE.labels(symbol=symbol).observe(score)


def update_risk_metrics(
    symbol: str,
    daily_pnl_pct: float,
    drawdown_pct: float,
    consecutive_losses: int,
    is_halted: bool
) -> None:
    """Update risk metrics."""
    RISK_DAILY_PNL.labels(symbol=symbol).set(daily_pnl_pct * 100)
    RISK_DRAWDOWN.labels(symbol=symbol).set(drawdown_pct * 100)
    RISK_CONSECUTIVE_LOSSES.labels(symbol=symbol).set(consecutive_losses)
    RISK_HALTED.labels(symbol=symbol).set(1 if is_halted else 0)


def record_tick_latency(symbol: str, latency_seconds: float) -> None:
    """Record tick processing latency."""
    TICK_PROCESSING_LATENCY.labels(symbol=symbol).observe(latency_seconds)


def record_signal_latency(symbol: str, latency_seconds: float) -> None:
    """Record signal generation latency."""
    SIGNAL_GENERATION_LATENCY.labels(symbol=symbol).observe(latency_seconds)


def update_ws_status(symbol: str, connected: bool) -> None:
    """Update WebSocket connection status."""
    WS_CONNECTION_STATUS.labels(symbol=symbol).set(1 if connected else 0)


def record_ws_reconnect(symbol: str) -> None:
    """Record WebSocket reconnection."""
    WS_RECONNECT_TOTAL.labels(symbol=symbol).inc()


def record_profile_update(symbol: str) -> None:
    """Record profile update."""
    PROFILE_UPDATES_TOTAL.labels(symbol=symbol).inc()


def update_poc(symbol: str, poc: float) -> None:
    """Update POC value."""
    VOLUME_PROFILE_POC.labels(symbol=symbol).set(poc)