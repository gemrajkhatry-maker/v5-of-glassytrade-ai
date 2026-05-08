"""OI Analytics - Open interest analysis and PCR."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from brokersv2.analytics.options.events import OptionType, OIEvent


class OIAnalyzer:
    """
    Open interest analytics.
    
    Features:
    - Put-Call ratio calculation
    - Max pain/open interest detection
    - OI change tracking
    - Support/resistance identification
    """

    def __init__(self, underlying: str):
        """
        Initialize OI analyzer.
        
        Args:
            underlying: Underlying symbol
        """
        self.underlying = underlying
        self._oi_data: Dict[Tuple[float, OptionType], int] = {}
        self._previous_oi: Dict[Tuple[float, OptionType], int] = {}

    def update_oi(
        self,
        strike: float,
        option_type: OptionType,
        open_interest: int,
    ) -> None:
        """
        Update OI for a strike.
        
        Args:
            strike: Strike price
            option_type: Call or Put
            open_interest: Current open interest
        """
        key = (strike, option_type)
        
        # Store previous
        if key in self._oi_data:
            self._previous_oi[key] = self._oi_data[key]
        
        self._oi_data[key] = open_interest

    def get_pcr(self, strike: float) -> float:
        """
        Get put-call ratio at strike.
        
        Args:
            strike: Strike price
            
        Returns:
            PCR value
        """
        call_oi = self._oi_data.get((strike, OptionType.CALL), 0)
        put_oi = self._oi_data.get((strike, OptionType.PUT), 0)
        
        if call_oi > 0:
            return put_oi / call_oi
        return 0.0

    def get_max_oi_strike(self, option_type: OptionType) -> Optional[float]:
        """
        Get strike with maximum OI.
        
        Args:
            option_type: Call or Put
            
        Returns:
            Strike with max OI
        """
        max_strike = None
        max_oi = 0
        
        for (strike, otype), oi in self._oi_data.items():
            if otype == option_type and oi > max_oi:
                max_oi = oi
                max_strike = strike
        
        return max_strike

    def get_oi_change(self, strike: float, option_type: OptionType) -> int:
        """
        Get OI change from previous.
        
        Args:
            strike: Strike price
            option_type: Call or Put
            
        Returns:
            OI change
        """
        key = (strike, option_type)
        current = self._oi_data.get(key, 0)
        previous = self._previous_oi.get(key, 0)
        
        return current - previous

    def get_total_oi(self, option_type: OptionType) -> int:
        """
        Get total OI across all strikes.
        
        Args:
            option_type: Call or Put
            
        Returns:
            Total OI
        """
        return sum(
            oi for (strike, otype), oi in self._oi_data.items()
            if otype == option_type
        )

    def get_chain_pcr(self) -> float:
        """
        Get chain-wide put-call ratio.
        
        Returns:
            Chain PCR
        """
        total_call = self.get_total_oi(OptionType.CALL)
        total_put = self.get_total_oi(OptionType.PUT)
        
        if total_call > 0:
            return total_put / total_call
        return 0.0

    def get_support_resistance(self) -> Tuple[Optional[float], Optional[float]]:
        """
        Identify support and resistance from OI.
        
        Returns:
            (support_strike, resistance_strike)
        """
        # Resistance = Max Call OI strike
        resistance = self.get_max_oi_strike(OptionType.CALL)
        
        # Support = Max Put OI strike
        support = self.get_max_oi_strike(OptionType.PUT)
        
        return (support, resistance)


class OIBuildupDetector:
    """
    Detect OI buildup patterns.
    
    Patterns:
    - Long buildup (OI up, price up)
    - Short buildup (OI up, price down)
    - Long unwinding (OI down, price down)
    - Short covering (OI down, price up)
    """

    def __init__(self, threshold: int = 2000):
        """
        Initialize detector.
        
        Args:
            threshold: Minimum OI change to detect
        """
        self.threshold = threshold
        self._changes: List[Dict] = []

    def track_oi_change(
        self,
        strike: float,
        option_type: OptionType,
        oi_change: int,
        price_change: float,
    ) -> None:
        """
        Track OI and price change.
        
        Args:
            strike: Strike price
            option_type: Call or Put
            oi_change: Change in OI
            price_change: Change in option price (%)
        """
        self._changes.append({
            "strike": strike,
            "option_type": option_type,
            "oi_change": oi_change,
            "price_change": price_change,
            "timestamp": datetime.now(),
        })

    def get_buildups(self) -> List[Dict]:
        """Get all significant OI buildups."""
        return [
            change for change in self._changes
            if abs(change["oi_change"]) >= self.threshold
        ]

    def get_long_buildups(self) -> List[Dict]:
        """Get long buildups (OI up, price up)."""
        return [
            change for change in self._changes
            if change["oi_change"] >= self.threshold
            and change["price_change"] > 0
        ]

    def get_short_buildups(self) -> List[Dict]:
        """Get short buildups (OI up, price down)."""
        return [
            change for change in self._changes
            if change["oi_change"] >= self.threshold
            and change["price_change"] < 0
        ]

    def get_unwindings(self) -> List[Dict]:
        """Get OI unwindings (OI down)."""
        return [
            change for change in self._changes
            if change["oi_change"] <= -self.threshold
        ]

    def get_short_covering(self) -> List[Dict]:
        """Get short covering (OI down, price up)."""
        return [
            change for change in self._changes
            if change["oi_change"] <= -self.threshold
            and change["price_change"] > 0
        ]
