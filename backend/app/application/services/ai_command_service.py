"""Application services for AI endpoints."""

from __future__ import annotations


_SYMBOL_KEYWORDS = {
    "nifty": "NIFTY",
    "banknifty": "BANKNIFTY",
    "finnifty": "FINNIFTY",
    "crude": "CRUDEOIL",
    "crudeoil": "CRUDEOIL",
    "natural gas": "NATURALGAS",
    "gold": "GOLD",
    "silver": "SILVER",
}

_INTERVAL_KEYWORDS = {
    "15m": "15m",
    "1m": "1m",
    "5m": "5m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
}

_COLOR_KEYWORDS = {
    "red": "#ef4444",
    "green": "#10b981",
    "blue": "#3b82f6",
    "purple": "#8b5cf6",
    "cyan": "#06b6d4",
    "amber": "#f59e0b",
    "neon": "#39ff14",
    "pink": "#ec4899",
    "white": "#ffffff",
}


class AiCommandService:
    """Use-case service for NL command parsing and command-driven actions."""

    def parse_market_command(self, prompt: str) -> dict:
        text = prompt.lower().strip()
        config_updates: dict[str, object] = {}
        messages: list[str] = []

        for kw, sym in _SYMBOL_KEYWORDS.items():
            if kw in text:
                config_updates["symbol"] = sym
                messages.append(f"Switched to {sym}")
                break

        for kw, interval in _INTERVAL_KEYWORDS.items():
            if kw in text:
                config_updates["interval"] = interval
                messages.append(f"Interval set to {interval}")
                break

        if "bull" in text:
            for kw, color in _COLOR_KEYWORDS.items():
                if kw in text:
                    config_updates["bullColor"] = color
                    messages.append(f"Bull color set to {kw}")
                    break

        if "bear" in text:
            for kw, color in _COLOR_KEYWORDS.items():
                if kw in text:
                    config_updates["bearColor"] = color
                    messages.append(f"Bear color set to {kw}")
                    break

        if "volume profile" in text:
            if "off" in text or "hide" in text:
                config_updates["showVolumeProfile"] = False
                config_updates["vpMode"] = "off"
                messages.append("Volume profile hidden")
            else:
                config_updates["showVolumeProfile"] = True
                config_updates["vpMode"] = "session"
                messages.append("Volume profile enabled")

        if "predictions" in text or "ghost" in text:
            show = "off" not in text and "hide" not in text
            config_updates["showPredictions"] = show
            messages.append(f"Predictions {'shown' if show else 'hidden'}")

        if "footprint" in text:
            messages.append("Switch to footprint mode using the tab at top-left")

        if not messages:
            messages.append(
                f"I understood: \"{prompt}\". Try commands like 'show nifty', 'set interval 5m', or 'bull color cyan'."
            )

        return {
            "message": " | ".join(messages),
            "configUpdates": config_updates if config_updates else None,
            "action": "UPDATE_CONFIG" if config_updates else None,
        }

    def analyze_market(self, service, req_data: dict) -> dict:
        analysis = service.analyze_market(req_data)
        return {
            "direction": analysis["direction"],
            "rationale": analysis["rationale"],
            "raw_output": analysis.get("raw_output", ""),
        }

    def get_decision_history(self, storage, active_symbols: list[str], start: str | None, end: str | None, limit: int) -> dict:
        safe_limit = min(limit, 200)
        llm_rows = storage.query_llm_decisions(
            start=start, end=end, symbols=active_symbols if active_symbols else None
        )
        if len(llm_rows) > safe_limit:
            llm_rows = llm_rows[-safe_limit:]

        signal_rows = storage.query_signal_decisions(
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
