"""VWAP (Volume-Weighted Average Price) Analytics."""

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VWAPResult:
    """VWAP calculation result."""
    symbol: str
    vwap: float
    total_volume: int
    total_trades: int


@dataclass(frozen=True)
class AnchoredVWAP:
    """Anchored VWAP result."""
    symbol: str
    vwap: float
    anchor_time: datetime
    total_volume: int
    total_trades: int


@dataclass(frozen=True)
class RollingVWAP:
    """Rolling VWAP result."""
    symbol: str
    vwap: float
    window: timedelta
    total_volume: int
    total_trades: int


@dataclass(frozen=True)
class VWAPBands:
    """VWAP with standard deviation bands."""
    symbol: str
    vwap: float
    upper_band: float
    lower_band: float
    std_dev: float
    total_volume: int


@dataclass(frozen=True)
class ExecutionQuality:
    """Execution quality metrics vs VWAP."""
    execution_price: float
    vwap: float
    side: str  # "buy" or "sell"
    deviation_pct: float
    is_better_than_vwap: bool


def calculate_session_vwap(symbol: str, trades: List[dict]) -> VWAPResult:
    """
    Calculate session VWAP.
    
    VWAP = sum(price * volume) / sum(volume)
    
    Args:
        symbol: Instrument symbol
        trades: List of trade dicts with 'price' and 'volume' keys
        
    Returns:
        VWAPResult with session VWAP
    """
    if not trades:
        return VWAPResult(symbol=symbol, vwap=0.0, total_volume=0, total_trades=0)
    
    total_pv = 0.0
    total_volume = 0
    
    for trade in trades:
        price = trade["price"]
        volume = trade["volume"]
        total_pv += price * volume
        total_volume += volume
    
    vwap = total_pv / total_volume if total_volume > 0 else 0.0
    
    return VWAPResult(
        symbol=symbol,
        vwap=vwap,
        total_volume=total_volume,
        total_trades=len(trades),
    )


def calculate_anchored_vwap(
    symbol: str,
    trades: List[dict],
    anchor_time: datetime,
) -> AnchoredVWAP:
    """
    Calculate VWAP anchored to specific time.
    
    Only includes trades from anchor_time onwards.
    
    Args:
        symbol: Instrument symbol
        trades: List of trade dicts with 'timestamp', 'price', 'volume'
        anchor_time: Anchor time to start calculation from
        
    Returns:
        AnchoredVWAP result
    """
    # Filter trades from anchor_time onwards
    filtered_trades = [
        t for t in trades
        if t.get("timestamp", datetime.min.replace(tzinfo=timezone.utc)) >= anchor_time
    ]
    
    if not filtered_trades:
        return AnchoredVWAP(
            symbol=symbol,
            vwap=0.0,
            anchor_time=anchor_time,
            total_volume=0,
            total_trades=0,
        )
    
    result = calculate_session_vwap(symbol, filtered_trades)
    
    return AnchoredVWAP(
        symbol=symbol,
        vwap=result.vwap,
        anchor_time=anchor_time,
        total_volume=result.total_volume,
        total_trades=result.total_trades,
    )


def calculate_rolling_vwap(
    symbol: str,
    trades: List[dict],
    window: timedelta,
) -> RollingVWAP:
    """
    Calculate rolling VWAP with sliding window.
    
    Only includes trades within window from latest trade.
    
    Args:
        symbol: Instrument symbol
        trades: List of trade dicts with 'timestamp', 'price', 'volume'
        window: Time window for calculation
        
    Returns:
        RollingVWAP result
    """
    if not trades:
        return RollingVWAP(
            symbol=symbol,
            vwap=0.0,
            window=window,
            total_volume=0,
            total_trades=0,
        )
    
    # Find latest trade timestamp
    latest_time = max(
        t.get("timestamp", datetime.min.replace(tzinfo=timezone.utc))
        for t in trades
    )
    
    # Filter trades within window
    window_start = latest_time - window
    filtered_trades = [
        t for t in trades
        if t.get("timestamp", datetime.min.replace(tzinfo=timezone.utc)) >= window_start
    ]
    
    if not filtered_trades:
        return RollingVWAP(
            symbol=symbol,
            vwap=0.0,
            window=window,
            total_volume=0,
            total_trades=0,
        )
    
    result = calculate_session_vwap(symbol, filtered_trades)
    
    return RollingVWAP(
        symbol=symbol,
        vwap=result.vwap,
        window=window,
        total_volume=result.total_volume,
        total_trades=result.total_trades,
    )


def calculate_vwap_bands(
    symbol: str,
    trades: List[dict],
    num_std: float = 2.0,
) -> VWAPBands:
    """
    Calculate VWAP with standard deviation bands.
    
    Args:
        symbol: Instrument symbol
        trades: List of trade dicts with 'price' and 'volume'
        num_std: Number of standard deviations for bands
        
    Returns:
        VWAPBands with upper/lower bands
    """
    if not trades:
        return VWAPBands(
            symbol=symbol,
            vwap=0.0,
            upper_band=0.0,
            lower_band=0.0,
            std_dev=0.0,
            total_volume=0,
        )
    
    # Calculate VWAP
    result = calculate_session_vwap(symbol, trades)
    vwap = result.vwap
    
    # Calculate weighted standard deviation
    total_volume = result.total_volume
    if total_volume == 0:
        return VWAPBands(
            symbol=symbol,
            vwap=vwap,
            upper_band=vwap,
            lower_band=vwap,
            std_dev=0.0,
            total_volume=0,
        )
    
    variance = 0.0
    for trade in trades:
        price = trade["price"]
        volume = trade["volume"]
        variance += volume * (price - vwap) ** 2
    
    variance /= total_volume
    std_dev = math.sqrt(variance)
    
    upper_band = vwap + num_std * std_dev
    lower_band = vwap - num_std * std_dev
    
    return VWAPBands(
        symbol=symbol,
        vwap=vwap,
        upper_band=upper_band,
        lower_band=lower_band,
        std_dev=std_dev,
        total_volume=total_volume,
    )


def calculate_execution_quality(
    execution_price: float,
    vwap: float,
    side: str,
) -> ExecutionQuality:
    """
    Calculate execution quality vs VWAP.
    
    For buys: negative deviation is better (bought below VWAP)
    For sells: positive deviation is better (sold above VWAP)
    
    Args:
        execution_price: Actual execution price
        vwap: Benchmark VWAP
        side: "buy" or "sell"
        
    Returns:
        ExecutionQuality metrics
    """
    if vwap == 0:
        deviation_pct = 0.0
    else:
        deviation_pct = (execution_price - vwap) / vwap * 100.0
    
    # Determine if execution is better than VWAP
    if side.lower() == "buy":
        is_better = execution_price <= vwap
    else:  # sell
        is_better = execution_price >= vwap
    
    return ExecutionQuality(
        execution_price=execution_price,
        vwap=vwap,
        side=side,
        deviation_pct=deviation_pct,
        is_better_than_vwap=is_better,
    )
