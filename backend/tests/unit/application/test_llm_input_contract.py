"""Contract tests for LLM entry input correctness (Task 5).

Covers: VWAP key alignment (session_vwap/vwap_upper_2/vwap_lower_2),
session/gate/option context propagation, never-read key removal, and worker
decision consistency (the worker must NOT hot-refresh prompt fields from a
newer session.last_amt).
"""

from __future__ import annotations

import inspect
import queue
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.application.handlers.llm_entry_handler import LLMEntryHandler
from quant.inference.prompt_builder import build_entry_prompt
from quant.contracts.enums import SetupType
from quant.contracts.value_objects import AMTResult, OHLC

# Keys verified (grep) as never read by any prompt block / parser. delta is
# deliberately NOT here: the key is still emitted by _build_market_data_ai
# (only its prompt_builder read was removed).
NEVER_READ_KEYS = (
    "volume",
    "session_elapsed_minutes",
    "prior_analysis_context",
    "strategy_hint",
    "hvns",
    "opening_relation",
    "structure_confidence",
    "balance_ratio",
    "episodic_memory",
    "absorption_side",
    "absorption_range_ratio",
    "absorption_vol_ratio",
    "price_velocity",
    "break_direction",
    "break_type",
    "break_level",
    "poc_signal",
    "poc_vs_price",
    "amt_time_window",
    "aggression_warning",
    "drive_warning",
    "cvd_warning",
    "ofi",
)


def _amt(**kwargs: object) -> AMTResult:
    base = {
        "market_state": "BALANCED",
        "poc": 24000.0,
        "value_area_high": 24100.0,
        "value_area_low": 23900.0,
        "session_vwap": 24000.0,
        "vwap_upper_2": 24080.0,
        "vwap_lower_2": 23920.0,
        "aggression": 0.6,
        "cvd_slope": 4.0,
        "profile_shape": "D",
        "dev_poc": 24010.0,
        "dev_vah": 24060.0,
        "dev_val": 23950.0,
        "market_structure": "BALANCE",
        "leg_poc": 0.0,
        "leg_vah": 0.0,
        "leg_val": 0.0,
        "ib_high": 0.0,
        "ib_low": 0.0,
        "ib_complete": False,
        "prior_poc": 0.0,
        "prior_vah": 0.0,
        "prior_val": 0.0,
        "gap_type": "",
        "opening_bias": "",
        "acceptance_above": False,
        "acceptance_below": False,
        "rejection_at_high": False,
        "rejection_at_low": False,
        "lvn_play": None,
        "lvns": (),
        "hvns": (),
        "cvd_divergence": "",
        "leg_lvns": (),
        "aggressive_prints": (),
        "ofi": 0.0,
    }
    base.update(kwargs)
    return AMTResult(**base)  # type: ignore[arg-type]


def _tick(close: float = 24020.0) -> OHLC:
    return OHLC.create(
        "2025-01-15T10:00:00+05:30", close, close * 1.01, close * 0.99, close, 1000.0
    )


def _session_stub():
    return SimpleNamespace(
        _lock=threading.Lock(),
        _agent_decision=None,
        _last_fp_domain=None,
        data=[
            OHLC.create(
                "2025-01-15T09:20:00+05:30", 100.0, 101.0, 99.0, 100.0, 500.0
            )
        ],
        last_amt=None,
        _ai_running=False,
    )


def _handler() -> tuple[LLMEntryHandler, MagicMock]:
    gen = MagicMock()
    gen.is_ready.return_value = True
    return LLMEntryHandler(gen_ai_service=gen, exchange="NSE"), gen


def _session_info(**overrides):
    base = dict(
        session="NSE_PRIMARY",
        phase=2,
        is_london=False,
        is_new_york=False,
        opening_relation="IN_BALANCE",
        favor_strategy="TREND_CONTINUATION",
        allow_entry=True,
        allow_trend=True,
        allow_reversion=True,
        force_exit=False,
        market="NSE",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _build_md(
    handler,
    session,
    amt,
    symbol: str = "NIFTY 30 JAN 24000 CALL",
):
    return handler._build_market_data_ai(
        symbol,
        session,
        _tick(),
        amt,
        _session_info(),
        SetupType.MEAN_REVERSION,
        "D",
        "Balanced",
        False,
    )


class TestVWAPKeys:
    def test_market_data_ai_writes_session_vwap_keys(self):
        handler, _ = _handler()
        md, status = _build_md(handler, _session_stub(), _amt())
        assert status == "OK"
        assert md["session_vwap"] == 24000.0
        assert md["vwap_upper_2"] == 24080.0
        assert md["vwap_lower_2"] == 23920.0
        assert "vwap" not in md  # no stale single-key alias

    def test_entry_prompt_renders_vwap_bias_from_market_data_ai(self):
        handler, _ = _handler()
        md, _ = _build_md(handler, _session_stub(), _amt())
        prompt = build_entry_prompt(md)
        assert "VWAP" in prompt
        assert "Bullish" in prompt


class TestContextPropagation:
    def test_market_data_ai_includes_session_and_option_context(self):
        handler, _ = _handler()
        md, _ = _build_md(handler, _session_stub(), _amt())
        assert md["session_name"] == "NSE_PRIMARY"
        assert md["favor_strategy"] == "TREND_CONTINUATION"
        assert md["dev_poc"] == 24010.0
        assert md["dev_vah"] == 24060.0
        assert md["dev_val"] == 23950.0
        # AMTResult has no iv/theta — safe defaults must be used
        assert md["iv"] == 0.0
        assert md["theta"] == 0.0

    def test_session_favor_renders_in_prompt(self):
        handler, _ = _handler()
        md, _ = _build_md(handler, _session_stub(), _amt())
        prompt = build_entry_prompt(md)
        assert "SESSION: NSE_PRIMARY." in prompt
        assert "Session favors: TREND CONTINUATION." in prompt


class TestNeverReadKeys:
    def test_market_data_ai_omits_never_read_keys(self):
        handler, _ = _handler()
        md, _ = _build_md(handler, _session_stub(), _amt())
        for key in NEVER_READ_KEYS:
            assert key not in md, f"dead key {key!r} still present"


class TestNoDeadPromptKeys:
    def test_market_data_ai_has_no_dead_keys(self):
        handler, _ = _handler()
        md, _ = _build_md(handler, _session_stub(), _amt())
        for dead in ("gate_context", "session_context_for_llm", "strategy_hint"):
            assert dead not in md, f"dead prompt key {dead!r} still in market_data_ai"


class TestPostTradeContext:
    def test_post_trade_prompt_has_entry_context(self):
        from app.application.handlers.post_trade_analyst import (
            build_post_trade_prompt,
        )

        prompt = build_post_trade_prompt(
            symbol="NIFTY",
            entry_price=100.0,
            exit_price=105.0,
            side="LONG",
            pnl=5.0,
            hold_time_seconds=60.0,
            close_reason="TAKE_PROFIT",
            entry_context="State=Trending SessionVWAP=24000.00",
            exit_context="State=Trending SessionVWAP=24050.00 Price=105.00",
        )
        assert "[Entry Context] State=Trending" in prompt
        assert "[Market at Close] State=Trending SessionVWAP=24050.00" in prompt
        assert "Not recorded" not in prompt

    def test_on_position_closed_passes_entry_and_exit_context(self):
        from decimal import Decimal

        from app.application.services.exit_coordinator import ExitCoordinator
        from app.application.services.session_state_manager import (
            SessionStateManager,
        )
        from quant.contracts.entities import Position
        from quant.contracts.enums import PositionStatus, Side, Source

        class FakePostTrade:
            def __init__(self):
                self.calls = []

            def analyze(self, **kwargs):
                self.calls.append(kwargs)

        class FakeExitEngine:
            def get_position_metrics(self, *_args, **_kwargs):
                return {"tick_count": 5, "mfe": 2.0, "mae": 1.0}

        class FakeLifecycle:
            exit_engine = FakeExitEngine()

        class FakeLogger:
            def log_exit(self, **_kwargs):
                pass

            def log_partial_exit(self, **_kwargs):
                pass

        class FakeOverseer:
            def reset_position_state(self):
                pass

        class FakeRiskManager:
            value = "NORMAL"
            stop_loss_pct = 0.02
            session_pnl = 0.0
            consecutive_wins = 0
            consecutive_losses = 0
            risk_tier = SimpleNamespace(value="NORMAL")
            trade_count = 0

            def record_trade(self, _pnl: float):
                pass

        class FakeRiskCoordinator:
            def get_session_risk_manager(self, _symbol: str):
                return FakeRiskManager()

            def persist_risk_state(self, _symbol: str):
                pass

        class FakeStorage:
            def delete_open_position(self, _position_id: str):
                pass

        class FakeLLM:
            def record_successful_exit(self, **_kwargs):
                pass

            def record_stop_out(self, *_args, **_kwargs):
                pass

        class FakeBroker:
            def cancel_order(self, *_args, **_kwargs):
                pass

        class FakeLearning:
            def learn(self, _position):
                pass

        post = FakePostTrade()
        ec = ExitCoordinator(
            broker=FakeBroker(),
            lifecycle_handler=FakeLifecycle(),
            event_logger=FakeLogger(),
            overseer_handler=FakeOverseer(),
            state_manager=SessionStateManager(),
            storage=FakeStorage(),
            llm_handler=FakeLLM(),
            risk_coordinator=FakeRiskCoordinator(),
            post_trade_analyst=post,
        )
        session = ec._state_manager.get_or_create_session("NIFTY")
        session.learning = FakeLearning()
        session.last_amt = {"marketState": "Trending", "sessionVwap": 24050.0}
        pos = Position(
            id="p1",
            symbol="NIFTY",
            side=Side.LONG,
            source=Source.LLM,
            entry_price=Decimal("100"),
            size=Decimal("1"),
            stop_loss=Decimal("95"),
            take_profit=Decimal("110"),
            entry_time="2026-01-01T09:00:00Z",
            exit_time="2026-01-01T10:00:00Z",
            status=PositionStatus.CLOSED,
            pnl=Decimal("12.5"),
            metadata={"market_state_model": "Trending", "tick_trace_id": "t1"},
        )
        session.portfolio.positions.append(pos)

        ec.on_position_closed("NIFTY", pos, session=session)

        assert len(post.calls) == 1
        kwargs = post.calls[0]
        assert "Trending" in kwargs["entry_context"]
        assert "Trending" in kwargs["exit_context"]
        assert "24050.00" in kwargs["entry_context"]
        assert "24050.00" in kwargs["exit_context"]
        assert "Not recorded" not in kwargs["entry_context"]


class TestDecisionConsistency:
    def test_worker_does_not_refresh_prompt_fields(self):
        src = inspect.getsource(LLMEntryHandler)
        assert "_latest_amt" not in src, "hot-refresh block must be removed"
        assert "deltaNormalizedOption" not in src, (
            "dead delta write must be removed"
        )

    def test_worker_uses_enqueue_time_data_not_last_amt(self):
        handler, gen = _handler()
        gen.analyze_market.return_value = {
            "direction": "FLAT",
            "confidence": "Low",
            "rationale": "test",
            "market_state": "Balanced",
        }
        with patch.object(handler, "_process_build_signal", return_value=False):
            session = _session_stub()
            # Simulate a NEWER AMT result landing on the session while the
            # worker is still queued — the LLM must see the enqueue-time data.
            session.last_amt = {
                "aggression": 1.9,
                "cvdSlope": 99.0,
                "ofi": 0.9,
                "deltaNormalizedOption": 0.8,
                "marketState": "IMBALANCE",
            }
            amt = _amt()
            md, _ = _build_md(handler, session, amt)
            symbol = "NIFTY 30 JAN 24000 CALL"
            q = queue.Queue()
            handler._llm_queues[symbol] = q
            item = {
                "session": session,
                "symbol": symbol,
                "tick": _tick(),
                "amt_result": amt,
                "market_data_ai": md,
                "setup_type": SetupType.MEAN_REVERSION,
                "session_info": _session_info(),
                "strategy_hint": "hint",
                "profile_shape_str": "D",
                "market_state_str": "Balanced",
                "enqueue_time": time.time(),
            }
            q.put_nowait(item)
            t = threading.Thread(
                target=handler._llm_worker_loop, args=(symbol,), daemon=True
            )
            t.start()
            deadline = time.time() + 10
            while time.time() < deadline and not gen.analyze_market.called:
                time.sleep(0.01)
            q.put_nowait(None)
            t.join(timeout=10)

        assert gen.analyze_market.called
        called_md = gen.analyze_market.call_args[0][0]
        assert called_md["aggression"] == 0.6
        assert called_md["cvd_slope"] == 4.0
        assert called_md["market_state"] == "Balanced"
        assert called_md["ltp"] == 24020.0  # enqueue-time tick, not refreshed
