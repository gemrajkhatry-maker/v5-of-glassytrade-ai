from quant.decision.context import DecisionContext
from quant.decision.gates_auction import gate_failed_auction_sequence


def _ctx(**kw):
    d = dict(state=None, bar=None)
    d.update(kw)
    return DecisionContext(**d)


def test_balance_first_drive_rejected():
    # BALANCED + D1 touch (entry_valid=False) -> gate 3 blocks: a first touch
    # at the level is NOT evidence of a failed auction.
    r = gate_failed_auction_sequence(_ctx(
        market_state="BALANCED", drive_number=1, drive_entry_valid=False))
    assert not r.passed and r.gate == 3
    assert "drive=1" in r.reason


def test_balance_second_drive_accepted():
    # BALANCED + valid second-drive reclaim -> passes.
    r = gate_failed_auction_sequence(_ctx(
        market_state="BALANCED", drive_number=2, drive_entry_valid=True))
    assert r.passed and r.gate == 3


def test_imbalance_bypasses_sequence_gate():
    # Continuation trades in IMBALANCE do not need a failed auction.
    r = gate_failed_auction_sequence(_ctx(
        market_state="IMBALANCED", drive_number=1, drive_entry_valid=False))
    assert r.passed and r.gate == 3


def test_transition_bypasses_sequence_gate():
    # TRANSITION (neither balanced nor imbalanced) is not gated.
    r = gate_failed_auction_sequence(_ctx(
        market_state="TRANSITION", drive_number=0, drive_entry_valid=False))
    assert r.passed and r.gate == 3


def test_dead_market_bypasses_sequence_gate():
    # Dead-market refusal belongs to other gates; this gate stays out of it.
    r = gate_failed_auction_sequence(_ctx(market_state="DEAD"))
    assert r.passed
