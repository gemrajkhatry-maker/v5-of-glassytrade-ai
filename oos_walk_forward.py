import json
import time
from pathlib import Path
from mlx_lm import load, generate
import mlx.core as mx

# Force CPU for absolute stability
mx.set_default_device(mx.cpu)
print("Device set to CPU for stable OOS testing.")

# Configuration
ADAPTER_PATH = "/Users/apple/Downloads/v5-of-glassytrade-ai/gemma4_26b_amt_adapter_absolute"
TEST_FILE = "/Users/apple/Downloads/v5-of-glassytrade-ai/fabio_amt_dataset/test.jsonl"
OUTPUT_FILE = "walk_forward_results.json"
SAMPLES_PER_FOLD = 100  # We'll do 100 per fold for speed, total 600 (Representative sample)
TOTAL_FOLDS = 6

def load_oos_data():
    with open(TEST_FILE, 'r') as f:
        return [json.loads(line) for line in f]

def run_test():
    print(f"Loading model and adapter from {ADAPTER_PATH}...")
    model, tokenizer = load("mlx-community/gemma-4-26b-a4b-it-4bit", adapter_path=ADAPTER_PATH)
    
    data = load_oos_data()
    total_samples = len(data)
    print(f"Loaded {total_samples} OOS samples.")
    
    results = []
    
    for fold in range(TOTAL_FOLDS):
        start_idx = fold * (total_samples // TOTAL_FOLDS)
        end_idx = start_idx + SAMPLES_PER_FOLD
        
        fold_samples = data[start_idx:end_idx]
        correct = 0
        total = 0
        
        print(f"\n--- Testing Fold {fold + 1}/{TOTAL_FOLDS} (Indices {start_idx}-{end_idx}) ---")
        
        for item in fold_samples:
            prompt = item['messages'][0]['content']
            ground_truth = item['messages'][1]['content']
            
            # Format prompt for Gemma
            full_prompt = f"<start_of_turn>user\n{prompt}<end_of_turn>\n<start_of_turn>assistant\n"
            
            response = generate(model, tokenizer, prompt=full_prompt, max_tokens=30, verbose=False)
            response = response.strip().split("<end_of_turn>")[0].strip()
            
            if total < 3:
                print(f"\nDEBUG Sample {total+1}:")
                print(f"Prompt: {prompt}")
                print(f"Response: '{response}'")
                print(f"Ground Truth: '{ground_truth}'")

            is_correct = response.strip() == ground_truth.strip()
            if is_correct:
                correct += 1
            total += 1
            
            # Print periodic progress
            if total % 20 == 0:
                print(f"Fold {fold+1} Progress: {total}/{SAMPLES_PER_FOLD} | Current Acc: {correct/total:.2%}")

        fold_acc = correct / total
        results.append({
            "fold": fold + 1,
            "accuracy": fold_acc,
            "samples": total
        })
        print(f"Fold {fold+1} Final Accuracy: {fold_acc:.2%}")

    # Final summary
    avg_acc = sum(r['accuracy'] for r in results) / TOTAL_FOLDS
    summary = {
        "timestamp": time.ctime(),
        "adapter": ADAPTER_PATH,
        "average_accuracy": avg_acc,
        "fold_results": results
    }
    
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(summary, f, indent=4)
    
    print("\n========================================")
    print(f"Walk-Forward Testing Complete!")
    print(f"Average OOS Accuracy: {avg_acc:.2%}")
    print(f"Results saved to {OUTPUT_FILE}")
    print("========================================")

if __name__ == "__main__":
    run_test()
