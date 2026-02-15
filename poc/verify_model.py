from transformers import AutoModelForCausalLM, AutoTokenizer
import torch

MODEL_PATH = "./models/Nanbeige4.1-3B"

def verify_model():
    print(f"Loading model from {MODEL_PATH}...")
    try:
        tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
        model = AutoModelForCausalLM.from_pretrained(
            MODEL_PATH, 
            torch_dtype=torch.float16,
            device_map="auto",
            low_cpu_mem_usage=True
        )
        print("Model loaded successfully!")
        print(f"Model parameters: {model.num_parameters()}")
        print(f"Vocab size: {tokenizer.vocab_size}")
    except Exception as e:
        print(f"Error loading model: {e}")

if __name__ == "__main__":
    verify_model()
