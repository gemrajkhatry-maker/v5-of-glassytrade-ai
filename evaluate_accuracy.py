#!/usr/bin/env python3
"""
Accuracy evaluation script for fine-tuned LoRA adapters.
Tests model predictions against ground truth from the test dataset.
"""

import json
import time
import re
from pathlib import Path
from typing import Dict, List, Tuple
from collections import defaultdict

# Load test dataset
def load_test_data(test_file: str = "fabio_amt_dataset/test.jsonl", max_samples: int = 100) -> List[Dict]:
    """Load test samples from JSONL file."""
    samples = []
    with open(test_file, 'r') as f:
        for line in f:
            if len(samples) >= max_samples:
                break
            data = json.loads(line)
            messages = data['messages']
            
            # Extract user input and expected output
            user_content = messages[0]['content']
            assistant_content = messages[1]['content']
            
            # Parse expected decision
            expected_state = None
            expected_trade = None
            
            for line_text in assistant_content.split('\n'):
                if line_text.startswith('STATE:'):
                    expected_state = line_text.replace('STATE:', '').strip()
                elif line_text.startswith('TRADE:'):
                    expected_trade = line_text.replace('TRADE:', '').strip()
            
            samples.append({
                'input': user_content,
                'expected_state': expected_state,
                'expected_trade': expected_trade
            })
    
    return samples

def extract_model_decision(output: str) -> Dict:
    """Extract STATE and TRADE decisions from model output."""
    state = None
    trade = None
    
    # Look for STATE: and TRADE: patterns
    for line in output.split('\n'):
        line = line.strip()
        if line.startswith('STATE:'):
            state = line.replace('STATE:', '').strip()
        elif line.startswith('TRADE:'):
            # Take the first TRADE decision
            if trade is None:
                trade = line.replace('TRADE:', '').strip()
    
    # If not found with STATE:/TRADE: pattern, try to infer from text
    if trade is None:
        output_lower = output.lower()
        if 'long' in output_lower:
            trade = 'LONG'
        elif 'short' in output_lower:
            trade = 'SHORT'
        elif 'flat' in output_lower or 'no trade' in output_lower:
            trade = 'FLAT'
    
    if state is None:
        # Try to infer state from context
        output_lower = output.lower()
        if 'breakout' in output_lower:
            state = 'BREAKOUT'
        elif 'trend' in output_lower:
            state = 'TREND'
        elif 'rejection' in output_lower or 'reversal' in output_lower:
            state = 'REJECTION'
        elif 'rotation' in output_lower or 'balance' in output_lower or 'ranging' in output_lower:
            state = 'ROTATION'
        elif 'exhaustion' in output_lower:
            state = 'EXHAUSTION'
        elif 'failed' in output_lower:
            state = 'FAILED BREAKOUT'
    
    return {
        'state': state,
        'trade': trade
    }

def evaluate_accuracy(model_path: str, adapter_path: str, test_samples: List[Dict]) -> Dict:
    """Evaluate model accuracy on test samples."""
    try:
        from mlx_lm import load, generate
        
        print(f"\n{'='*80}")
        print(f"Loading model: {model_path}")
        print(f"Adapter: {adapter_path}")
        print(f"{'='*80}")
        
        # Load model
        start_load = time.time()
        model, tokenizer = load(model_path, adapter_path=adapter_path)
        load_time = time.time() - start_load
        print(f"✓ Model loaded in {load_time:.2f}s")
        
        results = []
        correct_state = 0
        correct_trade = 0
        total = len(test_samples)
        
        print(f"\nEvaluating {total} samples...\n")
        
        for i, sample in enumerate(test_samples):
            start = time.time()
            
            # Format as chat conversation for Gemma 4 IT
            messages = [{"role": "user", "content": sample['input']}]
            prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            
            # Generate prediction
            output = generate(
                model,
                tokenizer,
                prompt=prompt,
                max_tokens=50,  # Keep it short for STATE/TRADE
                verbose=False
            )
            
            inference_time = time.time() - start
            
            # Extract decisions
            predicted = extract_model_decision(output)
            
            # Check accuracy
            state_correct = (predicted['state'] == sample['expected_state']) if predicted['state'] else False
            trade_correct = (predicted['trade'] == sample['expected_trade']) if predicted['trade'] else False
            
            if state_correct:
                correct_state += 1
            if trade_correct:
                correct_trade += 1
            
            results.append({
                'sample_idx': i,
                'expected_state': sample['expected_state'],
                'expected_trade': sample['expected_trade'],
                'predicted_state': predicted['state'],
                'predicted_trade': predicted['trade'],
                'state_correct': state_correct,
                'trade_correct': trade_correct,
                'inference_time': inference_time,
                'output': output[:200]
            })
            
            # Progress indicator
            if (i + 1) % 10 == 0:
                acc_state = (correct_state / (i + 1)) * 100
                acc_trade = (correct_trade / (i + 1)) * 100
                print(f"  Processed {i+1}/{total} samples...")
                print(f"    State Accuracy: {acc_state:.1f}% | Trade Accuracy: {acc_trade:.1f}%")
        
        # Calculate final metrics
        final_state_acc = (correct_state / total) * 100
        final_trade_acc = (correct_trade / total) * 100
        avg_inference_time = sum(r['inference_time'] for r in results) / total
        
        return {
            'success': True,
            'load_time': load_time,
            'total_samples': total,
            'correct_state': correct_state,
            'correct_trade': correct_trade,
            'state_accuracy': final_state_acc,
            'trade_accuracy': final_trade_acc,
            'avg_inference_time': avg_inference_time,
            'results': results,
            'error': None
        }
        
    except Exception as e:
        print(f"✗ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'success': False,
            'load_time': 0,
            'total_samples': 0,
            'correct_state': 0,
            'correct_trade': 0,
            'state_accuracy': 0,
            'trade_accuracy': 0,
            'avg_inference_time': 0,
            'results': [],
            'error': str(e)
        }

def print_detailed_report(eval_result: Dict):
    """Print detailed accuracy report."""
    if not eval_result['success']:
        print(f"\n✗ Evaluation failed: {eval_result['error']}")
        return
    
    print("\n" + "="*80)
    print("ACCURACY EVALUATION REPORT")
    print("="*80)
    
    print(f"\n📊 Overall Performance:")
    print(f"  Total Samples: {eval_result['total_samples']}")
    print(f"  Model Load Time: {eval_result['load_time']:.2f}s")
    print(f"  Avg Inference Time: {eval_result['avg_inference_time']:.2f}s")
    
    print(f"\n🎯 Accuracy Metrics:")
    print(f"  STATE Accuracy: {eval_result['state_accuracy']:.1f}% ({eval_result['correct_state']}/{eval_result['total_samples']})")
    print(f"  TRADE Accuracy: {eval_result['trade_accuracy']:.1f}% ({eval_result['correct_trade']}/{eval_result['total_samples']})")
    
    # Analyze by trade type
    trade_confusion = defaultdict(lambda: defaultdict(int))
    for r in eval_result['results']:
        expected = r['expected_trade'] or 'UNKNOWN'
        predicted = r['predicted_trade'] or 'UNKNOWN'
        trade_confusion[expected][predicted] += 1
    
    print(f"\n📈 Trade Decision Confusion Matrix:")
    print(f"{'Expected/Predicted':<20}", end="")
    all_predictions = set()
    for expected in trade_confusion:
        for predicted in trade_confusion[expected]:
            all_predictions.add(predicted)
    for pred in sorted(all_predictions):
        print(f"{pred:<15}", end="")
    print()
    print("-" * 80)
    
    for expected in sorted(trade_confusion.keys()):
        print(f"{expected:<20}", end="")
        for pred in sorted(all_predictions):
            count = trade_confusion[expected].get(pred, 0)
            print(f"{count:<15}", end="")
        print()
    
    # Show sample predictions
    print(f"\n📝 Sample Predictions (first 10):")
    print("-" * 80)
    for r in eval_result['results'][:10]:
        state_icon = "✓" if r['state_correct'] else "✗"
        trade_icon = "✓" if r['trade_correct'] else "✗"
        print(f"\nSample {r['sample_idx'] + 1}:")
        print(f"  Expected:  STATE={r['expected_state']:<20} TRADE={r['expected_trade']:<10}")
        print(f"  Predicted: STATE={r['predicted_state'] or 'N/A':<20} TRADE={r['predicted_trade'] or 'N/A':<10}")
        print(f"  Accuracy:  STATE {state_icon}  TRADE {trade_icon}")
        print(f"  Output: {r['output'][:100]}...")
    
    # Performance grade
    print(f"\n{'='*80}")
    print("PERFORMANCE GRADING")
    print("="*80)
    
    trade_acc = eval_result['trade_accuracy']
    if trade_acc >= 90:
        grade = "A+ (Excellent)"
        comment = "Production-ready accuracy"
    elif trade_acc >= 80:
        grade = "A (Very Good)"
        comment = "Suitable for production with monitoring"
    elif trade_acc >= 70:
        grade = "B (Good)"
        comment = "Acceptable, but could benefit from more training"
    elif trade_acc >= 60:
        grade = "C (Fair)"
        comment = "Needs improvement - more training data or iterations"
    else:
        grade = "D (Poor)"
        comment = "Significant retraining required"
    
    print(f"\n  Grade: {grade}")
    print(f"  Comment: {comment}")
    print(f"  Trade Accuracy: {trade_acc:.1f}%")
    
    if trade_acc < 70:
        print(f"\n⚠️  Recommendations:")
        print(f"  - Increase training iterations")
        print(f"  - Add more diverse training examples")
        print(f"  - Consider increasing LoRA rank")
        print(f"  - Review training data quality")

def main():
    print("🎯 Starting Accuracy Evaluation")
    print("="*80)
    
    # Load test data
    print("\nLoading test dataset...")
    test_samples = load_test_data(max_samples=50)  # Start with 50 samples
    print(f"✓ Loaded {len(test_samples)} test samples")
    
    # Evaluate the newly trained Gemma 4 26B model
    model_path = "mlx-community/gemma-4-26b-a4b-it-4bit"
    adapter_path = "./gemma4_26b_amt_adapter"
    
    eval_result = evaluate_accuracy(model_path, adapter_path, test_samples)
    
    # Print detailed report
    print_detailed_report(eval_result)
    
    # Save results
    output_file = Path("accuracy_results.json")
    with open(output_file, "w") as f:
        # Create serializable version
        serializable = {
            'success': eval_result['success'],
            'load_time': eval_result['load_time'],
            'total_samples': eval_result['total_samples'],
            'correct_state': eval_result['correct_state'],
            'correct_trade': eval_result['correct_trade'],
            'state_accuracy': eval_result['state_accuracy'],
            'trade_accuracy': eval_result['trade_accuracy'],
            'avg_inference_time': eval_result['avg_inference_time'],
            'error': eval_result['error'],
            'sample_predictions': [
                {
                    'sample_idx': r['sample_idx'],
                    'expected_state': r['expected_state'],
                    'expected_trade': r['expected_trade'],
                    'predicted_state': r['predicted_state'],
                    'predicted_trade': r['predicted_trade'],
                    'state_correct': r['state_correct'],
                    'trade_correct': r['trade_correct'],
                    'output_snippet': r['output'][:150]
                }
                for r in eval_result['results'][:20]  # Save first 20 samples
            ]
        }
        json.dump(serializable, f, indent=2)
    
    print(f"\n✓ Detailed results saved to {output_file}")

if __name__ == "__main__":
    main()
