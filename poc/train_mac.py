import torch
from datasets import load_dataset
from peft import LoraConfig, get_peft_model, TaskType
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
)
from trl import SFTTrainer, SFTConfig

# Configuration
MODEL_NAME = "./models/Nanbeige4.1-3B"
OUTPUT_DIR = "./lora_adapter_mac"
MAX_STEPS = 100 # Increased for better learning
BATCH_SIZE = 1

def train():
    print("Loading model for Mac (MPS)...")
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"Using device: {device}")

    # Load Tokenizer
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    # Load Model (Float16)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME,
        torch_dtype=torch.float16,
        device_map=device,
        trust_remote_code=True
    )
    
    # Configure LoRA
    peft_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM, 
        inference_mode=False, 
        r=16, # Increased rank
        lora_alpha=32, 
        lora_dropout=0.05,
        target_modules=["q_proj", "v_proj", "k_proj", "o_proj"]
    )
    # model = get_peft_model(model, peft_config) # SFTTrainer handles this if peft_config is passed
    # model.print_trainable_parameters()

    # Format Data
    alpaca_prompt = """Below is an instruction that describes a task, paired with an input that provides further context. Write a response that appropriately completes the request.

### Instruction:
{}

### Input:
{}

### Response:
{}"""

    def formatting_func(example):
        text = alpaca_prompt.format(example['instruction'], example['input'], example['output']) + tokenizer.eos_token
        return text

    # Load the NEW Fabio Logic dataset
    dataset = load_dataset("json", data_files="training_data_fabio.jsonl", split="train")
    
    # Training Config
    training_args = SFTConfig(
        output_dir=OUTPUT_DIR,
        per_device_train_batch_size=BATCH_SIZE,
        gradient_accumulation_steps=4,
        warmup_steps=10,
        max_steps=MAX_STEPS,
        learning_rate=2e-4,
        fp16=False, 
        bf16=False,
        logging_steps=5,
        optim="adamw_torch",
        save_strategy="no",
        use_mps_device=True,
        max_length=1024,
        packing=False,
        dataset_text_field="text"
    )

    # Initialize Trainer
    # Pass peft_config to allow internal handling
    trainer = SFTTrainer(
        model=model,
        processing_class=tokenizer, # Use processing_class for newer TRL
        train_dataset=dataset,
        formatting_func=formatting_func,
        args=training_args,
        peft_config=peft_config 
    )

    print("Starting training on Fabio Logic Data...")
    trainer.train()
    
    print("Saving adapter...")
    trainer.model.save_pretrained(OUTPUT_DIR)
    print("Done!")

if __name__ == "__main__":
    train()
