"""Smoke test: load the copied LFM2.5-2.6B-MLX-8bit + nifty_amt_lora adapter and generate on representative prompts."""
import json
import os
import sys
import time

MODEL_PATH = "models/lfm2.5-2.6b-mlx-8bit"
ADAPTER_PATH = "models/lfm2.5-nifty-amt-lora"

SYSTEM = (
    "You are an AMT scalping assistant for Indian markets (NIFTY/BankNifty). "
    "Think like Fabio Valentini. For each setup, reason through: market state, session phase, "
    "auction type, confirmation, risk-reward. Output ONLY valid JSON on a single line, no other text. "
    'Format example: {"direction": "LONG", "confidence": "High", "setup": "TRIPLE_A", "rationale": "one sentence"}.'
)

CASES = [
    "session: nse\nprofile_shape: P\nnote: P-shape: late buyers, potential exhaustion",
    "session: nse\ntime: 10:30\nphase: PRIME_MORNING\nstate: IMBALANCED\nsymbol: NIFTY\nin_trade: yes\ndirection: LONG\npnl_pts: +12\nstop_pts: +20\ncvd_slope: +1800\nnote: In profit 12pts, CVD slope >1500. Move stop to breakeven.",
    "session: nse\ntime: 14:45\nphase: POWER_HOUR\nstate: BALANCED\nsymbol: NIFTY\nprofile_shape: D\nnote: D-shape balanced rotation, no edge",
    "session: nse\ntime: 11:15\nphase: PRIME_MORNING\nstate: IMBALANCED\nsymbol: BANKNIFTY\nprofile_shape: b\ncvd_slope: -2500\nnote: b-shape below VWAP, CVD falling hard",
]

def main() -> int:
    if not os.path.isdir(MODEL_PATH):
        print(f"FATAL: model dir missing: {MODEL_PATH}", file=sys.stderr)
        return 1
    if not os.path.isfile(os.path.join(ADAPTER_PATH, "adapters.safetensors")):
        print(f"FATAL: adapter missing: {ADAPTER_PATH}", file=sys.stderr)
        return 1

    from pathlib import Path

    from mlx_lm import load, generate
    from mlx_lm.sample_utils import make_sampler
    from mlx_lm.utils import load_config

    cfg = load_config(Path(MODEL_PATH))
    print(f"model config: {cfg.get('model_type')} vocab={cfg.get('vocab_size')}", flush=True)

    t0 = time.time()
    model, tokenizer = load(MODEL_PATH, adapter_path=ADAPTER_PATH)
    print(f"loaded model+adapter in {time.time() - t0:.1f}s", flush=True)

    ok = 0
    for i, case in enumerate(CASES, 1):
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": case},
        ]
        prompt = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        # Prime with "{ " to force JSON output (same trick the POC eval uses).
        prime = "{ "
        t1 = time.time()
        out = generate(
            model, tokenizer, prompt=prompt + prime, max_tokens=120,
            sampler=make_sampler(temp=0.3),
        )
        dt = time.time() - t1
        full = prime + out
        parsed = None
        try:
            parsed = json.loads(full)
        except Exception:
            pass
        valid = "VALID-JSON" if parsed else "RAW"
        if parsed:
            ok += 1
        print(f"\n--- case {i} [{valid}] ({dt:.1f}s) ---")
        print(f"input : {case.splitlines()[0]} ...")
        print(f"output: {full.strip()[:400]}")

    print(f"\n== {ok}/{len(CASES)} valid JSON ==")
    return 0 if ok == len(CASES) else 2

if __name__ == "__main__":
    sys.exit(main())
