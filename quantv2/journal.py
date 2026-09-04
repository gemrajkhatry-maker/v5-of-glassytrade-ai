from __future__ import annotations
import json
from dataclasses import asdict, is_dataclass

class Journal:
    def __init__(self, path: str) -> None:
        self.path = path

    def _write(self, record: dict) -> None:
        with open(self.path, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def log_decision(self, symbol: str, decision) -> None:
        self._write({"kind": "decision", "symbol": symbol, "reason": decision.reason, "approved": decision.approved})

    def log_fill(self, symbol: str, fill) -> None:
        self._write({"kind": "fill", "symbol": symbol, **{k: getattr(fill, k) for k in ("pid", "qty", "price", "pnl", "reason")}})

    def lines(self) -> list[str]:
        try:
            with open(self.path) as f:
                return [ln.strip() for ln in f if ln.strip()]
        except OSError:
            return []