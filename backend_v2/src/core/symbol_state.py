"""
Symbol state — per-symbol mutable state dataclass.

Holds ALL state for a single symbol: profiles, buffers, indicators, positions.
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class SymbolState:
    """
    Per-symbol mutable state.

    Contains all data needed for a single symbol's processing pipeline.
    """

    symbol: str

    # =========================================================================
    # PROFILES
    # =========================================================================
    session_profile: Dict[float, int] = field(default_factory=dict)
    session_delta_profile: Dict[float, Dict[str, int]] = field(default_factory=dict)
    leg_profile: Dict[float, int] = field(default_factory=dict)
    leg_anchor: Optional[Dict[str, Any]] = None
    leg_active: bool = False

    # Value Area
    session_poc: Optional[float] = None
    session_vah: Optional[float] = None
    session_val: Optional[float] = None
    prev_session_poc: Optional[float] = None
    prev_session_vah: Optional[float] = None
    prev_session_val: Optional[float] = None

    # LVNs and HVNs
    lvns: List[float] = field(default_factory=list)
    hvns: List[float] = field(default_factory=list)

    # =========================================================================
    # BUFFERS
    # =========================================================================
    tick_buffer: deque = field(default_factory=lambda: deque(maxlen=10000))
    candle_buffer: deque = field(default_factory=lambda: deque(maxlen=200))
    cvd_series: List[float] = field(default_factory=list)

    # =========================================================================
    # CVD STATE
    # =========================================================================
    cvd_current: float = 0.0
    cvd_slope: float = 0.0
    cvd_divergence: Optional[str] = None  # "BULLISH" or "BEARISH"

    # =========================================================================
    # FOOTPRINT STATE
    # =========================================================================
    current_footprint: Dict[float, Dict[str, int]] = field(default_factory=dict)
    footprint_imbalance_confirmed: bool = False

    # =========================================================================
    # VWAP STATE
    # =========================================================================
    vwap: float = 0.0
    vwap_sigma1_upper: float = 0.0
    vwap_sigma1_lower: float = 0.0
    vwap_sigma2_upper: float = 0.0
    vwap_sigma2_lower: float = 0.0
    vwap_cumulative_pv: float = 0.0
    vwap_cumulative_vol: int = 0
    vwap_cumulative_sq: float = 0.0

    # =========================================================================
    # INITIAL BALANCE
    # =========================================================================
    ib_high: Optional[float] = None
    ib_low: Optional[float] = None
    ib_set: bool = False
    ib_broken: bool = False

    # =========================================================================
    # ATR AND VOLUME
    # =========================================================================
    atr: float = 0.0
    avg_volume: float = 0.0
    avg_trade_size: float = 0.0

    # =========================================================================
    # MARKET STATE
    # =========================================================================
    market_state: str = "OUTSIDE"  # NO_TRADE, BALANCED, IMBALANCED, PROBING, OUTSIDE
    market_zone: str = ""  # NEAR_VAH, NEAR_VAL, NEAR_POC, EMPTY

    # =========================================================================
    # DRIVE TRACKING
    # =========================================================================
    drive_level_history: Dict[float, Dict[str, Any]] = field(default_factory=dict)

    # =========================================================================
    # AGGRESSION
    # =========================================================================
    aggression_score: float = 0.0
    aggression_confirmed: bool = False
    pyramid_eligible: bool = False

    # =========================================================================
    # POSITIONS
    # =========================================================================
    open_entries: List[Dict[str, Any]] = field(default_factory=list)

    # =========================================================================
    # SESSION
    # =========================================================================
    session_start_ts: Optional[datetime] = None
    is_session_active: bool = False
    data_quality: str = "LIVE"  # LIVE, STALE, RECONNECTING
    last_tick_ts: Optional[datetime] = None
    last_signal: Optional[Dict[str, Any]] = None

    # =========================================================================
    # OFI
    # =========================================================================
    ofi_current: float = 0.0
    ofi_history: deque = field(default_factory=lambda: deque(maxlen=10))

    def reset_for_new_session(self) -> None:
        """Reset all session-scoped state for a new session."""
        self.session_profile.clear()
        self.session_delta_profile.clear()
        self.leg_profile.clear()
        self.leg_anchor = None
        self.leg_active = False

        self.session_poc = None
        self.session_vah = None
        self.session_val = None

        self.lvns.clear()
        self.hvns.clear()

        self.tick_buffer.clear()
        self.candle_buffer.clear()
        self.cvd_series.clear()

        self.cvd_current = 0.0
        self.cvd_slope = 0.0
        self.cvd_divergence = None

        self.current_footprint.clear()
        self.footprint_imbalance_confirmed = False

        self.vwap = 0.0
        self.vwap_sigma1_upper = 0.0
        self.vwap_sigma1_lower = 0.0
        self.vwap_sigma2_upper = 0.0
        self.vwap_sigma2_lower = 0.0
        self.vwap_cumulative_pv = 0.0
        self.vwap_cumulative_vol = 0
        self.vwap_cumulative_sq = 0.0

        self.ib_high = None
        self.ib_low = None
        self.ib_set = False
        self.ib_broken = False

        self.atr = 0.0
        self.avg_volume = 0.0
        self.avg_trade_size = 0.0

        self.market_state = "OUTSIDE"
        self.market_zone = ""

        self.drive_level_history.clear()

        self.aggression_score = 0.0
        self.aggression_confirmed = False
        self.pyramid_eligible = False

        self.ofi_current = 0.0
        self.ofi_history.clear()

        self.is_session_active = True
        self.data_quality = "LIVE"