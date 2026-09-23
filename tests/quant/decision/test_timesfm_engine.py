"""Unit tests for native TimesFM 3.0 Quantitative Decision Engine."""

from unittest.mock import Mock, patch

import pytest
from quant.bars import Bar
from quant.decision.context import DecisionContext
from quant.decision.timesfm_engine import (
    TimesFMEngine,
    reset_timesfm_model_cache,
)


@pytest.fixture
def sample_context():
    bar = Bar("2026-09-08T15:30:00", 6450.0, 6465.0, 6445.0, 6460.0, 2500, 350)
    return DecisionContext(
        symbol="CRUDEOIL",
        bar=bar,
        poc=6455.0,
        vah=6465.0,
        val=6445.0,
        cvd_slope=2.1,
        absorption_side="BUY",
        session_phase="PRIMARY",
    )


def test_timesfm_engine_padding(sample_context):
    engine = TimesFMEngine(target_horizon=32)
    prices, ctx_bars = engine.add_context(sample_context)
    assert len(prices) == 32
    assert ctx_bars == 1
    assert all(p == 6460.0 for p in prices)


def test_timesfm_engine_risk_halted():
    ctx = DecisionContext(symbol="GOLDM", risk_halted=True)
    engine = TimesFMEngine(target_horizon=32)
    res = engine.analyze(ctx)

    assert res["action"] == "FLAT"
    assert res["direction"] == "FLAT"
    assert res["setup"] == "NO_EDGE"
    assert "Daily risk threshold reached" in res["rationale"]


def test_timesfm_engine_opening_noise():
    ctx = DecisionContext(symbol="SILVERM", session_phase="OPENING_NOISE")
    engine = TimesFMEngine(target_horizon=32)
    res = engine.analyze(ctx)

    assert res["action"] == "FLAT"
    assert res["direction"] == "FLAT"
    assert "Opening noise" in res["rationale"]


def test_timesfm_engine_nse_opening_phase():
    """NSE_OPENING session phase must trigger opening noise guard in TimesFMEngine."""
    ctx = DecisionContext(symbol="NIFTY", session_phase="NSE_OPENING")
    engine = TimesFMEngine(target_horizon=32)
    res = engine.analyze(ctx)

    assert res["action"] == "FLAT"
    assert res["direction"] == "FLAT"
    assert res["reason"] == "OPENING_NOISE"
    assert "Opening noise" in res["rationale"]


def test_timesfm_engine_mcx_pre_open_phase():
    """MCX_PRE_OPEN session phase must trigger opening noise guard in TimesFMEngine."""
    ctx = DecisionContext(symbol="CRUDEOIL", session_phase="MCX_PRE_OPEN")
    engine = TimesFMEngine(target_horizon=32)
    res = engine.analyze(ctx)

    assert res["action"] == "FLAT"
    assert res["direction"] == "FLAT"
    assert res["reason"] == "OPENING_NOISE"
    assert "Opening noise" in res["rationale"]


def test_timesfm_engine_warmup_success():
    """warmup() returns True when model loads successfully."""
    reset_timesfm_model_cache()
    engine = TimesFMEngine(target_horizon=32)
    with patch("quant.decision.timesfm_engine.get_timesfm_model") as mock_load:
        mock_load.return_value = object()
        assert engine.warmup() is True
        assert engine.is_healthy() is True
        mock_load.assert_called_once_with("cpu")


def test_timesfm_engine_warmup_failure():
    """warmup() returns False and engine degrades to fallback mode on failure."""
    reset_timesfm_model_cache()
    engine = TimesFMEngine(target_horizon=32)
    with patch("quant.decision.timesfm_engine.get_timesfm_model") as mock_load:
        mock_load.side_effect = RuntimeError("Model not found")
        assert engine.warmup() is False
        assert engine.is_healthy() is False


def test_timesfm_engine_warmup_idempotent():
    """warmup() is safe to call multiple times."""
    reset_timesfm_model_cache()
    engine = TimesFMEngine(target_horizon=32)
    with patch("quant.decision.timesfm_engine.get_timesfm_model") as mock_load:
        mock_load.return_value = object()
        assert engine.warmup() is True
        assert engine.warmup() is True  # second call should be no-op
        mock_load.assert_called_once()  # model loaded only once


def test_timesfm_engine_health_check_healthy():
    """health_check() returns healthy status when model loads."""
    reset_timesfm_model_cache()
    with patch("quant.decision.timesfm_engine.get_timesfm_model") as mock_load:
        mock_load.return_value = object()
        result = TimesFMEngine.health_check()
        assert result["status"] == "healthy"
        assert result["model_loaded"] is True
        assert result["error"] is None


def test_timesfm_engine_health_check_unavailable():
    """health_check() returns unavailable status when model fails."""
    reset_timesfm_model_cache()
    with patch("quant.decision.timesfm_engine.get_timesfm_model") as mock_load:
        mock_load.side_effect = ImportError("timesfm not installed")
        result = TimesFMEngine.health_check()
        assert result["status"] == "unavailable"
        assert result["model_loaded"] is False
        assert result["error"] is not None


def test_timesfm_engine_session_gate_blocked():
    """analyze() returns FLAT with SESSION_GATE_BLOCKED when session gate denies entry."""
    ctx = DecisionContext(
        symbol="NIFTY",
        time_str="16:45",
        market="NSE",
        session_phase="CLOSE_PROTECTION",
    )
    engine = TimesFMEngine(target_horizon=32)
    with patch("quant.decision.timesfm_engine.session_allow_entry") as mock_gate:
        mock_gate.return_value = False
        res = engine.analyze(ctx)
        mock_gate.assert_called_once_with("16:45", "NSE")
        assert res["action"] == "FLAT"
        assert res["direction"] == "FLAT"
        assert res["reason"] == "SESSION_GATE_BLOCKED"
        assert res["confidenceScore"] == 0.0


def test_timesfm_engine_session_gate_allows():
    """analyze() proceeds past session gate when entry is allowed."""
    bar = Bar("2026-09-08T15:30:00", 6450.0, 6465.0, 6445.0, 6460.0, 2500, 350)
    ctx = DecisionContext(
        symbol="CRUDEOIL",
        bar=bar,
        time_str="10:30",
        market="MCX",
        session_phase="PRIMARY",
        cvd_slope=2.1,
        absorption_side="BUY",
    )
    engine = TimesFMEngine(target_horizon=32)
    with patch("quant.decision.timesfm_engine.session_allow_entry") as mock_gate:
        mock_gate.return_value = True
        with patch("quant.decision.timesfm_engine.get_timesfm_model") as mock_load:
            # Use a Mock that raises on predict to trigger fallback path
            mock_model = Mock()
            mock_model.predict.side_effect = RuntimeError("inference error")
            mock_load.return_value = mock_model
            engine.analyze(ctx)
            mock_gate.assert_called_once_with("10:30", "MCX")


def test_timesfm_engine_fallback_mode_returns_valid_payload():
    """When model fails to load, analyze() returns a valid fallback decision payload."""
    bar = Bar("2026-09-08T15:30:00", 6450.0, 6465.0, 6445.0, 6460.0, 2500, 350)
    ctx = DecisionContext(
        symbol="CRUDEOIL",
        bar=bar,
        poc=6455.0,
        vah=6465.0,
        val=6445.0,
        cvd_slope=2.1,
        absorption_side="SELL_ABSORBED",
        session_phase="PRIMARY",
    )
    engine = TimesFMEngine(target_horizon=32)
    with patch("quant.decision.timesfm_engine.get_timesfm_model") as mock_load:
        mock_load.side_effect = RuntimeError("timesfm package not installed")
        res = engine.analyze(ctx)

        # Verify valid fallback payload
        assert res["source"] == "TIMESFM_FALLBACK"
        assert res["reason"] == "TIMESFM_FALLBACK"
        assert res["setup"] == "RULE_BASED_FALLBACK"
        assert res["confidence"] == "Low"
        assert res["confidenceScore"] == 0.2
        # Canonical AMT: SELL_ABSORBED (sellers absorbed) is bullish, and the
        # CVD slope confirms it. The old bare "BUY" read was dead against the
        # live DTO and directionally inverted.
        assert res["direction"] == "LONG"
        assert res["action"] == "ENTER_LONG"
        assert res["role"] == "SCANNING"
        assert len(res["forecastSteps"]) == 32
        assert res["meanForecast"] == 6460.0
        assert "TimesFM unavailable" in res["rationale"]
        assert res["modelVersions"]["timesfm"] == "unavailable"
        assert res["modelVersions"]["engine"] == "rule_based_fallback"


def test_timesfm_engine_fallback_mode_flat_when_no_edge():
    """Fallback returns FLAT direction when no AMT edge is present."""
    bar = Bar("2026-09-08T15:30:00", 6450.0, 6465.0, 6445.0, 6460.0, 2500, 350)
    ctx = DecisionContext(
        symbol="CRUDEOIL",
        bar=bar,
        poc=6455.0,
        vah=6465.0,
        val=6445.0,
        cvd_slope=0.0,
        absorption_side="",
        session_phase="PRIMARY",
    )
    engine = TimesFMEngine(target_horizon=32)
    with patch("quant.decision.timesfm_engine.get_timesfm_model") as mock_load:
        mock_load.side_effect = RuntimeError("model load failed")
        res = engine.analyze(ctx)

        assert res["direction"] == "FLAT"
        assert res["action"] == "FLAT"
        assert all(s == "FLAT" for s in res["forecastSteps"])


def test_timesfm_engine_fallback_mode_short_edge():
    """Fallback returns SHORT direction when AMT signals are bearish."""
    bar = Bar("2026-09-08T15:30:00", 6450.0, 6465.0, 6445.0, 6460.0, 2500, 350)
    ctx = DecisionContext(
        symbol="CRUDEOIL",
        bar=bar,
        poc=6455.0,
        vah=6465.0,
        val=6445.0,
        cvd_slope=-3.5,
        absorption_side="BUY_ABSORBED",
        session_phase="PRIMARY",
    )
    engine = TimesFMEngine(target_horizon=32)
    with patch("quant.decision.timesfm_engine.get_timesfm_model") as mock_load:
        mock_load.side_effect = RuntimeError("model load failed")
        res = engine.analyze(ctx)

        assert res["direction"] == "SHORT"
        assert res["action"] == "ENTER_SHORT"


def test_timesfm_engine_fallback_mode_position_open():
    """Fallback returns HOLD action when position is open."""
    bar = Bar("2026-09-08T15:30:00", 6450.0, 6465.0, 6445.0, 6460.0, 2500, 350)
    ctx = DecisionContext(
        symbol="CRUDEOIL",
        bar=bar,
        poc=6455.0,
        vah=6465.0,
        val=6445.0,
        cvd_slope=2.1,
        absorption_side="BUY",
        session_phase="PRIMARY",
        position_open=True,
        position_side="LONG",
        position_entry_price=6450.0,
    )
    engine = TimesFMEngine(target_horizon=32)
    with patch("quant.decision.timesfm_engine.get_timesfm_model") as mock_load:
        mock_load.side_effect = RuntimeError("model load failed")
        res = engine.analyze(ctx)

        assert res["role"] == "POSITION_MANAGEMENT"
        assert res["action"] == "HOLD"


def test_add_context_is_idempotent_within_a_stamped_bar():
    """A shared engine (native advisor + E2E strategy) must not record the
    same bar twice — a duplicated price series corrupts the model input."""
    bar = Bar("2026-09-10T10:00:00", 100, 101, 99, 100.5, 1000, 100)
    ctx = DecisionContext(symbol="NIFTY", bar=bar, bar_index=7)
    engine = TimesFMEngine(target_horizon=8)

    engine.add_context(ctx)                      # first consumer (strategy)
    _, depth_after_first = engine.add_context(ctx)  # second consumer (advisor)

    assert depth_after_first == 1
    assert list(engine._price_buffers["NIFTY"]) == [100.5]

    # A new bar still records normally.
    ctx2 = DecisionContext(
        symbol="NIFTY",
        bar=Bar("2026-09-10T10:01:00", 101, 102, 100, 101.5, 1000, 100),
        bar_index=8,
    )
    engine.add_context(ctx2)
    assert list(engine._price_buffers["NIFTY"]) == [100.5, 101.5]


def test_native_advisor_scanner_call_uses_model_gates():
    """The advisor's UI gate payload is the scanner's own model gates — the same
    source that drives the E2E entry decision (model is authoritative). The
    advisor must not inject a separate canonical pipeline."""
    import numpy as np

    ctx = DecisionContext(
        symbol="NIFTY",
        bar=Bar("2026-09-10T10:00:00", 100, 101, 99, 100.5, 1000, 100),
        bar_index=7,
        session_open=True,
        warmup_complete=True,
        session_phase="PRIMARY",
        cvd_slope=0.0,
    )
    engine = TimesFMEngine(target_horizon=8)
    p50 = np.linspace(99.0, 100.5, 8, dtype=np.float32)
    fake = Mock()
    fake.predict.return_value = Mock(
        quantiles=np.stack([p50 - 1, p50 - .5, p50, p50, p50, p50, p50, p50 + .5, p50 + 1], axis=1)
    )
    with patch("quant.decision.timesfm_engine.get_timesfm_model", return_value=fake):
        with patch.object(engine.scanning_agent, "evaluate", return_value={
            "gateResults": [], "action": "FLAT", "direction": "FLAT",
            "setup": "NO_EDGE", "rationale": "test",
        }) as evaluate:
            engine.analyze(ctx)

    assert "canonical_gates" not in evaluate.call_args.kwargs


def test_add_context_is_thread_safe_for_one_bar():
    """D-10: two consumers racing on the same bar must append it once."""
    import threading

    engine = TimesFMEngine(target_horizon=8)
    bar = Bar("2026-09-10T10:00:00", 100, 101, 99, 100.5, 1000, 100)
    ctx = DecisionContext(symbol="NIFTY", bar=bar, bar_index=42)

    class _Rendezvous(dict):
        def __init__(self):
            super().__init__()
            self._barrier = threading.Barrier(2, timeout=5)

        def get(self, key, default=None):
            value = super().get(key, default)
            try:
                self._barrier.wait()
            except threading.BrokenBarrierError:
                pass
            return value

    engine._last_context_bar = _Rendezvous()

    def consumer():
        try:
            engine.add_context(ctx)
        except Exception:
            pass

    threads = [threading.Thread(target=consumer) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(engine._price_buffers["NIFTY"]) == 1


def test_add_context_ignores_a_late_replayed_bar():
    """D-10: the advisor drains its queue behind the engine thread, so a bar
    already recorded must not be appended again."""
    engine = TimesFMEngine(target_horizon=8)

    def mk(idx, px):
        bar = Bar(f"2026-09-10T10:{idx:02d}:00", px, px, px, px, 10, 10)
        return DecisionContext(symbol="NIFTY", bar=bar, bar_index=idx)

    for idx, px in [(1, 100.0), (2, 101.0), (3, 102.0)]:
        engine.add_context(mk(idx, px))          # strategy, on time
    for idx, px in [(1, 100.0), (2, 101.0), (3, 102.0)]:
        engine.add_context(mk(idx, px))          # advisor, lagging

    assert list(engine._price_buffers["NIFTY"]) == [100.0, 101.0, 102.0]


def test_add_context_still_accepts_unstamped_callers():
    """bar_index < 0 (unit tests, ad-hoc probes) keeps appending."""
    engine = TimesFMEngine(target_horizon=8)
    bar = Bar("2026-09-10T10:00:00", 100, 101, 99, 100.5, 1000, 100)
    ctx = DecisionContext(symbol="NIFTY", bar=bar, bar_index=-1)
    engine.add_context(ctx)
    engine.add_context(ctx)
    assert len(engine._price_buffers["NIFTY"]) == 2


def test_seed_history_holds_the_buffer_lock():
    """D-10 follow-up: seeding mutates the shared buffer and must serialise
    against add_context's append. Prove the mutation happens under the lock."""
    engine = TimesFMEngine(target_horizon=8)

    class _RecordingLock:
        def __init__(self, inner):
            self._inner = inner
            self.entered = False
            self.exited = False

        def __enter__(self):
            self.entered = True
            return self._inner.__enter__()

        def __exit__(self, *exc):
            self.exited = True
            return self._inner.__exit__(*exc)

    recorder = _RecordingLock(engine._buffer_lock)
    engine._buffer_lock = recorder

    loaded = engine.seed_history("NIFTY", [100.0, 101.0, 102.0])

    assert loaded == 3
    assert recorder.entered and recorder.exited, "seed_history mutated the buffer without the lock"
    assert list(engine._price_buffers["NIFTY"]) == [100.0, 101.0, 102.0]


def test_seed_history_ignores_a_late_seed_after_live_bars():
    """A seed that arrives after a stamped live bar carries strictly older
    prices; appending it would put out-of-order closes after live data."""
    engine = TimesFMEngine(target_horizon=8)
    bar = Bar("2026-09-10T10:00:00", 200, 201, 199, 200.0, 1000, 100)
    engine.add_context(DecisionContext(symbol="NIFTY", bar=bar, bar_index=7))

    loaded = engine.seed_history("NIFTY", [100.0, 101.0, 102.0])

    assert loaded == 0
    assert list(engine._price_buffers["NIFTY"]) == [200.0]


def test_seed_history_does_not_suppress_a_later_live_bar():
    """Seeding must not stamp _last_context_bar, or the monotonic rule would
    drop the next legitimate live bar."""
    engine = TimesFMEngine(target_horizon=8)
    engine.seed_history("NIFTY", [100.0, 101.0, 102.0])
    assert "NIFTY" not in engine._last_context_bar

    bar = Bar("2026-09-10T10:00:00", 103, 104, 102, 103.0, 1000, 100)
    engine.add_context(DecisionContext(symbol="NIFTY", bar=bar, bar_index=1))
    assert list(engine._price_buffers["NIFTY"]) == [100.0, 101.0, 102.0, 103.0]


def test_last_forecast_for_returns_recorded():
    from quant.decision.timesfm_engine import TimesFMEngine
    eng = TimesFMEngine.__new__(TimesFMEngine)
    eng._forecast_cache = {}
    sentinel = object()
    eng.record_forecast("NIFTY", 7, sentinel)
    assert eng.last_forecast_for("NIFTY") is sentinel
