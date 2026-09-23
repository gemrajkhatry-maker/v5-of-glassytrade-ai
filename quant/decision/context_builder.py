"""DecisionContextBuilder — constructs the DecisionContext from engine state.

Extracted from QuantEngine to improve locality: context construction is a
pure function of inputs (state, bar, AMT DTO, risk state) with no side
effects. The builder receives dependencies via constructor injection.
"""

from __future__ import annotations

import logging

from quant.contracts.constants import (
    FABIO_CVD_THRESHOLD_MCX,
    FABIO_CVD_THRESHOLD_NSE,
    FABIO_OBI_THRESHOLD,
    FABIO_OFI_THRESHOLD,
)
from quant.contracts.enums import MarketState
from quant.contracts.instrument_registry import is_option_contract
from quant.contracts.ports.greeks import GreeksPort
from quant.contracts.vocabulary import absorption_direction
from quant.amt.snapshot import AnalysisSnapshot
from quant.decision.context import DecisionContext
from quant.session_gates import ist_dt, session_allow_entry
from quant.amt.session.context import get_session_info
from quant.bars import DEFAULT_INTERVAL_SEC
from quant.decision.data_quality import normalize_data_quality, normalize_evidence_provenance

logger = logging.getLogger(__name__)

# Deterministic conviction the engine reports for its auction-state decisions.
# Construction metadata on the context only — no decision branch may read it
# (the old gate-4 probability check consumed it against a 0.65 threshold and
# was constant-true; removed in v7 prune N3).
_DETERMINISTIC_CONVICTION = 0.7


# ---------------------------------------------------------------------------
# Direction resolution (Fabio Triple-A edge)
# ---------------------------------------------------------------------------


def _print_levels_from_dto(amt_dto: dict, bar) -> tuple[float, float]:
    """Nearest big aggressive-print levels relative to the current close.

    A large BUY print below price acts as support; a large SELL print above
    acts as resistance (Fabio Gap #10: prints CREATE structural levels).
    "Big" = volume >= 2x the mean print volume. Returns (support, resistance)
    with 0.0 when absent.
    """
    prints = amt_dto.get("aggressivePrints") or []
    if not prints:
        return 0.0, 0.0
    px = float(getattr(bar, "close", 0) or 0) if bar is not None else 0.0
    if px <= 0:
        return 0.0, 0.0
    mean_vol = sum(float(p.get("volume") or 0) for p in prints) / len(prints)
    big = [p for p in prints if float(p.get("volume") or 0) >= 2.0 * mean_vol]
    support = max(
        (float(p["price"]) for p in big
         if p.get("side") == "BUY" and float(p["price"]) < px),
        default=0.0,
    )
    resistance = min(
        (float(p["price"]) for p in big
         if p.get("side") == "SELL" and float(p["price"]) > px),
        default=0.0,
    )
    return support, resistance


def _print_levels_from_result(prints, bar) -> tuple[float, float]:
    """Same as ``_print_levels_from_dto`` but reads typed ``AggressivePrint`` rows."""
    if not prints:
        return 0.0, 0.0
    px = float(getattr(bar, "close", 0) or 0) if bar is not None else 0.0
    if px <= 0:
        return 0.0, 0.0
    mean_vol = sum(float(getattr(p, "volume", 0) or 0) for p in prints) / len(prints)
    big = [p for p in prints if float(getattr(p, "volume", 0) or 0) >= 2.0 * mean_vol]
    support = max(
        (float(p.price) for p in big
         if getattr(p, "side", None) == "BUY" and float(p.price) < px),
        default=0.0,
    )
    resistance = min(
        (float(p.price) for p in big
         if getattr(p, "side", None) == "SELL" and float(p.price) > px),
        default=0.0,
    )
    return support, resistance


def _latest_stacked_imbalance(amt_dto: dict) -> tuple[str, int, float, float]:
    """Summarize the most recent stacked footprint imbalance.

    Returns (direction, magnitude, price_low, price_high). Empty/zero when no
    stacked imbalance exists in the latest footprint candle. Fabio: 3+
    consecutive 3:1 diagonal imbalances = institutional volume bubble.
    """
    fps = amt_dto.get("footprints") or {}
    if not fps:
        return "", 0, 0.0, 0.0
    sorted_keys = sorted(fps.keys(), reverse=True)
    # Check current forming candle, and fall back to the most recently completed candle
    for key in sorted_keys[:2]:
        levels = (fps[key] or {}).get("levels") or []
        best_dir, best_n = "", 0
        run_dir, run_n, run_prices = "", 0, []
        best_prices: list[float] = []
        for lvl in levels:
            if not lvl.get("stacked"):
                run_dir, run_n, run_prices = "", 0, []
                continue
            d = "BUY" if lvl.get("ask", 0) > lvl.get("bid", 0) else "SELL"
            if d != run_dir:
                run_dir, run_n, run_prices = d, 1, [lvl.get("price", 0.0)]
            else:
                run_n += 1
                run_prices.append(lvl.get("price", 0.0))
            if run_n > best_n:
                best_dir, best_n = run_dir, run_n
                best_prices = list(run_prices)
        if best_n >= 3:
            return best_dir, best_n, min(best_prices), max(best_prices)
    return "", 0, 0.0, 0.0



class DecisionContextBuilder:
    """Builds a DecisionContext from engine state and AMT analysis.

    The builder encapsulates the direction resolution logic (auction-state
    edge, absorption side, OBI imbalance, VA location) and the VWAP bias
    filter, producing a fully-populated DecisionContext ready for evaluation.
    """

    def __init__(self, *, greeks: GreeksPort | None = None) -> None:
        # Missing Greeks → option_delta stays None (DATA_DEGRADED at translate).
        self._greeks = greeks

    def _option_delta(
        self,
        symbol: str,
        *,
        contract_symbol: str | None = None,
        amt_dto: dict | None = None,
    ) -> float | None:
        """Greek delta for the *execution* option contract — never invent 0.50.

        When the decision context is built on the underlying (eval_symbol) but
        the engine trades an option, pass ``contract_symbol`` so lookup keys
        off the contract, not the futures root.
        """
        lookup = contract_symbol or symbol
        if not is_option_contract(lookup):
            return None
        if self._greeks is not None:
            try:
                raw = self._greeks.delta(lookup)
            except Exception:
                logger.debug("GreeksPort.delta failed for %s", lookup, exc_info=True)
                raw = None
            parsed = self._parse_delta(raw)
            if parsed is not None:
                return parsed
        # Bridge: scan/coordinator may stamp optionDelta onto the AMT DTO.
        if amt_dto:
            parsed = self._parse_delta(amt_dto.get("optionDelta"))
            if parsed is not None:
                return parsed
        return None

    @staticmethod
    def _parse_delta(raw: object) -> float | None:
        if raw is None:
            return None
        try:
            d = float(raw)
        except (TypeError, ValueError):
            return None
        if not (0.0 < abs(d) <= 1.0):
            return None
        return abs(d)

    # ------------------------------------------------------------------
    # DTO safe-access helpers (eliminate repeated ``or`` patterns)
    # ------------------------------------------------------------------

    @staticmethod
    def _df(d: dict, key: str, default: float = 0.0) -> float:
        """Safely read a float from a dict (None/empty -> default)."""
        return float(d.get(key) or default)

    @staticmethod
    def _ds(d: dict, key: str, default: str = "") -> str:
        """Safely read a string from a dict (None/empty -> default)."""
        return str(d.get(key) or default)

    @staticmethod
    def _db(d: dict, key: str) -> bool:
        """Safely read a bool from a dict (None/empty -> False)."""
        return bool(d.get(key))

    @staticmethod
    def _di(d: dict, key: str, default: int = 0) -> int:
        """Safely read an int from a dict (None/empty -> default)."""
        return int(d.get(key) or default)

    @staticmethod
    def _vwap_std_from_result(result) -> float:
        """Price-unit σ from VWAP bands (not deviation-in-sigmas)."""
        session_vwap = float(getattr(result, "session_vwap", 0) or 0)
        upper_1 = float(getattr(result, "vwap_upper_1", 0) or 0)
        if session_vwap > 0 and upper_1 > 0:
            return abs(upper_1 - session_vwap)
        return 0.0

    # ------------------------------------------------------------------
    # Direction resolution
    # ------------------------------------------------------------------

    def _resolve_direction(self, amt_dto: dict, close_px: float, vah: float,
                           val: float, obi: float, ofi: float,
                           vwap_upper_1: float, vwap_lower_1: float,
                           market: str = "NSE") -> str | None:
        """Determine agent direction from AMT state (hierarchy of intent)."""
        raw_ms = self._ds(amt_dto, "marketState", "BALANCED").upper()
        break_dir = self._ds(amt_dto, "breakDirection").upper()
        break_type = self._ds(amt_dto, "breakType").upper()
        triple_a_sig = self._ds(amt_dto, "tripleASignal").upper()
        cvd_val = self._df(amt_dto, "cvdSlope")

        cvd_threshold = FABIO_CVD_THRESHOLD_MCX if str(market).upper() == "MCX" else FABIO_CVD_THRESHOLD_NSE
        if break_type == "INITIATIVE" and break_dir in ("UP", "DOWN"):
            # ponytail: CVD strongly opposing the break indicates absorption/exhaustion trap (Fabio Gap #2/#7)
            if break_dir == "DOWN" and cvd_val > cvd_threshold:
                return "LONG"
            if break_dir == "UP" and cvd_val < -cvd_threshold:
                return "SHORT"
            return "LONG" if break_dir == "UP" else "SHORT"
        if triple_a_sig in ("LONG", "SHORT"):
            return triple_a_sig
        if absorption_direction(amt_dto.get("absorptionSide")):
            return absorption_direction(amt_dto.get("absorptionSide"))
        if obi >= FABIO_OBI_THRESHOLD and close_px > vwap_upper_1:
            return "LONG"
        if obi <= -FABIO_OBI_THRESHOLD and close_px < vwap_lower_1:
            return "SHORT"
        if cvd_val > cvd_threshold and (close_px > vah or ofi > FABIO_OFI_THRESHOLD):
            return "LONG"
        if cvd_val < -cvd_threshold and (close_px < val or ofi < -FABIO_OFI_THRESHOLD):
            return "SHORT"
        if raw_ms == "IMBALANCED":
            if (vah > 0 and close_px > vah) or ofi > FABIO_OFI_THRESHOLD or (close_px > vwap_upper_1):
                return "LONG"
            if (val > 0 and close_px < val) or ofi < -FABIO_OFI_THRESHOLD or (close_px < vwap_lower_1):
                return "SHORT"
        if raw_ms == "BALANCED":
            if val > 0 and close_px <= val and cvd_val >= -0.2:
                return "LONG"
            if vah > 0 and close_px >= vah and cvd_val <= 0.2:
                return "SHORT"
            if cvd_val > cvd_threshold:
                return "LONG"
            if cvd_val < -cvd_threshold:
                return "SHORT"
        return None

    @staticmethod
    def _nearest_leg_lvn(amt_dto: dict, close_px: float) -> float:
        """Compatibility wrapper around the canonical LVN resolver."""
        from quant.amt.profile.leg_lvn import resolve_leg_lvn
        return resolve_leg_lvn(amt_dto, close_px).level

    # ------------------------------------------------------------------
    # Setup evidence
    # ------------------------------------------------------------------

    def _build_setup_evidence(self, amt_dto: dict, agent_direction: str | None,
                              nearest_leg_lvn: float, bar=None) -> object | None:
        """Construct SetupEvidence from AMT state."""
        from quant.decision.setup_state import SetupEvidence
        setup_dir = str(agent_direction or "").upper()
        cvd_val = self._df(amt_dto, "cvdSlope")
        bool(
            (setup_dir == "LONG" and cvd_val >= -0.2)
            or (setup_dir == "SHORT" and cvd_val <= 0.2)
        )
        rejection_at_high = self._db(amt_dto, "rejectionAtHigh")
        rejection_at_low = self._db(amt_dto, "rejectionAtLow")
        is_second_drive = self._db(amt_dto, "isSecondDrive")
        drive_number = self._di(amt_dto, "driveNumber")
        triple_phase = self._ds(amt_dto, "tripleAPhase")
        triple_signal = self._ds(amt_dto, "tripleASignal")

        close_px = float(bar.close) if bar is not None else 0.0
        tick = float(getattr(bar, "tick_size", 0.0) or 0.0) if bar is not None else 0.0
        if tick <= 0:
            tick = 0.05
        vah = self._df(amt_dto, "valueAreaHigh")
        val = self._df(amt_dto, "valueAreaLow")
        session_vwap = self._df(amt_dto, "sessionVwap") or self._df(amt_dto, "vwap")
        price_loc = "IN_VA"
        if close_px > 0 and vah > 0 and val > 0:
            if close_px > vah:
                price_loc = "ABOVE_VAH"
            elif close_px < val:
                price_loc = "BELOW_VAL"

        cb_bars = self._di(amt_dto, "compressionBoxBars")
        cb_vah = self._df(amt_dto, "compressionBoxVah")
        cb_val = self._df(amt_dto, "compressionBoxVal")
        in_compression = bool(cb_bars >= 3 and cb_vah > 0 and cb_val > 0 and cb_val <= close_px <= cb_vah)

        cluster_high = self._df(amt_dto, "absorptionClusterHigh")
        cluster_low = self._df(amt_dto, "absorptionClusterLow")
        departed = self._db(amt_dto, "driveDepartedAndReapproached") or self._db(
            amt_dto, "departedAndReapproached"
        )
        # isSecondDrive / drive_entry_valid is only set by the drive tracker when
        # a genuine Drive-2 re-approach is valid — treat that as the departure flag.
        if is_second_drive or self._db(amt_dto, "driveEntryValid"):
            departed = True

        def _lvn_ok(level: float, max_ticks: float = 5.0) -> bool:
            if level <= 0 or close_px <= 0:
                return False
            return abs(close_px - level) <= (max_ticks * tick + 1e-9)

        def _breakout(direction: str) -> bool:
            if direction == "LONG":
                if cluster_high > 0:
                    return close_px > cluster_high
                if cb_bars >= 3 and cb_vah > 0:
                    return close_px > cb_vah
                return price_loc in ("ABOVE_VAH", "AT_LVN") or not in_compression
            if direction == "SHORT":
                if cluster_low > 0:
                    return close_px < cluster_low
                if cb_bars >= 3 and cb_val > 0:
                    return close_px < cb_val
                return price_loc in ("BELOW_VAL", "AT_LVN") or not in_compression
            return False

        if triple_phase == "AGGRESSION" and (triple_signal in ("LONG", "SHORT") or agent_direction in ("LONG", "SHORT")):
            direction = triple_signal or agent_direction
            accepted = bool(
                amt_dto.get("acceptanceAbove") if direction == "LONG"
                else amt_dto.get("acceptanceBelow")
            )
            if accepted:
                # Only mark cvd_agrees against the setup's own direction.
                setup_cvd = bool(
                    (direction == "LONG" and cvd_val >= -0.2)
                    or (direction == "SHORT" and cvd_val <= 0.2)
                )
                return SetupEvidence(
                    setup_type="TRIPLE_A", direction=direction,
                    absorption=True, accumulation=True, aggression=True,
                    acceptance=True, cvd_agrees=setup_cvd,
                    price_location="IN_COMPRESSION" if in_compression else price_loc,
                    price=close_px, tick_size=tick, session_vwap=session_vwap,
                    level=nearest_leg_lvn,
                    breakout_beyond_cluster=_breakout(direction),
                    lvn_proximity_ok=_lvn_ok(nearest_leg_lvn, max_ticks=5.0),
                )
        if is_second_drive:
            direction = setup_dir or ("SHORT" if rejection_at_high else "LONG")
            setup_cvd = bool(
                (direction == "LONG" and cvd_val >= -0.2)
                or (direction == "SHORT" and cvd_val <= 0.2)
            )
            return SetupEvidence(
                setup_type="SECOND_DRIVE",
                direction=direction,
                drive_number=drive_number or 2, d1_rejected=True,
                rejection=rejection_at_high or rejection_at_low,
                cvd_agrees=setup_cvd,
                price_location=price_loc,
                price=close_px, tick_size=tick, session_vwap=session_vwap,
                departed_and_reapproached=bool(departed),
            )
        if rejection_at_high or rejection_at_low:
            direction = "SHORT" if rejection_at_high else "LONG"
            setup_cvd = bool(
                (direction == "LONG" and cvd_val >= -0.2)
                or (direction == "SHORT" and cvd_val <= 0.2)
            )
            return SetupEvidence(
                setup_type="VA_FADE", direction=direction,
                rejection=rejection_at_high or rejection_at_low,
                acceptance=self._db(amt_dto, "acceptanceAbove") or self._db(amt_dto, "acceptanceBelow"),
                cvd_agrees=setup_cvd,
                price_location=price_loc,
                price=close_px, tick_size=tick, session_vwap=session_vwap,
            )
        if nearest_leg_lvn > 0 and absorption_direction(amt_dto.get("absorptionSide")):
            direction = absorption_direction(amt_dto.get("absorptionSide"))
            setup_cvd = bool(
                (direction == "LONG" and cvd_val >= -0.2)
                or (direction == "SHORT" and cvd_val <= 0.2)
            )
            return SetupEvidence(
                setup_type="LVN_SNIPER", direction=direction,
                level=nearest_leg_lvn, absorption=True, cvd_agrees=setup_cvd,
                price_location=price_loc,
                price=close_px, tick_size=tick, session_vwap=session_vwap,
                lvn_proximity_ok=_lvn_ok(nearest_leg_lvn, max_ticks=3.0),
            )
        return None


    # ------------------------------------------------------------------
    # Position extraction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _infer_side_from_size(raw_sz: float) -> str:
        """Infer position side from signed size when side field is absent."""
        if raw_sz > 0:
            return "LONG"
        if raw_sz < 0:
            return "SHORT"
        return ""

    @staticmethod
    def _first_truthy_dict(d: dict, keys: tuple, default: float = 0.0) -> float:
        """Return the first truthy value from *d* for the given *keys*."""
        for k in keys:
            v = d.get(k, 0.0)
            if v:
                return float(v)
        return float(default)

    @staticmethod
    def _first_truthy_obj(obj, attrs: tuple, default: float = 0.0) -> float:
        """Return the first truthy getattr value from *obj*."""
        for a in attrs:
            v = getattr(obj, a, 0.0)
            if v:
                return float(v)
        return float(default)

    def _extract_position_from_dict(self, position: dict, bar_index: int,
                                    entry_bar_index: int) -> dict:
        """Extract position state from a dict (frontend DTO / portfolio)."""
        raw_sz = float(position.get("size", 0.0))
        pos_side = self._ds(position, "side").upper() or self._infer_side_from_size(raw_sz)
        pos_entry = self._first_truthy_dict(position, ("entryPrice", "entry", "open_price"))
        pos_sl = self._first_truthy_dict(position, ("stopLoss", "sl", "stop_loss"))
        pos_tp = self._first_truthy_dict(position, ("takeProfit", "tp", "take_profit"))
        pos_pnl = self._df(position, "pnl")
        pos_bars_held = self._di(position, "barsHeld")
        if pos_bars_held == 0 and entry_bar_index > 0:
            pos_bars_held = max(0, bar_index - entry_bar_index)
        return {"pos_open": True, "pos_side": pos_side, "pos_entry": pos_entry,
                "pos_size": raw_sz, "pos_sl": pos_sl, "pos_tp": pos_tp,
                "pos_pnl": pos_pnl, "pos_bars_held": pos_bars_held}

    @staticmethod
    def _extract_sl_tp_from_object(position) -> tuple[float, float]:
        """Extract stop-loss and take-profit from a position object."""
        order = getattr(position, "order", None)
        signal = getattr(order, "signal", None) if order is not None else None
        if signal is not None:
            return float(signal.sl or 0.0), float(signal.tp or 0.0)
        pos_sl = DecisionContextBuilder._first_truthy_obj(
            position, ("sl", "stop_loss", "stopLoss"))
        pos_tp = DecisionContextBuilder._first_truthy_obj(
            position, ("tp", "take_profit", "takeProfit"))
        return pos_sl, pos_tp

    @staticmethod
    def _compute_position_pnl(position, close_px: float, pos_entry: float,
                              raw_sz: float, pos_side: str) -> float:
        """Compute unrealized PnL for an object-based position."""
        can_compute = close_px > 0 and pos_entry > 0 and raw_sz != 0
        if not can_compute:
            return float(getattr(position, "pnl", 0.0) or 0.0)
        mult = 1.0 if pos_side == "LONG" else -1.0 if pos_side == "SHORT" else 1.0
        return (close_px - pos_entry) * abs(raw_sz) * mult

    @staticmethod
    def _compute_bars_held(position, bar_index: int, entry_bar_index: int) -> int:
        """Compute bars-held for an object-based position."""
        if entry_bar_index > 0:
            return max(0, bar_index - entry_bar_index)
        return int(getattr(position, "bars_held", 0) or 0)

    def _extract_position_from_object(self, position, close_px: float,
                                      bar_index: int,
                                      entry_bar_index: int) -> dict:
        """Extract position state from a Position / PositionState object."""
        raw_sz = float(getattr(position, "size", 0.0))
        pos_side = (str(getattr(position, "side", "") or "").upper()
                    or self._infer_side_from_size(raw_sz))
        pos_entry = self._first_truthy_obj(
            position, ("entry", "open_price", "entry_price", "entryPrice"))
        pos_sl, pos_tp = self._extract_sl_tp_from_object(position)
        pos_pnl = self._compute_position_pnl(
            position, close_px, pos_entry, raw_sz, pos_side)
        pos_bars_held = self._compute_bars_held(position, bar_index, entry_bar_index)
        return {"pos_open": True, "pos_side": pos_side, "pos_entry": pos_entry,
                "pos_size": raw_sz, "pos_sl": pos_sl, "pos_tp": pos_tp,
                "pos_pnl": pos_pnl, "pos_bars_held": pos_bars_held}

    def _extract_position(self, position, close_px: float, bar_index: int,
                          entry_bar_index: int) -> dict:
        """Extract position state into a flat dict for DecisionContext.
        
        Supports Position (quant/execution/order.py), PositionState (quant/state_machine.py),
        and dict (frontend DTO / portfolio) transparently.
        """
        if position is None:
            return {"pos_open": False, "pos_side": "", "pos_entry": 0.0,
                    "pos_size": 0.0, "pos_sl": 0.0, "pos_tp": 0.0,
                    "pos_pnl": 0.0, "pos_bars_held": 0}
        if isinstance(position, dict):
            return self._extract_position_from_dict(position, bar_index, entry_bar_index)
        return self._extract_position_from_object(position, close_px, bar_index, entry_bar_index)

    # ------------------------------------------------------------------
    # Build helpers — session, squeeze, market state, data quality
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_best_bid_ask(order_book) -> tuple[float, float]:
        """Extract best bid/ask from an order book (or 0.0 if absent)."""
        if order_book is None:
            return 0.0, 0.0
        bids = getattr(order_book, "bids", ()) or ()
        asks = getattr(order_book, "asks", ()) or ()
        best_bid = float(bids[0].price) if bids else 0.0
        best_ask = float(asks[0].price) if asks else 0.0
        return best_bid, best_ask

    @staticmethod
    def _parse_effective_time(bar) -> tuple[str, bool, bool]:
        """Determine the effective time string and its format flags.

        The bar owns the time: the AMT DTO has no ``time`` key (the event that
        carries it passes the bar's), so there is nothing to fall back to.
        """
        effective_time = str((bar.time if bar else None) or "").strip()
        is_epoch = (
            effective_time.replace(".", "", 1).lstrip("-").isdigit()
            and len(effective_time) >= 9
            and "T" not in effective_time
        )
        is_iso = "T" in effective_time or "+" in effective_time or ":" in effective_time
        return effective_time, is_epoch, is_iso

    @staticmethod
    def _fetch_session_info(effective_time: str, is_epoch: bool, is_iso: bool,
                            market: str):
        """Resolve session info, returning None on failure or empty time."""
        if is_epoch or is_iso:
            try:
                return get_session_info(effective_time, market=market)
            except Exception:
                logger.warning(
                    "session-info resolution failed for %r (market=%s); falling back to PRIMARY phase",
                    effective_time, market, exc_info=True,
                )
                return None
        if not effective_time:
            try:
                return get_session_info(market=market)
            except Exception:
                logger.warning(
                    "session-info resolution failed (market=%s); falling back to PRIMARY phase",
                    market, exc_info=True,
                )
                return None
        return None

    @staticmethod
    def _resolve_expiry(effective_time: str, is_epoch: bool, is_iso: bool,
                        contract_expiry):
        """Compute bar_dt and is_expiry from the effective time."""
        bar_dt = ist_dt(effective_time) if (effective_time and (is_epoch or is_iso)) else None
        is_expiry = (bar_dt.date() == contract_expiry) if (contract_expiry and bar_dt) else False
        return is_expiry

    @staticmethod
    def _resolve_squeeze(amt_dto: dict, bar, tick_size: float) -> tuple[bool, str, float, bool]:
        """Resolve squeeze detection fields from AMT state."""
        squeeze_dir = str(amt_dto.get("squeezeDirection", ""))
        trapped_lvl = float(amt_dto.get("squeezeTrappedLevel", 0.0))
        squeeze_detected = bool(squeeze_dir and trapped_lvl > 0)
        pullback = False
        if squeeze_detected and bar is not None:
            tick = tick_size or 0.05
            pullback = abs(float(bar.close) - trapped_lvl) <= 3.0 * tick  # ponytail: retest proxy
        return squeeze_detected, squeeze_dir, trapped_lvl, pullback

    @staticmethod
    def _resolve_market_state_enum(amt_dto: dict) -> MarketState:
        """Map the raw AMT marketState string to a MarketState enum."""
        raw_ms = str(amt_dto.get("marketState") or "BALANCED").upper()
        if raw_ms == "DEAD":
            return MarketState.DEAD
        if raw_ms == "IMBALANCED":
            return MarketState.IMBALANCED
        return MarketState.BALANCED

    @staticmethod
    def _resolve_data_quality(amt_dto: dict):
        """Normalize data quality from AMT DTO, or None when the key is absent."""
        if "dataQuality" not in amt_dto:
            return None
        return normalize_data_quality(amt_dto.get("dataQuality"))

    @staticmethod
    def _resolve_evidence_provenance(amt_dto: dict):
        return normalize_evidence_provenance(amt_dto.get("evidenceProvenance"))

    @staticmethod
    def _resolve_session_open(effective_time: str, market: str,
                              contract_expiry, session_info) -> bool:
        """Determine whether the session allows entry."""
        if effective_time:
            return session_allow_entry(
                effective_time, market=market, contract_expiry=contract_expiry
            )
        if session_info:
            return session_info.allow_entry
        return True

    @staticmethod
    def _apply_setup_direction(agent_direction, setup_evidence) -> str | None:
        """Override agent_direction when a complete setup evidence exists."""
        if setup_evidence is None:
            return agent_direction
        ev_dir = getattr(setup_evidence, "direction", None)
        is_complete = getattr(setup_evidence, "is_complete", lambda: False)()
        if ev_dir and is_complete:
            return ev_dir
        return agent_direction

    @staticmethod
    def _apply_option_short_suppression(symbol: str, agent_direction) -> str | None:
        """Suppress SHORT direction for option contracts (retail scalpers are buyers)."""
        if is_option_contract(symbol) and agent_direction == "SHORT":
            return None
        return agent_direction

    # ------------------------------------------------------------------
    # Context construction
    # ------------------------------------------------------------------

    def _build_context_kwargs(
        self, *, bar, symbol, market, bar_index, effective_time, contract_expiry,
        warm_bars, warmup_bars, cooldown_remaining_sec, risk_state,
        agent_direction, setup_evidence, pos, amt_dto, best_bid, best_ask,
        session_phase, is_expiry, allow_trend, allow_reversion,
        amt_market_state, obi, vah, val, nearest_leg_lvn, tick_size,
        squeeze_detected, squeeze_dir, trapped_lvl, pullback,
        break_dir, break_type, si_dir, si_mag, si_low, si_high,
        buy_wall_below, sell_wall_above, recent_decisions, session_info,
        vwap_std_override=None,
        contract_symbol: str | None = None,
    ) -> dict:
        """Build the keyword-argument dict for the DecisionContext constructor."""
        df, ds, db, di = self._df, self._ds, self._db, self._di
        session_open = self._resolve_session_open(
            effective_time, market, contract_expiry, session_info)
        vwap_std = (
            float(vwap_std_override)
            if vwap_std_override is not None
            else df(amt_dto, "vwapDeviationSigmas")
        )
        return dict(
            state=None,
            bar=bar,
            symbol=symbol,
            market=market,
            bar_index=bar_index,
            session_open=session_open,
            warmup_complete=(bar_index + warm_bars) >= warmup_bars,
            position_open=pos["pos_open"],
            position_side=pos["pos_side"],
            position_entry_price=pos["pos_entry"],
            position_size=pos["pos_size"],
            position_unrealized_pnl=pos["pos_pnl"],
            position_sl=pos["pos_sl"],
            position_tp=pos["pos_tp"],
            position_bars_held=pos["pos_bars_held"],
            cooldown_remaining_sec=cooldown_remaining_sec,
            risk_halted=risk_state.halted,
            consecutive_losses=risk_state.consecutive_losses,
            consecutive_wins=getattr(risk_state, "consecutive_wins", 0),
            setup_grade="A+" if getattr(risk_state, "consecutive_wins", 0) >= 2 else ("A" if getattr(risk_state, "consecutive_wins", 0) == 1 else ""),
            agent_direction=agent_direction,
            # Metadata only: the deterministic engine has no model conviction.
            # Provenance gating lives in DecisionLoop (data_quality below).
            agent_probability=_DETERMINISTIC_CONVICTION,
            data_quality=self._resolve_data_quality(amt_dto),
            evidence_provenance=self._resolve_evidence_provenance(amt_dto),
            setup_evidence=setup_evidence,
            market_state=amt_market_state,
            balance_ratio=df(amt_dto, "balanceRatio"),
            drive_entry_valid=db(amt_dto, "isSecondDrive"),
            drive_number=di(amt_dto, "driveNumber"),
            break_direction=break_dir,
            break_type=break_type,
            obi=obi,
            poc=df(amt_dto, "poc"),
            vah=df(amt_dto, "valueAreaHigh"),
            val=df(amt_dto, "valueAreaLow"),
            prior_poc=df(amt_dto, "priorPoc"),
            prior_vah=df(amt_dto, "priorVah"),
            prior_val=df(amt_dto, "priorVal"),
            gap_type=ds(amt_dto, "gapType"),
            opening_bias=ds(amt_dto, "openingBias"),
            npoc_above=df(amt_dto, "npocAbove"),
            npoc_below=df(amt_dto, "npocBelow"),
            tick_size=tick_size,
            session_vwap=df(amt_dto, "sessionVwap") or (float(bar.vwap) if bar and getattr(bar, "vwap", None) else 0.0),
            vwap_std=vwap_std,
            vwap_upper_2=df(amt_dto, "vwapUpper2"),
            vwap_lower_2=df(amt_dto, "vwapLower2"),
            cvd_slope=df(amt_dto, "cvdSlope"),
            # Gate 3 alignment veto (C1): AMTResult.cvd_divergence is produced by
            # quant.amt.orderflow.cvd and emitted as "cvdDivergence" by dto.py.
            # An empty string means "no divergence", which passes the veto by
            # design; mapping it here is what keeps that meaning honest.
            cvd_divergence=ds(amt_dto, "cvdDivergence"),
            absorption_side=ds(amt_dto, "absorptionSide"),
            aggression_components=amt_dto.get("aggressionComponents"),
            cvd_state=amt_dto.get("cvdState"),
            ofi_result=amt_dto.get("ofiResult"),
            norm_delta=df(amt_dto, "normDelta"),
            equity=risk_state.equity,
            risk_per_trade_pct=risk_state.risk_per_trade_pct,
            leg_lvn=nearest_leg_lvn,
            # The DTO carries no quote: bid/ask are the order book's best levels.
            bid=best_bid,
            ask=best_ask,
            time_str=effective_time,
            session_phase=session_phase,
            allow_trend=allow_trend,
            allow_reversion=allow_reversion,
            is_expiry=is_expiry,
            profile_shape=ds(amt_dto, "profileShape"),
            # Greek delta only — never invent 0.50. Missing → None → DATA_DEGRADED
            # at option translation / sizing. Key off the execution contract when
            # the decision context is built on the underlying eval symbol.
            option_delta=self._option_delta(
                symbol, contract_symbol=contract_symbol, amt_dto=amt_dto,
            ),
            contested_bubble_zone=db(amt_dto, "contestedZone"),
            stacked_imbalance_direction=si_dir,
            stacked_imbalance_magnitude=si_mag,
            stacked_imbalance_price_low=si_low,
            stacked_imbalance_price_high=si_high,
            nearest_buy_print_below=buy_wall_below,
            nearest_sell_print_above=sell_wall_above,
            triple_a_phase=ds(amt_dto, "tripleAPhase"),
            triple_a_signal=ds(amt_dto, "tripleASignal"),
            absorption_cluster_high=df(amt_dto, "absorptionClusterHigh"),
            absorption_cluster_low=df(amt_dto, "absorptionClusterLow"),
            squeeze_detected=squeeze_detected,
            squeeze_direction=squeeze_dir,
            squeeze_trapped_level=trapped_lvl,
            pullback_confirmed=pullback,
            compression_box_poc=df(amt_dto, "compressionBoxPoc"),
            compression_box_vah=df(amt_dto, "compressionBoxVah"),
            compression_box_val=df(amt_dto, "compressionBoxVal"),
            compression_box_bars=di(amt_dto, "compressionBoxBars"),
            gap_profile_poc=df(amt_dto, "gapProfilePoc"),
            gap_profile_vah=df(amt_dto, "gapProfileVah"),
            gap_profile_val=df(amt_dto, "gapProfileVal"),
            # VA_Fade stop placement (C2): the analyzer tracks the full session
            # probe extremes; mapping them lets va_fade put the stop beyond the
            # true probe instead of falling back to the last bar's wick.
            session_extreme_low=df(amt_dto, "sessionExtremeLow"),
            session_extreme_high=df(amt_dto, "sessionExtremeHigh"),
            vars_result=amt_dto.get("vars"),
            recent_decisions=tuple(recent_decisions or ()),
        )

    def build(
        self,
        bar,
        symbol: str,
        market: str,
        contract_expiry,
        tick_size: float,
        bar_index: int,
        warm_bars: int,
        cooldown_remaining_sec: float,
        risk_state,
        amt_dto: dict | None = None,
        snapshot: AnalysisSnapshot | None = None,
        order_book=None,
        interval_seconds: int = DEFAULT_INTERVAL_SEC,
        position=None,
        entry_bar_index: int = 0,
        recent_decisions: list | None = None,
        contract_symbol: str | None = None,
    ) -> DecisionContext:
        """Build a DecisionContext from the given inputs.
        
        Args:
            bar: The closed Bar
            symbol: Instrument symbol
            market: Exchange market (NSE/MCX)
            contract_expiry: Option contract expiry date
            tick_size: Minimum price increment
            bar_index: Current bar count
            warm_bars: Number of seeded history bars
            cooldown_remaining_sec: Cooldown time remaining in seconds
            risk_state: Current RiskState
            amt_dto: AMT analysis DTO (fallback when snapshot is absent)
            snapshot: Typed analysis snapshot (preferred over amt_dto)
            interval_seconds: Bar interval in seconds
            
        Returns:
            A fully-populated DecisionContext
        """
        warmup_bars = 15
        vwap_std_override = None
        if snapshot is not None:
            from quant.amt.dto import amt_result_to_dto

            r = snapshot.result
            effective_dto = amt_result_to_dto(r)
            vwap_std_override = self._vwap_std_from_result(r)
            _si_dir = snapshot.stacked_imbalance_direction
            _si_mag = snapshot.stacked_imbalance_magnitude
            _si_low = snapshot.stacked_imbalance_low
            _si_high = snapshot.stacked_imbalance_high
            _buy_wall_below, _sell_wall_above = _print_levels_from_result(
                r.aggressive_prints, bar
            )
        else:
            effective_dto = amt_dto or {}
            _si_dir, _si_mag, _si_low, _si_high = _latest_stacked_imbalance(effective_dto)
            _buy_wall_below, _sell_wall_above = _print_levels_from_dto(effective_dto, bar)

        df = self._df
        obi = df(effective_dto, "obi")
        close_px = float(bar.close if bar else 0.0)
        vah = df(effective_dto, "valueAreaHigh")
        val = df(effective_dto, "valueAreaLow")
        ofi = df(effective_dto, "ofi")
        vwap_upper_1 = df(effective_dto, "vwapUpper1") or float("inf")
        vwap_lower_1 = df(effective_dto, "vwapLower1") or float("-inf")
        best_bid, best_ask = self._extract_best_bid_ask(order_book)

        # Session & Expiry
        effective_time, is_epoch, is_iso = self._parse_effective_time(bar)
        session_info = self._fetch_session_info(effective_time, is_epoch, is_iso, market)
        session_phase = session_info.session if session_info else "PRIMARY"
        is_expiry = self._resolve_expiry(effective_time, is_epoch, is_iso, contract_expiry)

        # Direction, Setup, Position via extracted helpers
        agent_direction = self._resolve_direction(
            effective_dto, close_px, vah, val, obi, ofi, vwap_upper_1, vwap_lower_1, market=market
        )
        nearest_leg_lvn = self._nearest_leg_lvn(effective_dto, close_px)
        setup_evidence = self._build_setup_evidence(
            effective_dto, agent_direction, nearest_leg_lvn, bar=bar
        )
        # ponytail: a confirmed structural setup evidence establishes the trade direction
        agent_direction = self._apply_setup_direction(agent_direction, setup_evidence)
        agent_direction = self._apply_option_short_suppression(symbol, agent_direction)
        pos = self._extract_position(position, close_px, bar_index, entry_bar_index)

        # Squeeze, market state, session
        squeeze_detected, squeeze_dir, trapped_lvl, pullback = self._resolve_squeeze(
            effective_dto, bar, tick_size
        )
        amt_market_state = self._resolve_market_state_enum(effective_dto)
        allow_trend = session_info.allow_trend if session_info else True
        allow_reversion = session_info.allow_reversion if session_info else True
        break_dir = self._ds(effective_dto, "breakDirection").upper()
        break_type = self._ds(effective_dto, "breakType").upper()

        ctx_kwargs = self._build_context_kwargs(
            bar=bar, symbol=symbol, market=market, bar_index=bar_index,
            effective_time=effective_time, contract_expiry=contract_expiry,
            warm_bars=warm_bars, warmup_bars=warmup_bars,
            cooldown_remaining_sec=cooldown_remaining_sec, risk_state=risk_state,
            agent_direction=agent_direction, setup_evidence=setup_evidence,
            pos=pos, amt_dto=effective_dto, best_bid=best_bid, best_ask=best_ask,
            session_phase=session_phase, is_expiry=is_expiry,
            allow_trend=allow_trend, allow_reversion=allow_reversion,
            amt_market_state=amt_market_state, obi=obi, vah=vah, val=val,
            nearest_leg_lvn=nearest_leg_lvn, tick_size=tick_size,
            squeeze_detected=squeeze_detected, squeeze_dir=squeeze_dir,
            trapped_lvl=trapped_lvl, pullback=pullback,
            break_dir=break_dir, break_type=break_type,
            si_dir=_si_dir, si_mag=_si_mag, si_low=_si_low, si_high=_si_high,
            buy_wall_below=_buy_wall_below, sell_wall_above=_sell_wall_above,
            recent_decisions=recent_decisions, session_info=session_info,
            vwap_std_override=vwap_std_override,
            contract_symbol=contract_symbol,
        )
        return DecisionContext(**ctx_kwargs)
