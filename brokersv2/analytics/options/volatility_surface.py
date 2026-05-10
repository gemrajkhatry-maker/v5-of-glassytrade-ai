"""Volatility Surface, Skew, and Term Structure Analytics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional


@dataclass(frozen=True)
class IVSurface:
    """Immutable IV surface representing volatility across strikes and expiries."""
    underlying: str
    timestamp: datetime
    spot_price: float
    iv_data: List[Dict[str, float]]

    def get_iv(self, strike: float, expiry_days: int) -> Optional[float]:
        """Get IV at specific strike and expiry."""
        for point in self.iv_data:
            if (abs(point.get("strike", 0) - strike) < 0.01 and
                abs(point.get("expiry_days", 0) - expiry_days) < 0.01):
                return point.get("iv")
        return None

    def get_atm_iv(self, expiry_days: int) -> Optional[float]:
        """Get ATM IV for a specific expiry."""
        atm_data = [
            point for point in self.iv_data
            if abs(point.get("strike", 0) - self.spot_price) < 0.01
            and abs(point.get("expiry_days", 0) - expiry_days) < 0.01
        ]
        if atm_data:
            return atm_data[0].get("iv")
        return None

    def get_all_expiries(self) -> List[int]:
        """Get all unique expiry days."""
        return sorted(list(set(
            point.get("expiry_days", 0) for point in self.iv_data
        )))

    def get_all_strikes(self, expiry_days: Optional[int] = None) -> List[float]:
        """Get all strikes, optionally filtered by expiry."""
        if expiry_days is None:
            return sorted(list(set(
                point.get("strike", 0) for point in self.iv_data
            )))
        return sorted(list(set(
            point.get("strike", 0) for point in self.iv_data
            if abs(point.get("expiry_days", 0) - expiry_days) < 0.01
        )))


@dataclass(frozen=True)
class SkewMetrics:
    """Immutable volatility skew metrics."""
    underlying: str
    timestamp: datetime
    spot_price: float
    expiry_days: int
    atm_iv: float
    skew_25d: float  # 25-delta skew (OTM PE IV - OTM CE IV)
    risk_reversal_25d: float = 0.0  # Risk reversal measure

    @property
    def is_positive_skew(self) -> bool:
        """Positive skew indicates puts have higher IV than calls."""
        return self.skew_25d > 0

    @property
    def is_negative_skew(self) -> bool:
        """Negative skew indicates calls have higher IV than puts."""
        return self.skew_25d < 0


@dataclass(frozen=True)
class TermStructureMetrics:
    """Immutable volatility term structure metrics."""
    underlying: str
    timestamp: datetime
    spot_price: float
    strike: float
    slope: float  # IV change per day
    is_contango: bool
    is_backwardation: bool

    @property
    def market_regime(self) -> str:
        """Get market regime based on term structure."""
        if self.is_contango:
            return "contango"
        elif self.is_backwardation:
            return "backwardation"
        return "neutral"


def calculate_skew(
    underlying: str,
    spot_price: float,
    expiry_days: int,
    iv_data: List[Dict[str, float]],
) -> SkewMetrics:
    """
    Calculate volatility skew metrics.

    Args:
        underlying: Underlying symbol
        spot_price: Current spot price
        expiry_days: Expiry to analyze
        iv_data: IV data points

    Returns:
        SkewMetrics with skew calculations
    """
    # Filter data for specific expiry
    expiry_data = [
        point for point in iv_data
        if abs(point.get("expiry_days", 0) - expiry_days) < 0.01
    ]

    # Find ATM IV
    atm_data = [
        point for point in expiry_data
        if abs(point.get("strike", 0) - spot_price) < 0.01
    ]
    atm_iv = atm_data[0].get("iv", 0.0) if atm_data else 0.0

    # Find OTM options (25-delta approximation: ~10% OTM)
    otm_strike = spot_price * 1.10  # 10% OTM call
    otm_pe_strike = spot_price * 0.90  # 10% OTM put

    # Find closest strikes
    otm_ce_data = min(
        [p for p in expiry_data if p.get("strike", 0) > spot_price],
        key=lambda x: abs(x.get("strike", 0) - otm_strike),
        default=None
    )
    otm_pe_data = min(
        [p for p in expiry_data if p.get("strike", 0) < spot_price],
        key=lambda x: abs(x.get("strike", 0) - otm_pe_strike),
        default=None
    )

    otm_ce_iv = otm_ce_data.get("iv", 0.0) if otm_ce_data else 0.0
    otm_pe_iv = otm_pe_data.get("iv", 0.0) if otm_pe_data else 0.0

    # Calculate skew
    skew_25d = otm_pe_iv - otm_ce_iv
    risk_reversal = (otm_ce_iv - otm_pe_iv) / 2.0

    return SkewMetrics(
        underlying=underlying,
        timestamp=datetime.now(timezone.utc),
        spot_price=spot_price,
        expiry_days=expiry_days,
        atm_iv=atm_iv,
        skew_25d=skew_25d,
        risk_reversal_25d=risk_reversal,
    )


def calculate_term_structure(
    underlying: str,
    spot_price: float,
    strike: float,
    iv_data: List[Dict[str, float]],
) -> TermStructureMetrics:
    """
    Calculate volatility term structure.

    Args:
        underlying: Underlying symbol
        spot_price: Current spot price
        strike: Strike to analyze (typically ATM)
        iv_data: IV data points

    Returns:
        TermStructureMetrics with term structure analysis
    """
    # Filter data for specific strike
    strike_data = sorted(
        [
            point for point in iv_data
            if abs(point.get("strike", 0) - strike) < 0.01
        ],
        key=lambda x: x.get("expiry_days", 0)
    )

    if len(strike_data) < 2:
        return TermStructureMetrics(
            underlying=underlying,
            timestamp=datetime.now(timezone.utc),
            spot_price=spot_price,
            strike=strike,
            slope=0.0,
            is_contango=False,
            is_backwardation=False,
        )

    # Calculate slope using linear regression (simplified)
    shortest = strike_data[0]
    longest = strike_data[-1]

    expiry_diff = longest.get("expiry_days", 0) - shortest.get("expiry_days", 0)
    iv_diff = longest.get("iv", 0.0) - shortest.get("iv", 0.0)

    slope = iv_diff / expiry_diff if expiry_diff > 0 else 0.0

    # Determine market regime
    is_contango = slope > 0.0005  # Positive slope
    is_backwardation = slope < -0.0005  # Negative slope

    return TermStructureMetrics(
        underlying=underlying,
        timestamp=datetime.now(timezone.utc),
        spot_price=spot_price,
        strike=strike,
        slope=slope,
        is_contango=is_contango,
        is_backwardation=is_backwardation,
    )
