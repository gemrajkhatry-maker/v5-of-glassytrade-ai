#!/usr/bin/env python3
"""
Evaluate DeepSeek R1 Qwen3 8B on realistic market simulation data
Tests model against known market scenarios with expected outcomes
"""

import sys
sys.path.insert(0, '/Users/apple/Downloads/v5-of-glassytrade-ai/backend')

from mlx_lm import load, generate
import json
import time
from datetime import datetime
from collections import defaultdict, Counter

# Load the trained model
print("Loading DeepSeek R1 Qwen3 8B model...")
model_path = "lmstudio-community/DeepSeek-R1-0528-Qwen3-8B-MLX-8bit"
adapter_path = "poc_deepseek8b/deepseek8b_amt_adapter"

model, tokenizer = load(model_path, adapter_path=adapter_path)
print("✅ Model loaded successfully!\n")

# Load simulation dataset
sim_file = "validation/deepseek8b_simulation/simulation_data.jsonl"
print(f"Loading simulation data: {sim_file}")

sim_data = []
with open(sim_file, 'r') as f:
    for line in f:
        sim_data.append(json.loads(line))

print(f"Loaded {len(sim_data)} simulation scenarios\n")

# Evaluation tracking
results = {
    "model": "DeepSeek-R1-Qwen3-8B-MLX-8bit",
    "adapter": "poc_deepseek8b/deepseek8b_amt_adapter",
    "dataset": sim_file,
    "total_samples": len(sim_data),
    "evaluated_at": datetime.now().isoformat(),
    "metrics": {},
    "by_scenario": {},
    "confusion_matrix": {},
    "errors": [],
    "detailed_results": []
}

total = 0
direction_correct = 0
confidence_correct = 0
joint_correct = 0
parse_errors = 0

direction_confusion = defaultdict(lambda: defaultdict(int))
scenario_performance = defaultdict(lambda: {"total": 0, "correct": 0})

start_time = time.time()

print(f"{'='*80}")
print(f"STARTING SIMULATION EVALUATION")
print(f"{'='*80}\n")

for i, example in enumerate(sim_data):
    metadata = example['metadata']
    messages = example['messages']
    
    # Extract ground truth
    gt_direction = metadata['expected_direction']
    gt_confidence = metadata['expected_confidence']
    scenario_type = metadata['scenario_type']
    scenario_desc = metadata['scenario_description']
    
    # Get user input and system prompt
    system_msg = messages[0]['content']
    user_msg = messages[1]['content']
    
    # Format prompt
    prompt_messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg}
    ]
    prompt = tokenizer.apply_chat_template(prompt_messages, add_generation_prompt=True)
    
    # Generate prediction
    try:
        response = generate(
            model,
            tokenizer,
            prompt=prompt,
            max_tokens=256,
            verbose=False
        )
        
        # Parse prediction
        if '{' in response and '}' in response:
            json_start = response.rfind('{')
            json_end = response.rfind('}') + 1
            pred_json = json.loads(response[json_start:json_end])
            
            pred_direction = pred_json.get('direction', 'UNKNOWN')
            pred_confidence = pred_json.get('confidence', 'UNKNOWN')
            pred_rationale = pred_json.get('rationale', '')
            
            # Evaluate
            total += 1
            dir_match = pred_direction == gt_direction
            conf_match = pred_confidence == gt_confidence
            
            if dir_match:
                direction_correct += 1
            if conf_match:
                confidence_correct += 1
            if dir_match and conf_match:
                joint_correct += 1
            
            # Track confusion
            direction_confusion[gt_direction][pred_direction] += 1
            
            # Track scenario performance
            scenario_performance[scenario_type]['total'] += 1
            if dir_match:
                scenario_performance[scenario_type]['correct'] += 1
            
            # Progress update
            if (i + 1) % 25 == 0:
                elapsed = time.time() - start_time
                speed = (i + 1) / elapsed
                eta = (len(sim_data) - i - 1) / speed if speed > 0 else 0
                dir_acc = direction_correct / total * 100 if total > 0 else 0
                print(f"Progress: {i+1}/{len(sim_data)} | "
                      f"Dir Acc: {direction_correct}/{total} ({dir_acc:.1f}%) | "
                      f"Speed: {speed:.2f} ex/sec | ETA: {eta:.0f}s")
            
            # Store detailed result
            results['detailed_results'].append({
                "index": i,
                "scenario_type": scenario_type,
                "scenario_description": scenario_desc,
                "expected_direction": gt_direction,
                "expected_confidence": gt_confidence,
                "predicted_direction": pred_direction,
                "predicted_confidence": pred_confidence,
                "predicted_rationale": pred_rationale,
                "direction_correct": dir_match,
                "confidence_correct": conf_match
            })
        else:
            parse_errors += 1
            results['errors'].append({
                "index": i,
                "scenario_type": scenario_type,
                "error": "No JSON found in response",
                "response": response[:200]
            })
    except Exception as e:
        parse_errors += 1
        results['errors'].append({
            "index": i,
            "scenario_type": scenario_type,
            "error": str(e)
        })

# Calculate final metrics
elapsed = time.time() - start_time
direction_acc = direction_correct / total if total > 0 else 0
confidence_acc = confidence_correct / total if total > 0 else 0
joint_acc = joint_correct / total if total > 0 else 0

# Store metrics
results['metrics'] = {
    "direction_accuracy": direction_acc,
    "confidence_accuracy": confidence_acc,
    "joint_accuracy": joint_acc,
    "parse_errors": parse_errors,
    "total_evaluated": total,
    "evaluation_time_seconds": elapsed,
    "speed_examples_per_sec": total / elapsed if elapsed > 0 else 0
}

# Store confusion matrix
results['confusion_matrix'] = {
    gt: dict(preds) for gt, preds in direction_confusion.items()
}

# Store scenario performance
for scenario, perf in scenario_performance.items():
    results['by_scenario'][scenario] = {
        "accuracy": perf['correct'] / perf['total'] if perf['total'] > 0 else 0,
        "correct": perf['correct'],
        "total": perf['total']
    }

# Print results
print(f"\n{'='*80}")
print(f"SIMULATION EVALUATION COMPLETE")
print(f"{'='*80}")

print(f"\n📊 OVERALL PERFORMANCE:")
print(f"  Direction Accuracy:  {direction_acc*100:.2f}% ({direction_correct}/{total})")
print(f"  Confidence Accuracy: {confidence_acc*100:.2f}% ({confidence_correct}/{total})")
print(f"  Joint Accuracy:      {joint_acc*100:.2f}% ({joint_correct}/{total})")
print(f"  Parse Errors:        {parse_errors}")
print(f"  Evaluation Time:     {elapsed:.1f}s")
print(f"  Speed:               {total/elapsed:.2f} examples/sec")

print(f"\n📈 CONFUSION MATRIX:")
print(f"  {'Actual ↓ / Predicted →':<25}", end="")
all_dirs = sorted(set().union(*[set(d.keys()) for d in direction_confusion.values()]))
for d in all_dirs:
    print(f"{d:<10}", end="")
print()

for gt_dir in sorted(direction_confusion.keys()):
    print(f"  {gt_dir:<25}", end="")
    for pred_dir in all_dirs:
        count = direction_confusion[gt_dir][pred_dir]
        marker = "✅" if gt_dir == pred_dir else "❌"
        print(f"{count}{marker:<8}", end="")
    print()

print(f"\n🎯 SCENARIO PERFORMANCE:")
for scenario, perf in sorted(results['by_scenario'].items()):
    acc = perf['accuracy'] * 100
    status = "✅" if acc >= 90 else "⚠️" if acc >= 75 else "❌"
    print(f"  {status} {scenario:<30} {acc:5.1f}% ({perf['correct']}/{perf['total']})")

# Save results
output_file = "validation/deepseek8b_simulation/evaluation_results.json"
with open(output_file, 'w') as f:
    json.dump(results, f, indent=2)

print(f"\n{'='*80}")
print(f"✅ Results saved to: {output_file}")
print(f"{'='*80}")

# Generate summary report
report_file = "validation/deepseek8b_simulation/SIMULATION_REPORT.md"
with open(report_file, 'w') as f:
    f.write(f"# DeepSeek R1 Qwen3 8B - Market Simulation Report\n\n")
    f.write(f"**Evaluation Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    f.write(f"**Model**: DeepSeek-R1-Qwen3-8B-MLX-8bit\n")
    f.write(f"**Adapter**: poc_deepseek8b/deepseek8b_amt_adapter\n")
    f.write(f"**Dataset**: 200 realistic market scenarios\n\n")
    
    f.write(f"## Overall Performance\n\n")
    f.write(f"| Metric | Score |\n")
    f.write(f"|--------|-------|\n")
    f.write(f"| Direction Accuracy | {direction_acc*100:.2f}% |\n")
    f.write(f"| Confidence Accuracy | {confidence_acc*100:.2f}% |\n")
    f.write(f"| Joint Accuracy | {joint_acc*100:.2f}% |\n")
    f.write(f"| Parse Errors | {parse_errors} |\n")
    f.write(f"| Speed | {total/elapsed:.2f} examples/sec |\n\n")
    
    f.write(f"## Scenario Performance\n\n")
    f.write(f"| Scenario | Accuracy | Correct/Total |\n")
    f.write(f"|----------|----------|---------------|\n")
    for scenario, perf in sorted(results['by_scenario'].items()):
        acc = perf['accuracy'] * 100
        f.write(f"| {scenario} | {acc:.1f}% | {perf['correct']}/{perf['total']} |\n")
    
    f.write(f"\n## Confusion Matrix\n\n")
    f.write(f"| Actual \\ Predicted |")
    for d in all_dirs:
        f.write(f" {d} |")
    f.write(f"\n|---|")
    for _ in all_dirs:
        f.write(f"---|")
    f.write(f"\n")
    
    for gt_dir in sorted(direction_confusion.keys()):
        f.write(f"| {gt_dir} |")
        for pred_dir in all_dirs:
            count = direction_confusion[gt_dir][pred_dir]
            f.write(f" {count} |")
        f.write(f"\n")

print(f"✅ Report saved to: {report_file}")
