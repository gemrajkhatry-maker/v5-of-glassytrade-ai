from types import SimpleNamespace

from quant.multi_engine import QuantCoordinator


def test_position_management_does_not_hold_through_choppy_market():
    open_position = {
        "entryPrice": 100.0,
        "currentPrice": 99.0,
        "stopLoss": 98.0,
        "takeProfit": 104.0,
        "side": "LONG",
        "size": 10,
        "barsHeld": 8,
    }
    live = SimpleNamespace(ltp=99.0)
    view = SimpleNamespace(amt={"marketState": "CHOP"})

    decision = QuantCoordinator._build_position_mgmt_decision(
        open_position, live, None, "CRUDEOIL SEP FUT", view
    )

    assert decision["action"] != "HOLD"
    assert decision["reason"] in {"CHOP_EXIT", "CHOP_TIGHTEN"}


def test_position_management_preserves_hold_in_healthy_auction():
    open_position = {
        "entryPrice": 100.0,
        "currentPrice": 101.5,
        "stopLoss": 99.0,
        "takeProfit": 104.0,
        "side": "LONG",
        "size": 10,
        "barsHeld": 3,
    }
    live = SimpleNamespace(ltp=101.5)
    view = SimpleNamespace(amt={"marketState": "IMBALANCED"})

    decision = QuantCoordinator._build_position_mgmt_decision(
        open_position, live, None, "CRUDEOIL SEP FUT", view
    )

    assert decision["action"] == "HOLD"
    assert decision["reason"] == "TREND_INTACT"
