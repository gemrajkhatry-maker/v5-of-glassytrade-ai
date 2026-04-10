#!/usr/bin/env python3
"""
Benchmark script to test speed and quality of all fine-tuned LoRA adapters.
Tests inference speed and output quality across all trained adapters.
"""

import time
import json
from pathlib import Path
from typing import Dict, List, Tuple

# Test prompts relevant to trading/AMT
TEST_PROMPTS = [
    {
        "instruction": "Analyze the current market auction state. Price is at POC with declining volume and balanced order flow.",
        "input": "Market State: BALANCED\nPOC: 24500\nValue Area: 24450-24550\nVolume: Declining\nCVD: Flat\nAggression Score: 1.2"
    },
    {
        "instruction": "Identify the optimal entry setup based on AMT principles.",
        "input": "Market State: IMBALANCED\nDirection: Long\nInitiative Buy: Strong\nResponsive Sell: Absent\nLVN Below: 24400\nAggression: 4.5 sigma"
    },
    {
        "instruction": "Assess whether this is a valid breakout or potential trap.",
        "input": "Price breaking above VAH\nVolume: 2.5x average\nFootprint: Aggressive buying at ask\nCVD Slope: +45\nBig Trades: 8 in last 3 bars"
    }
]

def get_adapter_info() -> List[Dict]:
    """Get information about all available adapters."""
    adapters = [
        {
            "name": "poc_lfm2/lora_adapter_mlx",
            "path": "poc_lfm2/lora_adapter_mlx",
            "base_model": None,  # Model doesn't exist locally
            "description": "LFM2-24B (2000 iterations)"
        },
        {
            "name": "poc4/qwen35_mlx_adapters",
            "path": "poc4/qwen35_mlx_adapters",
            "base_model": "poc4/mlx_model/qwen35-0.8b-4bit",
            "description": "Qwen3.5 0.8B (1000 iterations)"
        },
        {
            "name": "poc3/lora_adapter_options_mlx",
            "path": "poc3/lora_adapter_options_mlx",
            "base_model": "poc3/models/glassytrade-options-fused",
            "description": "Options Model (800 iterations)"
        },
        {
            "name": "poc8/adapters",
            "path": "poc8/adapters",
            "base_model": "poc8/model",
            "description": "Qwen 4B Reasoning (300 iterations)"
        }
    ]
    
    return adapters

def test_adapter_speed(adapter_path: str, base_model: str, num_runs: int = 3) -> Dict:
    """Test inference speed for an adapter."""
    try:
        from mlx_lm import load, generate
        import os
        
        print(f"\n{'='*60}")
        print(f"Loading: {adapter_path}")
        print(f"Base Model: {base_model}")
        print(f"{'='*60}")
        
        # Convert to absolute path if relative
        if not os.path.isabs(base_model):
            base_model_abs = os.path.join(os.getcwd(), base_model)
        else:
            base_model_abs = base_model
            
        if not os.path.isabs(adapter_path):
            adapter_path_abs = os.path.join(os.getcwd(), adapter_path)
        else:
            adapter_path_abs = adapter_path
        
        print(f"Absolute base model path: {base_model_abs}")
        print(f"Absolute adapter path: {adapter_path_abs}")
        
        # Check if paths exist
        if not os.path.exists(base_model_abs):
            raise FileNotFoundError(f"Base model not found: {base_model_abs}")
        if not os.path.exists(adapter_path_abs):
            raise FileNotFoundError(f"Adapter not found: {adapter_path_abs}")
        
        # Load model with local paths
        start_load = time.time()
        model, tokenizer = load(base_model_abs, adapter_path=adapter_path_abs)
        load_time = time.time() - start_load
        print(f"✓ Model loaded in {load_time:.2f}s")
        
        # Test inference
        times = []
        outputs = []
        
        for i, prompt_data in enumerate(TEST_PROMPTS):
            prompt = f"<start_of_turn>user\n{prompt_data['instruction']}\n\n{prompt_data['input']}<end_of_turn>\n<start_of_turn>model\n"
            
            run_times = []
            for run in range(num_runs):
                start = time.time()
                output = generate(
                    model,
                    tokenizer,
                    prompt=prompt,
                    max_tokens=120,
                    verbose=False
                )
                elapsed = time.time() - start
                run_times.append(elapsed)
                
                if run == 0:  # Store output from first run
                    outputs.append({
                        "prompt_num": i + 1,
                        "output": output
                    })
            
            avg_time = sum(run_times) / len(run_times)
            times.append(avg_time)
            print(f"  Prompt {i+1}: {avg_time:.2f}s")
        
        avg_inference = sum(times) / len(times)
        
        return {
            "success": True,
            "load_time": load_time,
            "avg_inference_time": avg_inference,
            "total_time": load_time + avg_inference,
            "outputs": outputs,
            "error": None
        }
        
    except Exception as e:
        print(f"✗ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "load_time": 0,
            "avg_inference_time": 0,
            "total_time": 0,
            "outputs": [],
            "error": str(e)
        }

def print_comparison(results: Dict[str, Dict]):
    """Print comparison table."""
    print("\n" + "="*80)
    print("BENCHMARK RESULTS COMPARISON")
    print("="*80)
    print(f"{'Adapter':<35} {'Load (s)':<12} {'Infer (s)':<12} {'Total (s)':<12} {'Status':<10}")
    print("-"*80)
    
    # Sort by total time (fastest first)
    sorted_results = sorted(
        [(name, data) for name, data in results.items() if data["success"]],
        key=lambda x: x[1]["total_time"]
    )
    
    for name, data in sorted_results:
        print(f"{name:<35} {data['load_time']:<12.2f} {data['avg_inference_time']:<12.2f} {data['total_time']:<12.2f} {'✓':<10}")
    
    # Print failed ones
    for name, data in results.items():
        if not data["success"]:
            print(f"{name:<35} {'N/A':<12} {'N/A':<12} {'N/A':<12} {'✗ FAILED':<10}")
            print(f"  Error: {data['error']}")
    
    print("="*80)
    
    if sorted_results:
        fastest = sorted_results[0]
        print(f"\n🏆 FASTEST: {fastest[0]} ({fastest[1]['total_time']:.2f}s total)")
        print(f"   - Load time: {fastest[1]['load_time']:.2f}s")
        print(f"   - Avg inference: {fastest[1]['avg_inference_time']:.2f}s")

def print_sample_outputs(results: Dict[str, Dict]):
    """Print sample outputs for quality assessment."""
    print("\n" + "="*80)
    print("SAMPLE OUTPUTS (for quality assessment)")
    print("="*80)
    
    for name, data in results.items():
        if data["success"] and data["outputs"]:
            print(f"\n{'─'*80}")
            print(f"Model: {name}")
            print(f"{'─'*80}")
            for output_data in data["outputs"][:1]:  # Show first prompt only
                print(f"Prompt {output_data['prompt_num']}:")
                print(output_data['output'][:300])
                print("...")

def main():
    print("🚀 Starting Adapter Benchmark")
    print("="*80)
    
    adapters = get_adapter_info()
    results = {}
    
    for adapter in adapters:
        print(f"\n\nTesting: {adapter['description']}")
        if adapter["base_model"]:
            print(f"Base model: {adapter['base_model']}")
        else:
            print("⚠ No base model found in config, skipping...")
            results[adapter["name"]] = {
                "success": False,
                "load_time": 0,
                "avg_inference_time": 0,
                "total_time": 0,
                "outputs": [],
                "error": "No base model configured"
            }
            continue
        
        result = test_adapter_speed(adapter["path"], adapter["base_model"])
        results[adapter["name"]] = result
    
    # Print comparison
    print_comparison(results)
    
    # Print sample outputs
    print_sample_outputs(results)
    
    # Save results
    output_file = Path("benchmark_results.json")
    with open(output_file, "w") as f:
        # Convert outputs to serializable format
        serializable_results = {}
        for name, data in results.items():
            serializable_results[name] = {
                "success": data["success"],
                "load_time": data["load_time"],
                "avg_inference_time": data["avg_inference_time"],
                "total_time": data["total_time"],
                "error": data["error"],
                "sample_outputs": [o["output"][:500] for o in data.get("outputs", [])[:2]]
            }
        json.dump(serializable_results, f, indent=2)
    
    print(f"\n✓ Results saved to {output_file}")

if __name__ == "__main__":
    main()
