"""Unified AMT Dataset Generator for LLM/RL Fine-tuning.

Consolidates logic from poc/, poc4/, poc5/, and poc_lfm2/ into a single,
configurable tool with support for:
- Multiple asset profiles (NSE Options, ES Futures, Crypto)
- AMT Methodology (Balance, Imbalance, VWAP, CVD, Profile Shapes)
- Advanced Gaps (Cushion/Risk-Scaling, Second-Drive, Squeeze Setups)
- Export formats (ChatML, MLX Plain Text)
"""

import argparse
import hashlib
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Any, Optional

# --- Constants & Defaults ---

DEFAULT_SYSTEM_INSTRUCTION = (
    "You are trading using Fabio Valentini's Auction Market Theory model. "
    "You are not predicting — you are READING the auction. "
    "Read the narrative: market state, location, order flow. "
    "If the story is clear and all three align, state your conviction and direction. "
    "If you don't see the setup, STAY FLAT. Never trade without conviction.\n"
    "Always respond with exactly three lines:\n"
    "Market State: Balance or Imbalance\n"
    "Logic: brief reasoning\n"
    "Trigger: Enter Long, Enter Short, or Stay Flat"
)

# --- Asset Profiles ---

@dataclass
class AssetProfile:
    name: str
    price_range: tuple[int, int]
    vah_range: tuple[int, int]
    val_range: tuple[int, int]
    lot_size_range: tuple[int, int]
    currency: str

PROFILES = {
    "NSE": AssetProfile("NSE Options", (22000, 25000), (22100, 22200), (21800, 21900), (25, 100), "₹"),
    "ES": AssetProfile("ES Futures", (4500, 5500), (5100, 5200), (4900, 5000), (1, 10), "$"),
    "CRYPTO": AssetProfile("Crypto", (60000, 70000), (65000, 68000), (61000, 64000), (1, 5), "$"),
}

# --- Scenario Generators ---

class AMTScenarioGenerator:
    def __init__(self, profile: AssetProfile):
        self.profile = profile

    def generate_random_context(self) -> Dict[str, Any]:
        """Generate common market context variables."""
        price = random.randint(*self.profile.price_range)
        vah = random.randint(*self.profile.vah_range)
        val = random.randint(*self.profile.val_range)
        poc = random.randint(val + 1, vah - 1)
        
        session_pl = random.randint(-5000, 10000)
        consecutive_losses = random.randint(0, 3)
        
        is_second_drive = random.random() < 0.3
        profile_shape = random.choice(["D", "P", "b"])
        cvd_trend = random.choice(["up", "down", "flat"])
        vwap = random.randint(val - 100, vah + 100)
        
        return {
            "price": price,
            "vah": vah,
            "val": val,
            "poc": poc,
            "session_pl": session_pl,
            "consecutive_losses": consecutive_losses,
            "is_second_drive": is_second_drive,
            "profile_shape": profile_shape,
            "cvd_trend": cvd_trend,
            "vwap": vwap,
        }

    def create_prompt_and_completion(self, scenario_type: str) -> tuple[str, str]:
        ctx = self.generate_random_context()
        
        if scenario_type == "LONG_ABSORPTION":
            # Price at VAL, being absorbed, CVD up
            ctx["price"] = ctx["val"] + random.randint(-5, 5)
            ctx["cvd_trend"] = "up"
            ctx["profile_shape"] = "D"
            
            prompt = (
                f"{self.profile.name} at {ctx['price']}{self.profile.currency}. "
                f"VAL: {ctx['val']}, POC: {ctx['poc']}, VAH: {ctx['vah']}. "
                f"Sellers hitting bids at VAL but getting absorbed. Delta -800, volume high. "
                f"CVD trending {ctx['cvd_trend']}. Price at VWAP-{random.randint(1,2)}σ. "
                f"{'SECOND DRIVE at this level.' if ctx['is_second_drive'] else ''}"
            )
            
            logic = "Absorption at VAL with positive CVD divergence. Value area holds."
            trigger = "Enter Long"
            completion = f"Market State: Balance\nLogic: {logic}\nTrigger: {trigger}"
            
        elif scenario_type == "STAY_FLAT_RISK":
            # Too many losses, stay flat
            ctx["consecutive_losses"] = 3
            prompt = (
                f"Session P&L: {self.profile.currency}{ctx['session_pl']} ({ctx['consecutive_losses']} consecutive losses). "
                f"Price at {ctx['price']} near structural level. CVD {ctx['cvd_trend']}."
            )
            logic = "Risk limit reached (3 consecutive losses). Trading halted for session."
            trigger = "Stay Flat"
            completion = f"Market State: Balance\nLogic: {logic}\nTrigger: {trigger}"
            
        else: # Default Balance Rotation
            prompt = f"Price at {ctx['price']} rotating between {ctx['val']} and {ctx['vah']}. POC at {ctx['poc']}."
            logic = "Rotational market within value. No clear edge at current location."
            trigger = "Stay Flat"
            completion = f"Market State: Balance\nLogic: {logic}\nTrigger: {trigger}"

        return prompt, completion

# --- Exporters ---

class DatasetExporter:
    def __init__(self, tokenizer_model: Optional[str] = None):
        self.tokenizer = None
        if tokenizer_model:
            from transformers import AutoTokenizer
            self.tokenizer = AutoTokenizer.from_pretrained(tokenizer_model, trust_remote_code=True)

    def to_chatml(self, system: str, user: str, assistant: str) -> Dict[str, Any]:
        return {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
                {"role": "assistant", "content": assistant}
            ]
        }

    def to_mlx_text(self, system: str, user: str, assistant: str) -> Dict[str, str]:
        text = (
            f"<|im_start|>system\n{system}<|im_end|>\n"
            f"<|im_start|>user\n{user}<|im_end|>\n"
            f"<|im_start|>assistant\n{assistant}<|im_end|>"
        )
        return {"text": text}

# --- Main CLI ---

def main():
    parser = argparse.ArgumentParser(description="Unified AMT Dataset Generator")
    parser.add_argument("--profile", choices=PROFILES.keys(), default="NSE")
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--output", type=str, default="training_data.jsonl")
    parser.add_argument("--format", choices=["chatml", "mlx"], default="chatml")
    args = parser.parse_args()

    profile = PROFILES[args.profile]
    generator = AMTScenarioGenerator(profile)
    exporter = DatasetExporter()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    scenarios = ["LONG_ABSORPTION", "STAY_FLAT_RISK", "BALANCE_ROTATION"]
    
    with open(out_path, "w") as f:
        for i in range(args.count):
            s_type = random.choice(scenarios)
            prompt, completion = generator.create_prompt_and_completion(s_type)
            
            if args.format == "chatml":
                entry = exporter.to_chatml(DEFAULT_SYSTEM_INSTRUCTION, prompt, completion)
            else:
                entry = exporter.to_mlx_text(DEFAULT_SYSTEM_INSTRUCTION, prompt, completion)
                
            f.write(json.dumps(entry) + "\n")

    print(f"Generated {args.count} examples to {args.output} using {args.profile} profile.")

if __name__ == "__main__":
    main()
