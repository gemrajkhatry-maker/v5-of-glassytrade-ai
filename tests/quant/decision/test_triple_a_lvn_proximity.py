from quant.decision.gates_edge import gate_triple_a_edge
from quant.decision.context import DecisionContext
from quant.bars import Bar


def _make_ctx(**overrides):
    """Build a minimal DecisionContext for Gate 3 testing."""
    defaults = dict(
        symbol="NIFTY",
        agent_direction="LONG",
        tick_size=0.05,
        bar=Bar(time=1, open=100.5, high=101.1, low=100.4, close=101,
                volume=1000, buy_volume=600, sell_volume=400,
                delta=200, oi=50000, vwap=100.5),
        triple_a_phase="AGGRESSION",
        triple_a_signal="LONG",
        allow_trend=True,
        cvd_slope=0.5,
        absorption_side="SELL_ABSORBED",
        poc=100.0,
        val=98.0,
        vah=102.0,
        session_vwap=100.0,
        absorption_cluster_high=100.5,
        absorption_cluster_low=99.5,
        leg_lvn=0.0,
    )
    defaults.update(overrides)
    # Filter to only valid DecisionContext fields
    valid_fields = set(DecisionContext.__dataclass_fields__.keys())
    filtered = {k: v for k, v in defaults.items() if k in valid_fields}
    return DecisionContext(**filtered)


def test_triple_a_passes_when_price_at_leg_lvn():
    ctx = _make_ctx(leg_lvn=100.9)
    result = gate_triple_a_edge(ctx)
    assert result.passed is True


def test_triple_a_passes_when_price_far_from_lvn():
    ctx = _make_ctx(leg_lvn=95.0)
    result = gate_triple_a_edge(ctx)
    assert result.passed is True
    assert result.setup_key == "TRIPLE_A"


def test_triple_a_passes_when_no_lvn():
    ctx = _make_ctx(leg_lvn=0.0)
    result = gate_triple_a_edge(ctx)
    assert result.passed is True
    assert result.setup_key == "TRIPLE_A"
