"""Cross-engine opportunity auction — capital to the highest-quality setup.

Engines ``submit()`` proposals during a bar-cycle window; ``settle_bar()``
ranks by score and grants portfolio risk until ``can_accept`` fails.
``propose()`` is the single-call compat wrapper (submit → wait hold → settle).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from quant.decision.setup_labels import canonical_setup_type


@dataclass(frozen=True)
class OpportunityProposal:
    symbol: str
    side: str
    score: float
    requested_risk_rupees: float
    signal: object
    quantity: float
    reason: str = ""
    ttl_sec: float = 5.0
    created_at: float = field(default_factory=time.time)

    @property
    def expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl_sec


# Setup-path priority weights (canonical SetupType keys). Higher = better.
_SETUP_WEIGHTS = {
    "SQUEEZE": 100.0,
    "TRIPLE_A": 90.0,
    "SECOND_DRIVE": 85.0,
    "INITIATIVE": 80.0,
    "LVN_SNIPER": 70.0,
    "VA_FADE": 50.0,
}


def score_opportunity(
    *,
    setup_key: str = "",
    rr: float = 0.0,
    absorption_vol_ratio: float = 0.0,
    drive_entry_valid: bool = False,
    spread_quality: float = 1.0,
    lvn_ticks: float | None = None,
    cvd_agrees: bool = False,
) -> float:
    """Deterministic quality score for ranking pending opportunities."""
    key = canonical_setup_type(setup_key) or str(setup_key or "").upper().replace("-", "_")
    base = float(_SETUP_WEIGHTS.get(key, 40.0))
    if drive_entry_valid:
        base += 10.0
    if cvd_agrees:
        base += 5.0
    if lvn_ticks is not None and lvn_ticks >= 0:
        base += max(0.0, 10.0 - float(lvn_ticks))
    base += min(20.0, max(0.0, float(rr)) * 5.0)
    base += min(15.0, max(0.0, float(absorption_vol_ratio)) * 5.0)
    base *= max(0.1, min(1.0, float(spread_quality)))
    return float(base)


class OpportunityAuction:
    """Coordinator-owned pending book. Thread-safe. Bar-cycle settle."""

    def __init__(self, portfolio_risk, hold_sec: float = 0.0) -> None:
        self._portfolio_risk = portfolio_risk
        # >0 opens a ranking window so competing engines can join before settle.
        self._hold_sec = max(0.0, float(hold_sec))
        self._lock = threading.RLock()
        self._pending: dict[str, OpportunityProposal] = {}
        self._last_granted: set[str] = set()

    def submit(self, proposal: OpportunityProposal) -> None:
        """Stage a proposal for the current bar cycle (does not grant)."""
        with self._lock:
            if proposal.expired:
                return
            self._pending[proposal.symbol] = proposal

    def pending_symbols(self) -> set[str]:
        with self._lock:
            self._expire()
            return set(self._pending)

    def settle_bar(self, *, force: bool = False) -> list[OpportunityProposal]:
        """Rank pending proposals and grant until the book refuses.

        When ``hold_sec > 0`` and ``force`` is False, returns ``[]`` while the
        ranking window is still open (oldest pending younger than hold_sec).
        Losers are dropped without a session latch — they may re-propose next bar.
        """
        with self._lock:
            self._expire()
            if not self._pending:
                return []
            if not force and self._hold_sec > 0:
                oldest = min(p.created_at for p in self._pending.values())
                if (time.time() - oldest) < self._hold_sec:
                    return []
            ordered = sorted(
                self._pending.values(),
                key=lambda p: (p.score, -p.created_at),
                reverse=True,
            )
            self._pending.clear()
            granted: list[OpportunityProposal] = []
            for proposal in ordered:
                ok, _why = self._portfolio_risk.can_accept(
                    proposal.requested_risk_rupees, symbol=proposal.symbol,
                )
                if not ok:
                    continue
                if not self._portfolio_risk.register_open(
                    proposal.requested_risk_rupees, symbol=proposal.symbol,
                ):
                    continue
                granted.append(proposal)
            self._last_granted = {g.symbol for g in granted}
            return granted

    def propose(self, proposal: OpportunityProposal) -> tuple[bool, str]:
        """Submit, wait out the ranking window, settle, return grant status.

        Multi-engine coordinators may instead call ``submit()`` then
        ``settle_bar()`` once per bar; this path is safe for both.
        """
        self.submit(proposal)
        return self.await_grant(proposal.symbol)

    def await_grant(self, symbol: str) -> tuple[bool, str]:
        """Poll ``settle_bar`` until this symbol is granted, outranked, or forced."""
        deadline = time.monotonic() + self._hold_sec + 0.05
        while True:
            grants = self.settle_bar()
            if any(g.symbol == symbol for g in grants):
                return True, "granted"
            with self._lock:
                pending = symbol in self._pending
                granted = symbol in self._last_granted
            if granted:
                return True, "granted"
            if not pending:
                return False, "OUTRANKED"
            if time.monotonic() >= deadline:
                grants = self.settle_bar(force=True)
                if any(g.symbol == symbol for g in grants):
                    return True, "granted"
                with self._lock:
                    if symbol in self._last_granted:
                        return True, "granted"
                return False, "OUTRANKED"
            time.sleep(0.005)

    def _expire(self) -> None:
        dead = [s for s, p in self._pending.items() if p.expired]
        for s in dead:
            self._pending.pop(s, None)

    def _pick_winner(self) -> OpportunityProposal | None:
        if not self._pending:
            return None
        return max(self._pending.values(), key=lambda p: (p.score, -p.created_at))
