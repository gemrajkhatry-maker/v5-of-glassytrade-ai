#!/usr/bin/env python3
"""Load fused Gemma4 MLX weights and run one tiny generation (project venv)."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Repo layout: backend/scripts/this_file.py
REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
MODEL_DIR = REPO / "gemma4_26b_fused_production"

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
for p in (str(REPO), str(BACKEND)):
    if p not in sys.path:
        sys.path.insert(0, p)


def main() -> int:
    if not MODEL_DIR.is_dir():
        print(f"FAIL: model dir missing: {MODEL_DIR}", file=sys.stderr)
        return 1

    t0 = time.time()
    print(f"MODEL_DIR={MODEL_DIR}")
    from app.infrastructure.transformers_quiet import quiet_gemma4_tokenizer_config_warning

    quiet_gemma4_tokenizer_config_warning()
    print("Importing mlx_lm...")
    from mlx_lm import generate, load

    print("Loading weights (first load can take several minutes)...")
    t_load = time.time()
    model, tokenizer = load(str(MODEL_DIR))
    print(f"Load finished in {time.time() - t_load:.1f}s")

    messages = [{"role": "user", "content": "Reply with exactly the two letters OK and nothing else."}]
    if hasattr(tokenizer, "apply_chat_template"):
        prompt = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
    else:
        prompt = "Reply with exactly: OK\n"
    print("Running generate(max_tokens=16)...")
    t_gen = time.time()
    out = generate(
        model,
        tokenizer,
        prompt=prompt,
        max_tokens=16,
        verbose=False,
    )
    print(f"Generate finished in {time.time() - t_gen:.1f}s")
    text = (out or "").strip()
    print(f"OUTPUT: {text!r}")
    print(f"TOTAL wall {time.time() - t0:.1f}s")
    if not text:
        print("FAIL: empty generation", file=sys.stderr)
        return 2
    print("OK: local MLX inference ran")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
