from quant.contracts.enums import MarketState
from dataclasses import dataclass
from typing import Any, Optional

from quant.contracts.value_objects import AMTResult
from quant.bars import Bar


@dataclass(frozen=True)
class DecisionContext:
    # state is deprecated, all context is directly populated
    state: Optional[AMTResult] = None
    bar: Optional[Bar] = None             # the bar that closed to produce state
    symbol: str = ""
    # session / risk facts
    session_open: bool = True
    warmup_complete: bool = True      # enough bars (> 15) for analysis
    position_open: bool = False
    cooldown_remaining_sec: int = 0
    risk_halted: bool = False
    consecutive_losses: int = 0
    # intended direction from a higher-level agent (may be None -> gates decide)
    agent_direction: Optional[str] = None   # "LONG" | "SHORT" | "FLAT" | None
    agent_probability: float = 0.0
    setup_evidence: Any | None = None
    # AMT market state (Fabio 2-state model) from the AMT analyzer. The
    # Triple-A edge (absorption → accumulation → VWAP breakout) fires in both
    # BALANCED and IMBALANCED auctions; a DEAD market (volume collapse)
    # rejects — there is nothing to trade. The VA-fade fallback is the
    # balance-returning reversion trade and also refuses a dead market.
    market_state: MarketState = MarketState.BALANCED          # "BALANCED" | "IMBALANCED" | "DEAD"
    balance_ratio: float = 0.0              # fraction of recent closes inside VA
    # Failed-auction drive tracker (Fabio): a BALANCE entry must be a return
    # visit after an outside probe was rejected ("second drive"). Populated
    # from AMTResult.drive_number / drive_entry_valid; carried for journal /
    # ML features only — the simplified gate pipeline no longer gates on it.
    drive_entry_valid: bool = False
    drive_number: int = 0                   # 0 = no level tested, 1 = D1, 2 = D2, 3+ exhausted
    # Structural targets for the Triple-A take-profit (Fabio: target the
    # previous balance area / prior POC). Carried from the AMT DTO; zeros mean
    # no structure is available and the fixed R-multiple placeholder applies.
    prior_poc: float = 0.0                  # previous session's POC
    npoc_above: float = 0.0                 # nearest unfilled prior-session POC above
    npoc_below: float = 0.0                 # nearest unfilled prior-session POC below
    # Depth-derived order book imbalance ([-1, 1], +1 = bid-heavy). Carried
    # from the AMT analyzer's live order-book snapshot so gate 3's order-flow
    # aggression leg can fire on depth — the playbook's A3 trigger — instead
    # of relying on bar-derived absorption alone.
    obi: float = 0.0
    # CANONICAL session value area from the AMT analyzer (session-scoped,
    # recent-range clamped — the exact POC/VA the UI renders). Gate 4 (and
    # SignalBuilder) anchor their stop on these so the LOCATION gate compares
    # price against the SAME profile the operator watches, not the
    # coordinator's bar-based VolumeProfileBuilder snapshot (different
    # bucketing, unclamped). Zeros mean "no AMT VA" and fall back to the
    # state's volume profile.
    poc: float = 0.0
    vah: float = 0.0
    val: float = 0.0
    # capital for sizing
    equity: float = 1_000_000.0
    risk_per_trade_pct: float = 0.01
    tick_size: float = 0.05
    vwap_std: float = 0.0
    vwap_upper_2: float = 0.0
    vwap_lower_2: float = 0.0
    cvd_slope: float = 0.0
    absorption_side: str = ""
    # Impulse Leg LVN (Layer 3 profile) — primary LVN from the most recent
    # directional impulse leg (swing low → high). Used by Gate 3 Path C
    # (Playbook C LVN Sniper) and the pyramid engine. Zero means unavailable.
    # Populated from amt_dto["legLvn"] in runtime._decide().
    leg_lvn: float = 0.0
    # Initiative / Breakout state from AMT analyzer (Fabio Model 1)
    break_direction: str = ""   # "UP" | "DOWN" | ""
    break_type: str = ""        # "INITIATIVE" | "RESPONSIVE" | "ABSORPTION" | ""
    # Live bid/ask quote prices for spread & slippage protection
    bid: float = 0.0
    ask: float = 0.0
    time_str: str = ""
    # Fabio 5-Phase Session & Expiry Context
    session_phase: str = ""
    allow_trend: bool = True
    allow_reversion: bool = True
    is_expiry: bool = False
    profile_shape: str = ""
    option_delta: float = 0.50
    contested_bubble_zone: bool = False
