from quant.decision.decision_service import DecisionService, QuantDecision
from quant.decision.context import DecisionContext
from quant.auction_state import AuctionState
from quant.vwap import VWAPState
from quant.volume_profile import VolumeProfile
from quant.order_flow import OrderFlowState
from quant.location import LocationState


def _state(triple_a_phase="", triple_a_signal=None):
    return AuctionState(
        time="t", close=100.0,
        volume_profile=VolumeProfile(levels=(), poc=100.0, vah=100.5, val=99.5,
                                     step=0.1, total_volume=100),
        vwap=VWAPState(value=100.0, upper_1=101.0, lower_1=99.0,
                       upper_2=102.0, lower_2=98.0, std=1, deviation_sigmas=0),
        order_flow=OrderFlowState(delta=0, cvd=0.0, cvd_slope=0.0,
                                  cvd_divergence="NONE", aggressive_prints=()),
        absorption=None,
        location=LocationState(ib_high=105, ib_low=95, ib_complete=True,
                               zone="INSIDE_VA", nearest_level=100.0, distance_to_level=0),
        triple_a_phase=triple_a_phase, triple_a_signal=triple_a_signal,
    )


def _va_fade_state():
    return AuctionState(
        time="t", close=99.6,
        volume_profile=VolumeProfile(levels=(), poc=101.0, vah=102.0, val=100.0,
                                     step=0.5, total_volume=100),
        vwap=VWAPState(value=99.0, upper_1=100.0, lower_1=98.0,
                       upper_2=101.0, lower_2=97.0, std=1, deviation_sigmas=0),
        order_flow=OrderFlowState(delta=0, cvd=50.0, cvd_slope=0.0,
                                  cvd_divergence="NONE", aggressive_prints=()),
        absorption=None,
        location=LocationState(ib_high=105, ib_low=95, ib_complete=True,
                               zone="BELOW_VA", nearest_level=100.0, distance_to_level=0),
        triple_a_phase="", triple_a_signal=None,
    )


def _thin_va_fade_state():
    # Same setup but step shrinks SL to 99.55 (0.05% stop, sub-0.1% -> rejected).
    return AuctionState(
        time="t", close=99.6,
        volume_profile=VolumeProfile(levels=(), poc=101.0, vah=102.0, val=100.0,
                                     step=0.05, total_volume=100),
        vwap=VWAPState(value=99.0, upper_1=100.0, lower_1=98.0,
                       upper_2=101.0, lower_2=97.0, std=1, deviation_sigmas=0),
        order_flow=OrderFlowState(delta=0, cvd=50.0, cvd_slope=0.0,
                                  cvd_divergence="NONE", aggressive_prints=()),
        absorption=None,
        location=LocationState(ib_high=105, ib_low=95, ib_complete=True,
                               zone="BELOW_VA", nearest_level=100.0, distance_to_level=0),
        triple_a_phase="", triple_a_signal=None,
    )


def _quiet_state():
    return AuctionState(
        time="t", close=100.0,
        volume_profile=VolumeProfile(levels=(), poc=100.0, vah=102.0, val=98.0,
                                     step=1.0, total_volume=100),
        vwap=VWAPState(value=100.0, upper_1=101.0, lower_1=99.0,
                       upper_2=102.0, lower_2=98.0, std=1, deviation_sigmas=0),
        order_flow=OrderFlowState(delta=0, cvd=0.0, cvd_slope=0.0,
                                  cvd_divergence="NONE", aggressive_prints=()),
        absorption=None,
        location=LocationState(ib_high=105, ib_low=95, ib_complete=True,
                               zone="INSIDE_VA", nearest_level=100.0, distance_to_level=0),
        triple_a_phase="", triple_a_signal=None,
    )


def test_aggression_long_approved():
    ctx = DecisionContext(state=_state(triple_a_phase="AGGRESSION", triple_a_signal="LONG"),
                          bar=None, agent_direction="LONG", agent_probability=0.7,
                          market_state="IMBALANCED")
    d = DecisionService().evaluate(ctx)
    assert d.approved and d.signal is not None and d.signal.type == "LONG"
    assert d.reason == "Triple-A"


def test_aggression_approved_in_balanced_market():
    """Fabio playbook (simplified): a valid Triple-A edge executes in balanced
    rotation too — the playbook trades the same absorption/breakout setup
    everywhere (default market_state is BALANCED)."""
    ctx = DecisionContext(state=_state(triple_a_phase="AGGRESSION", triple_a_signal="LONG"),
                          bar=None, agent_direction="LONG", agent_probability=0.7)
    d = DecisionService().evaluate(ctx)
    assert d.approved and d.signal is not None and d.signal.type == "LONG"
    assert d.reason == "Triple-A"


def test_aggression_blocked_in_dead_market():
    ctx = DecisionContext(state=_state(triple_a_phase="AGGRESSION", triple_a_signal="LONG"),
                          bar=None, agent_direction="LONG", agent_probability=0.7,
                          market_state="DEAD")
    d = DecisionService().evaluate(ctx)
    assert not d.approved and d.signal is None and d.reason == "NO_EDGE"


def test_va_fade_fallback():
    ctx = DecisionContext(state=_va_fade_state(), bar=None, agent_direction="LONG", agent_probability=0.7,
                          market_state="IMBALANCED")
    d = DecisionService().evaluate(ctx)
    assert d.approved and d.signal is not None and d.reason == "VA_FADE"

def test_va_fade_thin_stop_rejected():
    # entry 99.6, SL at VAL - step = 99.61 -> ~0.01% stop -> rejected as NO_EDGE.
    ctx = DecisionContext(state=_thin_va_fade_state(), bar=None, agent_direction="LONG", agent_probability=0.7,
                          market_state="IMBALANCED")
    d = DecisionService().evaluate(ctx)
    assert not d.approved and d.signal is None and d.reason == "NO_EDGE"

def test_va_fade_healthy_stop_passes():
    # entry 99.6, SL at VAL - step = 99.5 -> ~0.1% stop -> guard met, fade passes.
    ctx = DecisionContext(state=_va_fade_state(), bar=None, agent_direction="LONG", agent_probability=0.7,
                          market_state="IMBALANCED")
    d = DecisionService().evaluate(ctx)
    assert d.approved and d.signal is not None and d.reason == "VA_FADE"

def test_va_fade_blocked_in_dead_market():
    """Even the reversion trade refuses a dead market."""
    ctx = DecisionContext(state=_va_fade_state(), bar=None, agent_direction="LONG", agent_probability=0.7,
                          market_state="DEAD")
    d = DecisionService().evaluate(ctx)
    assert not d.approved and d.signal is None and d.reason == "NO_EDGE"

def test_no_edge():
    ctx = DecisionContext(state=_quiet_state(), bar=None, agent_direction=None, agent_probability=0.0)
    d = DecisionService().evaluate(ctx)
    assert not d.approved and d.signal is None and d.reason == "NO_EDGE"


def test_no_state_guard():
    d = DecisionService().evaluate(DecisionContext(state=None, bar=None))
    assert not d.approved and d.signal is None and d.reason == "NO_EDGE"
    assert d.phase == "" and d.gate_results == ()


# ── Defect regression tests ──────────────────────────────────────────────────

def test_halted_emits_explicit_halted_decision():
    """Defect 2 regression: a halted system must emit approved=False reason=HALTED,
    never silently return without a decision. The StateProjector must not carry
    stale ENTER state after a halt is triggered."""
    ctx = DecisionContext(
        state=_state(triple_a_phase="AGGRESSION", triple_a_signal="LONG"),
        bar=None,
        agent_direction="LONG",
        agent_probability=0.9,
        risk_halted=True,
    )
    d = DecisionService().evaluate(ctx)
    assert not d.approved, "Halted system must not approve any signal"
    assert d.signal is None, "Halted system must emit no signal"
    assert d.reason == "HALTED", f"Expected reason=HALTED, got {d.reason!r}"
    assert len(d.block_reasons) > 0, "HALTED decision must include a block_reason"
    assert "halted" in d.block_reasons[0].lower(), f"Block reason should mention halt: {d.block_reasons[0]!r}"


def test_approved_requires_aggression_phase():
    """Defect 1 regression: approved=True must only occur when triple_a_phase==AGGRESSION
    (or VA_FADE). Phases WAITING / ABSORBING / ACCUMULATING must all yield approved=False."""
    for non_entry_phase in ("WAITING", "ABSORBING", "ACCUMULATING", ""):
        ctx = DecisionContext(
            state=_state(triple_a_phase=non_entry_phase, triple_a_signal=None),
            bar=None,
            agent_direction="LONG",
            agent_probability=0.9,
        )
        d = DecisionService().evaluate(ctx)
        assert not d.approved, (
            f"approved=True must not fire in phase {non_entry_phase!r}, got reason={d.reason!r}"
        )
        assert d.signal is None, f"No signal expected in phase {non_entry_phase!r}"


def test_approved_signal_carries_model_label():
    """A Triple-A approved signal must carry a non-empty model_label string."""
    ctx = DecisionContext(
        state=_state(triple_a_phase="AGGRESSION", triple_a_signal="LONG"),
        bar=None,
        agent_direction="LONG",
        agent_probability=0.9,
        market_state="IMBALANCED",
    )
    d = DecisionService().evaluate(ctx)
    assert d.approved and d.signal is not None
    assert d.signal.model_label, "Approved signal must have a non-empty model_label"
    assert d.model_label, "QuantDecision must carry model_label when approved"
    assert d.signal.model_label == d.model_label, "Signal and decision model_label must match"
