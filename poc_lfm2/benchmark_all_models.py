"""
Multi-Model Fabio AMT Benchmark
Tests all locally available MLX models on the same 24-case Fabio methodology suite.
Covers accuracy (%), avg latency (s), and produces a ranked comparison.

System requirements:
  - LLM_TIMEOUT_SECONDS = 30s (from config.py)
  - Need response within ~5s for real-time scalping (5m candles, 30s timeout budget)
"""
import time, json, sys
from mlx_lm import load, generate
from mlx_lm.sample_utils import make_sampler

# ═══════════════════════════════════════════════
# MODELS TO TEST (all locally cached)
# ═══════════════════════════════════════════════
MODELS = [
    {
        "id":    "mlx-community/DeepSeek-R1-Distill-Qwen-1.5B-4bit",
        "label": "DeepSeek-R1-1.5B-4bit",
        "size":  "965 MB",
        "skip":  False,  # Already tested but included for baseline
        "cached_accuracy": 38.0,
        "cached_latency":  0.80,
    },
    {
        "id":    "mlx-community/gemma-4-e2b-8bit",
        "label": "Gemma-4-E2B-8bit (MoE 2B active)",
        "size":  "5.5 GB",
        "skip":  False,
    },
    {
        "id":    "mlx-community/gemma-4-e4b-8bit",
        "label": "Gemma-4-E4B-8bit (MoE 4B active)",
        "size":  "8.4 GB",
        "skip":  False,
    },
    {
        "id":    "mlx-community/gemma-4-e4b-it-nvfp4",
        "label": "Gemma-4-E4B-it-nvfp4 (instruct, MoE 4B)",
        "size":  "6.4 GB",
        "skip":  False,
    },
    {
        "id":    "mlx-community/Qwen3-4B-8bit",
        "label": "Qwen3-4B-8bit",
        "size":  "4.0 GB",
        "skip":  False,
    },
]

SYSTEM = (
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

TESTS = [
    ("Triple-A: All align → Long",
     "NSE Primary Window (09:30-11:30). Market in Balance. Price at VAL 22100. "
     "Aggressive selling -900 Delta but price NOT moving down — iceberg buyers absorbing. "
     "D-shaped profile. Volume bubbles: 2.5σ buy at 22100 (3000 contracts). "
     "CVD trending up. Price above VWAP (22050). SECOND DRIVE at this level.", "LONG"),

    ("Triple-A: Missing aggression → Flat",
     "NSE Primary Window. Market in Balance. Price at VAL 22100. "
     "No volume bubbles. Delta neutral. No aggressive prints detected. "
     "D-shaped profile. CVD flat. Price at VWAP. First touch.", "FLAT"),

    ("Triple-A: State unclear → Flat",
     "NSE Primary Window. Market state unclear — mixed overlap with partial acceptance. "
     "Price near POC 22300. Delta choppy. Some volume but no clear direction. "
     "D-shaped profile. First touch.", "FLAT"),

    ("Second Drive: Higher conviction Long",
     "Price returned to VAL 22100 after first rejection. Buyers stepping in again. "
     "Delta +800. Volume 3000. SECOND DRIVE — market returned after initial test. "
     "CVD up. Price above VWAP. D-shaped profile.", "LONG"),

    ("First Touch: Lower conviction → cautious",
     "Price arriving at VAL 22100 for the first time today. Some buying interest. "
     "Delta +400. Volume 1500. First touch at this level. "
     "CVD slightly positive. Price at VWAP.", "FLAT"),

    ("Trend: LVN pullback entry",
     "Market is out of balance — displacement leg broke above VAH 22500. "
     "Acceptance outside value confirmed. Price pulled back to LVN at 22350. "
     "Aggressive buyers at LVN with +1200 Delta. Volume 4000. "
     "CVD trending up strongly. Price above VWAP. SECOND DRIVE.", "LONG"),

    ("MeanRev: Failed breakout → Short",
     "Market was in Balance. Price broke above VAH 22500 but failed to hold. "
     "No acceptance — price snapped back inside value. Now at reclaim-leg LVN 22400. "
     "Sellers aggressive with -800 Delta. CVD turning down. "
     "P-shape profile forming. SECOND DRIVE.", "SHORT"),

    ("AAA Short at VAH",
     "Price at VAH 48200. Aggressive buying +1500 Delta but price NOT moving up. "
     "Passive sellers absorbing all buy pressure. Supply > Demand. "
     "P-Shape profile. CVD divergence bearish — price rising, buying pressure declining. "
     "Price above VWAP+1σ. SECOND DRIVE at resistance.", "SHORT"),

    ("Squeeze: Trapped shorts forced to cover",
     "Price breaking through 22500 where previous shorts were stopped out. "
     "Short covering accelerating — forced liquidation in progress. "
     "Delta +2500. Volume 7000. CVD slope strongly positive. "
     "Their covering IS the fuel. SECOND DRIVE.", "LONG"),

    ("Squeeze: Trapped longs liquidating",
     "Price crashing through VAL 47000 where previous longs were stopped out. "
     "Long liquidation accelerating. Delta -2000. Volume 6000. "
     "CVD slope strongly negative — forced liquidation. SECOND DRIVE.", "SHORT"),

    ("CVD confirms Long → Move to BE",
     "Entered Long at 22100. CVD slope strongly positive +1200. "
     "Market confirming direction. Aggressive buyers still pushing. "
     "Move to breakeven immediately — market has shown its hand.", "FLAT"),

    ("VWAP Bias: Don't long below VWAP",
     "Long signal at VAL 22050. But price is below VWAP at 21980. VWAP at 22100. "
     "Bearish bias — price below fair value. D-shaped profile.", "FLAT"),

    ("VWAP Bias: Don't short above VWAP",
     "Short signal at VAH 22500. But price is above VWAP at 22550. VWAP at 22300. "
     "Bullish bias — price above fair value. D-shaped profile.", "FLAT"),

    ("3-Loss Stop: Walk away",
     "Session P&L: -₹4,000 (3 consecutive losses). A-grade signal firing at VAL. "
     "D-shaped profile. Despite good setup, discipline says STOP.", "FLAT"),

    ("Cushion: Scale up on profit",
     "Session P&L: +₹5,000 (strong cushion built). Price trending strongly. "
     "A-grade momentum signal firing. CVD confirms. SECOND DRIVE. "
     "Risk session profit — increase size.", "LONG"),

    ("2 Losses: Reduce to minimum",
     "Session P&L: -₹2,800 (2 consecutive losses). B-grade setup at VAL. "
     "D-shaped profile. CVD slightly positive. First touch.", "FLAT"),

    ("Midday: Downgrade all setups",
     "NSE Midday (11:30-14:00). B-grade momentum signal. Volume declining. "
     "Low conviction. False breakouts common in midday.", "FLAT"),

    ("Opening Noise: Skip first 5 min",
     "NSE Opening (09:15-09:20). Wild price swings. Spreads wide. "
     "High volume but chaotic. Delta whipsawing. Skip opening noise.", "FLAT"),

    ("Close Protection: Exit everything",
     "NSE Close Protection (15:15-15:30). Position still open. "
     "Session ending. No new trades. Exit all positions.", "FLAT"),

    ("Delta Divergence: Kill the trade",
     "Holding Long. Price making new highs above 22500. "
     "But delta diverging negative at -1200. No real aggression. "
     "Hidden supply. Passive sellers absorbing.", "SHORT"),

    ("No Follow-Through: Scratch",
     "Entered Long at 22100. Volume dried up immediately. "
     "No follow-through. Delta turned neutral. CVD slope flat. "
     "Confirmation disappeared.", "FLAT"),

    ("Wide Spread: No trade",
     "Price at VAL 22100 with good setup. But bid-ask spread is 15 bps — "
     "wider than usual. Liquidity thin. MCX late hours. "
     "Skip trades with poor liquidity.", "FLAT"),

    ("Event Risk: Stay out",
     "RBI policy announcement in 15 minutes. Price consolidating. "
     "Good technical setup at POC 22300 but major event imminent. "
     "Never trade ahead of major events.", "FLAT"),

    ("Wrong immediately: Accept loss",
     "Entered Short at VAH. Price immediately broke higher with +2000 Delta. "
     "Strong buying. SL about to hit. If wrong, wrong immediately. "
     "Never widen stop loss.", "FLAT"),
]


def parse_direction(text: str) -> str:
    t = text.lower()
    if "</think>" in t:
        t = t.split("</think>")[-1]
    if "enter long" in t or "trigger: long" in t:
        return "LONG"
    elif "enter short" in t or "trigger: short" in t:
        return "SHORT"
    return "FLAT"


def run_model(model_cfg: dict) -> dict:
    mid = model_cfg["id"]
    label = model_cfg["label"]

    # Use cached result for already-run models
    if model_cfg.get("skip") and "cached_accuracy" in model_cfg:
        return {
            "model": mid,
            "label": label,
            "size": model_cfg.get("size", "?"),
            "accuracy_pct": model_cfg["cached_accuracy"],
            "avg_latency_s": model_cfg["cached_latency"],
            "correct": int(model_cfg["cached_accuracy"] * 24 / 100),
            "total": 24,
            "results": [],
        }

    print(f"\n{'═'*70}")
    print(f"  Model: {label}  ({model_cfg.get('size','?')})")
    print(f"{'═'*70}")

    t0 = time.time()
    try:
        model, tokenizer = load(mid)
    except Exception as e:
        print(f"  ❌ Failed to load: {e}")
        return {"model": mid, "label": label, "error": str(e)}
    load_time = time.time() - t0
    print(f"  Loaded in {load_time:.1f}s\n")

    sampler = make_sampler(temp=0.1)
    results = []
    correct = 0
    total_time = 0.0

    print(f"  {'#':>2}  {'Status':6}  {'Test':42}  {'Exp':5}  {'Got':5}  {'t':>5}")

    for i, (name, inp, expected) in enumerate(TESTS):
        msgs = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": inp},
        ]
        try:
            prompt = tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        except Exception:
            prompt = f"<|im_start|>system\n{SYSTEM}<|im_end|>\n<|im_start|>user\n{inp}<|im_end|>\n<|im_start|>assistant\n"
        prompt += "Market State:"

        t_start = time.time()
        resp = generate(model, tokenizer, prompt=prompt, max_tokens=120, sampler=sampler)
        elapsed = time.time() - t_start
        total_time += elapsed

        got = parse_direction(resp)
        ok = (got == expected)
        if ok:
            correct += 1

        status = "✅" if ok else "❌"
        print(f"  {i+1:>2}  {status}      {name:42}  {expected:5}  {got:5}  {elapsed:>4.1f}s")
        results.append({"test": name, "expected": expected, "got": got, "correct": ok, "time": elapsed})

    # Free model from memory
    del model
    import gc; gc.collect()

    accuracy = 100 * correct / len(TESTS)
    avg_lat  = total_time / len(TESTS)
    print(f"\n  → {correct}/{len(TESTS)} correct  ({accuracy:.0f}%)  |  avg {avg_lat:.2f}s")

    return {
        "model":        mid,
        "label":        label,
        "size":         model_cfg.get("size", "?"),
        "accuracy_pct": round(accuracy, 1),
        "avg_latency_s": round(avg_lat, 3),
        "correct":      correct,
        "total":        len(TESTS),
        "results":      results,
    }


def main():
    all_results = []

    # Known baselines (already run, no reload needed)
    all_results.append({
        "model": "mlx-community/DeepSeek-R1-Distill-Qwen-1.5B-4bit",
        "label": "DeepSeek-R1-1.5B-4bit ⟵ already run",
        "size":  "965 MB",
        "accuracy_pct":  38.0,
        "avg_latency_s": 0.80,
        "correct": 9,
        "total": 24,
        "results": [],
    })

    # Run remaining models
    for m in MODELS:
        if m.get("skip"):
            continue
        r = run_model(m)
        all_results.append(r)

    # ─── Final Ranked Summary ─────────────────────────────────────────────────
    valid = [r for r in all_results if "error" not in r]
    valid.sort(key=lambda x: (-x["accuracy_pct"], x["avg_latency_s"]))

    print(f"\n\n{'═'*80}")
    print("  FINAL RANKING — Fabio AMT Accuracy + Speed")
    print(f"  System budget: LLM_TIMEOUT=30s | Target: <5s/inference for live scalping")
    print(f"{'═'*80}")
    print(f"  {'Rank':4}  {'Model':40}  {'Size':7}  {'Acc':5}  {'Latency':8}  {'Status'}")
    print(f"  {'─'*78}")

    for rank, r in enumerate(valid, 1):
        lat = r["avg_latency_s"]
        acc = r["accuracy_pct"]
        speed_ok = "⚡ Fast" if lat < 3 else ("✅ OK" if lat < 8 else "⚠️ Slow")
        acc_ok   = "🟢" if acc >= 65 else ("🟡" if acc >= 50 else "🔴")
        print(f"  #{rank:<3}  {r['label'][:40]:40}  {r.get('size','?'):7}  "
              f"{acc_ok}{acc:4.0f}%  {lat:5.2f}s    {speed_ok}")

    # Add known reference points
    print(f"\n  Reference models (not locally cached):")
    print(f"  {'─'*78}")
    refs = [
        ("LFM2-24B + LoRA 1000 iters (AMT fine-tuned)", "~17 GB", 70.8, 4.3, "Best accuracy found"),
        ("Nanbeige-3B (current prod system)", "~2 GB",  40.0, 2.4, "Current baseline"),
    ]
    for label, size, acc, lat, note in refs:
        acc_ok = "🟢" if acc >= 65 else ("🟡" if acc >= 50 else "🔴")
        print(f"  {'':4}  {label[:40]:40}  {size:7}  {acc_ok}{acc:4.0f}%  {lat:5.2f}s    {note}")

    print(f"\n{'═'*80}")
    print("\n  Fine-Tune Recommendation:")
    print("  ─────────────────────────")
    print("  Best candidate = highest base accuracy + <8s latency + MLX LoRA support")
    print("  The fine-tuned LFM2-24B LoRA remains the accuracy leader at 70.8%.")
    print("  Among newly tested models, see ranking above.")

    # Save
    out = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "ranked": valid, "system_timeout_s": 30}
    with open("poc_lfm2/benchmark_all_models_results.json", "w") as f:
        json.dump(out, f, indent=2)
    print("\n  Results saved → poc_lfm2/benchmark_all_models_results.json\n")


if __name__ == "__main__":
    main()
