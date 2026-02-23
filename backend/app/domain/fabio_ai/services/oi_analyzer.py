"""OI Analyzer — NSE Open Interest wall detection and Put-Call Ratio analysis.

Implements Fabio AMT methodology for identifying OI-based support/resistance
walls, max-pain calculation, and OI-change interpretation. This is the
NSE-specific equivalent of Fabio's "protection levels" and "big trades."
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Value Objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StrikeOI:
    """OI data for a single strike — input from option chain."""

    strike: int
    ce_oi: int
    pe_oi: int
    ce_oi_change: int = 0
    pe_oi_change: int = 0


@dataclass(frozen=True)
class OIWall:
    """A significant OI concentration acting as support or resistance."""

    strike: int
    wall_type: str       # "CALL_WALL" (resistance) or "PUT_WALL" (support)
    oi: int
    oi_change: int       # change in last interval
    strength: float      # oi / avg_oi (> 3 = strong wall)


@dataclass(frozen=True)
class OIAnalysis:
    """Complete OI analysis for the current expiry."""

    pcr: float               # Put OI / Call OI for current expiry
    pcr_trend: str           # "RISING" | "FALLING" | "STABLE"
    walls: tuple[OIWall, ...]
    max_pain: int            # strike where total OI loss is minimum
    sentiment: str           # "BULLISH" | "BEARISH" | "NEUTRAL"
    nearest_call_wall: OIWall | None  # nearest resistance above spot
    nearest_put_wall: OIWall | None   # nearest support below spot


# ---------------------------------------------------------------------------
# OI Analyzer
# ---------------------------------------------------------------------------

# Threshold multiplier: a strike's OI must exceed avg OI by this factor
# to qualify as a wall.
_WALL_THRESHOLD = 3.0

# PCR change beyond this value is considered a directional shift.
_PCR_CHANGE_THRESHOLD = 0.05

# PCR sentiment boundaries (Fabio methodology).
_PCR_BULLISH = 1.2
_PCR_BEARISH = 0.8


class OIAnalyzer:
    """Pure-domain service for NSE option-chain OI analysis.

    Stateless — call :meth:`analyze` with the current option chain snapshot.
    """

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def analyze(
        self,
        chain: list[StrikeOI],
        spot_price: float,
        prev_pcr: float = 0.0,
    ) -> OIAnalysis:
        """Run full OI analysis on an option-chain snapshot.

        Parameters
        ----------
        chain:
            List of :class:`StrikeOI` for all strikes in the current expiry.
        spot_price:
            Current underlying spot price.
        prev_pcr:
            Previous PCR value used to determine trend direction.

        Returns
        -------
        OIAnalysis
            Aggregated OI metrics, detected walls, max-pain, and sentiment.
        """
        if not chain:
            return OIAnalysis(
                pcr=0.0,
                pcr_trend="STABLE",
                walls=(),
                max_pain=0,
                sentiment="NEUTRAL",
                nearest_call_wall=None,
                nearest_put_wall=None,
            )

        # --- PCR ----------------------------------------------------------
        total_pe = sum(s.pe_oi for s in chain)
        total_ce = sum(s.ce_oi for s in chain)
        pcr = total_pe / total_ce if total_ce > 0 else 0.0

        pcr_diff = pcr - prev_pcr
        if pcr_diff > _PCR_CHANGE_THRESHOLD:
            pcr_trend = "RISING"
        elif pcr_diff < -_PCR_CHANGE_THRESHOLD:
            pcr_trend = "FALLING"
        else:
            pcr_trend = "STABLE"

        # --- Walls --------------------------------------------------------
        avg_ce = total_ce / len(chain)
        avg_pe = total_pe / len(chain)

        walls: list[OIWall] = []
        for s in chain:
            if avg_ce > 0 and s.ce_oi > _WALL_THRESHOLD * avg_ce:
                walls.append(OIWall(
                    strike=s.strike,
                    wall_type="CALL_WALL",
                    oi=s.ce_oi,
                    oi_change=s.ce_oi_change,
                    strength=s.ce_oi / avg_ce,
                ))
            if avg_pe > 0 and s.pe_oi > _WALL_THRESHOLD * avg_pe:
                walls.append(OIWall(
                    strike=s.strike,
                    wall_type="PUT_WALL",
                    oi=s.pe_oi,
                    oi_change=s.pe_oi_change,
                    strength=s.pe_oi / avg_pe,
                ))

        # --- Max Pain -----------------------------------------------------
        max_pain = self._compute_max_pain(chain)

        # --- Sentiment ----------------------------------------------------
        if pcr > _PCR_BULLISH:
            sentiment = "BULLISH"
        elif pcr < _PCR_BEARISH:
            sentiment = "BEARISH"
        else:
            sentiment = "NEUTRAL"

        # --- Nearest walls ------------------------------------------------
        nearest_call_wall = self._nearest_wall_above(walls, spot_price)
        nearest_put_wall = self._nearest_wall_below(walls, spot_price)

        return OIAnalysis(
            pcr=pcr,
            pcr_trend=pcr_trend,
            walls=tuple(walls),
            max_pain=max_pain,
            sentiment=sentiment,
            nearest_call_wall=nearest_call_wall,
            nearest_put_wall=nearest_put_wall,
        )

    @staticmethod
    def check_wall_alignment(
        wall: OIWall,
        vp_level: float,
        buffer_pct: float = 0.005,
    ) -> bool:
        """Check if an OI wall aligns with a Volume Profile level.

        A VP-based VAH that aligns with a CE wall strike indicates
        VERY STRONG resistance; similarly VAL + PE wall = strong support.

        Parameters
        ----------
        wall:
            The OI wall to check.
        vp_level:
            A VP reference price (VAH, VAL, or LVN).
        buffer_pct:
            Percentage tolerance for alignment (default 0.5%).

        Returns
        -------
        bool
            ``True`` when the wall strike is within *buffer_pct* of *vp_level*.
        """
        if vp_level <= 0:
            return False
        distance = abs(wall.strike - vp_level) / vp_level
        return distance <= buffer_pct

    @staticmethod
    def interpret_oi_change(price_change: float, oi_change: int) -> str:
        """Interpret combined price and OI movement.

        Returns one of:
        - ``"NEW_LONGS"``       — price UP + OI UP (bullish)
        - ``"NEW_SHORTS"``      — price DOWN + OI UP (bearish)
        - ``"SHORT_COVERING"``  — price UP + OI DOWN (less sustainable)
        - ``"LONG_UNWINDING"``  — price DOWN + OI DOWN (potential bottom)
        """
        price_up = price_change >= 0
        oi_up = oi_change >= 0

        if price_up and oi_up:
            return "NEW_LONGS"
        if not price_up and oi_up:
            return "NEW_SHORTS"
        if price_up and not oi_up:
            return "SHORT_COVERING"
        return "LONG_UNWINDING"

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _compute_max_pain(chain: list[StrikeOI]) -> int:
        """Find the strike where total intrinsic-value loss is minimised.

        For each candidate strike *K*, the total loss is:
          sum over all strikes S of:
            CE intrinsic = max(K - S, 0) × ce_oi   (calls expire worthless below K)
            PE intrinsic = max(S - K, 0) × pe_oi   (puts expire worthless above K)
        The strike with the smallest total is max pain.
        """
        strikes = [s.strike for s in chain]
        if not strikes:
            return 0

        best_strike = strikes[0]
        best_loss = float("inf")

        for k in strikes:
            total_loss = 0
            for s in chain:
                # Call writers lose when spot > strike
                if k > s.strike:
                    total_loss += (k - s.strike) * s.ce_oi
                # Put writers lose when spot < strike
                if k < s.strike:
                    total_loss += (s.strike - k) * s.pe_oi
            if total_loss < best_loss:
                best_loss = total_loss
                best_strike = k

        return best_strike

    @staticmethod
    def _nearest_wall_above(
        walls: list[OIWall],
        spot: float,
    ) -> OIWall | None:
        """Return the closest CALL_WALL above *spot*, or ``None``."""
        call_walls = [w for w in walls if w.wall_type == "CALL_WALL" and w.strike > spot]
        if not call_walls:
            return None
        return min(call_walls, key=lambda w: w.strike - spot)

    @staticmethod
    def _nearest_wall_below(
        walls: list[OIWall],
        spot: float,
    ) -> OIWall | None:
        """Return the closest PUT_WALL below *spot*, or ``None``."""
        put_walls = [w for w in walls if w.wall_type == "PUT_WALL" and w.strike < spot]
        if not put_walls:
            return None
        return min(put_walls, key=lambda w: spot - w.strike)
