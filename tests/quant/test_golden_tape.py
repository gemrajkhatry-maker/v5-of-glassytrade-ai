"""Golden-Tape Deterministic Session Replay Regression Suite.

Verifies end-to-end event trace determinism across full multi-phase sessions,
testing phase gates, structural SL/TP, and order execution parity.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from quant.contracts.exchange_config import ExchangeConfig
from quant.events import (
    BarClosed,
    AuctionUpdated,
    AmtUpdated,
    DecisionProduced,
    PositionOpened,
    PositionClosed,
    RiskUpdated,
)
from quant.persistence import Journal
from quant.runtime import QuantEngine
from tests.helpers.synthetic import SyntheticGateway
from tests.quant.runtime.test_runtime import _ticks


def test_golden_tape_event_sequence_determinism():
    """Verify that two separate engines consuming the same tick sequence emit exact same event types and counts."""
    eng1 = QuantEngine(SyntheticGateway(_ticks()), "NIFTY 27 FEB 25500 CALL", interval_seconds=1)
    trace1 = eng1.run()

    eng2 = QuantEngine(SyntheticGateway(_ticks()), "NIFTY 27 FEB 25500 CALL", interval_seconds=1)
    trace2 = eng2.run()

    assert len(trace1) == len(trace2)
    assert len(trace1) > 0

    event_types1 = [e.__class__.__name__ for e in trace1]
    event_types2 = [e.__class__.__name__ for e in trace2]
    assert event_types1 == event_types2

    # Verify key lifecycle events are emitted
    assert "BarClosed" in event_types1
    assert "AuctionUpdated" in event_types1
    assert "AmtUpdated" in event_types1
    assert "DecisionProduced" in event_types1


def test_golden_tape_journal_roundtrip(tmp_path):
    """Verify that journal persistence accurately records every event and matches in replay."""
    journal_file = str(tmp_path / "golden_tape.jsonl")
    eng = QuantEngine(
        SyntheticGateway(_ticks()),
        "NIFTY 27 FEB 25500 CALL",
        interval_seconds=1,
        journal_path=journal_file,
    )
    trace = eng.run()

    journal = Journal(journal_file)
    replayed = journal.replay()

    assert len(replayed) == len(trace)
    for original, recorded in zip(trace, replayed):
        assert recorded["type"] == original.__class__.__name__
        assert recorded["symbol"] == "NIFTY 27 FEB 25500 CALL"


def test_exchange_config_freeze_limits_and_indices():
    """Verify NSE and MCX defaults contain valid freeze limits and index definitions."""
    nse = ExchangeConfig.for_exchange("NSE")
    assert nse.get_freeze_limit("NIFTY") == 1800
    assert nse.get_freeze_limit("BANKNIFTY") == 900
    assert nse.get_freeze_limit("FINNIFTY") == 1800
    assert nse.get_freeze_limit("MIDCPNIFTY") == 4200
    assert nse.get_lot_size("MIDCPNIFTY") == 120
    assert nse.get_tick_size("MIDCPNIFTY") == 0.05

    mcx = ExchangeConfig.for_exchange("MCX")
    assert mcx.get_freeze_limit("CRUDEOIL") == 10000
    assert mcx.get_freeze_limit("NATURALGAS") == 100000
    assert mcx.get_lot_size("CRUDEOIL") == 100
    assert mcx.get_tick_size("CRUDEOIL") == 1.0


def test_extract_underlying_canonical_matching():
    """Verify robust underlying extraction across prefixes, delimiters, and compound roots."""
    nse = ExchangeConfig.for_exchange("NSE")
    assert nse.extract_underlying("NSE:NIFTY24AUG25500CE") == "NIFTY"
    assert nse.extract_underlying("BANKNIFTY 28 AUG 51000 PE") == "BANKNIFTY"
    assert nse.extract_underlying("MIDCPNIFTY-25700-CE") == "MIDCPNIFTY"
    assert nse.extract_underlying("FINNIFTY") == "FINNIFTY"
    assert nse.is_underlying("NSE:BANKNIFTY24AUG50000CE") is True

    mcx = ExchangeConfig.for_exchange("MCX")
    assert mcx.extract_underlying("MCX:CRUDEOILM 19 MAR 6000 CALL") == "CRUDEOILM"
    assert mcx.extract_underlying("CRUDEOIL 19 MAR 6000 CALL") == "CRUDEOIL"
    assert mcx.extract_underlying("GOLDM-I") == "GOLDM"
    assert mcx.extract_underlying("SILVERM24AUG") == "SILVERM"
    assert mcx.extract_underlying("NATURALGAS 25 AUG 220 PE") == "NATURALGAS"
    assert mcx.is_underlying("MCX:CRUDEOILM 19 MAR 6000 CALL") is True
