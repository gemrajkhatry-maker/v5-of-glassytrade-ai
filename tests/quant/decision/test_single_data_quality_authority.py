"""Single data-quality authority on the entry path (v7 prune, N3).

History: two independent gates enforced data quality with *different*
thresholds. ``DecisionService.evaluate`` short-circuited with
``DATA_QUALITY_BLOCKED`` whenever ``agent_probability >= 0.65`` (a condition
the deterministic engine made constant-true) and the aggregate quality was not
in ``{TICK_EXACT, CANDLE_DISTRIBUTED}``; ``DecisionLoop._build_decision``
separately required strict ``TICK_EXACT`` for live OMS capability and marked
paper runs ``PROXY_MODE``. The first gate masked the second, force-blocked
paper/replay (tests had to monkeypatch the DTO to get past it), and produced
1,968 consecutive blocked cycles in the live log.

Contract after N3:

1. ``DecisionService`` never inspects data quality — provenance gating lives
   only in ``DecisionLoop`` (capability-aware: live OMS -> TICK_EXACT strict,
   paper/replay -> PROXY_MODE metadata, no block).
2. ``DATA_QUALITY_BLOCKED`` no longer exists as a decision reason.
3. ``agent_probability`` is construction metadata on the context only; no
   decision branch may read it (a drifting-literal guard keeps the threshold
   comparison from returning).
4. Live evidence remains fail-closed per evidence family
   (``live_evidence_exact``) — unchanged.
"""



from quant.bars import Bar
from quant.decision.context import DecisionContext
from quant.decision.data_quality import DataQuality, live_evidence_exact
from quant.decision.decision_service import DecisionService
from quant.decision.signal_builder import Signal
from quant.engine.decision_loop import DecisionLoop


def _ctx(quality: DataQuality) -> DecisionContext:
    return DecisionContext(
        bar=Bar(
            time="2026-01-15T10:00:00+05:30", open=100, high=105, low=95,
            close=102, volume=1000,
        ),
        symbol="SYM",
        data_quality=quality,
        agent_probability=0.7,  # construction metadata; must not gate anything
        evidence_provenance={family: quality for family in (
            "footprint_imbalance", "cvd_delta", "ofi_depth", "absorption",
            "stacked_imbalance",
        )},
    )


def test_service_does_not_block_on_gaussian_quality():
    """Paper/replay with CANDLE_GAUSSIAN must reach the gate pipeline.

    Before N3 this returned DATA_QUALITY_BLOCKED before any gate ran — the
    force-block that made paper replay un-testable without DTO monkeypatching.
    """
    decision = DecisionService().evaluate(_ctx(DataQuality.CANDLE_GAUSSIAN))
    assert decision.reason != "DATA_QUALITY_BLOCKED"


def test_service_does_not_block_on_unavailable_quality():
    decision = DecisionService().evaluate(_ctx(DataQuality.UNAVAILABLE))
    assert decision.reason != "DATA_QUALITY_BLOCKED"


def test_service_blocked_decisions_come_from_gates_not_provenance():
    """With synthetic bars the gates still reject — but through GateResults."""
    decision = DecisionService().evaluate(_ctx(DataQuality.CANDLE_GAUSSIAN))
    if not decision.approved:
        assert decision.gate_results, (
            "a non-approved decision on the service path must carry gate "
            "results (provenance short-circuit removed)"
        )


def test_data_quality_blocked_reason_is_retired():
    decision = DecisionService().evaluate(_ctx(DataQuality.CANDLE_GAUSSIAN))
    assert decision.reason != "DATA_QUALITY_BLOCKED"


def test_live_evidence_exact_still_fails_closed_per_family():
    """The per-family live contract is untouched by N3."""
    assert not live_evidence_exact({
        "footprint_imbalance": "TICK_EXACT",
        "cvd_delta": "CANDLE_DISTRIBUTED",
        "ofi_depth": "TICK_EXACT",
        "absorption": "TICK_EXACT",
        "stacked_imbalance": "TICK_EXACT",
    })
    assert live_evidence_exact({family: "TICK_EXACT" for family in (
        "footprint_imbalance", "cvd_delta", "ofi_depth", "absorption",
        "stacked_imbalance",
    )})


def test_service_source_has_no_provenance_branch():
    """Guard: the removed gate must not quietly return (source-level check)."""
    import inspect

    import quant.decision.decision_service as svc

    source = inspect.getsource(svc)
    assert "DATA_QUALITY_BLOCKED" not in source
    assert "conviction_allowed" not in source
    assert "agent_probability" not in source
    assert "CONFIDENCE_HIGH_THRESHOLD" not in source


# ---------------------------------------------------------------------------
# DecisionLoop remains the single authority — pin its existing contract so the
# removal above cannot silently weaken live safety.
# ---------------------------------------------------------------------------

class _Risk:
    class _State:
        trades_today = 0
        halted = False
        consecutive_losses = 0
        consecutive_wins = 0
        equity = 100000.0
        risk_per_trade_pct = 0.01

    def can_trade(self):
        return True, ""

    def state(self):
        return self._State()

    def position_size(self, *args, **kwargs):
        return 1


class _LiveOMS:
    lot_size = 1
    is_live = True

    def __init__(self):
        self.submissions = []

    def submit(self, signal, quantity):
        self.submissions.append((signal, quantity))


class _PaperOMS:
    lot_size = 1
    is_live = False

    def __init__(self):
        self.submissions = []

    def submit(self, signal, quantity):
        self.submissions.append((signal, quantity))


class _PositionManager:
    current_position = None


class _AMT:
    warm_bars = 20
    interval_seconds = 300
    last_amt_dto = {}


def _loop(oms, context):
    strategy = type(
        "Strategy", (),
        {"should_enter": lambda self, ctx: _approved_decision()},
    )()
    loop = DecisionLoop(
        config={"symbol": "SYM", "market": "NSE", "cooldown_bars": 0},
        deps={
            "risk": _Risk(), "oms": oms, "strategy": strategy,
            "amt_engine": _AMT(),
            "get_position_manager": lambda: _PositionManager(),
            "execution_enabled": True, "underlying_gateway": None,
        },
        state={
            "get_bar_index": lambda: 10, "get_entry_bar_index": lambda: 0,
            "set_entry_bar_index": lambda value: None,
            "get_last_close_bar_index": lambda: -1,
            "get_latch": lambda: {}, "set_latch": lambda key, value: None,
            "clear_latch": lambda: None, "get_cert_records": lambda: [],
            "get_last_depth": lambda: None, "get_recent_decisions": lambda: [],
            "get_exposure_state": lambda: None,
        },
        emit=lambda event: None,
    )
    loop._build_context = lambda bar, amt_dto, cooldown: context
    return loop


def _approved_decision():
    signal = Signal("LONG", "Triple-A", 100, 98, 106, 3, "Triple-A", "SYM", "t")
    from quant.decision.decision_service import QuantDecision

    return QuantDecision(True, signal, "Triple-A", "", (), model_label="Triple-A")


def _bar():
    return Bar(
        time="2026-01-15T10:00:00+05:30", open=100, high=105, low=95,
        close=102, volume=1000,
    )


def test_loop_live_blocks_non_exact_quality():
    oms = _LiveOMS()
    decision = _loop(oms, _ctx(DataQuality.CANDLE_DISTRIBUTED)).evaluate({}, _bar())
    assert decision.approved is False
    assert decision.reason == "PROXY_FLOW_BLOCKED"
    assert oms.submissions == []


def test_loop_live_passes_exact_quality():
    oms = _LiveOMS()
    decision = _loop(oms, _ctx(DataQuality.TICK_EXACT)).evaluate({}, _bar())
    assert decision.approved is True


def test_loop_paper_marks_proxy_mode_without_blocking():
    oms = _PaperOMS()
    decision = _loop(oms, _ctx(DataQuality.CANDLE_GAUSSIAN)).evaluate({}, _bar())
    assert decision.approved is True
    assert decision.metadata["mode"] == "PROXY_MODE"
    assert oms.submissions
