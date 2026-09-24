from quant.decision.gates_edge import gate_triple_a_edge
from quant.decision.context import DecisionContext
from quant.bars import Bar


def _bar():
    return Bar(time=1, open=99.5, high=102, low=99, close=101.5, volume=1000,
               buy_volume=600, sell_volume=400, delta=200, oi=50000, vwap=100.5)


def _ctx(**kw):
    base = dict(symbol="NIFTY", agent_direction="LONG", tick_size=0.05,
                bar=_bar(), triple_a_phase="AGGRESSION", triple_a_signal="LONG",
                allow_trend=True, cvd_slope=0.5, absorption_side="SELL_ABSORBED",
                session_vwap=100.0, absorption_cluster_high=100.5,
                absorption_cluster_low=99.5,
                poc=100.0, val=98.0, vah=102.0, leg_lvn=101.5)

    base.update(kw)
    return DecisionContext(**{k: v for k, v in base.items()
                             if k in DecisionContext.__dataclass_fields__})


def test_triple_a_aggression_tags_setup_key():
    r = gate_triple_a_edge(_ctx())
    assert r.passed and r.setup_key == "TRIPLE_A"
