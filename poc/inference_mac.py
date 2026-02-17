import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

BASE_MODEL = "./models/Nanbeige4.1-3B"
ADAPTER_PATH = "./lora_adapter_mac"

SYSTEM_INSTRUCTION = (
    "Analyze the trading scenario based on Fabio Valentini's "
    "methodology (Orderflow, Auction Market Theory). "
    "Always respond with exactly three lines:\n"
    "Market State: Balance or Imbalance\n"
    "Logic: brief reasoning\n"
    "Trigger: Enter Long, Enter Short, or Stay Flat"
)

def test_inference(input_text):
    print(f"Loading base model from {BASE_MODEL}...")
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"Using device: {device}")

    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    base_model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL, torch_dtype=torch.float16, device_map=device, trust_remote_code=True
    )

    print(f"Loading LoRA adapter from {ADAPTER_PATH}...")
    model = PeftModel.from_pretrained(base_model, ADAPTER_PATH)
    model.eval()

    # ChatML format with response prefill (matches MLX inference adapter)
    prompt = (
        f"<|im_start|>system\n{SYSTEM_INSTRUCTION}<|im_end|>\n"
        f"<|im_start|>user\n{input_text}<|im_end|>\n"
        "<|im_start|>assistant\nMarket State:"
    )
    inputs = tokenizer(prompt, return_tensors="pt").to(device)

    print("Generating response...")
    with torch.no_grad():
        outputs = model.generate(
            **inputs, max_new_tokens=80, use_cache=True, temperature=0.3,
        )

    response = tokenizer.decode(outputs[0], skip_special_tokens=True)
    clean = "Market State:" + response.split("Market State:")[-1].strip()
    print("\n--- Model Output ---\n")
    print(clean)
    print("\n--------------------\n")

if __name__ == "__main__":
    # Test: AAA Setup with full indicator context
    input_text = (
        "NY morning. VAL test at 15050. Aggressive selling with -800 Delta. "
        "Price not moving down. Iceberg buyers visible in the footprint. "
        "D-shaped profile. Market is balanced and rotational. "
        "Volume bubbles detected: 2.5σ aggressive buy at 15050 (3200 contracts). "
        "Key HVN levels: 15030, 15080. "
        "Low Volume Nodes (LVN): 15060. Price moves quickly through these levels. "
        "CVD trending up. Buyers in control. "
        "Price above VWAP (15040). Bullish bias."
    )

    print(f"Input: {input_text}\n")
    test_inference(input_text)
