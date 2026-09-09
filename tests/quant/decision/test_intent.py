from dataclasses import dataclass
from datetime import datetime

import pytest

from quant.decision.intent import TradeIntent


def test_trade_intent_rejects_invalid_direction_and_preserves_no_quantity():
    with pytest.raises(ValueError, match="direction"):
        TradeIntent(symbol="NIFTY", direction="HOLD", setup="MODEL", entry=100, stop=95, target=110)


def test_trade_intent_is_immutable_and_quantity_free():
    intent = TradeIntent(symbol="NIFTY", direction="LONG", setup="MODEL", entry=100, stop=95, target=110)
    assert intent.to_dict()["symbol"] == "NIFTY"
    assert "quantity" not in intent.to_dict()
    with pytest.raises(Exception):
        intent.entry = 101
