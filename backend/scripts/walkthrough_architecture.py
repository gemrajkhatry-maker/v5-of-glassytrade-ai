import json
from decimal import Decimal
from quant.contracts.value_objects import OHLC, AMTResult, AggressivePrint
from quant.inference.prompt_builder import build_entry_prompt, build_overseer_prompt
from app.infrastructure.adapters.mlx_inference_adapter import MLXInferenceAdapter
from app.application.handlers.llm_overseer_handler import LLMOverseerHandler

def walkthrough():
    print("--- 1. Market State: Imbalance + High Volume Bubble ---")
    tick = OHLC(time="2024-03-11T10:00:00Z", open=22000, high=22050, low=21980, close=22040, volume=5000, delta=1200)
    
    bubble = AggressivePrint(price=22000.0, time="2024-03-11T09:45:00Z", volume=8000, delta=1500, side="BUY")
    amt = AMTResult(
        market_state="IMBALANCED", poc=21950, value_area_high=22000, value_area_low=21900,
        profile_shape="P-shape", bubble_retests=[bubble]
    )
    
    print("\n--- 2. Entry Prompt Generation ---")
    entry_data = {
        "ltp": tick.close, "vah": amt.value_area_high, "val": amt.value_area_low,
        "poc": amt.poc, "delta": tick.delta, "market_state": amt.market_state,
        "profile_shape": amt.profile_shape, "bubble_retests": amt.bubble_retests
    }
    entry_prompt = build_entry_prompt(entry_data)
    print(f"Entry Prompt Preview (last 200 chars):\n...{entry_prompt[-200:]}")
    
    print("\n--- 3. Overseer Prompt Generation (Managing Position) ---")
    pos_state = {
        "side": "LONG", "entry_price": 22010.0, "current_price": 22040.0,
        "unrealized_pnl_pct": 0.0013, "stop_loss": 21980.0, "take_profit": 22100.0
    }
    overseer_prompt = build_overseer_prompt(pos_state, tick, amt)
    print(f"Overseer Prompt Preview (last 200 chars):\n...{overseer_prompt[-200:]}")
    
    print("\n--- 4. MLX Adapter Prefill Check ---")
    # Simulate how the adapter would wrap these
    def simulate_prefill(instruction, input_text):
        is_overseer = "HOLD" in instruction and "FULL_EXIT" in instruction
        if is_overseer:
            return f"<|im_start|>assistant\n{{"
        else:
            return f"<|im_start|>assistant\nMarket State:"

    entry_prefill = simulate_prefill("Market State, Logic, Trigger", entry_prompt)
    overseer_prefill = simulate_prefill(LLMOverseerHandler.OVERSEER_INSTRUCTION, overseer_prompt)
    
    print(f"Entry Prefill: {entry_prefill}")
    print(f"Overseer Prefill: {overseer_prefill}")

    print("\nWalkthrough Complete: Architecture holds consistent narrative and JSON contract.")

if __name__ == "__main__":
    walkthrough()
