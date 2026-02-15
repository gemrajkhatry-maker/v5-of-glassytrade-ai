from transformers import AutoModelForCausalLM, AutoTokenizer
import torch

MODEL_PATH = "./models/Nanbeige4.1-3B"

def test_inference():
    print(f"Loading model from {MODEL_PATH}...")
    
    # Determine device (MPS for Mac, else CPU)
    if torch.backends.mps.is_available():
        device = "mps"
    elif torch.cuda.is_available():
        device = "cuda"
    else:
        device = "cpu"
    
    print(f"Using device: {device}")

    try:
        tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
        model = AutoModelForCausalLM.from_pretrained(
            MODEL_PATH, 
            torch_dtype=torch.float16,
            device_map=device,
            trust_remote_code=True
        )
        
        prompt = """### Instruction:
Analyze the current market state.

### Input:
New York Open. Price broke VAH at 15250 and is holding above.

### Response:
"""
        inputs = tokenizer(prompt, return_tensors="pt").to(device)
        
        print("Generating response...")
        outputs = model.generate(
            **inputs, 
            max_new_tokens=100, 
            use_cache=True,
            temperature=0.1
        )
        
        response = tokenizer.decode(outputs[0], skip_special_tokens=True)
        print("\n--- Model Output (Base Model) ---")
        print(response)
        
    except Exception as e:
        print(f"Error during inference: {e}")

if __name__ == "__main__":
    test_inference()
