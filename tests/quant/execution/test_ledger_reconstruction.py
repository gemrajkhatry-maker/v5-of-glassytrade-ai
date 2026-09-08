from quant.execution.ledger_reconstruction import reconstruct_fill_ledger


def _fill(fid, side="BUY", qty=10, price=100, *, order_id="entry:p", position_id="p"):
    return {
        "fill_id": fid,
        "order_id": order_id,
        "position_id": position_id,
        "symbol": "X",
        "side": side,
        "quantity": qty,
        "fill_price": price,
    }


def test_reconstructs_open_quantity_after_partial_exit():
    result = reconstruct_fill_ledger([
        _fill("e1"),
        _fill("x1", "SELL", 4, 110, order_id="partial:p"),
    ])
    assert result.issues == set()
    assert result.positions["p"].signed_quantity == 6


def test_duplicate_fill_is_idempotent():
    fill = _fill("e1")
    result = reconstruct_fill_ledger([fill, dict(fill)])
    assert result.issues == set()
    assert result.positions["p"].signed_quantity == 10


def test_reconstructs_short_entry_and_buy_exit():
    result = reconstruct_fill_ledger([
        _fill("e1", "SELL"),
        _fill("x1", "BUY", 4, 90, order_id="close:p"),
    ])
    assert result.issues == set()
    assert result.positions["p"].signed_quantity == -6


def test_over_close_is_quarantined():
    result = reconstruct_fill_ledger([
        _fill("e1"),
        _fill("x1", "SELL", 11, 90, order_id="close:p"),
    ])
    assert "p" in result.issues
    assert "p" not in result.positions


def test_legacy_long_short_entry_aliases_are_supported():
    long_result = reconstruct_fill_ledger([
        _fill("e1", "LONG"),
        _fill("x1", "SELL", 4, 110, order_id="partial:p"),
    ])
    short_result = reconstruct_fill_ledger([
        _fill("e2", "SHORT", position_id="s", order_id="entry:s"),
        _fill("x2", "BUY", 4, 90, position_id="s", order_id="close:s"),
    ])
    assert long_result.issues == set()
    assert long_result.positions["p"].signed_quantity == 6
    assert short_result.issues == set()
    assert short_result.positions["s"].signed_quantity == -6


def test_conflicting_duplicate_fill_is_quarantined():
    fill = _fill("e1")
    result = reconstruct_fill_ledger([fill, dict(fill, quantity=11)])
    assert "conflicting-fill:e1" in result.issues
    assert "p" in result.issues
    assert "p" not in result.positions


def test_invalid_numeric_and_unknown_side_are_quarantined():
    result = reconstruct_fill_ledger([
        _fill("bad-number", qty=float("nan")),
        _fill("bad-side", "UNKNOWN"),
    ])
    assert {"bad-number", "bad-side"} <= result.issues
    assert result.positions == {}


def test_missing_identity_is_quarantined():
    result = reconstruct_fill_ledger([_fill("", position_id="")])
    assert "missing-fill-id" in result.issues
    assert result.positions == {}
