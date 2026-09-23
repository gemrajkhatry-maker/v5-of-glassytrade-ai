"""Laya-MLX Typed Decision Advisor for Auction Market Theory (AMT).

High-speed (13ms), low-memory (<700MB) typed decision layer running
natively on Apple Silicon via Apple MLX.

Supports two specialized, role-swapping agents matching the AI Market Thesis:
1. SCANNING Role (Flat / No Position):
   - Discovers edge setups (Triple-A, VA-Fade, Second-Drive, LVN-Sniper)
   - Evaluates directional actions (ENTER_LONG, ENTER_SHORT, FLAT)
   - Rates setup conviction & edge quality (0.0 to 4.0)
2. POSITION_MANAGEMENT Role (Active Trade in Progress):
   - Manages open positions (HOLD, TIGHTEN_SL, TAKE_PROFIT, EXIT)
   - Monitors trailing stops, breakeven risk-free thresholds, structural targets, and adverse flow
   - Rates holding conviction & position verdict (RUNNING_WELL, EXTENDED, STAGNANT, ADVERSE)
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import laya_mlx as laya
    import mlx.core as mx
    _LAYA_AVAILABLE = True
except ImportError:
    laya = None
    mx = None
    _LAYA_AVAILABLE = False

try:
    from quant.contracts.instrument_registry import is_option_contract
except ImportError:
    def is_option_contract(sym: str) -> bool:
        sym_u = sym.upper()
        return " CE" in sym_u or " PE" in sym_u or sym_u.endswith("CE") or sym_u.endswith("PE")


class LayaDecisionAdvisor:
    """Evaluates AMT auction snapshots via Laya-MLX typed decision heads with dual roles."""

    DEFAULT_CHECKPOINT = "aac6fef/laya-multilingual-mlx"

    def __init__(self, model_id: str = DEFAULT_CHECKPOINT, enabled: Optional[bool] = None):
        if enabled is None:
            # Model use is disabled by default for zero-overhead deterministic execution
            laya_env = os.getenv("LAYA_MODEL_ENABLED", "false").strip().lower() in ("1", "true", "yes")
            self.enabled = laya_env and _LAYA_AVAILABLE
        else:
            self.enabled = enabled and _LAYA_AVAILABLE
        self.model_id = model_id
        self._agent = None
        self._warmed_up = False
        self._lock = threading.Lock()
        self._eval_cache: Dict[str, Tuple[int, Dict[str, Any]]] = {}

        if not _LAYA_AVAILABLE and enabled:
            logger.warning("laya-mlx or mlx.core not installed. LayaDecisionAdvisor disabled.")
            self.enabled = False

    def initialize(self) -> bool:
        """Loads weights and warms up the MLX execution graph under lock."""
        if not self.enabled or self._agent is not None:
            return self._agent is not None

        with self._lock:
            if self._agent is not None:
                return True
            try:
                t0 = time.perf_counter()
                self._agent = laya.load(self.model_id)
                load_time = time.perf_counter() - t0
                logger.info("Laya-MLX loaded checkpoint %s in %.2fs", self.model_id, load_time)

                # Warmup pass
                warmup_state = "GOLDM: Price=163000.00, POC=163000.00, VAH=163815.00, VAL=162185.00, Phase=PRIMARY, State=BALANCED, CVD_Slope=0.38, Absorption=NONE, Profile=D, Spread=0.05, Expiry=False"
                warmup_q = {
                    "action": {
                        "type": "choice",
                        "instructions": "According to Fabio Valentini Auction Market Theory, what is the valid order action?",
                        "criteria": ["BUY (Enter Long)", "SELL (Enter Short)", "HOLD (Wait / No Edge)"],
                    }
                }
                self._agent.predict(warmup_state, warmup_q)
                if mx:
                    mx.eval()
                self._warmed_up = True
                logger.info("Laya-MLX execution graph compiled and ready.")
                return True
            except Exception as e:
                logger.error("Failed to initialize Laya-MLX: %s", e, exc_info=True)
                self.enabled = False
                return False

    def evaluate_auction_snapshot(
        self,
        symbol: str,
        session_phase: str,
        market_state: str,
        price: float,
        poc: float,
        vah: float,
        val: float,
        cvd_slope: float,
        absorption_side: str,
        profile_shape: str,
        spread: float,
        is_expiry: bool = False,
        ib_high: float = 0.0,
        ib_low: float = 0.0,
        drive_number: int = 0,
        position_open: bool = False,
        position_side: str = "",
        position_unrealized_pnl: float = 0.0,
        risk_halted: bool = False,
        cooldown_sec: int = 0,
        consecutive_losses: int = 0,
        *,
        market: str = "MCX",
        session_vwap: float = 0.0,
        vwap_std: float = 0.0,
        vwap_upper_2: float = 0.0,
        vwap_lower_2: float = 0.0,
        obi: float = 0.0,
        cvd_divergence: str = "",
        norm_delta: float = 0.0,
        stacked_imbalance_dir: str = "",
        stacked_imbalance_mag: int = 0,
        stacked_imbalance_low: float = 0.0,
        stacked_imbalance_high: float = 0.0,
        nearest_buy_print_below: float = 0.0,
        nearest_sell_print_above: float = 0.0,
        triple_a_phase: str = "",
        triple_a_signal: str = "",
        break_direction: str = "",
        break_type: str = "",
        leg_lvn: float = 0.0,
        prior_poc: float = 0.0,
        npoc_above: float = 0.0,
        npoc_below: float = 0.0,
        compression_box_poc: float = 0.0,
        compression_box_vah: float = 0.0,
        compression_box_val: float = 0.0,
        compression_box_bars: int = 0,
        squeeze_detected: bool = False,
        squeeze_direction: str = "",
        squeeze_trapped_level: float = 0.0,
        pullback_confirmed: bool = False,
        balance_ratio: float = 0.0,
        option_delta: Optional[float] = None,
        consecutive_wins: int = 0,
        setup_grade: str = "",
        allow_trend: bool = True,
        allow_reversion: bool = True,
        drive_entry_valid: bool = False,
        bid: float = 0.0,
        ask: float = 0.0,
        role: Optional[str] = None,
        position_entry_price: float = 0.0,
        position_sl: float = 0.0,
        position_tp: float = 0.0,
        position_bars_held: int = 0,
    ) -> Dict[str, Any]:
        """Evaluates auction state using high-fidelity Fabio Valentini AMT parameters and dual specialized roles."""
        if not self.enabled:
            return {"status": "disabled"}

        if self._agent is None and not self.initialize():
            return {"status": "error", "message": "initialization_failed"}

        # Resolve Role: SCANNING vs POSITION_MANAGEMENT
        effective_role = role or ("POSITION_MANAGEMENT" if position_open else "SCANNING")
        is_position_mgmt = (effective_role == "POSITION_MANAGEMENT")

        # Determine asset class & retail scalper execution policy
        is_opt = is_option_contract(symbol)
        if is_opt and option_delta is not None and option_delta > 0:
            asset_desc = f"Option Contract (Greek Delta {option_delta:.2f})"
        elif is_opt:
            asset_desc = "Option Contract"
        elif market == "MCX":
            asset_desc = "MCX Commodity Futures"
        else:
            asset_desc = "Equity Index Futures"

        if is_position_mgmt:
            policy_desc = "Active Position Management Mode (evaluating hold, trail stop, profit taking, or invalidation exit)"
        else:
            policy_desc = (
                "Retail Option Buyer (call buying for bullish momentum, put buying for bearish momentum; never write naked options)"
                if is_opt
                else "Two-way long and short futures execution permitted"
            )

        # 1. Semantically rich price location relative to Value Area
        if price > vah + 0.01:
            loc_text = (
                f"Price {price:.2f} is trading +{price - vah:.2f} pts ABOVE Value Area High ({vah:.2f}) "
                f"[VAL: {val:.2f}, POC: {poc:.2f}]. Auction state: Expansion and initiative breakout above value."
            )
        elif price < val - 0.01:
            loc_text = (
                f"Price {price:.2f} is trading -{val - price:.2f} pts BELOW Value Area Low ({val:.2f}) "
                f"[VAH: {vah:.2f}, POC: {poc:.2f}]. Auction state: Extension and initiative breakdown below value."
            )
        else:
            dist_poc = price - poc
            loc_text = (
                f"Price {price:.2f} is trading INSIDE Value Area [{val:.2f}, {vah:.2f}], "
                f"{abs(dist_poc):.2f} pts from POC ({poc:.2f}). Auction state: Value acceptance and rotational balance."
            )

        # 2. Market Structure & Profile
        regime_parts = [
            f"Market regime is {market_state} (Profile Shape: {profile_shape or 'D'}).",
            f"Balance ratio: {balance_ratio * 100:.1f}% volume inside value.",
        ]
        if ib_high > 0 and ib_low > 0:
            regime_parts.append(f"Initial Balance: [{ib_low:.2f} - {ib_high:.2f}].")
        if drive_number > 0:
            regime_parts.append(f"Auction Drive: #{drive_number} (Failed probe return: {drive_entry_valid}).")
        if compression_box_poc > 0:
            regime_parts.append(
                f"Micro-compression range active across {compression_box_bars} bars "
                f"[Box VAH: {compression_box_vah:.2f}, VAL: {compression_box_val:.2f}, POC: {compression_box_poc:.2f}]."
            )
        regime_text = " ".join(regime_parts)

        # 3. Session VWAP & Volatility Bands
        if session_vwap > 0:
            vwap_diff = price - session_vwap
            sigmas = (vwap_diff / vwap_std) if vwap_std > 0 else 0.0
            vwap_text = (
                f"Session VWAP is {session_vwap:.2f} (Price vs VWAP: {vwap_diff:+.2f} pts, {sigmas:+.2f}σ). "
                f"Upper +2σ band: {vwap_upper_2:.2f}, Lower -2σ band: {vwap_lower_2:.2f}."
            )
        else:
            vwap_text = "Session VWAP benchmark unavailable."

        # 4. Order Flow, Footprint & Liquidity Depth
        flow_parts = []
        if cvd_slope > 0.15:
            flow_parts.append(f"Aggressive market buyers accumulating inventory (CVD slope +{cvd_slope:.2f})")
        elif cvd_slope < -0.15:
            flow_parts.append(f"Aggressive market sellers distributing inventory (CVD slope {cvd_slope:.2f})")
        else:
            flow_parts.append(f"Market delta flat and neutral (CVD slope {cvd_slope:+.2f})")

        if cvd_divergence:
            flow_parts.append(f"CRITICAL CVD WARNING: {cvd_divergence} divergence active against price action")
        else:
            flow_parts.append("No CVD divergence; order flow confirms price movement")

        if obi > 0.15:
            flow_parts.append(f"Order book depth heavily BID-DOMINATED with +{obi * 100:.1f}% buy depth cushion (OBI +{obi:.2f})")
        elif obi < -0.15:
            flow_parts.append(f"Order book depth heavily ASK-DOMINATED with {obi * 100:.1f}% sell depth pressure (OBI {obi:.2f})")
        else:
            flow_parts.append(f"Order book depth balanced between bids and asks (OBI {obi:+.2f})")

        # Canonical tags: SELL_ABSORBED = sellers absorbed (bullish),
        # BUY_ABSORBED = buyers absorbed (bearish). Bare BUY/SELL accepted
        # as short aliases only when unambiguous — never compare bare BUY/SELL
        # alone (pre-release bare-absorption rule).
        _abs = str(absorption_side or "").upper()
        if "SELL_ABSORBED" in _abs or _abs == "SELL":
            flow_parts.append("Institutional SELL absorption soaking up selling pressure at support")
        elif "BUY_ABSORBED" in _abs or _abs == "BUY":
            flow_parts.append("Institutional BUY absorption capping buying rallies at resistance")
        else:
            flow_parts.append("No institutional absorption detected")

        if stacked_imbalance_dir and stacked_imbalance_mag >= 3:
            flow_parts.append(
                f"Stacked Footprint Bubble: {stacked_imbalance_mag} consecutive 3:1 diagonal "
                f"{stacked_imbalance_dir} imbalances between {stacked_imbalance_low:.2f} and {stacked_imbalance_high:.2f}"
            )

        if nearest_buy_print_below > 0:
            flow_parts.append(f"Nearest institutional buy wall support floor: {nearest_buy_print_below:.2f}")
        if nearest_sell_print_above > 0:
            flow_parts.append(f"Nearest institutional sell wall resistance ceiling: {nearest_sell_print_above:.2f}")

        flow_text = " | ".join(flow_parts)

        # 5. Position Management or Setup Structure
        if is_position_mgmt:
            # Check risk-free status (stop at or beyond entry price)
            is_risk_free = False
            pos_dir = (position_side or "LONG").upper()
            if pos_dir == "LONG" and position_entry_price > 0:
                is_risk_free = bool(position_sl >= position_entry_price)
            elif pos_dir == "SHORT" and position_entry_price > 0:
                is_risk_free = bool(position_sl > 0 and position_sl <= position_entry_price)

            pos_block = (
                f"[ACTIVE POSITION UNDER MANAGEMENT]\n"
                f"Position Side: {pos_dir} | Entry Price: {position_entry_price:.2f} | Current LTP: {price:.2f}\n"
                f"Unrealized PnL: {position_unrealized_pnl:+.2f} pts ({'PROFITABLE' if position_unrealized_pnl > 0 else 'DRAWDOWN'})\n"
                f"Stop Loss: {position_sl:.2f} ({'RISK-FREE (Locked Profit / Breakeven)' if is_risk_free else 'Capital at Risk'})\n"
                f"Take Profit Target: {position_tp:.2f} | Bars Held: {position_bars_held}\n"
            )
            setup_text = (
                f"Target POC Above: {npoc_above:.2f} | Target POC Below: {npoc_below:.2f} | Prior POC: {prior_poc:.2f} | "
                f"Leg LVN: {leg_lvn:.2f}"
            )
        else:
            is_risk_free = False
            pos_block = ""
            setup_parts = []
            if triple_a_phase:
                setup_parts.append(f"Triple-A Machine: {triple_a_phase} phase (Signal: {triple_a_signal or 'NONE'})")
            if break_type and break_direction:
                setup_parts.append(f"Breakout State: {break_type} {break_direction}")
            if leg_lvn > 0:
                setup_parts.append(f"Impulse Leg LVN: {leg_lvn:.2f}")
            if squeeze_detected:
                setup_parts.append(f"Trapped Squeeze: {squeeze_direction} at {squeeze_trapped_level:.2f} (Retest confirmed: {pullback_confirmed})")
            if npoc_above > 0:
                setup_parts.append(f"Naked POC Target Above: {npoc_above:.2f}")
            if npoc_below > 0:
                setup_parts.append(f"Naked POC Target Below: {npoc_below:.2f}")
            if prior_poc > 0:
                setup_parts.append(f"Prior Session POC: {prior_poc:.2f}")
            setup_text = " | ".join(setup_parts) if setup_parts else "No structural setup active. Auction is in two-way balance chop around POC."

        # 6. Session Timing & Account Risk Clearances
        if risk_halted or cooldown_sec > 0:
            risk_text = (
                f"RISK BLOCKED: Account execution halted (halted={risk_halted}, cooldown={cooldown_sec}s, losses={consecutive_losses}). "
                "Strictly prohibit new trades."
            )
        else:
            risk_text = (
                f"Risk Clearance: NORMAL (Drawdown limits satisfied, cooldown=0s, consecutive_wins={consecutive_wins}, "
                f"setup_grade={setup_grade or 'Standard'}). Session timing: allow_trend={allow_trend}, allow_reversion={allow_reversion}."
            )

        spread_pts = (ask - bid) if (ask > 0 and bid > 0) else spread
        risk_text += f" Spread: {spread_pts:.2f} pts (Bid {bid:.2f} / Ask {ask:.2f})."

        # Assemble State Representation
        if is_position_mgmt:
            state_repr = (
                f"[MARKET & CONTRACT]\n"
                f"Instrument: {symbol} | Market: {market} | Role: POSITION_MANAGEMENT\n"
                f"{pos_block}\n"
                f"[AUCTION MARKET STRUCTURE]\n"
                f"{loc_text}\n"
                f"{regime_text}\n"
                f"{vwap_text}\n\n"
                f"[VOLUME & ORDER FLOW MICROSTRUCTURE]\n"
                f"{flow_text}\n\n"
                f"[STRUCTURAL TARGETS]\n"
                f"{setup_text}\n\n"
                f"[RISK & CLEARANCE]\n"
                f"{risk_text}"
            )

            # Specialized Position Management Schema
            schema = {
                "management_action": {
                    "type": "choice",
                    "instructions": (
                        f"Evaluate active position management for the open {position_side or 'LONG'} position: "
                        "Choose HOLD (Trend Intact) if order flow and CVD confirm continuation toward target. "
                        "Choose TIGHTEN_SL (Move Stop Higher) if price has advanced and stop should be ratcheted to lock profit. "
                        "Choose TAKE_PROFIT (Target Hit / Scale Out) if structural target, Naked POC, or extreme band is hit. "
                        "Choose EXIT (Thesis Flipped / Adverse Flow) if opposing order flow, adverse absorption, or reversal divergence threatens capital."
                    ),
                    "criteria": [
                        "HOLD (Trend Intact)",
                        "TIGHTEN_SL (Move Stop Higher)",
                        "TAKE_PROFIT (Target Hit / Scale Out)",
                        "EXIT (Thesis Flipped / Adverse Flow)",
                    ],
                },
                "holding_conviction": {
                    "type": "score",
                    "instructions": "Rate holding conviction from 0 (urgent exit) to 4 (high conviction ride):",
                    "criteria": [
                        "0: Urgent Exit (Adverse Flow)",
                        "1: High Risk / Consider Closing",
                        "2: Neutral / Tight Stop Required",
                        "3: Strong Hold (Momentum Intact)",
                        "4: Elite Hold (Max Continuation Conviction)",
                    ],
                },
                "position_verdict": {
                    "type": "choice",
                    "instructions": "Select the position status verdict:",
                    "criteria": [
                        "RUNNING_WELL (Flow Confirms)",
                        "EXTENDED_EXHAUSTION (Consider Scaling)",
                        "STAGNANT_CONSOLIDATION (Time Risk)",
                        "ADVERSE_REVERSAL (Opposing Volume)",
                    ],
                },
                "execution_gate": {
                    "type": "choice",
                    "instructions": "Determine if position management execution is permitted by risk rules:",
                    "criteria": ["PERMITTED (Risk limits cleared)", "BLOCKED (Risk halted or cooldown active)"],
                },
                "trade_permitted": {
                    "type": "noul",
                    "instructions": "Are risk rules and limits satisfied to permit trade operations?",
                },
            }
        else:
            state_repr = (
                f"[MARKET & CONTRACT]\n"
                f"Instrument: {symbol} | Market: {market} | Role: SCANNING | Asset: {asset_desc} | Session Phase: {session_phase}\n"
                f"Execution Policy: {policy_desc}.\n\n"
                f"[AUCTION MARKET STRUCTURE]\n"
                f"{loc_text}\n"
                f"{regime_text}\n"
                f"{vwap_text}\n\n"
                f"[VOLUME & ORDER FLOW MICROSTRUCTURE]\n"
                f"{flow_text}\n\n"
                f"[FABIO AMT SETUP CONFLUENCE]\n"
                f"{setup_text}\n\n"
                f"[RISK & EXECUTION CLEARANCE]\n"
                f"{risk_text}\n"
                "Existing Position: None (Account flat, ready for entry)."
            )

            # Specialized Scanning Schema
            schema = {
                "action": {
                    "type": "choice",
                    "instructions": (
                        "Evaluate auction momentum and order flow confluence according to Fabio Valentini AMT: "
                        "Choose BUY (Enter Long) if aggressive buyers are driving an initiative breakout above value, or absorbing selling at value low, supported by positive CVD and bid depth. "
                        "Choose SELL (Enter Short) if aggressive sellers are driving a breakdown below value, or rejecting value high, supported by negative CVD and ask depth. "
                        "Choose HOLD (Wait / No Edge) if market is dead chop, volume is collapsed, price is sitting at POC inside balance, or risk rules forbid trading."
                    ),
                    "criteria": ["BUY (Enter Long)", "SELL (Enter Short)", "HOLD (Wait / No Edge)"],
                },
                "setup": {
                    "type": "choice",
                    "instructions": "Identify the primary Fabio Valentini AMT setup structure:",
                    "criteria": [
                        "Triple-A (Absorption + Accumulation Breakout)",
                        "VA-Fade (Value Area Mean Reversion)",
                        "Second-Drive (Failed Probe Return)",
                        "LVN-Sniper (Low Volume Node Rejection)",
                        "No Edge / Random Chop",
                    ],
                },
                "conviction_score": {
                    "type": "score",
                    "instructions": (
                        "Rate the setup conviction and confluence quality from 0 to 4: "
                        "0 = No edge / dead chop / rotational balance / conflicting CVD divergence / risk halt. "
                        "1 = Marginal edge / weak volume / noise. "
                        "2 = Standard B-grade setup with partial confluence. "
                        "3 = High-conviction A-grade setup with CVD and depth alignment. "
                        "4 = Elite A+ confluence: Triple-A aggression, stacked imbalance, depth support, and clean structural target."
                    ),
                    "criteria": [
                        "0: No Edge / Dead Market (Avoid)",
                        "1: Marginal Edge / C-grade (Noise)",
                        "2: Standard Edge / B-grade (Normal)",
                        "3: Strong Edge / A-grade (High Conviction)",
                        "4: Elite Edge / A+ Confluence (Max Conviction)",
                    ],
                },
                "execution_gate": {
                    "type": "choice",
                    "instructions": "Determine if trade execution is permitted by risk rules, cooldowns, spread tolerance, and session timing:",
                    "criteria": ["PERMITTED (Risk limits cleared)", "BLOCKED (Risk halted or cooldown active)"],
                },
                "trade_permitted": {
                    "type": "noul",
                    "instructions": "Are all risk limits, cooldowns, spread tolerance, and session timing rules satisfied to permit real execution?",
                },
            }

        try:
            with self._lock:
                t0 = time.perf_counter()
                pred = self._agent.predict(state_repr, schema)
                if mx:
                    mx.eval()
                lat_ms = (time.perf_counter() - t0) * 1000.0

            ans = pred.get("answers", {})
            exec_res = ans.get("execution_gate", {})
            permitted_res = ans.get("trade_permitted", {})
            gate_probs = exec_res.get("probabilities", {})
            gate_choice = exec_res.get("choice", "PERMITTED")
            trade_permitted_prob = round(
                float(gate_probs.get("PERMITTED (Risk limits cleared)", permitted_res.get("noul", permitted_res.get("p_true", 0.0)))),
                4,
            )
            gate_verdict = "PERMITTED" if "PERMITTED" in gate_choice else "BLOCKED"

            if is_position_mgmt:
                # ── POSITION MANAGEMENT RESULT MAPPING ──
                mgmt_res = ans.get("management_action", {})
                verdict_res = ans.get("position_verdict", {})
                score_res = ans.get("holding_conviction", {})

                raw_action = mgmt_res.get("choice", "HOLD")
                if "HOLD" in raw_action:
                    std_action = "HOLD"
                elif "TIGHTEN" in raw_action:
                    std_action = "TIGHTEN_SL"
                elif "TAKE_PROFIT" in raw_action:
                    std_action = "TAKE_PROFIT"
                elif "EXIT" in raw_action:
                    std_action = "EXIT"
                else:
                    std_action = "HOLD"

                raw_verdict = verdict_res.get("choice", "RUNNING_WELL")
                if "RUNNING" in raw_verdict:
                    std_verdict = "RUNNING_WELL"
                elif "EXTENDED" in raw_verdict:
                    std_verdict = "EXTENDED_EXHAUSTION"
                elif "STAGNANT" in raw_verdict:
                    std_verdict = "STAGNANT_CONSOLIDATION"
                elif "ADVERSE" in raw_verdict:
                    std_verdict = "ADVERSE_REVERSAL"
                else:
                    std_verdict = "RUNNING_WELL"

                raw_probs = mgmt_res.get("probabilities", {})
                clean_probs = {
                    "HOLD": round(float(raw_probs.get("HOLD (Trend Intact)", 0.80)), 4),
                    "TIGHTEN_SL": round(float(raw_probs.get("TIGHTEN_SL (Move Stop Higher)", 0.10)), 4),
                    "TAKE_PROFIT": round(float(raw_probs.get("TAKE_PROFIT (Target Hit / Scale Out)", 0.05)), 4),
                    "EXIT": round(float(raw_probs.get("EXIT (Thesis Flipped / Adverse Flow)", 0.05)), 4),
                }

                score_val = round(float(score_res.get("score", 2.5)), 3)
                score_pct = round((score_val / 4.0) * 100, 1)

                active_pos_payload = {
                    "side": position_side or "LONG",
                    "entryPrice": position_entry_price,
                    "currentPrice": price,
                    "pnl": position_unrealized_pnl,
                    "stopLoss": position_sl,
                    "takeProfit": position_tp,
                    "barsHeld": position_bars_held,
                    "isRiskFree": is_risk_free,
                }

                thesis = (
                    f"Laya-MLX Position Manager: [{std_action}] recommendation (Holding Conviction: {score_val:.2f}/4.0). "
                    f"{position_side or 'Open'} position running at {position_unrealized_pnl:+.2f} pts uPnL "
                    f"({'Risk-Free' if is_risk_free else 'Capital at Risk'}). Verdict: {std_verdict}. "
                    f"Order flow: CVD slope {cvd_slope:+.2f}, OBI {obi:+.2f}."
                )

                return {
                    "status": "ok",
                    "role": "POSITION_MANAGEMENT",
                    "action": std_action,
                    "setup": "POSITION_MGMT",
                    "position_verdict": std_verdict,
                    "active_position": active_pos_payload,
                    "probabilities": clean_probs,
                    "confidence": round(float(mgmt_res.get("confidence", 0.0)), 4),
                    "conviction_score": score_val,
                    "score_max": 4.0,
                    "score_percent": score_pct,
                    "trade_permitted_p": trade_permitted_prob,
                    "execution_gate": gate_verdict,
                    "thesis": thesis,
                    "latency_ms": round(lat_ms, 2),
                    "source": "LAYA_MLX_MULTILINGUAL",
                    "model": "Laya-MLX (322M mmBERT)",
                    "timestamp": time.time(),
                }
            else:
                # ── SCANNING RESULT MAPPING ──
                action_res = ans.get("action", {})
                setup_res = ans.get("setup", {})
                conviction_res = ans.get("conviction_score", {})

                raw_action = action_res.get("choice", "HOLD")
                if "BUY" in raw_action:
                    std_action = "ENTER_LONG"
                elif "SELL" in raw_action:
                    std_action = "ENTER_SHORT"
                else:
                    std_action = "FLAT"

                raw_setup = setup_res.get("choice", "No Edge")
                if "Triple-A" in raw_setup:
                    std_setup = "TRIPLE_A"
                elif "VA-Fade" in raw_setup:
                    std_setup = "VA_FADE"
                elif "Second-Drive" in raw_setup:
                    std_setup = "SECOND_DRIVE"
                elif "LVN-Sniper" in raw_setup:
                    std_setup = "LVN_SNIPER"
                else:
                    std_setup = "NO_EDGE"

                raw_probs = action_res.get("probabilities", {})
                clean_probs = {
                    "ENTER_LONG": round(float(raw_probs.get("BUY (Enter Long)", 0.10)), 4),
                    "ENTER_SHORT": round(float(raw_probs.get("SELL (Enter Short)", 0.10)), 4),
                    "FLAT": round(float(raw_probs.get("HOLD (Wait / No Edge)", raw_probs.get("HOLD (Flat / No Edge)", 0.80))), 4),
                }

                raw_setup_probs = setup_res.get("probabilities", {})
                clean_setup_probs = {
                    "TRIPLE_A": round(float(raw_setup_probs.get("Triple-A (Absorption + Accumulation Breakout)", 0.10)), 4),
                    "VA_FADE": round(float(raw_setup_probs.get("VA-Fade (Value Area Mean Reversion)", 0.10)), 4),
                    "SECOND_DRIVE": round(float(raw_setup_probs.get("Second-Drive (Failed Probe Return)", 0.10)), 4),
                    "LVN_SNIPER": round(float(raw_setup_probs.get("LVN-Sniper (Low Volume Node Rejection)", 0.10)), 4),
                    "NO_EDGE": round(float(raw_setup_probs.get("No Edge / Random Chop", 0.60)), 4),
                }

                score_val = round(float(conviction_res.get("score", 0.0)), 3)
                score_pct = round((score_val / 4.0) * 100, 1)

                thesis = (
                    f"Laya-MLX Auction Scanner: [{std_setup}] setup with [{std_action}] conviction "
                    f"({score_val:.2f}/4.0, {score_pct}%). Market {market_state} with CVD slope {cvd_slope:+.2f} "
                    f"and OBI {obi:+.2f}. Risk clearance: {gate_verdict} (Safety {trade_permitted_prob * 100:.1f}%)."
                )

                return {
                    "status": "ok",
                    "role": "SCANNING",
                    "action": std_action,
                    "setup": std_setup,
                    "probabilities": clean_probs,
                    "setup_probabilities": clean_setup_probs,
                    "confidence": round(float(action_res.get("confidence", 0.0)), 4),
                    "conviction_score": score_val,
                    "score_max": 4.0,
                    "score_percent": score_pct,
                    "trade_permitted_p": trade_permitted_prob,
                    "execution_gate": gate_verdict,
                    "thesis": thesis,
                    "latency_ms": round(lat_ms, 2),
                    "source": "LAYA_MLX_MULTILINGUAL",
                    "model": "Laya-MLX (322M mmBERT)",
                    "timestamp": time.time(),
                }
        except Exception as e:
            logger.error("Laya evaluation error for %s: %s", symbol, e)
            return {"status": "error", "message": str(e)}

    def evaluate_from_context(self, ctx: Any) -> Dict[str, Any]:
        """Convenience method extracting full high-fidelity auction fields directly from a DecisionContext."""
        if not self.enabled:
            return {"status": "disabled"}

        symbol = getattr(ctx, "symbol", "UNKNOWN")
        market = getattr(ctx, "market", "MCX")
        bar_idx = getattr(ctx, "bar_index", -1)

        # Fast path: return cached evaluation for this symbol & bar index
        if bar_idx >= 0 and symbol in self._eval_cache:
            cached_idx, cached_res = self._eval_cache[symbol]
            if cached_idx == bar_idx:
                return cached_res

        # Guard: skip cold startup / warmup replay to protect Apple Silicon Metal buffer
        warmup_done = getattr(ctx, "warmup_complete", True)
        bar = getattr(ctx, "bar", None)
        price = float(bar.close if bar else 0.0)

        pos_open = bool(getattr(ctx, "position_open", False))
        role = "POSITION_MANAGEMENT" if pos_open else "SCANNING"

        if not warmup_done or (bar_idx >= 0 and bar_idx < 15) or price <= 0.0:
            return {
                "status": "warmup_pending",
                "role": role,
                "action": "HOLD" if pos_open else "FLAT",
                "setup": "POSITION_MGMT" if pos_open else "NO_EDGE",
                "probabilities": {"HOLD": 1.0} if pos_open else {"ENTER_LONG": 0.1, "ENTER_SHORT": 0.1, "FLAT": 0.8},
                "confidence": 0.0,
                "conviction_score": 0.0,
                "score_max": 4.0,
                "score_percent": 0.0,
                "trade_permitted_p": 0.0,
                "latency_ms": 0.0,
                "source": "LAYA_MLX_MULTILINGUAL",
                "model": "Laya-MLX (322M mmBERT)",
                "timestamp": time.time(),
            }

        state = getattr(ctx, "state", None)
        poc = float(getattr(ctx, "poc", getattr(state, "poc", price) if state else price) or price)
        vah = float(getattr(ctx, "vah", getattr(state, "vah", price) if state else price) or price)
        val = float(getattr(ctx, "val", getattr(state, "val", price) if state else price) or price)

        phase = str(getattr(ctx, "session_phase", "REGULAR") or "REGULAR")
        m_state = getattr(ctx, "market_state", None)
        market_state = m_state.value if hasattr(m_state, "value") else str(m_state or "BALANCED")

        session_vwap = float(getattr(ctx, "session_vwap", 0.0) or (float(bar.vwap) if bar and getattr(bar, "vwap", None) else 0.0))
        vwap_std = float(getattr(ctx, "vwap_std", 0.0))
        vwap_upper_2 = float(getattr(ctx, "vwap_upper_2", 0.0))
        vwap_lower_2 = float(getattr(ctx, "vwap_lower_2", 0.0))

        obi = float(getattr(ctx, "obi", 0.0))
        cvd_slope = float(getattr(ctx, "cvd_slope", 0.0))
        cvd_divergence = str(getattr(ctx, "cvd_divergence", "") or "")
        norm_delta = float(getattr(ctx, "norm_delta", 0.0))
        absorption_side = str(getattr(ctx, "absorption_side", "NONE") or "NONE")

        profile_shape = str(getattr(ctx, "profile_shape", getattr(state, "shape", "D") if state else "D") or "D")
        balance_ratio = float(getattr(ctx, "balance_ratio", 0.0))
        ib_high = float(getattr(ctx, "ib_high", getattr(state, "ib_high", 0.0) if state else 0.0))
        ib_low = float(getattr(ctx, "ib_low", getattr(state, "ib_low", 0.0) if state else 0.0))
        drive_num = int(getattr(ctx, "drive_number", getattr(state, "drive_number", 0) if state else 0))
        drive_entry_valid = bool(getattr(ctx, "drive_entry_valid", False))

        leg_lvn = float(getattr(ctx, "leg_lvn", 0.0))
        prior_poc = float(getattr(ctx, "prior_poc", 0.0))
        npoc_above = float(getattr(ctx, "npoc_above", 0.0))
        npoc_below = float(getattr(ctx, "npoc_below", 0.0))

        compression_box_poc = float(getattr(ctx, "compression_box_poc", 0.0))
        compression_box_vah = float(getattr(ctx, "compression_box_vah", 0.0))
        compression_box_val = float(getattr(ctx, "compression_box_val", 0.0))
        compression_box_bars = int(getattr(ctx, "compression_box_bars", 0))

        squeeze_detected = bool(getattr(ctx, "squeeze_detected", False))
        squeeze_direction = str(getattr(ctx, "squeeze_direction", "") or "")
        squeeze_trapped_level = float(getattr(ctx, "squeeze_trapped_level", 0.0))
        pullback_confirmed = bool(getattr(ctx, "pullback_confirmed", False))

        stacked_imbalance_dir = str(getattr(ctx, "stacked_imbalance_direction", "") or "")
        stacked_imbalance_mag = int(getattr(ctx, "stacked_imbalance_magnitude", 0))
        stacked_imbalance_low = float(getattr(ctx, "stacked_imbalance_price_low", 0.0))
        stacked_imbalance_high = float(getattr(ctx, "stacked_imbalance_price_high", 0.0))

        nearest_buy_print_below = float(getattr(ctx, "nearest_buy_print_below", 0.0))
        nearest_sell_print_above = float(getattr(ctx, "nearest_sell_print_above", 0.0))

        triple_a_phase = str(getattr(ctx, "triple_a_phase", "") or "")
        triple_a_signal = str(getattr(ctx, "triple_a_signal", "") or "")
        break_direction = str(getattr(ctx, "break_direction", "") or "")
        break_type = str(getattr(ctx, "break_type", "") or "")

        bid = float(getattr(ctx, "bid", 0.0))
        ask = float(getattr(ctx, "ask", 0.0))
        spread = float(getattr(ctx, "spread", (ask - bid) if (ask > 0 and bid > 0) else 0.05))
        is_expiry = bool(getattr(ctx, "is_expiry", False))
        allow_trend = bool(getattr(ctx, "allow_trend", True))
        allow_reversion = bool(getattr(ctx, "allow_reversion", True))
        option_delta = getattr(ctx, "option_delta", None)

        pos_side = str(getattr(ctx, "position_side", "") or "")
        pos_pnl = float(getattr(ctx, "position_unrealized_pnl", 0.0))
        pos_entry = float(getattr(ctx, "position_entry_price", 0.0))
        pos_sl = float(getattr(ctx, "position_sl", 0.0))
        pos_tp = float(getattr(ctx, "position_tp", 0.0))
        pos_bars_held = int(getattr(ctx, "position_bars_held", 0))

        risk_halt = bool(getattr(ctx, "risk_halted", False))
        cooldown = int(getattr(ctx, "cooldown_remaining_sec", 0))
        losses = int(getattr(ctx, "consecutive_losses", 0))
        wins = int(getattr(ctx, "consecutive_wins", 0))
        setup_grade = str(getattr(ctx, "setup_grade", "") or "")

        res = self.evaluate_auction_snapshot(
            symbol=symbol,
            session_phase=phase,
            market_state=market_state,
            price=price,
            poc=poc,
            vah=vah,
            val=val,
            cvd_slope=cvd_slope,
            absorption_side=absorption_side,
            profile_shape=profile_shape,
            spread=spread,
            is_expiry=is_expiry,
            ib_high=ib_high,
            ib_low=ib_low,
            drive_number=drive_num,
            position_open=pos_open,
            position_side=pos_side,
            position_unrealized_pnl=pos_pnl,
            risk_halted=risk_halt,
            cooldown_sec=cooldown,
            consecutive_losses=losses,
            market=market,
            session_vwap=session_vwap,
            vwap_std=vwap_std,
            vwap_upper_2=vwap_upper_2,
            vwap_lower_2=vwap_lower_2,
            obi=obi,
            cvd_divergence=cvd_divergence,
            norm_delta=norm_delta,
            stacked_imbalance_dir=stacked_imbalance_dir,
            stacked_imbalance_mag=stacked_imbalance_mag,
            stacked_imbalance_low=stacked_imbalance_low,
            stacked_imbalance_high=stacked_imbalance_high,
            nearest_buy_print_below=nearest_buy_print_below,
            nearest_sell_print_above=nearest_sell_print_above,
            triple_a_phase=triple_a_phase,
            triple_a_signal=triple_a_signal,
            break_direction=break_direction,
            break_type=break_type,
            leg_lvn=leg_lvn,
            prior_poc=prior_poc,
            npoc_above=npoc_above,
            npoc_below=npoc_below,
            compression_box_poc=compression_box_poc,
            compression_box_vah=compression_box_vah,
            compression_box_val=compression_box_val,
            compression_box_bars=compression_box_bars,
            squeeze_detected=squeeze_detected,
            squeeze_direction=squeeze_direction,
            squeeze_trapped_level=squeeze_trapped_level,
            pullback_confirmed=pullback_confirmed,
            balance_ratio=balance_ratio,
            option_delta=option_delta,
            consecutive_wins=wins,
            setup_grade=setup_grade,
            allow_trend=allow_trend,
            allow_reversion=allow_reversion,
            drive_entry_valid=drive_entry_valid,
            bid=bid,
            ask=ask,
            role=role,
            position_entry_price=pos_entry,
            position_sl=pos_sl,
            position_tp=pos_tp,
            position_bars_held=pos_bars_held,
        )

        if bar_idx >= 0 and res.get("status") == "ok":
            self._eval_cache[symbol] = (bar_idx, res)

        return res


_GLOBAL_LAYA_ADVISOR: Optional[LayaDecisionAdvisor] = None


def get_laya_advisor() -> LayaDecisionAdvisor:
    """Returns the process singleton LayaDecisionAdvisor."""
    global _GLOBAL_LAYA_ADVISOR
    if _GLOBAL_LAYA_ADVISOR is None:
        _GLOBAL_LAYA_ADVISOR = LayaDecisionAdvisor()
        _GLOBAL_LAYA_ADVISOR.initialize()
    return _GLOBAL_LAYA_ADVISOR
