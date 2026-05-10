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
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None


@dataclass(frozen=True)
class AnchoredVWAP:
    """Anchored VWAP result."""
    symbol: str
    vwap: float
    anchor_time: datetime
    total_volume: int
    total_trades: int
    periods_since_anchor: int = 0
    current_price: float = 0.0
    distance_from_vwap_pct: float = 0.0


@dataclass(frozen=True)
class RollingVWAP:
    """Rolling VWAP result."""
    symbol: str
    values: List[float]  # List of VWAP values over time
    window_periods: int
    latest_vwap: float
    total_volume: int = 0
    total_trades: int = 0


@dataclass(frozen=True)
class VWAPBands:
    """VWAP with standard deviation bands."""
    symbol: str
    vwap: float
    upper_band: float
    lower_band: float
    std_dev: float
    total_volume: int
    band_width: float = 0.0
    band_width_pct: float = 0.0
    current_price: float = 0.0
    position: Optional[str] = None  # "above", "below", "within"


@dataclass(frozen=True)
class ExecutionQuality:
    """Execution quality metrics vs VWAP."""
    side: str  # "BUY" or "SELL"
    avg_fill_price: float
    benchmark_vwap: float
    slippage: float  # avg_fill_price - vwap
    slippage_bps: float  # slippage in basis points
    implementation_shortfall: float  # total cost of execution


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
    
    # Extract timestamps if available
    timestamps = [t.get("timestamp") for t in trades if "timestamp" in t]
    start_time = min(timestamps) if timestamps else None
    end_time = max(timestamps) if timestamps else None
    
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
        start_time=start_time,
        end_time=end_time,
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
            periods_since_anchor=0,
            current_price=0.0,
            distance_pct=0.0,
        )
    
    result = calculate_session_vwap(symbol, filtered_trades)
    current_price = filtered_trades[-1]["price"]
    distance_from_vwap_pct = ((current_price - result.vwap) / result.vwap * 100.0) if result.vwap > 0 else 0.0
    
    return AnchoredVWAP(
        symbol=symbol,
        vwap=result.vwap,
        anchor_time=anchor_time,
        total_volume=result.total_volume,
        total_trades=result.total_trades,
        periods_since_anchor=len(filtered_trades),
        current_price=current_price,
        distance_from_vwap_pct=distance_from_vwap_pct,
    )


def calculate_rolling_vwap(
    symbol: str,
    trades: List[dict],
    window_periods: int = 20,
) -> RollingVWAP:
    """
    Calculate rolling VWAP over sliding window.
    
    Args:
        symbol: Instrument symbol
        trades: List of trade dicts with 'price', 'volume'
        window_periods: Number of periods in rolling window
        
    Returns:
        RollingVWAP with list of VWAP values
    """
    if not trades or window_periods <= 0:
        return RollingVWAP(
            symbol=symbol,
            values=[],
            window_periods=window_periods,
            latest_vwap=0.0,
        )
    
    values: List[float] = []
    total_volume = 0
    
    # Calculate VWAP for each window position
    for i in range(len(trades)):
        # Get window of trades
        start_idx = max(0, i - window_periods + 1)
        window = trades[start_idx:i+1]
        
        # Calculate VWAP for this window
        window_pv = sum(t["price"] * t["volume"] for t in window)
        window_vol = sum(t["volume"] for t in window)
        
        if window_vol > 0:
            vwap = window_pv / window_vol
            values.append(vwap)
            total_volume = window_vol
    
    latest_vwap = values[-1] if values else 0.0
    
    return RollingVWAP(
        symbol=symbol,
        values=values,
        window_periods=window_periods,
        latest_vwap=latest_vwap,
        total_volume=total_volume,
        total_trades=len(trades),
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
    band_width = upper_band - lower_band
    band_width_pct = (band_width / vwap * 100.0) if vwap > 0 else 0.0
    current_price = trades[-1]["price"] if trades else vwap
    
    # Determine position relative to bands
    if current_price > upper_band:
        position = "above"
    elif current_price < lower_band:
        position = "below"
    else:
        position = "within"
    
    return VWAPBands(
        symbol=symbol,
        vwap=vwap,
        upper_band=upper_band,
        lower_band=lower_band,
        std_dev=std_dev,
        total_volume=total_volume,
        band_width=band_width,
        band_width_pct=band_width_pct,
        current_price=current_price,
        position=position,
    )


def calculate_execution_quality(
    trades: List[dict],
    side: str,
    avg_fill_price: float,
) -> ExecutionQuality:
    """
    Calculate execution quality vs VWAP.
    
    Args:
        trades: List of trade dicts with 'price', 'volume' for VWAP calculation
        side: "BUY" or "SELL"
        avg_fill_price: Average fill price of execution
        
    Returns:
        ExecutionQuality metrics
    """
    # Calculate benchmark VWAP
    vwap_result = calculate_session_vwap("BENCHMARK", trades)
    benchmark_vwap = vwap_result.vwap
    
    if benchmark_vwap == 0:
        slippage = 0.0
        slippage_bps = 0.0
        implementation_shortfall = 0.0
    else:
        # Slippage: positive means worse execution
        slippage = avg_fill_price - benchmark_vwap
        slippage_bps = (slippage / benchmark_vwap) * 10000  # basis points
        
        # Implementation shortfall: total cost
        total_volume = vwap_result.total_volume
        implementation_shortfall = abs(slippage) * total_volume
    
    return ExecutionQuality(
        side=side,
        avg_fill_price=avg_fill_price,
        benchmark_vwap=benchmark_vwap,
        slippage=slippage,
        slippage_bps=slippage_bps,
        implementation_shortfall=implementation_shortfall,
    )
