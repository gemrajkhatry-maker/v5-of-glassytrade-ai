"""Greeks Calculator - Black-Scholes options Greeks."""

from __future__ import annotations

import math
from datetime import datetime

from brokersv2.analytics.options.events import (
    GreeksSnapshot,
    OptionType,
)


class GreeksCalculator:
    """
    Calculate options Greeks using Black-Scholes model.
    
    Features:
    - Delta calculation
    - Gamma calculation
    - Theta (time decay)
    - Vega (volatility sensitivity)
    - Rho (interest rate sensitivity)
    - Complete Greeks snapshots
    """

    def __init__(self, risk_free_rate: float = 0.05):
        """
        Initialize calculator.
        
        Args:
            risk_free_rate: Risk-free interest rate (default 5%)
        """
        self.risk_free_rate = risk_free_rate

    def _d1_d2(
        self,
        underlying_price: float,
        strike: float,
        time_to_expiry: float,
        volatility: float,
    ) -> tuple[float, float]:
        """Calculate d1 and d2 for Black-Scholes."""
        if time_to_expiry <= 0 or volatility <= 0:
            return 0.0, 0.0
        
        d1 = (
            math.log(underlying_price / strike)
            + (self.risk_free_rate + 0.5 * volatility**2) * time_to_expiry
        ) / (volatility * math.sqrt(time_to_expiry))
        
        d2 = d1 - volatility * math.sqrt(time_to_expiry)
        return d1, d2

    def delta(
        self,
        underlying_price: float,
        strike: float,
        time_to_expiry: float,
        volatility: float,
        risk_free_rate: float = None,
        option_type: OptionType = OptionType.CALL,
    ) -> float:
        """
        Calculate option delta.
        
        Args:
            underlying_price: Current underlying price
            strike: Strike price
            time_to_expiry: Time to expiry in days
            volatility: Implied volatility
            risk_free_rate: Risk-free rate
            option_type: Call or Put
            
        Returns:
            Delta value
        """
        if risk_free_rate is None:
            risk_free_rate = self.risk_free_rate
            
        time_years = time_to_expiry / 365.0
        d1, _ = self._d1_d2(underlying_price, strike, time_years, volatility)
        
        delta = self._norm_cdf(d1)
        
        if option_type == OptionType.PUT:
            delta = delta - 1.0
        
        return delta

    def gamma(
        self,
        underlying_price: float,
        strike: float,
        time_to_expiry: float,
        volatility: float,
        risk_free_rate: float = None,
    ) -> float:
        """
        Calculate option gamma.
        
        Args:
            underlying_price: Current underlying price
            strike: Strike price
            time_to_expiry: Time to expiry in days
            volatility: Implied volatility
            risk_free_rate: Risk-free rate
            
        Returns:
            Gamma value
        """
        if risk_free_rate is None:
            risk_free_rate = self.risk_free_rate
            
        time_years = time_to_expiry / 365.0
        d1, _ = self._d1_d2(underlying_price, strike, time_years, volatility)
        
        if volatility <= 0 or time_years <= 0:
            return 0.0
        
        gamma = self._norm_pdf(d1) / (
            underlying_price * volatility * math.sqrt(time_years)
        )
        
        return gamma

    def theta(
        self,
        underlying_price: float,
        strike: float,
        time_to_expiry: float,
        volatility: float,
        risk_free_rate: float = None,
        option_type: OptionType = OptionType.CALL,
    ) -> float:
        """
        Calculate option theta (time decay).
        
        Args:
            underlying_price: Current underlying price
            strike: Strike price
            time_to_expiry: Time to expiry in days
            volatility: Implied volatility
            risk_free_rate: Risk-free rate
            option_type: Call or Put
            
        Returns:
            Theta value (typically negative)
        """
        if risk_free_rate is None:
            risk_free_rate = self.risk_free_rate
            
        time_years = time_to_expiry / 365.0
        d1, d2 = self._d1_d2(underlying_price, strike, time_years, volatility)
        
        if volatility <= 0 or time_years <= 0:
            return 0.0
        
        # Common term
        term1 = -(underlying_price * self._norm_pdf(d1) * volatility) / (
            2 * math.sqrt(time_years)
        )
        
        if option_type == OptionType.CALL:
            term2 = risk_free_rate * strike * math.exp(-risk_free_rate * time_years) * self._norm_cdf(d2)
            theta = term1 - term2
        else:
            term2 = risk_free_rate * strike * math.exp(-risk_free_rate * time_years) * self._norm_cdf(-d2)
            theta = term1 + term2
        
        # Convert to daily theta
        return theta / 365.0

    def vega(
        self,
        underlying_price: float,
        strike: float,
        time_to_expiry: float,
        volatility: float,
        risk_free_rate: float = None,
    ) -> float:
        """
        Calculate option vega.
        
        Args:
            underlying_price: Current underlying price
            strike: Strike price
            time_to_expiry: Time to expiry in days
            volatility: Implied volatility
            risk_free_rate: Risk-free rate
            
        Returns:
            Vega value
        """
        if risk_free_rate is None:
            risk_free_rate = self.risk_free_rate
            
        time_years = time_to_expiry / 365.0
        d1, _ = self._d1_d2(underlying_price, strike, time_years, volatility)
        
        if volatility <= 0 or time_years <= 0:
            return 0.0
        
        vega = underlying_price * self._norm_pdf(d1) * math.sqrt(time_years)
        
        return vega

    def calculate_all_greeks(
        self,
        symbol: str,
        underlying_price: float,
        strike: float,
        time_to_expiry: float,
        volatility: float,
        risk_free_rate: float = None,
        option_type: OptionType = OptionType.CALL,
    ) -> GreeksSnapshot:
        """
        Calculate all Greeks in one snapshot.
        
        Args:
            symbol: Option symbol
            underlying_price: Current underlying price
            strike: Strike price
            time_to_expiry: Time to expiry in days
            volatility: Implied volatility
            risk_free_rate: Risk-free rate
            option_type: Call or Put
            
        Returns:
            Complete Greeks snapshot
        """
        if risk_free_rate is None:
            risk_free_rate = self.risk_free_rate
        
        return GreeksSnapshot(
            symbol=symbol,
            timestamp=datetime.now(),
            delta=self.delta(underlying_price, strike, time_to_expiry, volatility, risk_free_rate, option_type),
            gamma=self.gamma(underlying_price, strike, time_to_expiry, volatility, risk_free_rate),
            theta=self.theta(underlying_price, strike, time_to_expiry, volatility, risk_free_rate, option_type),
            vega=self.vega(underlying_price, strike, time_to_expiry, volatility, risk_free_rate),
            implied_vol=volatility,
            underlying_price=underlying_price,
            strike=strike,
        )

    @staticmethod
    def _norm_cdf(x: float) -> float:
        """Standard normal cumulative distribution function."""
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    @staticmethod
    def _norm_pdf(x: float) -> float:
        """Standard normal probability density function."""
        return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)
