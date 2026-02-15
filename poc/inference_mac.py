import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer
import os

BASE_MODEL = "./models/Nanbeige4.1-3B"
ADAPTER_PATH = "./lora_adapter_mac"

def test_inference(instruction, input_text):
    print(f"Loading base model from {BASE_MODEL}...")
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"Using device: {device}")
    
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    base_model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        torch_dtype=torch.float16,
        device_map=device,
        trust_remote_code=True
    )
    
    print(f"Loading LoRA adapter from {ADAPTER_PATH}...")
    model = PeftModel.from_pretrained(base_model, ADAPTER_PATH)
    model.eval()
    
    alpaca_prompt = """Below is an instruction that describes a task, paired with an input that provides further context. Write a response that appropriately completes the request.

### Instruction:
{}

### Input:
{}

### Response:
"""
    prompt = alpaca_prompt.format(instruction, input_text)
    inputs = tokenizer(prompt, return_tensors="pt").to(device)
    
    print("Generating response...")
    with torch.no_grad():
        outputs = model.generate(
            **inputs, 
            max_new_tokens=256, 
            use_cache=True,
            temperature=0.1, # Low temp for deterministic logic
        )
    
    response = tokenizer.decode(outputs[0], skip_special_tokens=True)
    print("\n--- Model Output ---\n")
    print(response.split("### Response:")[-1].strip())
    print("\n--------------------\n")

if __name__ == "__main__":
    # Test Case 1: AAA Setup (Absorption)
    instruction = "Analyze the trading scenario based on Fabio Valentini's methodology (Orderflow, Auction Market Theory)."
    input_text = "New York Open. Price is testing Value Area Low (VAL) at 15050. Sellers are aggressive with -500 Delta but price is not moving down. Big buy orders are hitting the bid."
    
    print(f"Input: {input_text}")
    test_inference(instruction, input_text)
