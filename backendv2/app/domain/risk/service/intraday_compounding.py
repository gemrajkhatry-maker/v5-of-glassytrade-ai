"""Intraday compounding / cushion system for dynamic risk sizing.

Implements Fabio Valentini's cushion methodology:
- CONSERVATIVE phase: 0.25% base risk, no cushion (first 1-2 trades)
- NORMAL phase: 0.50% base risk, no cushion
- CUSHION phase: 0.35% base + 20% of session profit
- MOMENTUM phase: 0.40% base + 20% of session profit
- DEFENSIVE phase: 0.25% base, no cushion (after losses)

Total risk is capped at 0.50% of equity (hard ceiling).

This doubles returns on good days by compounding session profits,
while protecting capital during drawdowns.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.fabio_ai.services.session_risk_manager import CapitalRiskBand


@dataclass(frozen=True)
class CompoundingResult:
    """Result of intraday compounding calculation."""
    lots: int = 0
    risk_per_lot: float = 0.0
    base_risk_amount: float = 0.0
    base_risk_pct: float = 0.0
    cushion_amount: float = 0.0
    total_risk: float = 0.0
    is_valid: bool = False
    capped: bool = False
    reason: str = ""


@dataclass
class IntradayCompoundingEngine:
    """Calculate position sizes with Fabio's cushion system."""
    
    # Risk percentages by tier
    RISK_BY_TIER = {
        CapitalRiskBand.CONSERVATIVE: 0.0025,  # 0.25%
        CapitalRiskBand.NORMAL: 0.0050,         # 0.50%
        CapitalRiskBand.CUSHION: 0.0035,        # 0.35%
        CapitalRiskBand.MOMENTUM: 0.0040,       # 0.40%
        CapitalRiskBand.DEFENSIVE: 0.0025,      # 0.25%
    }
    
    # Cushion tiers (only these get profit cushion)
    CUSHION_TIERS = {CapitalRiskBand.CUSHION, CapitalRiskBand.MOMENTUM}
    
    # Maximum total risk as % of equity
    MAX_TOTAL_RISK_PCT = 0.0050  # 0.50% hard ceiling
    
    # Cushion percentage of session profit
    CUSHION_PCT = 0.20  # 20% of session profit
    
    def calculate_with_cushion(
        self,
        equity: float,
        entry_price: float,
        stop_loss: float,
        point_value: float,
        session_pnl: float,
        risk_tier: CapitalRiskBand,
    ) -> CompoundingResult:
        """Calculate position size with intraday compounding.
        
        Args:
            equity: Current account equity.
            entry_price: Position entry price.
            stop_loss: Stop loss price.
            point_value: Dollar value per point.
            session_pnl: Current session PnL (positive = profit).
            risk_tier: Current risk tier from SessionRiskManager.
            
        Returns:
            CompoundingResult with lot size and risk breakdown.
        """
        # Validate inputs
        if equity <= 0:
            return CompoundingResult(reason="Equity is zero or negative")
        
        risk_per_unit = abs(entry_price - stop_loss)
        if risk_per_unit <= 0:
            return CompoundingResult(reason="Stop loss equals entry")
        
        if point_value <= 0:
            return CompoundingResult(reason="Point value is zero or negative")
        
        # Base risk by tier
        base_risk_pct = self.RISK_BY_TIER.get(risk_tier, 0.0050)
        base_risk_amount = equity * base_risk_pct
        
        # Calculate cushion (only for CUSHION and MOMENTUM tiers, only with profit)
        cushion_amount = 0.0
        if session_pnl > 0 and risk_tier in self.CUSHION_TIERS:
            cushion_amount = session_pnl * self.CUSHION_PCT
        
        # Total risk before cap
        total_risk = base_risk_amount + cushion_amount
        capped = False
        
        # Apply hard cap at 0.50% of equity
        max_risk = equity * self.MAX_TOTAL_RISK_PCT
        if total_risk > max_risk:
            total_risk = max_risk
            capped = True
        
        # Calculate lot size
        risk_per_lot = risk_per_unit * point_value
        if risk_per_lot <= 0:
            return CompoundingResult(reason="Risk per lot is zero")
        
        lots = int(total_risk / risk_per_lot)
        
        # Ensure at least 1 lot if risk budget allows
        if lots < 1 and total_risk >= risk_per_lot:
            lots = 1
        
        # Calculate actual risk
        actual_risk = lots * risk_per_lot
        
        return CompoundingResult(
            lots=lots,
            risk_per_lot=risk_per_lot,
            base_risk_amount=base_risk_amount,
            base_risk_pct=base_risk_pct,
            cushion_amount=cushion_amount,
            total_risk=actual_risk,
            is_valid=True,
            capped=capped,
            reason=(
                f"Base: {base_risk_amount:.0f} ({base_risk_pct*100:.2f}%), "
                f"cushion: {cushion_amount:.0f}, "
                f"total: {actual_risk:.0f}, "
                f"lots: {lots}"
                + (" [CAPPED]" if capped else "")
            ),
        )
