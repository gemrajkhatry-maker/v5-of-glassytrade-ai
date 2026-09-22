"""Cert E13 (determinism edge): parse_contract_expiry must accept an injected today.

Replay/cert paths pin the clock; without injection year resolution uses
datetime.now() — a determinism edge that breaks golden-tape identity across
runs on different dates.
"""
from __future__ import annotations

from datetime import date

from quant.session_gates import parse_contract_expiry


def test_parse_contract_expiry_accepts_injected_today():
    """Expired MDY without year refuses — never invents +1 year."""
    got = parse_contract_expiry("NIFTY 26 DEC 25000 CE", today=date(2026, 12, 31))
    assert got is None

    # Same calendar year, still ahead of injected today → that year.
    got2 = parse_contract_expiry("CRUDEOIL 17 AUG 7450 CALL", today=date(2026, 8, 1))
    assert got2 == date(2026, 8, 17)

    # Explicit future year is accepted; past explicit year still refuses.
    assert parse_contract_expiry("NIFTY 26 DEC 2025 CE", today=date(2026, 12, 31)) is None
    assert parse_contract_expiry("NIFTY 26 DEC 2027 CE", today=date(2026, 12, 31)) == date(2027, 12, 26)
