"""Application services for AI endpoints.

The natural-language command/reply overlay (NL command parsing and its
keyword tables) was removed as out-of-scope: it was dead code with no
frontend caller or tests. The LLM remains advisory-only (entry journal +
overseer) via analyze_market / get_decision_history / journal endpoints.
"""

from __future__ import annotations

from app.core.async_boundary import ensure_sync_adapter_result


class AiCommandService:
    """Use-case service for AI analysis, decision history, and journal endpoints."""

    def analyze_market(self, service, req_data: dict) -> dict:
        analysis = service.analyze_market(req_data)
        return {
            "direction": analysis["direction"],
            "rationale": analysis["rationale"],
            "raw_output": analysis.get("raw_output", ""),
        }

    def get_decision_history(self, storage, active_symbols: list[str], start: str | None, end: str | None, limit: int) -> dict:
        safe_limit = min(limit, 200)
        llm_rows = ensure_sync_adapter_result(
            "storage.query_llm_decisions",
            storage.query_llm_decisions,
            start=start,
            end=end,
            symbols=active_symbols if active_symbols else None,
        )
        if len(llm_rows) > safe_limit:
            llm_rows = llm_rows[-safe_limit:]

        signal_rows = ensure_sync_adapter_result(
            "storage.query_signal_decisions",
            storage.query_signal_decisions,
            symbol=active_symbols[0] if active_symbols else None,
            limit=safe_limit,
        )
        return {"decisions": llm_rows, "signal_decisions": signal_rows}

    def get_journal_endpoint(self, journal, date: str | None, run_id: str | None, action: str):
        if action == "entries":
            return {"entries": journal.read_entries(date, run_id=run_id)}
        if action == "trades":
            return {"trades": journal.get_completed_trades(date, run_id=run_id)}
        if action == "summary":
            return journal.summary(date, run_id=run_id)
        if action == "compare":
            return journal.compare_runs(start_date=date, end_date=date, run_ids=run_id)
        if action == "promotion":
            raise NotImplementedError("Promotion action requires explicit criteria")

        raise ValueError("Unknown action")

    def get_promotion(self, journal, **kwargs) -> dict:
        return journal.assess_promotion(**kwargs)
