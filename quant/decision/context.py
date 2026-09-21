from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from quant.bars import Bar
from quant.contracts.aggregates import INITIAL_CAPITAL
from quant.contracts.enums import MarketState
from quant.contracts.value_objects import AMTResult
from quant.decision.data_quality import DataQuality


@dataclass(frozen=True)
class DecisionContext:
    # state is deprecated, all context is directly populated
    state: Optional[AMTResult] = None
    bar: Optional[Bar] = None             # the bar that closed to produce state
    symbol: str = ""
    market: str = "NSE"
    # Index of the bar that produced this context (-1 = unknown; set by
    # DecisionContextBuilder from its bar_index param). Lets downstream
    # caches (e.g. TimesFM forecasts) stamp what they computed against.
    bar_index: int = -1
    # session / risk facts
    session_open: bool = True
    warmup_complete: bool = True      # enough bars (> 15) for analysis
    position_open: bool = False
    position_side: str = ""                # "LONG" | "SHORT" | ""
    position_entry_price: float = 0.0      # entry fill price
    position_size: float = 0.0             # signed position quantity
    position_unrealized_pnl: float = 0.0   # current unrealized P&L in currency units
    position_sl: float = 0.0               # current stop loss price
    position_tp: float = 0.0               # target take profit price
    position_bars_held: int = 0            # number of bars held since entry
    cooldown_remaining_sec: int = 0
    risk_halted: bool = False
    consecutive_losses: int = 0
    consecutive_wins: int = 0
    # Narrative setup grade (Fabio Gap #6): A/A+ grade for second-drive
    # entries boosts confidence; carried from context_builder / risk tier.
    setup_grade: str = ""
    # intended direction from a higher-level agent (may be None -> gates decide)
    agent_direction: Optional[str] = None   # "LONG" | "SHORT" | "FLAT" | None
    agent_probability: float = 0.0
    # Provenance of order-flow evidence; unknown quality must not pass a
    # high-conviction entry gate.
    data_quality: DataQuality | None = None
    evidence_provenance: dict[str, DataQuality] | None = None
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
    equity: float = float(INITIAL_CAPITAL)
    risk_per_trade_pct: float = 0.01
    tick_size: float = 0.05
    session_vwap: float = 0.0
    vwap_std: float = 0.0
    vwap_upper_2: float = 0.0
    vwap_lower_2: float = 0.0
    cvd_slope: float = 0.0
    absorption_side: str = ""
    # Raw aggression components from AMT engine (no direction gating).
    # Re-scored with resolved agent_direction in gate_triple_a_edge.
    aggression_components: dict | None = None
    cvd_state: Any | None = None
    ofi_result: Any | None = None
    norm_delta: float = 0.0
    # Impulse Leg LVN (Layer 3 profile) — primary LVN from the most recent
    # directional impulse leg (swing low → high). Used by Gate 3 Path C
    # (Playbook C LVN Sniper) and the pyramid engine. Zero means unavailable.
    # Resolved from amt_dto["legLvns"] by DecisionContextBuilder.
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
    option_delta: float | None = None
    contested_bubble_zone: bool = False
    # Stacked footprint imbalance (Fabio volume bubble, audit Gap #2):
    # direction ("BUY"/"SELL"/""), magnitude (consecutive 3:1 levels), and
    # the price band. Derived from the latest footprint candle in
    # context_builder — opposing stacked flow BLOCKS entry.
    # Aggressive prints as structural levels (Fabio Gap #10): a massive
    # print at a price MAKES that price support/resistance. Nearest big
    # BUY print below = support; nearest big SELL print above = resistance.
    nearest_buy_print_below: float = 0.0
    nearest_sell_print_above: float = 0.0
    stacked_imbalance_direction: str = ""
    stacked_imbalance_magnitude: int = 0
    stacked_imbalance_price_low: float = 0.0
    stacked_imbalance_price_high: float = 0.0
    # Sequential Triple-A machine (per-symbol). Playbook A enters only at
    # AGGRESSION with matching signal. Empty phase = machine not running.
    triple_a_phase: str = ""
    triple_a_signal: str = ""
    absorption_cluster_high: float = 0.0
    absorption_cluster_low: float = 0.0
    # Fabio Playbook #4 — trapped-volume squeeze (consumes Task 2a DTO keys).
    # squeeze_direction / squeeze_trapped_level come from RegimeDetector via
    # the AMT DTO; pullback_confirmed is a concrete retest of the trapped VA
    # level (within 3 ticks) computed in context_builder.
    squeeze_detected: bool = False
    squeeze_direction: str = ""
    squeeze_trapped_level: float = 0.0
    pullback_confirmed: bool = False
    # Layer 2 Compression Box (spec §5.2): micro-POC/VAH/VAL from a tight
    # 15-30m balance range. A close beyond micro_vah/micro_val confirms a
    # true out-of-balance breakout (used by Playbook A/B gate paths).
    compression_box_poc: float = 0.0
    compression_box_vah: float = 0.0
    compression_box_val: float = 0.0
    compression_box_bars: int = 0
    # Layer 4 Gap Profile (spec §5.2): gap-POC/VAH/VAL from overnight gap
    gap_profile_poc: float = 0.0
    gap_profile_vah: float = 0.0
    gap_profile_val: float = 0.0
    # LuxAlgo Value Area Reversion Signals (VARS)
    vars_result: Any | None = None
    # Rolling history of recent decisions and rationales (last 3-5 bars)
    recent_decisions: Tuple[Dict[str, Any], ...] = ()
    # Session extreme prices for VA_Fade stop placement (Fabio failed-breakout rule):
    # the full probe beyond the value area across all session bars. When non-zero,
    # VA_Fade references these instead of just the current bar's wick so the stop
    # sits beyond the true probe extreme. Zero means unavailable → fall back to bar.
    session_extreme_low: float = 0.0
    session_extreme_high: float = 0.0
    # CVD divergence flag from the analyzer's CVD tracker (Gate 3 alignment veto).
    # "BULLISH_DIV" | "BEARISH_DIV" | "" ("" = no divergence detected). Produced by
    # quant.amt.orderflow.cvd, carried on AMTResult.cvd_divergence, and mapped from
    # the DTO's "cvdDivergence" key by DecisionContextBuilder.build(). Gate 3
    # (gates_edge._check_guards) vetoes a trade whose direction opposes the
    # divergence; an empty value means "no conflict", so this field MUST be wired
    # or the veto silently fails open on every bar of every session.
    cvd_divergence: str = ""
