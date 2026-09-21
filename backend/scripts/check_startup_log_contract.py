#!/usr/bin/env python
"""Validate startup log tail for known async/runtime hazards."""

from __future__ import annotations

import os
import re
from collections import deque
from pathlib import Path


def _load_log_tail(path: Path, max_lines: int = 2000) -> str:
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        return "".join(deque(fh, maxlen=max_lines))


def _find_last_startup_window(log_text: str, marker: str) -> str:
    marker_index = log_text.rfind(marker)
    if marker_index != -1:
        return log_text[marker_index:]
    return log_text


def main() -> int:
    # Primary log is now backend/logs/backend.log (managed by RotatingFileHandler)
    log_path = Path(
        os.getenv("BACKEND_RUNTIME_LOG_PATH")
        or os.getenv("BACKEND_LOG_PATH")
        or (Path(__file__).resolve().parents[1] / "logs" / "backend.log")
    )
    if not log_path.exists():
        print(f"SKIP: startup log not found at {log_path}")
        return 0

    log_text = _load_log_tail(log_path, int(os.getenv("BACKEND_RUNTIME_LOG_TAIL_LINES", "2000")))
    log_text = _find_last_startup_window(
        log_text,
        os.getenv("BACKEND_STARTUP_LOG_MARKER", "Starting GlassyTrade AI application..."),
    )

    banned_patterns = (
        (r"RuntimeWarning: coroutine '.*' was never awaited", 0),
        (r"NameError: name 'count' is not defined", 0),
        (r"unraisable", re.IGNORECASE),
    )

    matches = []
    for pattern, flags in banned_patterns:
        if re.search(pattern, log_text, flags):
            matches.append(pattern)

    if matches:
        print("FAIL: startup log contract violated")
        for pattern in matches:
            print(f"  - {pattern}")
        return 1

    print(f"PASS: startup log contract clean ({log_path})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
