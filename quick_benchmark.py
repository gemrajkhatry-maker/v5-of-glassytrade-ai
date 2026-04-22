import json
import time
import os
from pathlib import Path
from mlx_lm import load, generate

def load_test_samples(file_path, count=3):
    samples = []
    with open(file_path, 'r') as f:
        for i, line in enumerate(f):
            if i >= count:
                break
            data = json.loads(line)
            # Standard dataset format
            messages = data.get('messages', [])
            if messages:
                user_msg = [m['content'] for m in messages if m['role'] == 'user'][0]
                assistant_msg = [m['content'] for m in messages if m['role'] == 'assistant'][0]
                samples.append({'input': user_msg, 'expected': assistant_msg})
    return samples

def benchmark_model(model_name, model_path, adapter_path, test_samples):
    print(f"\n🚀 Benchmarking {model_name}...")
    try:
        start_load = time.time()
        model, tokenizer = load(model_path, adapter_path=adapter_path)
        load_time = time.time() - start_load
        
        individual_latencies = []
        accuracies = []
        
        for sample in test_samples:
            prompt = tokenizer.apply_chat_template([{"role": "user", "content": sample['input']}], tokenize=False, add_generation_prompt=True)
            
            start_gen = time.time()
            output = generate(model, tokenizer, prompt=prompt, max_tokens=100, verbose=False)
            gen_time = time.time() - start_gen
            individual_latencies.append(gen_time)
            
            # Basic accuracy check
            expected = sample['expected'].strip()
            # Check if expected STATE: and TRADE: are in output
            expected_state = ""
            expected_trade = ""
            for line in expected.split('\n'):
                if 'STATE:' in line: expected_state = line.split('STATE:')[1].strip()
                if 'TRADE:' in line: expected_trade = line.split('TRADE:')[1].strip()
            
            match_state = expected_state in output if expected_state else True
            match_trade = expected_trade in output if expected_trade else True
            
            accuracies.append(match_state and match_trade)
            print(f"  - Sample complete. Latency: {gen_time:.2f}s | Match: {match_state and match_trade}")
            print(f"    Raw Output: {output[:150].replace('\n', ' ')}...")

        avg_latency = sum(individual_latencies) / len(individual_latencies)
        accuracy_rate = (sum(accuracies) / len(accuracies)) * 100
        
        return {
            'name': model_name,
            'load_time': load_time,
            'avg_latency': avg_latency,
            'accuracy': accuracy_rate,
            'success': True
        }
    except Exception as e:
        print(f"  ❌ Error loading/running {model_name}: {e}")
        return {'name': model_name, 'success': False, 'error': str(e)}

def main():
    test_data_path = "fabio_amt_dataset/test.jsonl"
    if not os.path.exists(test_data_path):
        print(f"Error: {test_data_path} not found.")
        return
        
    samples = load_test_samples(test_data_path, count=3)
    print(f"Loaded {len(samples)} test samples.")
    
    candidates = [
        {
            'name': 'Qwen 0.8B (Fastest)',
            'model': 'poc4/mlx_model/qwen35-0.8b-4bit',
            'adapter': 'poc4/qwen35_mlx_adapters'
        },
        {
            'name': 'Gemma 4 4B (Balanced)',
            'model': 'mlx-community/gemma-4-e4b-it-nvfp4',
            'adapter': 'poc_gemma4_e4b/adapters'
        },
        {
            'name': 'Gemma 4 26B (Powerhouse)',
            'model': 'mlx-community/gemma-4-26b-a4b-it-4bit',
            'adapter': 'gemma4_26b_amt_adapter_test'
        }
    ]
    
    summary = []
    for cand in candidates:
        res = benchmark_model(cand['name'], cand['model'], cand['adapter'], samples)
        summary.append(res)
    
    print("\n" + "="*50)
    print("FINAL BENCHMARK RESULTS")
    print("="*50)
    print(f"{'Model':<25} | {'Load':<8} | {'Inference':<10} | {'Accuracy':<8}")
    print("-" * 50)
    for s in summary:
        if s['success']:
            print(f"{s['name']:<25} | {s['load_time']:<8.2f}s | {s['avg_latency']:<10.2f}s | {s['accuracy']:<8.1f}%")
        else:
            print(f"{s['name']:<25} | {'FAILED':<32}")
    print("="*50)

if __name__ == "__main__":
    main()
