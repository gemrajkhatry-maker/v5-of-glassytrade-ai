import copy

from backend.app.api.websocket.gameloop import _compute_delta


def test_delta_detects_nested_mutation_after_shallow_copy():
    # shallow copy hides nested mutation — the bug we fixed in gameloop.py
    snap1 = {"_symbol": "NIFTY AUG FUT", "portfolio": {"balance": 1_000_000, "positions": []}}
    prev = dict(snap1)  # shallow — bug
    snap1["portfolio"]["positions"].append({"id": "x"})
    delta = _compute_delta(prev, snap1)
    # Bug: shallow copy shares same list object → _deep_equal sees same list → delta == {}
    assert delta == {}, "shallow copy hides nested mutation — should be deep copy"

    # Fixed path: deepcopy detects nested mutation
    snap2 = {"_symbol": "NIFTY AUG FUT", "portfolio": {"balance": 1_000_000, "positions": []}}
    prev2 = copy.deepcopy(snap2)
    snap2["portfolio"]["positions"].append({"id": "x"})
    delta2 = _compute_delta(prev2, snap2)
    assert delta2 != {}, "deep copy should detect nested mutation"
