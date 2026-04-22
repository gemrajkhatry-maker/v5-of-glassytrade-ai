import sys
from mlx_lm import load, generate

model_path = "/Users/apple/Downloads/v5-of-glassytrade-ai/gemma4_26b_fused_production"
print(f"Attempting to load Gemma 4 26B using mlx_lm from: {model_path}")

try:
    model, processor = load(model_path)
    print("Success! Model loaded using mlx_lm.")
    
    prompt = "Symbol: NIFTY, Market State: IMBALANCED. Decision?"
    # Simple generation
    response = generate(model, processor, prompt=prompt, max_tokens=20)
    print(f"Response: {response}")
except Exception as e:
    print(f"Failed to load using mlx_lm: {e}")
