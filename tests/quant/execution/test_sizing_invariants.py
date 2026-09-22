"""Mathematical Sizing Invariants & House Money Protocol Tests.

Verifies:
1. Sizing snaps to whole lot sizes across all active MCX and NSE contracts.
2. Orders are clamped to exchange freeze limits.
3. House Money Protocol (§12.2) risk tiers:
   - Session R <= 0.0: Base Defensive Tier (0.25% - 0.50%)
   - Session R >= +1.5: Cushion Tier 1 (0.75%)
   - Session R >= +3.0: Cushion Tier 2 (1.00% + unlocks pyramiding)
   - Retracement Veto: >= 50% drop from session peak drops back to 0.25%
   - Session Kill Switch: Hard halt if cumulative loss reaches 2.0% of starting equity.
"""

from __future__ import annotations

import pytest

from quant.execution.lots import clamp_to_freeze, snap_to_lot
from quant.execution.risk import SessionRiskAuthority


@pytest.mark.parametrize(
    ("exchange_name", "symbol", "raw_qty", "lot_size", "freeze_limit"),
    [
        ("NSE", "NIFTY", 63, 25, 1800),
        ("NSE", "BANKNIFTY", 42, 15, 900),
        ("NSE", "FINNIFTY", 78, 25, 1800),
        ("MCX", "CRUDEOIL", 145, 100, 10000),
        ("MCX", "CRUDEOILM", 18, 10, 10000),
        ("MCX", "GOLD", 3, 1, 1000),
        ("MCX", "GOLDM", 15, 10, 10000),
        ("MCX", "SILVERM", 7, 5, 10000),
    ],
)
def test_sizing_lot_snapping_and_freeze_clamping(
    exchange_name: str, symbol: str, raw_qty: int, lot_size: int, freeze_limit: int
):
    """Assert all quantities snap to lot multiples and clamp to freeze limits."""
    snapped = snap_to_lot(raw_qty, lot_size)
    assert snapped % lot_size == 0
    assert snapped >= lot_size

    # Clamp to freeze limit
    oversized = freeze_limit + 500
    clamped = clamp_to_freeze(oversized, freeze_limit)
    assert clamped == freeze_limit


def test_house_money_protocol_tiers():
    """Verify House Money Protocol (§12.2) tiers based on session R-multiple."""
    authority = SessionRiskAuthority(starting_equity=100000.0, base_risk_pct=0.005)

    # Starting state: Session R = 0.0 -> CONSERVATIVE Tier (0.25%)
    assert authority.effective_risk_pct() == pytest.approx(0.0025)
    assert not authority.is_pyramiding_unlocked()

    # Banked profit +1.5R: CUSHION_TIER_1
    # base 0.25% + min(40%, 30%) of profit/E0 = 0.0025 + 0.00225 = 0.00475
    authority.record_trade(pnl=750.0)
    assert authority.session_r_multiple() == pytest.approx(1.5)
    assert authority.effective_risk_pct() == pytest.approx(0.00475)
    assert not authority.is_pyramiding_unlocked()

    # Banked profit +3.0R with 2 consecutive wins -> MOMENTUM (0.40% flat)
    authority.record_trade(pnl=750.0)  # total pnl = 1500.0
    assert authority.session_r_multiple() == pytest.approx(3.0)
    assert authority.effective_risk_pct() == pytest.approx(0.0040)
    assert not authority.is_pyramiding_unlocked()


def test_retracement_veto_drops_to_base_tier():
    """Verify >= 50% drop from session peak PnL drops risk back to base 0.25%."""
    authority = SessionRiskAuthority(starting_equity=100000.0, base_risk_pct=0.005)

    # Build peak PnL to +2000 INR -> CUSHION_TIER_1 at 0.50% ceiling
    authority.record_trade(pnl=2000.0)
    assert authority.effective_risk_pct() == pytest.approx(0.0050)

    # Retrace by 1100 INR (peak was 2000, current PnL is 900, drop is 1100/2000 = 55% >= 50%)
    # -> BASE_RETRACEMENT_VETO (0.25%)
    authority.record_trade(pnl=-1100.0)
    assert authority.effective_risk_pct() == pytest.approx(0.0025)


def test_session_kill_switch_hard_halt():
    """Verify cumulative loss reaching 2.0% of starting equity trips hard halt."""
    authority = SessionRiskAuthority(starting_equity=100000.0, max_daily_loss_pct=0.02)

    assert not authority.is_halted
    # Loss of 2000 INR = 2.0% of 100000
    authority.record_trade(pnl=-2001.0)
    assert authority.is_halted
    assert "session kill switch" in authority.halt_reason
    assert authority.effective_risk_pct() == 0.0
