import argparse
import json
import re
import time
from mlx_lm import load, generate
from mlx_lm.sample_utils import make_sampler, make_repetition_penalty

BASE_MODEL = "mlx-community/gemma-4-e4b-it-nvfp4"

SYSTEM = (
    "You are an expert AMT scalping analyst using Fabio Valentini's Auction Market Theory. "
    "You READ the auction — you do NOT predict. "
    "MANDATORY REASONING STRUCTURE (Inside <think> tags): "
    "1. SESSION CHECK: [Window] -> Bias [Bullish/Bearish/Neutral] "
    "2. RISK CHECK: [P&L/Rule Status] -> Permit [Yes/No] "
    "3. STRUCTURE CHECK: [State/Location] -> Signal [Confirmed/No] "
    "4. AGGRESSION CHECK: [CVD/Delta/Bubbles] -> Trigger [Confirmed/No] "
    "5. FINAL LOGIC: [Narrative summary] "
    "Then respond with a JSON object only. "
    "JSON format: {\"direction\": \"LONG|SHORT|FLAT\", \"confidence\": \"High|Medium|Low\", \"rationale\": \"brief reason\"}"
)

# 24-Case Test Suite based on Fabio AMT Playbook
TESTS = [
    ("Triple-A: All align → Long",
     "NSE Primary (09:30-11:30). Balanced. Price at VAL 22100. Aggressive selling -900 Delta but price NOT moving — iceberg buyers. "
     "D-shape. Bubble: 2.5σ buy 3000 contracts. CVD: +650. Above VWAP. ✅ SECOND DRIVE.", "LONG"),

    ("Triple-A: No aggression → Flat",
     "NSE Primary. Balanced. Price at VAL 22100. No volume bubbles. Delta neutral. No aggressive prints. "
     "CVD: +18 (flat). D-shape. FIRST DRIVE.", "FLAT"),

    ("State unclear → Flat",
     "NSE Primary. Market state UNCLEAR — mixed overlap, partial acceptance. Price near POC 22300. "
     "Delta choppy. CVD: -35. D-shape. FIRST DRIVE.", "FLAT"),

    ("Second Drive Long",
     "NSE Primary. Balanced. Price returned to VAL 22100 (SECOND visit). Buyers: Delta +850, 3200 contracts, bubble 2.5σ. "
     "CVD: +420. Above VWAP. D-shape.", "LONG"),

    ("First Touch → cautious Flat",
     "NSE Primary. Balanced. Price at VAL 22100 FIRST TIME. Delta +420, volume 1500 (no bubble). CVD: +85. At VWAP. FIRST DRIVE.", "FLAT"),

    ("Imbalanced LVN pullback Long",
     "Market IMBALANCED, displacement broke above VAH 22500. Accepted outside value. Price pulled to LVN 22350. "
     "Buyers: Delta +1200, 4000 contracts, bubble 2.8σ. CVD: +780. Above VWAP. SECOND DRIVE.", "LONG"),

    ("Failed breakout → Short",
     "Balanced. Price broke above VAH 22500 but FAILED — snapped back inside value. At LVN 22400. "
     "Sellers: Delta -820, bubble 2.6σ. CVD: -560. P-shape. SECOND DRIVE.", "SHORT"),

    ("AAA Short at VAH",
     "Price at VAH 48200. Aggressive buying +1500 Delta but price NOT moving up. Passive sellers absorbing. "
     "P-shape. CVD divergence BEARISH. Above VWAP+1σ. SECOND DRIVE.", "SHORT"),

    ("Squeeze Long — trapped shorts",
     "Imbalanced. Price breaking through 22500 where previous shorts stopped out. Short covering accelerating. "
     "Delta: +2500. Volume: 7000. CVD: +1200. SECOND DRIVE. Above VWAP.", "LONG"),

    ("Squeeze Short — trapped longs",
     "Imbalanced. Price crashing through VAL 47000 where previous longs stopped out. Long liquidation. "
     "Delta: -2000. Volume: 6000. CVD: -950 (strongly negative). SECOND DRIVE.", "SHORT"),

    ("CVD confirms → move to breakeven",
     "Entered LONG at 22100. CVD: +1200 (strongly positive). Market confirming direction. "
     "Aggressive buyers still pushing. Price +45 in favor.", "FLAT"),

    ("VWAP: Don't Long Below VWAP",
     "NSE Primary. Balanced. Long signal at VAL 22050. BUT price BELOW VWAP. VWAP at 22100. "
     "Price 21980 = 120 below VWAP. Bearish bias. D-shape.", "FLAT"),

    ("VWAP: Don't Short Above VWAP",
     "NSE Primary. Balanced. Short signal at VAH 22500. BUT price ABOVE VWAP. VWAP at 22300. "
     "Price 22550 = 250 above VWAP. Bullish bias. D-shape.", "FLAT"),

    ("3 Losses → Walk away",
     "Session P&L: -₹4,200 (3 consecutive losses). A-grade signal: long at VAL 22100, bubble+CVD confirmed. "
     "D-shape. SECOND DRIVE.", "FLAT"),

    ("Cushion → Scale up",
     "Session P&L: +₹5,800 (strong cushion). A-grade signal: LVN pullback, imbalanced trend. "
     "CVD: +720. Delta: +1100. SECOND DRIVE. Above VWAP.", "LONG"),

    ("2 Losses → Reduce to minimum",
     "Session P&L: -₹2,800 (2 consecutive losses). B-grade setup at VAL 22100. CVD: +82 (weak). "
     "Delta: +180. FIRST DRIVE. At VWAP.", "FLAT"),

    ("Midday: Downgrade all setups",
     "SESSION: NSE Midday (11:30-14:00). B-grade momentum signal. Volume declining. CVD: +180. "
     "False breakouts common in midday.", "FLAT"),

    ("Opening Noise: Skip first 5 min",
     "SESSION: NSE Opening (09:15-09:20). Wild swings. Spreads 18bps. Delta whipsawing ±800. "
     "High volume but chaotic. No stable profile.", "FLAT"),

    ("Close Protection: Exit",
     "SESSION: Close Protection (15:15-15:30). Long position open, +₹800. Session ending in 15 min.", "FLAT"),

    ("Delta Divergence → Kill trade",
     "Holding LONG. Price making new highs above 22500. BUT delta diverging NEGATIVE: -1200. "
     "CVD turning down: -280. No real aggression. Hidden supply absorbing.", "SHORT"),

    ("No follow-through → Scratch",
     "Entered LONG at 22100. Volume dried up immediately. No follow-through. Delta: +15 (neutral). "
     "CVD slope flat: +12. Confirmation disappeared.", "FLAT"),

    ("Wide Spread → No trade",
     "Good setup at VAL 22100. Delta: +680, bubble present. But bid-ask spread: 18bps (normally 2-4bps). "
     "Liquidity thin.", "FLAT"),

    ("Event Risk → Stay out",
     "RBI policy announcement in 15 minutes. Good technical setup at POC 22300. CVD: +220. "
     "But major event imminent.", "FLAT"),

    ("Wrong immediately → Accept loss",
     "Entered SHORT at VAH. Price IMMEDIATELY broke higher with +2000 Delta surge. "
     "Strong buying momentum. SL about to hit.", "FLAT"),
]

def parse_response(text: str) -> tuple[str, bool, bool, str]:
    think_match = re.search(r"<think>(.*?)</think>", text, re.DOTALL)
    has_think = think_match is not None and len((think_match.group(1) or "").strip()) > 20
    after_think = text[think_match.end():].strip() if think_match else text
    json_ok = False
    direction = "FLAT"
    rationale = ""
    json_match = re.search(r"\{.*?\}", after_think, re.DOTALL)
    if json_match:
        try:
            obj = json.loads(json_match.group())
            json_ok = True
            direction = str(obj.get("direction", "FLAT")).upper()
            rationale = obj.get("rationale", "")
            if direction not in ("LONG", "SHORT", "FLAT"): direction = "FLAT"
        except Exception:
            t = after_think.lower()
            if "long" in t: direction = "LONG"
            elif "short" in t: direction = "SHORT"
    return direction, has_think, json_ok, rationale

def run_validation(model_path: str, is_adapter: bool = False):
    print(f"\n{'═'*72}\n  Loading {'fine-tuned (adapter)' if is_adapter else 'model'}: {model_path}\n{'═'*72}")
    t0 = time.time()
    if is_adapter:
        from mlx_lm.lora import load as lora_load
        model, tokenizer = lora_load(BASE_MODEL, adapter_path=model_path)
    else:
        model, tokenizer = load(model_path)
    print(f"  Loaded in {time.time() - t0:.1f}s\n")

    sampler = make_sampler(temp=0.1)
    rep_penalty = make_repetition_penalty(1.1, context_size=64)

    results = []; correct = 0; json_ok_count = 0; think_ok_count = 0; total_time = 0.0
    print(f"  {'#':>2}  {'✓':4}  {'JSON':4}  {'<⩽>':4}  {'Test':42}  {'Exp':5}  {'Got':5}  {'t':>5}\n  {'─'*78}")

    for i, (name, inp, expected) in enumerate(TESTS):
        msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": inp}]
        try:
            prompt = tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        except Exception:
            prompt = f"<|im_start|>system\n{SYSTEM}<|im_end|>\n<|im_start|>user\n{inp}<|im_end|>\n<|im_start|>assistant\n"

        t_start = time.time()
        # Correct usage for mlx-lm 0.31.2
        resp = generate(model, tokenizer, prompt=prompt, max_tokens=600, sampler=sampler, logits_processors=[rep_penalty])
        elapsed = time.time() - t_start
        total_time += elapsed

        direction, has_think, json_parseable, rationale = parse_response(resp)
        ok = (direction == expected)
        if ok: correct += 1
        if json_parseable: json_ok_count += 1
        if has_think: think_ok_count += 1

        print(f"  {i+1:>2}  {'✅' if ok else '❌'}    {'✅' if json_parseable else '❌'}    {'✅' if has_think else '❌'}    {name:42}  {expected:5}  {direction:5}  {elapsed:>4.1f}s")
        results.append({
            "test": name, "expected": expected, "got": direction, "correct": ok,
            "json_parseable": json_parseable, "has_think": has_think, "rationale_preview": rationale[:80],
            "latency_s": round(elapsed, 3), "raw_response": resp[:300],
        })

    accuracy = 100 * correct / len(TESTS); avg_lat = total_time / len(TESTS)
    json_pct = 100 * json_ok_count / len(TESTS); think_pct = 100 * think_ok_count / len(TESTS)

    print(f"\n{'═'*72}\n  RESULTS:")
    print(f"  Accuracy:       {correct}/{len(TESTS)} = {accuracy:.0f}%   (target: ≥90%)")
    print(f"  Avg latency:    {avg_lat:.2f}s/call     (target: <5s)")
    print(f"  JSON parseable: {json_ok_count}/{len(TESTS)} = {json_pct:.0f}%  (target: 100%)")
    print(f"  Has <think>:    {think_ok_count}/{len(TESTS)} = {think_pct:.0f}%  (target: ≥90%)")

    failures = [r for r in results if not r["correct"]]
    if failures:
        print(f"\n  Failures ({len(failures)}):")
        for f in failures: print(f"    ❌ {f['test']}: expected {f['expected']}, got {f['got']}")
    else: print("\n  🎉 Perfect score!")

    out_file = f"poc_gemma4_e4b/validation_results_{int(time.time())}.json"
    with open(out_file, "w") as f: json.dump({"accuracy": accuracy, "results": results}, f, indent=2)
    print(f"\n  Full results saved → {out_file}")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="poc_gemma4_e4b/adapters")
    args = p.parse_args()
    import os
    is_adapter = os.path.isdir(args.model) and os.path.exists(os.path.join(args.model, "adapter_config.json"))
    run_validation(args.model, is_adapter=is_adapter)

if __name__ == "__main__":
    main()
