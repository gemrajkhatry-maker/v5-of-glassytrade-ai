#!/usr/bin/env python3
"""
Test improved strong_trend_continuation scenarios with logical consistency
Compare v1 (72% accuracy) vs v2 (target: 96%+ accuracy)
"""

import json
import time
import sys
import os
from datetime import datetime
from mlx_lm import load, generate

# Load model
print("Loading model...")
model_path = "lmstudio-community/DeepSeek-R1-0528-Qwen3-8B-MLX-8bit"
adapter_path = "poc_deepseek8b/deepseek8b_amt_adapter"
model, tokenizer = load(model_path, adapter_path=adapter_path)
print("✅ Model loaded")

def extract_json(text):
    """Extract JSON from model response"""
    try:
        # Try direct JSON
        return json.loads(text)
    except:
        # Try finding JSON in text
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1:
            try:
                return json.loads(text[start:end+1])
            except:
                return None
    return None

def evaluate_trend_v2(test_file="validation/deepseek8b_simulation/simulation_data_trend_v2.jsonl"):
    """Evaluate improved trend scenarios"""
    
    # Load test data
    with open(test_file) as f:
        test_data = [json.loads(line) for line in f]
    
    print(f"\n{'='*80}")
    print(f"Testing {len(test_data)} improved trend scenarios")
    print(f"{'='*80}")
    
    results = {
        "model": "DeepSeek-R1-Qwen3-8B-MLX-8bit",
        "adapter": "poc_deepseek8b/deepseek8b_amt_adapter",
        "dataset": test_file,
        "total_samples": len(test_data),
        "evaluated_at": datetime.now().isoformat(),
        "metrics": {},
        "by_subtype": {},
        "detailed_results": [],
        "errors": []
    }
    
    correct_direction = 0
    correct_confidence = 0
    correct_joint = 0
    parse_errors = 0
    
    subtype_performance = {}
    
    start_time = time.time()
    
    for i, test in enumerate(test_data):
        if (i + 1) % 10 == 0:
            elapsed = time.time() - start_time
            speed = (i + 1) / elapsed
            print(f"  Progress: {i+1}/{len(test_data)} ({(i+1)/len(test_data)*100:.1f}%) - {speed:.2f} ex/sec")
        
        # Build messages with system prompt
        messages = test['messages']
        
        try:
            # Generate response
            prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            
            output = generate(
                model,
                tokenizer,
                prompt=prompt,
                max_tokens=512,
                verbose=False
            )
            
            # Parse output
            parsed = extract_json(output)
            
            if parsed is None:
                parse_errors += 1
                results['errors'].append({
                    "index": i,
                    "error": "Failed to parse JSON",
                    "output": output[:200]
                })
                continue
            
            # Extract predictions
            pred_direction = parsed.get('direction', '').upper()
            pred_confidence = parsed.get('confidence', '')
            pred_rationale = parsed.get('rationale', '')
            
            # Get expected values
            expected_direction = test['metadata']['expected_direction']
            expected_confidence = test['metadata']['expected_confidence']
            scenario_subtype = test['metadata']['scenario_subtype']
            
            # Check accuracy
            dir_match = pred_direction == expected_direction
            conf_match = pred_confidence == expected_confidence
            
            if dir_match:
                correct_direction += 1
            if conf_match:
                correct_confidence += 1
            if dir_match and conf_match:
                correct_joint += 1
            
            # Track subtype performance
            if scenario_subtype not in subtype_performance:
                subtype_performance[scenario_subtype] = {"correct": 0, "total": 0}
            
            subtype_performance[scenario_subtype]['total'] += 1
            if dir_match:
                subtype_performance[scenario_subtype]['correct'] += 1
            
            # Store result
            results['detailed_results'].append({
                "index": i,
                "scenario_subtype": scenario_subtype,
                "expected_direction": expected_direction,
                "expected_confidence": expected_confidence,
                "predicted_direction": pred_direction,
                "predicted_confidence": pred_confidence,
                "predicted_rationale": pred_rationale,
                "direction_correct": dir_match,
                "confidence_correct": conf_match
            })
            
        except Exception as e:
            results['errors'].append({
                "index": i,
                "error": str(e)
            })
            parse_errors += 1
    
    elapsed_time = time.time() - start_time
    
    # Calculate metrics
    total_evaluated = len(test_data) - parse_errors
    
    results['metrics'] = {
        "direction_accuracy": correct_direction / total_evaluated if total_evaluated > 0 else 0,
        "confidence_accuracy": correct_confidence / total_evaluated if total_evaluated > 0 else 0,
        "joint_accuracy": correct_joint / total_evaluated if total_evaluated > 0 else 0,
        "parse_errors": parse_errors,
        "total_evaluated": total_evaluated,
        "evaluation_time_seconds": elapsed_time,
        "speed_examples_per_sec": total_evaluated / elapsed_time if elapsed_time > 0 else 0
    }
    
    # Store subtype performance
    results['by_subtype'] = subtype_performance
    
    # Print results
    print(f"\n{'='*80}")
    print("IMPROVED STRONG TREND CONTINUATION - RESULTS")
    print(f"{'='*80}")
    print(f"Direction Accuracy:  {results['metrics']['direction_accuracy']:.2%} ({correct_direction}/{total_evaluated})")
    print(f"Confidence Accuracy: {results['metrics']['confidence_accuracy']:.2%} ({correct_confidence}/{total_evaluated})")
    print(f"Joint Accuracy:      {results['metrics']['joint_accuracy']:.2%} ({correct_joint}/{total_evaluated})")
    print(f"Parse Errors:        {parse_errors}")
    print(f"Speed:               {results['metrics']['speed_examples_per_sec']:.2f} examples/sec")
    
    print(f"\nScenario Subtype Performance:")
    for subtype, perf in sorted(subtype_performance.items(), key=lambda x: -x[1]['correct']/x[1]['total']):
        accuracy = perf['correct'] / perf['total']
        status = "✅" if accuracy >= 0.95 else "⚠️" if accuracy >= 0.80 else "❌"
        print(f"  {status} {subtype}: {accuracy:.1%} ({perf['correct']}/{perf['total']})")
    
    print(f"\n{'='*80}")
    
    # Compare with v1
    print("\nCOMPARISON: v1 vs v2")
    print(f"  v1 (original): 72.0% accuracy (18/25 correct)")
    print(f"  v2 (improved): {results['metrics']['direction_accuracy']:.1%} accuracy ({correct_direction}/{total_evaluated} correct)")
    
    improvement = results['metrics']['direction_accuracy'] - 0.72
    if improvement > 0:
        print(f"  ✅ Improvement: +{improvement:.1%} percentage points")
    else:
        print(f"  ⚠️ No improvement: {improvement:+.1%}")
    
    print(f"{'='*80}")
    
    # Save results
    output_file = "validation/deepseek8b_simulation/trend_v2_results.json"
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\n✅ Results saved to: {output_file}")
    
    return results

if __name__ == "__main__":
    results = evaluate_trend_v2()
