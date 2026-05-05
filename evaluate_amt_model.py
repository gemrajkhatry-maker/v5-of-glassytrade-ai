#!/usr/bin/env python3
"""
Evaluate trained AMT model against consolidated test set.

Usage:
    python3 evaluate_amt_model.py --model-path <path> --adapter-path <path>
    python3 evaluate_amt_model.py --use-openrouter  # test via API
"""

import json
import re
import sys
import argparse
from pathlib import Path
from collections import defaultdict, Counter


def load_test_set(path="amt_dataset/test.jsonl"):
    """Load consolidated test set (with ground truth in assistant message)."""
    samples = []
    with open(path) as f:
        for line in f:
            entry = json.loads(line)
            msgs = entry["messages"]
            # Extract ground truth from assistant message
            asst = msgs[2].content if hasattr(msgs[2], 'content') else msgs[2].get('content', '')
            # Parse JSON from end of assistant message
            m = re.search(r'\{[^{}]*"direction"\s*:\s*"[^"]*"[^{}]*\}', asst, re.DOTALL)
            if not m:
                m = re.search(r'\{"direction":\s*"(\w+)"', asst)
            direction = None
            confidence = None
            rationale = None
            try:
                parsed = json.loads(m.group())
                direction = parsed.get("direction")
                confidence = parsed.get("confidence")
                rationale = parsed.get("rationale", "")
            except:
                m2 = re.search(r'"direction"\s*:\s*"(\w+)"', asst)
                if m2:
                    direction = m2.group(1)

            samples.append({
                "user": msgs[1].get("content", "") if isinstance(msgs[1], dict) else msgs[1].content,
                "system": msgs[0].get("content", "") if isinstance(msgs[0], dict) else msgs[0].content,
                "expected_direction": direction,
                "expected_confidence": confidence,
                "expected_rationale": rationale,
                "scenario_type": entry.get("meta", {}).get("scenario_type", "unknown"),
                "tier": entry.get("meta", {}).get("tier", 0),
            })
    return samples


def parse_model_output(text):
    """Parse model output — handles JSON, CoT+JSON, keyword fallback."""
    text = text.strip()
    if not text:
        return None

    # Try direct JSON
    # Strip think tags if present
    clean = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()

    # Find JSON block
    for pattern in [
        r'\{\s*"direction"\s*:\s*"(\w+)"\s*,\s*"confidence"\s*:\s*"(\w+)"\s*,\s*"rationale"\s*:\s*"([^"]*)"\s*\}',
        r'\{\s*"direction"\s*:\s*"(\w+)"\s*\}',
    ]:
        m = re.search(pattern, clean)
        if m:
            direction = m.group(1).upper()
            confidence = m.group(2).capitalize() if m.lastindex >= 2 else "Medium"
            rationale = m.group(3) if m.lastindex >= 3 else ""
            return {"direction": direction, "confidence": confidence, "rationale": rationale}

    # Keyword fallback
    lower = clean.lower()
    if '"direction"' in lower:
        dm = re.search(r'"direction"\s*:\s*"(\w+)"', lower)
        if dm:
            return {"direction": dm.group(1).upper(), "confidence": "Medium", "rationale": ""}
    if re.search(r'\blong\b', lower) and not re.search(r'\bshort\b', lower):
        return {"direction": "LONG", "confidence": "Medium", "rationale": ""}
    if re.search(r'\bshort\b', lower):
        return {"direction": "SHORT", "confidence": "Medium", "rationale": ""}
    if "flat" in lower:
        return {"direction": "FLAT", "confidence": "Medium", "rationale": ""}

    return {"direction": "FLAT", "confidence": "Low", "rationale": f"unparseable: {text[:80]}"}


def evaluate(samples, predict_fn, max_samples=None):
    """
    Evaluate model against test samples.

    predict_fn: (system_msg, user_msg) -> str (raw model output)
    """
    if max_samples:
        samples = samples[:max_samples]

    results = []
    correct_dir = 0
    correct_both = 0
    total = 0
    by_type = defaultdict(lambda: {"correct": 0, "total": 0})
    by_tier = defaultdict(lambda: {"correct": 0, "total": 0})
    confusion = Counter()

    for i, sample in enumerate(samples):
        expected_dir = sample["expected_direction"]
        if not expected_dir:
            continue

        try:
            raw = predict_fn(sample["system"], sample["user"])
            parsed = parse_model_output(raw)
        except Exception as e:
            parsed = {"direction": "ERROR", "confidence": "Low", "rationale": str(e)[:100]}

        pred_dir = parsed.get("direction", "FLAT")
        is_correct = pred_dir == expected_dir

        total += 1
        if is_correct:
            correct_dir += 1

        st = sample["scenario_type"]
        by_type[st]["total"] += 1
        by_tier[sample["tier"]]["total"] += 1
        if is_correct:
            by_type[st]["correct"] += 1
            by_tier[sample["tier"]]["correct"] += 1

        confusion[(expected_dir, pred_dir)] += 1

        results.append({
            "i": i,
            "expected": expected_dir,
            "predicted": pred_dir,
            "confidence": parsed.get("confidence", "?"),
            "scenario_type": st,
            "tier": sample["tier"],
            "ok": is_correct,
        })

    # Print results
    print(f"\n{'=' * 60}")
    print(f"AMT Model Evaluation — {total} samples")
    print(f"{'=' * 60}")

    acc = correct_dir / total * 100 if total else 0
    print(f"\nDirection accuracy: {correct_dir}/{total} = {acc:.1f}%")

    print(f"\nBy scenario type:")
    for st in sorted(by_type.keys()):
        d = by_type[st]
        a = d["correct"] / d["total"] * 100 if d["total"] else 0
        print(f"  {st:20s}: {d['correct']:4d}/{d['total']:4d} = {a:.1f}%")

    print(f"\nBy tier:")
    for t in sorted(by_tier.keys()):
        d = by_tier[t]
        a = d["correct"] / d["total"] * 100 if d["total"] else 0
        label = "compact JSON" if t == 1 else "CoT"
        print(f"  Tier {t} ({label}): {d['correct']:4d}/{d['total']:4d} = {a:.1f}%")

    print(f"\nConfusion matrix (expected -> predicted):")
    for key in sorted(confusion.keys()):
        print(f"  {key[0]:5s} -> {key[1]:5s}: {confusion[key]}")

    # Show worst failures
    failures = [r for r in results if not r["ok"]]
    if failures:
        print(f"\nSample failures (first 10):")
        for f in failures[:10]:
            print(f"  [{f['scenario_type']}] exp={f['expected']} pred={f['predicted']} (tier {f['tier']})")

    return {
        "accuracy": acc,
        "correct": correct_dir,
        "total": total,
        "by_type": {k: v["correct"] / v["total"] for k, v in by_type.items() if v["total"]},
    }


def predict_with_mlx(model_path, adapter_path):
    """Create prediction function using MLX model."""
    from mlx_lm import load, generate

    print(f"Loading model: {model_path}")
    if adapter_path:
        print(f"  with adapter: {adapter_path}")

    model, tokenizer = load(model_path, adapter_path=adapter_path or None)
    print("Model loaded.")

    def predict(system_msg, user_msg):
        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ]
        prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        output = generate(model, tokenizer, prompt=prompt, max_tokens=256, temp=0.1)
        return output

    return predict


def predict_with_api(api_url, api_key, model_name):
    """Create prediction function using OpenRouter API."""
    import urllib.request

    def predict(system_msg, user_msg):
        payload = json.dumps({
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            "max_tokens": 256,
            "temperature": 0.1,
        }).encode()

        req = urllib.request.Request(
            api_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"]

    return predict


def main():
    parser = argparse.ArgumentParser(description="Evaluate AMT model")
    parser.add_argument("--model-path", default="mlx-community/gemma-4-e2b-8bit")
    parser.add_argument("--adapter-path", default=None)
    parser.add_argument("--test-set", default="amt_dataset/test.jsonl")
    parser.add_argument("--max-samples", type=int, default=None)
    parser.add_argument("--use-openrouter", action="store_true")
    parser.add_argument("--api-url", default="https://openrouter.ai/api/v1/chat/completions")
    parser.add_argument("--model-name", default="google/gemma-3-4b-it:free")
    args = parser.parse_args()

    samples = load_test_set(args.test_set)
    print(f"Loaded {len(samples)} test samples from {args.test_set}")

    if args.use_openrouter:
        import os
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            print("ERROR: set OPENROUTER_API_KEY environment variable")
            sys.exit(1)
        predict_fn = predict_with_api(args.api_url, api_key, args.model_name)
    else:
        predict_fn = predict_with_mlx(args.model_path, args.adapter_path)

    result = evaluate(samples, predict_fn, max_samples=args.max_samples)

    # Save results
    out_path = Path("evaluation/amt_eval_results.json")
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
