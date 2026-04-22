#!/usr/bin/env python3
"""
Comprehensive accuracy evaluation for all trained models.
Tests poc3, poc4, poc8, and gemma4_26b models.
"""

import json
import time
import re
from pathlib import Path
from typing import Dict, List
from collections import defaultdict

def load_test_data(test_file: str = "fabio_amt_dataset/test.jsonl", max_samples: int = 50) -> List[Dict]:
    """Load test samples from JSONL file."""
    samples = []
    with open(test_file, 'r') as f:
        for i, line in enumerate(f):
            if i >= max_samples:
                break
            data = json.loads(line)
            messages = data['messages']
            assistant_content = messages[1]['content']
            
            expected_state = None
            expected_trade = None
            for line_text in assistant_content.split('\n'):
                if line_text.startswith('STATE:'):
                    expected_state = line_text.replace('STATE:', '').strip()
                elif line_text.startswith('TRADE:'):
                    expected_trade = line_text.replace('TRADE:', '').strip()
            
            samples.append({
                'input': messages[0]['content'],
                'expected_state': expected_state,
                'expected_trade': expected_trade
            })
    return samples

def parse_state_trade(text: str) -> Dict[str, str]:
    """Parse STATE:/TRADE: format from model output."""
    state = None
    trade = None
    
    for line in text.split('\n'):
        if line.startswith('STATE:'):
            state = line.replace('STATE:', '').strip()
        elif line.startswith('TRADE:'):
            trade = line.replace('TRADE:', '').strip()
    
    return {'state': state, 'trade': trade}

def evaluate_model(model_path: str, adapter_path: str, test_samples: List[Dict], model_name: str) -> Dict:
    """Evaluate a single model on test samples."""
    try:
        from mlx_lm import load, generate
        
        print(f"\n{'='*80}")
        print(f"Testing: {model_name}")
        print(f"Model: {model_path}")
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
        inference_times = []
        
        print(f"\nEvaluating {total} samples...\n")
        
        for i, sample in enumerate(test_samples):
            start = time.time()
            
            # Format as chat conversation
            messages = [{"role": "user", "content": sample['input']}]
            prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            
            # Generate prediction
            output = generate(
                model,
                tokenizer,
                prompt=prompt,
                max_tokens=50,
                verbose=False
            )
            
            elapsed = time.time() - start
            inference_times.append(elapsed)
            
            # Parse output
            parsed = parse_state_trade(output)
            predicted_state = parsed.get('state')
            predicted_trade = parsed.get('trade')
            
            state_correct = predicted_state == sample['expected_state']
            trade_correct = predicted_trade == sample['expected_trade']
            
            if state_correct:
                correct_state += 1
            if trade_correct:
                correct_trade += 1
            
            results.append({
                'sample_idx': i,
                'expected_state': sample['expected_state'],
                'expected_trade': sample['expected_trade'],
                'predicted_state': predicted_state,
                'predicted_trade': predicted_trade,
                'state_correct': state_correct,
                'trade_correct': trade_correct,
                'output': output[:200],
                'inference_time': elapsed
            })
            
            print(f"  - Sample complete. Latency: {elapsed:.2f}s | Match: {trade_correct}")
            print(f"    Raw Output: {output[:150]}...")
        
        avg_inference = sum(inference_times) / len(inference_times)
        
        # Build confusion matrix
        trade_confusion = defaultdict(lambda: defaultdict(int))
        for r in results:
            expected = r['expected_trade'] or 'UNKNOWN'
            predicted = r['predicted_trade'] or 'UNKNOWN'
            trade_confusion[expected][predicted] += 1
        
        return {
            'success': True,
            'model_name': model_name,
            'load_time': load_time,
            'total_samples': total,
            'correct_state': correct_state,
            'correct_trade': correct_trade,
            'state_accuracy': correct_state / total * 100 if total > 0 else 0,
            'trade_accuracy': correct_trade / total * 100 if total > 0 else 0,
            'avg_inference_time': avg_inference,
            'results': results,
            'trade_confusion': dict(trade_confusion),
            'error': None
        }
        
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return {
            'success': False,
            'model_name': model_name,
            'error': str(e)
        }

def print_comparison(all_results: List[Dict]):
    """Print comparison table."""
    print(f"\n{'='*100}")
    print("MODEL COMPARISON SUMMARY")
    print(f"{'='*100}")
    print(f"{'Model':<25} {'Load (s)':<10} {'Infer (s)':<10} {'STATE Acc':<12} {'TRADE Acc':<12} {'Grade':<10}")
    print(f"{'-'*100}")
    
    for result in all_results:
        if result['success']:
            trade_acc = result['trade_accuracy']
            if trade_acc >= 90:
                grade = "A+ (Excellent)"
            elif trade_acc >= 80:
                grade = "A (Very Good)"
            elif trade_acc >= 70:
                grade = "B (Good)"
            elif trade_acc >= 60:
                grade = "C (Acceptable)"
            elif trade_acc >= 50:
                grade = "D (Poor)"
            else:
                grade = "F (Failed)"
            
            print(f"{result['model_name']:<25} {result['load_time']:<10.2f} {result['avg_inference_time']:<10.2f} {result['state_accuracy']:<11.1f}% {result['trade_accuracy']:<11.1f}% {grade}")
        else:
            print(f"{result['model_name']:<25} {'N/A':<10} {'N/A':<10} {'N/A':<12} {'N/A':<12} {'FAILED':<10}")
            print(f"  Error: {result['error']}")
    
    print(f"{'='*100}")

def main():
    print("🎯 Starting Comprehensive Model Evaluation")
    print(f"{'='*80}")
    
    # Load test data
    print("\nLoading test dataset...")
    test_samples = load_test_data(max_samples=50)
    print(f"✓ Loaded {len(test_samples)} test samples")
    
    # Define models to test
    models = [
        {
            'name': 'poc8 (Qwen 4B)',
            'model_path': '/Users/apple/Downloads/v5-of-glassytrade-ai/poc8/model',
            'adapter_path': '/Users/apple/Downloads/v5-of-glassytrade-ai/poc8/adapters'
        },
        {
            'name': 'poc4 (Qwen 0.8B)',
            'model_path': 'poc4/mlx_model/qwen35-0.8b-4bit',
            'adapter_path': 'poc4/qwen35_mlx_adapters'
        },
        {
            'name': 'poc3 (Options)',
            'model_path': 'poc3/mlx_model',
            'adapter_path': 'poc3/lora_adapter_options_mlx'
        },
        {
            'name': 'gemma4_26b (26B)',
            'model_path': 'mlx-community/gemma-4-26b-a4b-it-4bit',
            'adapter_path': './gemma4_26b_amt_adapter_test'
        }
    ]
    
    all_results = []
    
    for model_config in models:
        result = evaluate_model(
            model_config['model_path'],
            model_config['adapter_path'],
            test_samples,
            model_config['name']
        )
        all_results.append(result)
    
    # Print comparison
    print_comparison(all_results)
    
    # Save results
    output_file = Path("all_models_comparison.json")
    with open(output_file, "w") as f:
        # Create serializable version
        serializable = []
        for r in all_results:
            if r['success']:
                serializable.append({
                    'model_name': r['model_name'],
                    'success': True,
                    'load_time': r['load_time'],
                    'total_samples': r['total_samples'],
                    'correct_state': r['correct_state'],
                    'correct_trade': r['correct_trade'],
                    'state_accuracy': r['state_accuracy'],
                    'trade_accuracy': r['trade_accuracy'],
                    'avg_inference_time': r['avg_inference_time'],
                    'error': None
                })
            else:
                serializable.append({
                    'model_name': r['model_name'],
                    'success': False,
                    'error': r['error']
                })
        
        json.dump(serializable, f, indent=2)
    
    print(f"\n✓ Results saved to {output_file}")

if __name__ == "__main__":
    main()
