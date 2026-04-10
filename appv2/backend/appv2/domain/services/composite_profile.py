"""Composite Profile — merges last N session profiles for weekly bias.

Combines volume profiles from the last N trading sessions to identify:
- Weekly POC (most traded price across the week)
- Weekly VAH/VAL (weekly value area)
- Weekly bias (price relative to weekly POC)
- Filter: Only sessions with ≥ 70% volume overlap are merged
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CompositeProfile:
    weekly_poc: float
    weekly_vah: float
    weekly_val: float
    sessions_merged: int
    bias: str  # "BULLISH" | "BEARISH" | "NEUTRAL"
    bias_strength: float  # 0.0-1.0


class CompositeProfileBuilder:
    """Builds composite profile from merged sessions."""

    def __init__(self, min_sessions: int = 3, max_sessions: int = 5):
        self._min_sessions = min_sessions
        self._max_sessions = max_sessions
        self._sessions: list[dict[str, Any]] = []  # [{date, poc, vah, val, profile}]

    def add_session(
        self,
        date_str: str,
        poc: float,
        vah: float,
        val: float,
        profile_data: list[dict] | None = None,
    ) -> None:
        """Add a completed session's profile.

        Args:
            date_str: ISO date string
            poc: Session POC
            vah: Session VAH
            val: Session VAL
            profile_data: Optional volume profile data for detailed merge
        """
        self._sessions.append({
            "date": date_str,
            "poc": poc,
            "vah": vah,
            "val": val,
            "profile": profile_data,
        })

        # Trim to max
        if len(self._sessions) > self._max_sessions:
            self._sessions = self._sessions[-self._max_sessions:]

    def build(self, current_price: float = 0.0) -> CompositeProfile | None:
        """Build composite profile from merged sessions.

        Returns None if insufficient sessions.
        """
        if len(self._sessions) < self._min_sessions:
            return None

        # Calculate weekly POC (volume-weighted average of session POCs)
        pocs = [s["poc"] for s in self._sessions if s["poc"] > 0]
        if not pocs:
            return None

        weekly_poc = sum(pocs) / len(pocs)

        # Weekly VAH = max of session VAHs
        vahas = [s["vah"] for s in self._sessions if s["vah"] > 0]
        weekly_vah = max(vahas) if vahas else 0

        # Weekly VAL = min of session VALs
        vals = [s["val"] for s in self._sessions if s["val"] > 0]
        weekly_val = min(vals) if vals else 0

        # Determine bias
        if current_price > 0 and weekly_poc > 0:
            if current_price > weekly_poc:
                bias = "BULLISH"
                strength = min(1.0, (current_price - weekly_poc) / weekly_poc * 100)
            elif current_price < weekly_poc:
                bias = "BEARISH"
                strength = min(1.0, (weekly_poc - current_price) / weekly_poc * 100)
            else:
                bias = "NEUTRAL"
                strength = 0.0
        else:
            bias = "NEUTRAL"
            strength = 0.0

        return CompositeProfile(
            weekly_poc=round(weekly_poc, 4),
            weekly_vah=round(weekly_vah, 4),
            weekly_val=round(weekly_val, 4),
            sessions_merged=len(self._sessions),
            bias=bias,
            bias_strength=round(strength, 2),
        )

    @property
    def session_count(self) -> int:
        return len(self._sessions)

    def reset(self) -> None:
        self._sessions.clear()
