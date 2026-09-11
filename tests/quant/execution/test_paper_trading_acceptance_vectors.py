from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from quant.contracts.contracts import ContractRef
from quant.execution.paper_trading_contracts import (
    PaperSession,
    SquareOffPolicy,
    is_within_session,
    square_off_reason,
)

IST = ZoneInfo("Asia/Kolkata")


@pytest.mark.parametrize(
    "ref, expected",
    [
        (ContractRef("NIFTY", "NSE", "2026-09-24", 75, 0.05), ("NSE", 75, 0.05, "FUTURE")),
        (ContractRef("NIFTY", "NSE", "2026-09-24", 75, 0.05, 25000, "CE"), ("NSE", 75, 0.05, "OPTION")),
        (ContractRef("CRUDEOIL", "MCX", "2026-09-18", 100, 0.05), ("MCX", 100, 0.05, "FUTURE")),
    ],
)
def test_indian_contract_vectors_preserve_exchange_lot_tick_and_type(ref, expected):
    assert (ref.exchange, ref.lot_size, ref.tick_size, ref.instrument_type) == expected


@pytest.mark.parametrize(
    "session, timestamp, expected",
    [
        (PaperSession.NSE, datetime(2026, 9, 11, 9, 15, tzinfo=IST), True),
        (PaperSession.NSE, datetime(2026, 9, 11, 15, 30, tzinfo=IST), True),
        (PaperSession.NSE, datetime(2026, 9, 11, 15, 31, tzinfo=IST), False),
        (PaperSession.MCX, datetime(2026, 9, 11, 9, 0, tzinfo=IST), True),
        (PaperSession.MCX, datetime(2026, 9, 11, 23, 30, tzinfo=IST), True),
        (PaperSession.MCX, datetime(2026, 9, 11, 23, 31, tzinfo=IST), False),
    ],
)
def test_session_boundaries_are_inclusive_at_close(session, timestamp, expected):
    assert is_within_session(timestamp, session) is expected


def test_square_off_policy_closes_at_session_end_and_reports_reason():
    policy = SquareOffPolicy(PaperSession.NSE)
    assert policy.should_square_off(datetime(2026, 9, 11, 15, 30, tzinfo=IST))
    assert square_off_reason(policy, datetime(2026, 9, 11, 15, 30, tzinfo=IST)) == "SESSION_CLOSE"


def test_square_off_policy_does_not_close_inside_session():
    policy = SquareOffPolicy(PaperSession.MCX)
    assert not policy.should_square_off(datetime(2026, 9, 11, 20, 0, tzinfo=IST))
    assert square_off_reason(policy, datetime(2026, 9, 11, 20, 0, tzinfo=IST)) is None
