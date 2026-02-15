import json
import random

# Number of examples to generate
NUM_EXAMPLES = 500

# Constants
VAL_RANGE = (14900, 15000)
VAH_RANGE = (15100, 15200)
POC_RANGE = (15000, 15100)

def random_price(price_range):
    return random.randint(price_range[0], price_range[1])

def generate_aaa_setup():
    """
    AAA Setup: Value Area Low Fade / Absorption
    Context: Market tries to break lower (VAL) but sellers get absorbed.
    Action: Long targeting VAH.
    """
    val = random_price(VAL_RANGE)
    vah = random_price(VAH_RANGE)
    
    scenarios = [
        {
            "input": f"New York Open. Price is testing Value Area Low (VAL) at {val}. Sellers are aggressive with -500 Delta but price is not moving down. Big buy orders are hitting the bid.",
            "output": f"Market State: **Balance** (Bottom of Range). Logic: **AAA Setup**. Sellers are super aggressive but are being absorbed (passive buyers holding the wall). Trigger: **Enter Long**. Stop: Tight below absorption low. Target: Value Area High (~{vah}). Risk/Reward: Asymmetrical (High)."
        },
        {
            "input": f"Price pushed below VAL {val} during London close but is dragging back inside. Footprint shows 2000 contracts sold at lows with no follow-through.",
            "output": f"Market State: **Balance** (Failed Breakdown). Logic: **AAA Setup**. Sellers attempted to push but failed (Trapped Sellers). Absorption confirms support. Trigger: **Enter Long** on re-entry into Value. Target: VAH or Session High. Rule: Don't short into absorption."
        },
        {
            "input": f"Market is rotational. We are at the bottom of the distribution ({val}). Delta is continuously red but price is ticking higher.",
            "output": f"Market State: **Absorption**. Logic: **AAA Setup**. Passive buyers are consuming all sell pressure. Demand > Supply at this price. Trigger: **Long** with size. Target: Rotation to top of balance ({vah})."
        }
    ]
    return random.choice(scenarios)

def generate_momentum_setup():
    """
    Momentum Trade: Breakout / Squeeze
    Context: Price breaks VAH/High with aggression.
    Action: Long on pullback to protection level.
    """
    breakout_level = random_price(VAH_RANGE)
    
    scenarios = [
        {
            "input": f"Price broke above Value Area High {breakout_level} with strong +2000 Delta. Aggressive buyers are lifting the offer.",
            "output": f"Market State: **Imbalance** (Trend). Logic: **Momentum Squeeze**. Buyers are in full control. Sellers are trapped. Trigger: **Enter Long** on pullback to the **Protection Level** (where big buyers stepped in). Rule: Trail stop aggressively. Target: Extension/Blue Sky."
        },
        {
            "input": f"Trump tweeted (or news event). Volatility spike. Price blasted through {breakout_level}. A 'P-Shape' profile is forming.",
            "output": f"Market State: **Imbalance** (Short Covering). Logic: **Momentum**. Market is rebalancing higher. Structure is P-Shape (Short Covering). Trigger: **Long** on any dip. Do not fade. Target: Session Highs or Measured Move."
        },
        {
            "input": f"Aggressive buyers pushing. We are making Higher Highs. A wall of bids has formed at {breakout_level+10}.",
            "output": f"Market State: **Trend**. Logic: **Momentum**. Buyers are protecting the level. Trigger: **Add to Longs** risk-free. Stop: Below the protection wall. Target: Squeeze until exhaustion."
        }
    ]
    return random.choice(scenarios)

def generate_failed_auction_setup():
    """
    Failed Auction: Reversal
    Context: Breakout fails, rotates back.
    Action: Fade the move.
    """
    level = random_price(VAH_RANGE)
    val = random_price(VAL_RANGE)
    
    scenarios = [
        {
            "input": f"Price broke VAH {level} but immediately stalled. Delta was +1000 but price ticked down. Buyers are trapped at highs.",
            "output": f"Market State: **Failed Auction**. Logic: Breakout failed. Aggressive buyers are trapped. Market seeks value lower. Trigger: **Enter Short**. Target: Rotation back to Value Area Low (~{val})."
        },
        {
            "input": f"Tried to squeeze the high at {level} three times. Each time price rejected. Volume is drying up on the bid.",
            "output": f"Market State: **Balance** (Rejection). Logic: Buyers exhausted. 'Punching a wall'. Trigger: **Short** on confirmation of rotation back inside. Focus: Target middle of range first, then VAL."
        }
    ]
    return random.choice(scenarios)

def generate_risk_management_scenario():
    """
    Risk Management & Psychology
    """
    profit = random.randint(5000, 25000)
    drawdown = random.randint(1000, 5000)
    
    scenarios = [
        {
            "input": f"We are up ${profit} for the session. Price is entering a chop zone/contraction.",
            "output": f"Logic: **Risk Management**. Walk away. Do not give back profit. 'We are done in 20 minutes'. Rule: Protect the cushion. Don't overtrade."
        },
        {
            "input": f"I took two stop losses. Down ${drawdown}. Market is not giving a clear setup.",
            "output": f"Logic: **Discipline**. Stop trading or reduce size significantly. Rule: Daily drawdown limit is strict. Better to close small red than huge red. Wait for AAA setup only."
        },
        {
            "input": f"Floating ${profit} profit on a Long. Price is reaching a technical resistance.",
            "output": f"Logic: **Bank Profit**. Take partials or close. 'If the market wants to give me ${profit}, I take it.' Don't hold for the home run if structure breaks."
        }
    ]
    return random.choice(scenarios)

def main():
    data = []
    print(f"Generating {NUM_EXAMPLES} synthetic specific examples...")
    
    for _ in range(NUM_EXAMPLES):
        r = random.random()
        entry = {}
        
        # 30% AAA, 30% Momentum, 20% Fail, 20% Risk/Psychology
        if r < 0.3:
            s = generate_aaa_setup()
        elif r < 0.6:
            s = generate_momentum_setup()
        elif r < 0.8:
            s = generate_failed_auction_setup()
        else:
            s = generate_risk_management_scenario()
            
        entry = {
            "instruction": "Analyze the trading scenario based on Fabio Valentini's methodology (Orderflow, Auction Market Theory).",
            "input": s["input"],
            "output": s["output"]
        }
        data.append(entry)

    output_file = "training_data_fabio.jsonl"
    with open(output_file, "w") as f:
        for entry in data:
            json.dump(entry, f)
            f.write("\n")
    
    print(f"Successfully generated {len(data)} examples to {output_file}")

if __name__ == "__main__":
    main()
