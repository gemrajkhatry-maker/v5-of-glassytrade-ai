"""
Option Chain Analytics - Separated from OptionChain data class.

Provides analytical computations over OptionChain data without
mixing analytics concerns into the data model (SRP).
"""

from typing import Optional

from .entities import OptionChain


class OptionChainAnalytics:
    """Stateless analytics functions for OptionChain data."""

    @staticmethod
    def get_pcr(chain: OptionChain) -> Optional[float]:
        """
        Calculate Put-Call Ratio (PCR).

        Returns:
            PCR value or None if no OI data
        """
        total_call_oi = sum(opt.oi for opt in chain.calls.values() if opt.oi > 0)
        total_put_oi = sum(opt.oi for opt in chain.puts.values() if opt.oi > 0)

        if total_call_oi > 0:
            return total_put_oi / total_call_oi
        return None

    @staticmethod
    def get_max_pain_strike(chain: OptionChain) -> Optional[float]:
        """
        Calculate max pain strike (strike with minimum total loss to option writers).

        Returns:
            Max pain strike price or None
        """
        if not chain.strikes:
            return None

        min_loss = float("inf")
        max_pain_strike = None

        for strike in chain.strikes:
            total_loss = 0

            for call_strike, call_opt in chain.calls.items():
                if call_opt.oi > 0:
                    if strike > call_strike:
                        loss = (strike - call_strike) * call_opt.oi
                        total_loss += loss

            for put_strike, put_opt in chain.puts.items():
                if put_opt.oi > 0:
                    if strike < put_strike:
                        loss = (put_strike - strike) * put_opt.oi
                        total_loss += loss

            if total_loss < min_loss:
                min_loss = total_loss
                max_pain_strike = strike

        return max_pain_strike
