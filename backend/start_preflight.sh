#!/usr/bin/env bash
set -euo pipefail

# Startup preflight guard for backend launch.
# Produces explicit error categories for machine parsing.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$SCRIPT_DIR/venv/bin/python}"
BACKEND_ROOT="$SCRIPT_DIR"

if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="python3"
fi

"$PYTHON_BIN" - "$BACKEND_ROOT" <<'PY'
from __future__ import annotations

import json
import os
import py_compile
import shutil
from pathlib import Path
import re
import sys

project_root = Path(sys.argv[1]).resolve().parent.parent
backend_root = Path(sys.argv[1]).resolve()
errors = []
warnings = []


def add_error(category: str, message: str, file: str | None = None, line: int | None = None) -> None:
    entry = {"category": category, "message": message, "status": "FAIL"}
    if file is not None:
        entry["file"] = file
    if line is not None:
        entry["line"] = line
    errors.append(entry)


def add_warning(category: str, message: str, details: dict[str, object] | None = None) -> None:
    entry = {"category": category, "message": message, "status": "WARN"}
    if details:
        entry.update(details)
    warnings.append(entry)


def check_syntax() -> None:
    files = []
    for path in sorted(backend_root.rglob("*.py")):
        if ".venv" in path.parts or "__pycache__" in path.parts or "/.git/" in str(path):
            continue
        files.append(path)
        try:
            py_compile.compile(str(path), doraise=True)
        except (SyntaxError, ValueError) as exc:  # noqa: PERF203
            add_error(
                "syntax",
                str(exc),
                file=str(path),
                line=getattr(exc, "lineno", None),
            )

    if not files:
        add_warning(
            "syntax",
            "No backend Python files discovered for syntax check",
            {"count": 0},
        )


def resolve_mode_config() -> None:
    env = (os.getenv("GLASSYTRADE_ENV", "paper") or "").strip()
    if not env:
        add_error("env", "GLASSYTRADE_ENV is empty")
    strategy = (os.getenv("GLASSYTRADE_STRATEGY", "mcx_options") or "").strip()
    if not strategy:
        add_error("env", "GLASSYTRADE_STRATEGY is empty")

    try:
        from config.mode_config import ModeConfigLoader

        mode = ModeConfigLoader.load_from_env()
        if not getattr(mode, "strategy", ""):
            add_error("config", "ModeConfigLoader returned empty strategy")
        symbols = mode.active_symbols or []
        if not symbols:
            add_warning("config", "No active symbols found in mode config", {"strategy": strategy})

        # Persist resolved values for downstream launch parity.
        os.environ["GLASSYTRADE_ENV"] = mode.environment
        os.environ["GLASSYTRADE_STRATEGY"] = mode.strategy
    except Exception as exc:
        add_error("config", f"ModeConfigLoader.load_from_env failed: {exc}")


def validate_runtime_env() -> None:
    strategy = (os.getenv("GLASSYTRADE_STRATEGY", "") or "").strip()
    env = (os.getenv("GLASSYTRADE_ENV", "paper") or "").strip()

    # Broker/API credentials
    required_broker = [
        "DHAN_CLIENT_ID",
        "DHAN_ACCESS_TOKEN",
        "DHAN_API_KEY",
        "DHAN_API_SECRET",
    ]
    missing = [k for k in required_broker if not os.getenv(k)]
    if env == "live":
        for key in missing:
            add_error("credential", f"Missing required env var for live mode: {key}")
        if missing:
            add_error("credential", "Live mode requires all DHAN credentials")
    elif missing:
        add_warning("credential", "Missing DHAN credentials (paper mode)", {"missing": missing})

    # LLM policy
    fallback_enabled = (os.getenv("LLM_CLOUD_FALLBACK_ENABLED", "0") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if not fallback_enabled:
        model_path = (os.getenv("MLX_MODEL_PATH", "") or "").strip()
        if not model_path:
            if env == "live":
                add_error(
                    "llm",
                    "Live mode requires either MLX_MODEL_PATH or LLM_CLOUD_FALLBACK_ENABLED=1",
                )
            else:
                add_warning(
                    "llm",
                    "No local MLX model path configured; runtime may start in degraded LLM mode",
                )

    # Tooling
    if not shutil.which("uvicorn"):
        add_error("runtime", "uvicorn not found on PATH")


def main() -> int:
    check_syntax()
    resolve_mode_config()
    validate_runtime_env()

    summary = {
        "errors": len(errors),
        "warnings": len(warnings),
        "status": "failed" if errors else "passed",
        "checks": errors + warnings,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
PY
