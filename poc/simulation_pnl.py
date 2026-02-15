import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer
import random

# Configuration
BASE_MODEL = "./models/Nanbeige4.1-3B"
ADAPTER_PATH = "./lora_adapter_mac"
NUM_SCENARIOS = 10
RISK_PER_TRADE = 1000  # $1000 risk
REWARD_RATIO = 3       # 1:3 Risk:Reward on winning setups

def load_model():
    print(f"Loading base model from {BASE_MODEL}...")
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    base_model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        torch_dtype=torch.float16,
        device_map=device,
        trust_remote_code=True
    )
    
    print(f"Loading LoRA adapter from {ADAPTER_PATH}...")
    model = PeftModel.from_pretrained(base_model, ADAPTER_PATH)
    model.eval()
    return model, tokenizer, device

def generate_scenario_with_outcome():
    """
    Generates a market scenario and its future outcome (Win/Loss if taken).
    Returns: (instruction, input_text, optimal_action, outcome_pnl)
    """
    scenarios = [
        # SCENARIO 1: AAA Setup (Success)
        {
            "input": "Price is testing Value Area Low (VAL). Sellers are aggressive (-800 Delta) but price is absorbing (not moving down). Big buy orders hitting the bid.",
            "type": "AAA Setup",
            "optimal_action": "Long",
            "outcome_pnl": RISK_PER_TRADE * REWARD_RATIO  # +$3000
        },
        # SCENARIO 2: Momentum Breakout (Success)
        {
            "input": "Price broke VAH/Session High with strong +1500 Delta. Aggressive buyers lifting the offer. Retracement to protection level holding.",
            "type": "Momentum",
            "optimal_action": "Long",
            "outcome_pnl": RISK_PER_TRADE * REWARD_RATIO  # +$3000
        },
        # SCENARIO 3: Failed Auction (Success)
        {
            "input": "Price broke VAH but stalled immediately. Delta +2000 but price ticked down. Buyers trapped at highs.",
            "type": "Failed Auction",
            "optimal_action": "Short",
            "outcome_pnl": RISK_PER_TRADE * REWARD_RATIO  # +$3000
        },
        # SCENARIO 4: Chop/No Trade (Success if Flat)
        {
            "input": "Price is stuck inside yesterday's Value Area. Volume is low using Low Volume Nodes. No clear Delta divergence.",
            "type": "Chop",
            "optimal_action": "Flat",
            "outcome_pnl": 0  # $0 (Saved capital)
        },
        # SCENARIO 5: Trap (Loss if taken blindly)
        {
            "input": "Price is breaking VAH but volume is extremely low. No aggressive buying seen. Passive sellers stacking offers.",
            "type": "Fake Breakout",
            "optimal_action": "Short",  # Or Flat
            "outcome_pnl": -RISK_PER_TRADE # -$1000 if Long
        }
    ]
    
    scenario = random.choice(scenarios)
    return scenario

def get_model_decision(model, tokenizer, device, input_text):
    instruction = "Analyze the trading scenario based on Fabio Valentini's methodology (Orderflow, Auction Market Theory). Provide a Trigger: Enter Long, Enter Short, or Stay Flat."
    
    alpaca_prompt = """Below is an instruction that describes a task, paired with an input that provides further context. Write a response that appropriately completes the request.

### Instruction:
{}

### Input:
{}

### Response:
"""
    prompt = alpaca_prompt.format(instruction, input_text)
    inputs = tokenizer(prompt, return_tensors="pt").to(device)
    
    with torch.no_grad():
        outputs = model.generate(
            **inputs, 
            max_new_tokens=128, 
            use_cache=True,
            temperature=0.1, 
        )
    
    response = tokenizer.decode(outputs[0], skip_special_tokens=True)
    response_content = response.split("### Response:")[-1].strip()
    
    # Simple keyword extraction for decision
    decision = "Flat"
    if "Enter Long" in response_content or "**Long**" in response_content:
        decision = "Long"
    elif "Enter Short" in response_content or "**Short**" in response_content:
        decision = "Short"
        
    return decision, response_content

def main():
    print("Initializing P&L Simulation...")
    model, tokenizer, device = load_model()
    
    total_pnl = 0
    wins = 0
    losses = 0
    trades = 0
    
    print(f"\nScanning {NUM_SCENARIOS} market scenarios...\n")
    print(f"{'SCENARIO':<20} | {'MODEL DECISION':<15} | {'OPTIMAL':<10} | {'RESULT':<10} | {'P&L':<10}")
    print("-" * 80)
    
    for i in range(NUM_SCENARIOS):
        scenario = generate_scenario_with_outcome()
        decision, reasoning = get_model_decision(model, tokenizer, device, scenario["input"])
        
        step_pnl = 0
        result = "NEUTRAL"
        
        # Logic for P&L Calculation
        if decision == scenario["optimal_action"]:
            if decision != "Flat":
                step_pnl = scenario["outcome_pnl"]
                result = "WIN"
                wins += 1
                trades += 1
            else:
                step_pnl = 0
                result = "SKIPPED" # Good pass
        elif decision == "Flat" and scenario["optimal_action"] != "Flat":
            step_pnl = 0 # Missed opportunity, no loss
            result = "MISSED"
        else:
            # Wrong direction or taking a trade in Chop
            if decision != "Flat":
                step_pnl = -RISK_PER_TRADE
                result = "LOSS"
                losses += 1
                trades += 1
            
        total_pnl += step_pnl
        print(f"{scenario['type']:<20} | {decision:<15} | {scenario['optimal_action']:<10} | {result:<10} | ${step_pnl:<10}")
        # print(f"Reasoning: {reasoning[:100]}...") # Optional debug

    print("-" * 80)
    print(f"\nFinal Results:")
    print(f"Total P&L: ${total_pnl}")
    print(f"Win Rate: {wins}/{trades} ({wins/trades*100 if trades > 0 else 0:.1f}%)")
    print(f" Trades Taken: {trades}")

if __name__ == "__main__":
    main()
