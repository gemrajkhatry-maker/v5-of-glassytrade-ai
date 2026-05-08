"""IV Surface Engine - Implied volatility surface construction."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from brokersv2.analytics.options.events import IVSurfaceEvent


class IVSurfaceEngine:
    """
    Implied volatility surface construction and analysis.
    
    Features:
    - IV surface point storage
    - Volatility skew calculation
    - Term structure analysis
    - ATM IV interpolation
    - Surface visualization data
    """

    def __init__(self, underlying: str):
        """
        Initialize IV surface engine.
        
        Args:
            underlying: Underlying symbol
        """
        self.underlying = underlying
        self._iv_points: List[IVSurfaceEvent] = []

    @property
    def data_point_count(self) -> int:
        """Number of IV data points."""
        return len(self._iv_points)

    def add_iv_point(
        self,
        strike: float,
        expiry: datetime,
        implied_vol: float,
        underlying_price: float,
    ) -> None:
        """
        Add IV data point to surface.
        
        Args:
            strike: Strike price
            expiry: Expiry date
            implied_vol: Implied volatility
            underlying_price: Current underlying price
        """
        now = datetime.now(timezone.utc) if expiry.tzinfo else datetime.now()
        days_to_expiry = (expiry - now).days
        moneyness = strike / underlying_price if underlying_price > 0 else 1.0
        
        point = IVSurfaceEvent(
            underlying=self.underlying,
            timestamp=now,
            strike=strike,
            expiry=expiry,
            implied_vol=implied_vol,
            moneyness=moneyness,
            days_to_expiry=max(days_to_expiry, 1),
        )
        
        self._iv_points.append(point)

    def calculate_skew(
        self,
        expiry: datetime,
        underlying_price: float,
    ) -> float:
        """
        Calculate IV skew for given expiry.
        
        Skew = IV(OTM Put) - IV(ATM)
        Negative skew indicates puts have higher IV
        
        Args:
            expiry: Expiry date
            underlying_price: Current underlying price
            
        Returns:
            Skew value
        """
        # Filter by expiry
        expiry_points = [
            p for p in self._iv_points
            if p.expiry == expiry
        ]
        
        if len(expiry_points) < 2:
            return 0.0
        
        # Find ATM point
        atm_point = min(
            expiry_points,
            key=lambda p: abs(p.strike - underlying_price)
        )
        
        # Find OTM put (lower strike)
        otm_puts = [
            p for p in expiry_points
            if p.strike < underlying_price
        ]
        
        if not otm_puts:
            return 0.0
        
        # Use lowest strike OTM put
        otm_put = min(otm_puts, key=lambda p: p.strike)
        
        # Skew = OTM Put IV - ATM IV
        return otm_put.implied_vol - atm_point.implied_vol

    def get_term_structure(
        self,
        strike: float,
        underlying_price: float,
    ) -> List[Tuple[int, float]]:
        """
        Get IV term structure for given strike.
        
        Args:
            strike: Strike price
            underlying_price: Current underlying price
            
        Returns:
            List of (days_to_expiry, iv) tuples
        """
        # Filter points near this strike (within 1%)
        strike_points = [
            p for p in self._iv_points
            if abs(p.strike - strike) / strike < 0.01
        ]
        
        # Sort by days to expiry
        strike_points.sort(key=lambda p: p.days_to_expiry)
        
        return [(p.days_to_expiry, p.implied_vol) for p in strike_points]

    def get_atm_iv(
        self,
        underlying_price: float,
        expiry: datetime,
    ) -> Optional[float]:
        """
        Get ATM implied volatility.
        
        Args:
            underlying_price: Current underlying price
            expiry: Expiry date
            
        Returns:
            ATM IV or None
        """
        # Filter by expiry
        expiry_points = [
            p for p in self._iv_points
            if p.expiry == expiry
        ]
        
        if not expiry_points:
            return None
        
        # Find closest to ATM
        atm_point = min(
            expiry_points,
            key=lambda p: abs(p.strike - underlying_price)
        )
        
        return atm_point.implied_vol

    def get_surface_data(self) -> Dict:
        """
        Get complete surface data for visualization.
        
        Returns:
            Dictionary with strikes, expiries, and IV matrix
        """
        if not self._iv_points:
            return {"strikes": [], "expiries": [], "iv_matrix": []}
        
        # Collect unique strikes and expiries
        strikes = sorted(set(p.strike for p in self._iv_points))
        expiries = sorted(set(p.expiry for p in self._iv_points))
        
        # Build IV matrix
        iv_matrix = []
        for expiry in expiries:
            row = []
            for strike in strikes:
                # Find closest match
                matching = [
                    p for p in self._iv_points
                    if p.expiry == expiry and abs(p.strike - strike) / strike < 0.01
                ]
                
                if matching:
                    row.append(matching[0].implied_vol)
                else:
                    row.append(None)
            iv_matrix.append(row)
        
        return {
            "strikes": strikes,
            "expiries": expiries,
            "iv_matrix": iv_matrix,
        }
