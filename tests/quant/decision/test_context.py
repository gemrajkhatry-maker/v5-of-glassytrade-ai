from quant.decision.context import DecisionContext


def test_context_defaults():
    c = DecisionContext(state=None, bar=None)
    assert c.session_open is True
    assert c.position_open is False
    assert c.cooldown_remaining_sec == 0
    assert c.risk_per_trade_pct == 0.01

def test_context_is_frozen():
    c = DecisionContext(state=None, bar=None)
    try:
        c.session_open = False
        assert False, "should be immutable"
    except Exception:
        pass
