#!/usr/bin/env python3
"""
Consolidate all AMT training datasets into unified dataset.

Backend runtime contract (from backend analysis):
  - User input: build_entry_prompt() produces 5-section narrative
    (session context, market state, aggression/CVD, risk/gates, strategy hint)
  - Model output: JSON {direction, confidence, rationale}
  - Parser: JSON first, then structured text, then keyword fallback

Training contract (from train_gemma4_2b.py):
  - JSONL with messages array, mask_prompt=True (only train on assistant)

3 system prompt tiers:
  Tier 1: Compact JSON-only (expert narratives with rich rationale)
  Tier 2: Chain-of-thought with <think> (brief/structured rationales)

Output: amt_dataset/{train,valid,test}.jsonl + amt_dataset/mlx_format/
"""

import json
import hashlib
import random
import re
import sys
from pathlib import Path
from collections import defaultdict

random.seed(42)

OUTPUT_DIR = Path("amt_dataset")
OUTPUT_DIR.mkdir(exist_ok=True)

SYSTEM_COMPACT = (
    "You are an expert AMT scalping analyst. "
    "Analyze the market scenario and respond with ONLY JSON: "
    '{"direction": "LONG|SHORT|FLAT", "confidence": "High|Medium|Low", "rationale": "brief"}'
)

SYSTEM_COT = (
    "You are an expert AMT scalping analyst. "
    "Think step by step considering market state, location, "
    "aggression, and session context. "
    "Then respond with ONLY JSON: "
    '{"direction": "LONG|SHORT|FLAT", "confidence": "High|Medium|Low", "rationale": "brief"}'
)


def load_jsonl(path):
    rows = []
    with open(path) as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"WARN: skip line {i} in {path}", file=sys.stderr)
    return rows


def get_msg(msgs, role):
    for m in msgs:
        if m.get("role") == role:
            return m.get("content", "")
    return ""


def parse_json_from_text(text):
    text = text.strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "direction" in obj:
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    # Find JSON block with "direction"
    for pattern in [
        r'\{\s*"direction"\s*:\s*"[^"]*"\s*,\s*"confidence"\s*:\s*"[^"]*"\s*,\s*"rationale"\s*:\s*"[^"]*"\s*\}',
        r'\{\s*"direction"\s*:\s*"[^"]*"\s*\}',
        r'\{[^{}]*"direction"[^{}]*\}',
    ]:
        m = re.search(pattern, text, re.DOTALL)
        if m:
            try:
                obj = json.loads(m.group())
                if isinstance(obj, dict) and "direction" in obj:
                    return obj
            except (json.JSONDecodeError, ValueError):
                pass
    return None


def keyword_fallback(text):
    lower = text.lower()
    if re.search(r'"direction"\s*:\s*"long"', lower):
        return {"direction": "LONG", "confidence": "Medium", "rationale": ""}
    if re.search(r'"direction"\s*:\s*"short"', lower):
        return {"direction": "SHORT", "confidence": "Medium", "rationale": ""}
    if re.search(r'"direction"\s*:\s*"flat"', lower):
        return {"direction": "FLAT", "confidence": "Medium", "rationale": ""}
    if re.search(r'\blong\b', lower) and not re.search(r'\bshort\b', lower):
        return {"direction": "LONG", "confidence": "Medium", "rationale": ""}
    if re.search(r'\bshort\b', lower):
        return {"direction": "SHORT", "confidence": "Medium", "rationale": ""}
    return None


def classify(user_text, direction, rationale):
    """Classify scenario type. Uses rationale as primary signal (expert decision label)."""
    user = user_text.lower()
    rat = (rationale or "").lower()
    # Rationale is the expert's own label — most reliable signal
    combined = rat + " " + user

    # Order: most specific / rarest first
    if any(kw in combined for kw in ["circuit breaker", "stop trading", "three consecutive", "walk away", "give back profit"]):
        return "risk_mgmt"

    if any(kw in combined for kw in ["squeeze", "trapped long", "trapped short", "trapped buyer", "forced liquidate", "forced to liquidate"]):
        return "squeeze"

    if any(kw in combined for kw in ["delta divergence", "cvd divergence", "hidden demand", "hidden supply",
                                       "price falling on positive delta", "price rising on negative delta"]):
        return "divergence"

    # Absorption: match against RATIONALE text only (not field labels)
    if any(kw in rat for kw in ["absorption", "absorbing", "iceberg", "absorbed by passive", "absorption setup"]):
        return "absorption"

    if any(kw in combined for kw in ["rejected at vah", "rejected at val", "rejection at high", "rejection at low",
                                       "failed breakout", "failed breakdown", "bear trap", "bull trap", "false break",
                                       "fake breakout", "no follow-through"]):
        return "rejection"

    if any(kw in combined for kw in ["aaa setup", "a-grade setup", "aaa signal", "second drive",
                                       "pullback entry", "lvn pullback"]):
        return "aaa_setup"

    if any(kw in combined for kw in ["exhaustion", "overextended", "stretched far", "vwap extreme"]):
        return "exhaustion"

    if any(kw in combined for kw in ["breakout above vah", "breakout below val", "broke above vah", "broke below val",
                                       "breaking above vah", "breaking below val", "breakout zone"]):
        return "breakout"

    if any(kw in combined for kw in ["trend continuation", "displacement leg", "initiative trend",
                                       "strong uptrend", "strong downtrend"]):
        return "trend"

    if direction == "FLAT":
        if any(kw in combined for kw in ["opening noise", "spreads wide", "thin order book", "chaotic",
                                           "no one wants to trade", "scratching", "abort signal", "no setup",
                                           "no clear", "dead trade", "poor liquidity", "skip trade"]):
            return "no_trade"
        return "flat_general"

    if any(kw in combined for kw in ["mean reversion", "range-bound", "return to poc", "fade ",
                                       "buy on dip", "short at vah", "mean revert"]):
        return "mean_reversion"

    if any(kw in combined for kw in ["balanced", "rotating", "rotation", "rotational"]):
        return "balancing"

    if any(kw in combined for kw in ["vwap upper", "vwap below", "vwap+ ", "vwap- "]):
        return "vwap_play"

    if any(kw in combined for kw in ["london open", "ny open", "ny rejecting", "session transition"]):
        return "session_trade"

    if any(kw in combined for kw in ["stacked imbalance", "stacked buy", "stacked sell"]):
        return "absorption"

    return "general"


def validate_row(row, src):
    msgs = row.get("messages", [])
    if not msgs:
        return None

    user_text = get_msg(msgs, "user")
    asst_text = get_msg(msgs, "assistant")
    if not user_text or not asst_text:
        return None

    asst = asst_text.strip()
    has_think = "<think>" in asst

    clean = asst
    if has_think:
        parts = re.split(r"</think>\s*", asst, maxsplit=1)
        clean = parts[-1].strip() if len(parts) > 1 else re.sub(r"<think>.*", "", asst, flags=re.DOTALL).strip()

    parsed = parse_json_from_text(clean)
    if parsed is None:
        parsed = keyword_fallback(clean)
    if parsed is None:
        return None

    direction = parsed.get("direction", "FLAT").upper().strip()
    if direction not in ("LONG", "SHORT", "FLAT"):
        direction = "FLAT"

    confidence = parsed.get("confidence", "Medium").capitalize()
    if confidence not in ("High", "Medium", "Low"):
        confidence = "Medium"

    rationale = parsed.get("rationale", "").strip()
    if len(rationale) > 250:
        rationale = rationale[:247] + "..."

    if rationale.lower() in {"unknown", "n/a", "none", "null", "", "n/a.", "none."}:
        return None

    tier = 2 if has_think else 1

    return {
        "user_text": user_text,
        "direction": direction,
        "confidence": confidence,
        "rationale": rationale,
        "tier": tier,
        "src": src,
    }


def build_output(tier, direction, confidence, rationale, scenario_type):
    j = json.dumps({"direction": direction, "confidence": confidence, "rationale": rationale})
    if tier == 2:
        # Context-aware CoT based on scenario type
        type_hints = {
            "rejection": ("Price testing VA boundary", "Rejection vs breakout", "Absorption at boundary", f"Rejection signal: {rationale}"),
            "absorption": ("Check absorption side", "Absorption pattern recognized", "Institutional absorption confirmed", f"Absorption: {rationale}"),
            "divergence": ("Check delta/CVD alignment", "Divergence detected", "Hidden flow vs price divergence", f"Divergence: {rationale}"),
            "squeeze": ("Identify trapped traders", "Squeeze momentum building", "Trapped positions fueling move", f"Squeeze: {rationale}"),
            "breakout": ("Check breakout vs fakeout", "Volume confirms conviction", "Price sustaining beyond VA", f"Breakout: {rationale}"),
            "trend": ("Confirm trend structure", "Displacement leg active", "Trend continuation aligned", f"Trend continuation: {rationale}"),
            "aaa_setup": ("AAA-grade setup", "Multi-timeframe alignment", "Entry zone confirmed", f"AAA setup: {rationale}"),
            "exhaustion": ("Price extended from value", "Mean reversion likely", "Aggression declining", f"Exhaustion: {rationale}"),
            "risk_mgmt": ("Risk limits approaching", "Circuit breaker caution", "Discipline override", f"Risk: {rationale}"),
            "no_trade": ("Low conviction environment", "Poor reward/risk", "Conditions favor flat", f"No trade: {rationale}"),
            "balancing": ("Price rotating in range", "No directional edge", "Wait for conviction", f"Balance: {rationale}"),
        }
        hint = type_hints.get(scenario_type, ("Assess session context", "Check market structure", "Review aggression", rationale))
        if direction == "FLAT":
            hint = ("No clear edge identified", "Conditions unfavorable", "Risk/reward insufficient", rationale if rationale else "Stay flat — no conviction")
        return (
            f"<think>\n"
            f"1. SESSION CHECK: {hint[0]}.\n"
            f"2. RISK CHECK: {hint[1]}.\n"
            f"3. STRUCTURE CHECK: {hint[2]}.\n"
            f"4. AGGRESSION CHECK: {hint[3]}.\n"
            f"5. FINAL LOGIC: {rationale}\n"
            f"</think>\n{j}"
        )
    return j


def dedup_key(text):
    return hashlib.md5(" ".join(text.lower().split()).encode()).hexdigest()


def build_mlx_entry(messages):
    return {"messages": messages}


def main():
    print("=" * 60)
    print("AMT Dataset Consolidation")
    print("=" * 60)

    sources = {
        "expert_train": "expert_amt_dataset_clean/train.jsonl",
        "expert_valid": "expert_amt_dataset_clean/valid.jsonl",
        "fabio_train": "fabio_amt_dataset_clean/train.jsonl",
        "fabio_valid": "fabio_amt_dataset_clean/valid.jsonl",
    }

    all_rows = defaultdict(list)
    total_loaded = 0

    for name, path in sources.items():
        if not Path(path).exists():
            print(f"WARN: {path} not found")
            continue
        rows = load_jsonl(path)
        total_loaded += len(rows)
        valid_count = 0
        for row in rows:
            v = validate_row(row, name)
            if v:
                all_rows[dedup_key(v["user_text"])].append(v)
                valid_count += 1
        print(f"  {name}: {len(rows)} -> {valid_count} valid")

    print(f"\nTotal loaded: {total_loaded}, deduped unique: {len(all_rows)}")

    unified = []
    for key, variants in all_rows.items():
        # Prefer expert (tier 1 with rich rationale), then by rationale length
        best = max(variants, key=lambda v: (
            "expert" in v["src"],
            len(v["rationale"]),
        ))
        st = classify(best["user_text"], best["direction"], best["rationale"])
        tier = best["tier"]

        # For tier 1 entries: always use compact system prompt
        # For tier 2 entries (already have CoT from original): keep CoT
        # For entries with very short rationale from fabio: upgrade to tier 2
        if tier == 1 and len(best["rationale"]) < 15:
            tier = 2  # Brief rationale → add CoT wrapper

        sys_prompt = SYSTEM_COMPACT if tier == 1 else SYSTEM_COT
        asst_out = build_output(tier, best["direction"], best["confidence"], best["rationale"], st)

        unified.append({
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": best["user_text"]},
                {"role": "assistant", "content": asst_out},
            ],
            "meta": {"tier": tier, "scenario_type": st, "source": best["src"]},
        })

    # Stats
    dir_c = defaultdict(int)
    type_c = defaultdict(int)
    tier_c = defaultdict(int)
    for e in unified:
        a = e["messages"][2]["content"]
        p = parse_json_from_text(a[a.rfind("<think>") + 100:] if "<think>" in a else a)
        dir_c[p.get("direction", "FLAT") if p else "FLAT"] += 1
        type_c[e["meta"]["scenario_type"]] += 1
        tier_c[e["meta"]["tier"]] += 1

    print(f"\nDirection: {dict(dir_c)}")
    print(f"Types: {dict(sorted(type_c.items(), key=lambda x: -x[1]))}")
    print(f"Tiers:  {dict(tier_c)}")

    random.shuffle(unified)
    n = len(unified)
    n_test = max(1000, int(n * 0.075))
    n_valid = max(1000, int(n * 0.075))

    splits = {
        "train": unified[:n - n_test - n_valid],
        "valid": unified[n - n_test - n_valid:n - n_test],
        "test":  unified[n - n_test:],
    }

    print(f"\nSplit: train={len(splits['train'])}, valid={len(splits['valid'])}, test={len(splits['test'])}")

    def write(path, data):
        with open(path, "w") as f:
            for e in data:
                f.write(json.dumps(e) + "\n")

    for name, data in splits.items():
        write(OUTPUT_DIR / f"{name}.jsonl", data)

    mlx_dir = OUTPUT_DIR / "mlx_format"
    mlx_dir.mkdir(exist_ok=True)
    for name, data in splits.items():
        write(mlx_dir / f"{name}.jsonl", [build_mlx_entry(e["messages"]) for e in data])

    stats = {
        "total": n,
        **{k: len(v) for k, v in splits.items()},
        "direction_dist": dict(dir_c),
        "scenario_types": dict(type_c),
        "tier_dist": dict(tier_c),
    }
    with open(OUTPUT_DIR / "stats.json", "w") as f:
        json.dump(stats, f, indent=2)

    print(f"\n✓ {OUTPUT_DIR}/  (train/valid/test.jsonl + stats.json)")
    print(f"✓ {mlx_dir}/  (mlx_lm compatible)")
    print("=" * 60)


if __name__ == "__main__":
    main()
