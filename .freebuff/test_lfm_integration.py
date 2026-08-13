"""Integration test: run the LFM2.5 + nifty_amt_lora adapter through the app's real
MLXInferenceAdapter.predict() -> parse_entry_response() path, exactly as the engine
calls it at bar close.

Env is set BEFORE imports so _load_env_file (no-override) keeps our paths.
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

os.environ["MLX_MODEL_PATH"] = "models/lfm2.5-2.6b-mlx-8bit"
os.environ["MLX_ADAPTER_PATH"] = "models/lfm2.5-nifty-amt-lora"
os.environ["LLM_CLOUD_FALLBACK_ENABLED"] = "false"
os.environ["MLX_DEFER_LOADING"] = "0"

from quant.inference.mlx_inference_adapter import MLXInferenceAdapter  # noqa: E402
from quant.inference.prompt_builder import build_entry_prompt, parse_entry_response  # noqa: E402
from quant.runtime import QuantEngine  # noqa: E402


class VP:
    poc = 3344.86
    vah = 3498.78
    val = 2997.64


class VW:
    value = 3278.83
    upper_2 = 3282.11
    lower_2 = 3275.55


class OF:
    cvd = -210.5
    cvd_slope = -145.0
    cvd_divergence = False
    delta = -17.0


class ABS:
    side = "SELL"
    level = 3340.5
    age = 0


class ST:
    time = "17:20"
    close = 3282.5
    volume_profile = VP()
    vwap = VW()
    order_flow = OF()
    absorption = ABS()
    triple_a_signal = "SELL_ABSORPTION"
    triple_a_phase = "WAITING"


class BAR:
    time = "17:20"
    open = 3281.0
    high = 3283.2
    low = 3280.1
    close = 3282.5
    volume = 231


AMT_DTO = {
    "poc": 3344.86, "valueAreaHigh": 3498.78, "valueAreaLow": 2997.64,
    "marketState": "IMBALANCED", "aggression": 0.72,
    "sessionVwap": 3278.83, "vwapUpper2": 3282.11, "vwapLower2": 3275.55,
    "ibHigh": 3374.0, "ibLow": 3269.0, "ibComplete": True,
    "breakDirection": "DOWN", "breakType": "INITIATIVE", "breakLevel": 3337.0,
    "marketStructure": "BEARISH", "profileShape": "D",
    "acceptanceAbove": False, "acceptanceBelow": True,
    "rejectionAtHigh": False, "rejectionAtLow": True,
    "isSecondDrive": False, "lvnPlay": None, "lvns": [],
    "priorPoc": 3400.0, "priorVah": 3450.0, "priorVal": 3350.0,
    "gapType": "", "openingBias": "BEARISH",
    "cvdSlope": -145.0,
}


def main() -> int:
    st = ST()
    bar = BAR()

    # Instruction: exactly what QuantEngine._llm_instruction builds.
    instruction = build_entry_prompt({
        "symbol": "GOLDM 28 AUG 150500 CALL",
        "time": st.time,
        "ltp": st.close,
        "poc": AMT_DTO["poc"], "vah": AMT_DTO["valueAreaHigh"], "val": AMT_DTO["valueAreaLow"],
        "market_state": "IMBALANCED", "aggression": 0.72,
        "cvd": OF.cvd, "cvd_slope": -145.0, "cvd_divergence": False,
        "delta": OF.delta, "vwap": VW.value,
        "session_vwap": 3278.83, "vwap_upper_2": 3282.11, "vwap_lower_2": 3275.55,
        "ib_high": 3374.0, "ib_low": 3269.0, "ib_complete": True,
        "break_direction": "DOWN", "break_type": "INITIATIVE", "break_level": 3337.0,
        "absorption_side": "SELL",
        "market_structure": "BEARISH", "profile_shape": "D",
        "acceptance_above": False, "acceptance_below": True,
        "rejection_at_high": False, "rejection_at_low": True,
        "is_second_drive": False, "lvn_play": None, "lvns": [],
        "prior_poc": 3400.0, "prior_vah": 3450.0, "prior_val": 3350.0,
        "gap_type": "", "opening_bias": "BEARISH",
        "option_type": "CALL",
    }, allow_short=True)

    input_text = QuantEngine._llm_input(st, bar)

    print("=== instruction (first 500 chars) ===")
    print(instruction[:500])
    print("\n=== input_text ===")
    print(input_text)

    print("\n=== predict() through the real app path ===")
    adapter = MLXInferenceAdapter(temperature=0.3, max_new_tokens=256)
    t0 = time.time()
    raw = adapter.predict(instruction, input_text)
    dt = time.time() - t0
    print(f"[{dt:.1f}s] raw: {raw[:600]}")

    decision = parse_entry_response(raw)
    print("\n=== parsed decision ===")
    print(json.dumps(decision, indent=2))

    direction = str(decision.get("direction", "")).upper()
    print(f"\nDIRECTION={direction}  (expected SHORT for SELL absorption + DOWN break)")
    ok = direction in ("SHORT", "FLAT")
    print(f"RESULT: {'PASS' if ok else 'CHECK'}")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
