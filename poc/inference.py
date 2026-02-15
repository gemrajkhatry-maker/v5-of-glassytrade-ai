from unsloth import FastLanguageModel
import torch

max_seq_length = 2048
dtype = None
load_in_4bit = True

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = "lora_model", # Load the fine-tuned adapter
    max_seq_length = max_seq_length,
    dtype = dtype,
    load_in_4bit = load_in_4bit,
)
FastLanguageModel.for_inference(model) # Enable native 2x faster inference

alpaca_prompt = """Below is an instruction that describes a task, paired with an input that provides further context. Write a response that appropriately completes the request.

### Instruction:
{}

### Input:
{}

### Response:
{}"""

def run_inference(instruction, input_text):
    inputs = tokenizer(
        [
            alpaca_prompt.format(
                instruction, # instruction
                input_text, # input
                "", # output - leave this blank for generation!
            )
        ], return_tensors = "pt").to("cuda")

    outputs = model.generate(**inputs, max_new_tokens = 64, use_cache = True)
    response = tokenizer.batch_decode(outputs)
    return response

if __name__ == "__main__":
    # Test Scenario: Trend
    instruction = "Analyze the current market state based on Profile and Orderflow."
    input_text = "New York Open. Price broke previous session VAH at 15250. Price is holding above. A Low Volume Node (LVN) exists at 15260."
    
    print("\n--- Input ---")
    print(input_text)
    print("\n--- Model Output ---")
    print(run_inference(instruction, input_text))
