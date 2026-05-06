"""Session-level orchestration helpers."""

from __future__ import annotations

from app.domain.constants import AGENT_DECISION_THRESHOLD
from app.application.services.session_runtime_contracts import (
    EntryDecisionContract,
    LLMTriggerContract,
    TickTraceContract,
)


class SessionOrchestrator:
    """Small orchestration helpers for session decisioning."""

    @staticmethod
    def build_tick_trace_id(
        symbol: str,
        tick_time: str,
        sequence: int,
        trace_token: str = "",
    ) -> str:
        """Build a deterministic tick ingress trace identifier."""
        if trace_token:
            return f"{symbol}|{tick_time}|{sequence}|{trace_token}"
        return f"{symbol}|{tick_time}|{sequence}"

    @staticmethod
    def build_tick_trace_contract(
        symbol: str, tick_time: str, sequence: int, trace_token: str = ""
    ) -> TickTraceContract:
        """Build tick ingress contract consumed by runtime pipeline."""
        trace_id = SessionOrchestrator.build_tick_trace_id(
            symbol=symbol,
            tick_time=tick_time,
            sequence=sequence,
            trace_token=trace_token,
        )
        return TickTraceContract(
            trace_id=trace_id,
            sequence=sequence,
            symbol=symbol,
            tick_time=tick_time,
        )

    @staticmethod
    def collect_stacked_imbalances(fp_domain) -> list:
        """Collect currently stacked imbalance levels from footprint domain."""
        imbalances = []
        if not fp_domain:
            return imbalances
        try:
            latest_fp = list(fp_domain.values())[-1] if fp_domain else None
            if latest_fp and hasattr(latest_fp, "levels"):
                imbalances = [
                    lv for lv in latest_fp.levels if getattr(lv, "stacked", False)
                ]
        except Exception:
            pass
        return imbalances

    @staticmethod
    def compute_priority_score(agent_decision, amt_result, cache_data, detect_squeeze_fn) -> float:
        """Compute UI-facing priority score from decision, AMT features, and squeeze signal."""
        score = 0.0
        if agent_decision and agent_decision.direction != "FLAT":
            score += agent_decision.probability * 10

        if (
            getattr(amt_result, "cvd_slope", 0) > 0.4
            or getattr(amt_result, "cvd_slope", 0) < -0.4
        ):
            score += 2.0

        if detect_squeeze_fn is not None:
            if detect_squeeze_fn(cache_data, amt_result):
                score += 3.0
        return score

    @staticmethod
    def update_pending_decision(cache, trading_enabled: bool, agent_decision, amt_result, tick) -> None:
        """Persist best non-flat decision for the next candle, or clear when disabled."""
        if trading_enabled and agent_decision and agent_decision.direction != "FLAT" and (
            agent_decision.probability >= AGENT_DECISION_THRESHOLD
        ):
            cache.set_pending_decision(agent_decision, amt_result, tick)
        elif not trading_enabled:
            cache.clear_pending_decision()

    @staticmethod
    def resolve_entry_decision(
        agent_decision,
        cache,
        _is_new_candle: bool,
        has_position: bool,
        in_cooldown: bool,
        allow_short: bool = False,
        trading_enabled: bool = True,
    ) -> EntryDecisionContract:
        """Resolve whether a new entry should be attempted for current tick.

        Returns:
            EntryDecisionContract with resolved execution intent.
        """
        _exec_decision = None
        _exec_amt = None
        _exec_tick = None

        if (
            agent_decision
            and agent_decision.direction != "FLAT"
            and agent_decision.probability >= AGENT_DECISION_THRESHOLD
        ):
            _exec_decision = agent_decision

        pending_decision, pending_amt, pending_tick = cache.get_pending_decision()
        if _exec_decision is None and pending_decision:
            if (
                pending_decision.direction != "FLAT"
                and pending_decision.probability >= AGENT_DECISION_THRESHOLD
            ):
                _exec_decision = pending_decision
                _exec_amt = pending_amt
                _exec_tick = pending_tick

        if not trading_enabled:
            _exec_decision = None
            _exec_amt = None
            _exec_tick = None
            _exec_prob = 0
            _exec_dir = "NONE"
        else:
            _exec_dir = (
                getattr(_exec_decision, "direction", "NONE")
                if _exec_decision
                else "NONE"
            )
            _exec_prob = (
                getattr(_exec_decision, "probability", 0)
                if _exec_decision
                else 0
            )

        run_entry = (
            not has_position
            and not in_cooldown
            and _exec_decision is not None
            and _exec_dir in ("LONG", "SHORT")
            and (_exec_dir != "SHORT" or allow_short)
            and _exec_prob >= AGENT_DECISION_THRESHOLD
        )
        return EntryDecisionContract(
            exec_decision=_exec_decision,
            exec_amt=_exec_amt,
            exec_tick=_exec_tick,
            exec_dir=_exec_dir,
            exec_prob=_exec_prob,
            run_entry=run_entry,
        )

    @staticmethod
    def should_trigger_llm(
        should_trigger_llm_fn,
        session,
        has_position: bool,
        ai_running: bool,
        in_cooldown: bool,
        amt_result,
        event,
        ai_time,
        trading_enabled: bool = True,
    ) -> bool:
        """Delegate LLM trigger decision with explicit guard."""
        if not trading_enabled or should_trigger_llm_fn is None:
            return False
        return bool(
            should_trigger_llm_fn(
                session,
                has_position,
                ai_running,
                in_cooldown,
                amt_result,
                event,
                ai_time,
            )
        )

    @staticmethod
    def should_monitor_llm(market_state: str, last_trigger_ts: float, now_ts: float, interval_seconds: float = 300.0) -> bool:
        """Determine if monitoring-mode LLM should fire on market state cadence."""
        if market_state not in ("BALANCED", "IMBALANCED"):
            return False
        return (now_ts - last_trigger_ts) > interval_seconds

    @staticmethod
    def resolve_llm_triggers(
        should_trigger_llm_fn,
        session,
        has_position: bool,
        ai_running: bool,
        in_cooldown: bool,
        amt_result,
        event,
        ai_time,
        market_state: str,
        last_monitoring_llm: float,
        now_ts: float,
        monitoring_interval: float = 300.0,
        trading_enabled: bool = True,
    ) -> LLMTriggerContract:
        """Resolve LLM trigger decisions into a single contract."""
        trigger_llm = (
            trading_enabled
            and SessionOrchestrator.should_trigger_llm(
                should_trigger_llm_fn=should_trigger_llm_fn,
                session=session,
                has_position=has_position,
                ai_running=ai_running,
                in_cooldown=in_cooldown,
                amt_result=amt_result,
                event=event,
                ai_time=ai_time,
                trading_enabled=trading_enabled,
            )
        )
        monitoring_trigger = (
            trading_enabled
            and SessionOrchestrator.should_monitor_llm(
                market_state=market_state,
                last_trigger_ts=last_monitoring_llm,
                now_ts=now_ts,
                interval_seconds=monitoring_interval,
            )
        )
        return LLMTriggerContract(trigger_llm=trigger_llm, monitoring_trigger=monitoring_trigger)
