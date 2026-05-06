"""Max drawdown tracker with circuit breaker."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MaxDrawdownTracker:
    """Track max drawdown from peak equity and halt trading if threshold exceeded.
    
    This implements Fabio Valentini's max daily loss protection:
    - Track peak equity during session
    - Calculate drawdown percentage from peak
    - Halt trading if drawdown >= threshold (default 2%)
    - Provide halt reason for logging/alerting
    """
    
    max_drawdown_pct: float = 0.02  # 2% of account
    peak_equity: float = 0.0
    _current_equity: float = 0.0
    _halted: bool = False
    
    @property
    def current_equity(self) -> float:
        """Get current equity (last updated value)."""
        return self._current_equity
    
    @property
    def current_drawdown_pct(self) -> float:
        """Calculate current drawdown percentage from peak."""
        if self.peak_equity <= 0:
            return 0.0
        return (self.peak_equity - self._current_equity) / self.peak_equity
    
    @property
    def can_trade(self) -> bool:
        """Check if trading is allowed."""
        return not self._halted
    
    @property
    def halted(self) -> bool:
        """Check if halted due to max drawdown."""
        return self._halted
    
    @property
    def halt_reason(self) -> str:
        """Get reason for halt if halted."""
        if not self._halted:
            return ""
        drawdown = self.current_drawdown_pct * 100
        return (
            f"Max drawdown circuit breaker: "
            f"{drawdown:.2f}% drawdown from peak {self.peak_equity:.2f}"
        )
    
    def update(self, current_equity: float) -> bool:
        """Update tracker with current equity.
        
        Args:
            current_equity: Current account equity.
            
        Returns:
            True if trading is allowed, False if halted.
        """
        # Handle zero/negative equity
        if current_equity <= 0:
            self._halted = True
            self._current_equity = current_equity
            return False
        
        # Update current equity
        self._current_equity = current_equity
        
        # Update peak if new high
        if current_equity > self.peak_equity:
            self.peak_equity = current_equity
        
        # Check drawdown threshold
        if self.peak_equity > 0:
            drawdown = (self.peak_equity - current_equity) / self.peak_equity
            if drawdown >= self.max_drawdown_pct:
                self._halted = True
                return False
        
        return True
    
    def reset(self) -> None:
        """Reset for new session."""
        self.peak_equity = 0.0
        self._current_equity = 0.0
        self._halted = False
    
    def to_dict(self) -> dict:
        """Serialize state for persistence."""
        return {
            "peak_equity": self.peak_equity,
            "_current_equity": self._current_equity,
            "_halted": self._halted,
            "max_drawdown_pct": self.max_drawdown_pct,
        }
    
    def load_from_dict(self, data: dict) -> None:
        """Load state from dict (for session persistence)."""
        self.peak_equity = float(data.get("peak_equity", 0.0))
        self._current_equity = float(data.get("_current_equity", 0.0))
        self._halted = bool(data.get("_halted", False))
        self.max_drawdown_pct = float(data.get("max_drawdown_pct", 0.02))
