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
NUM_EPOCHS = 2
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
        r=8,
        lora_alpha=16,
        lora_dropout=0.1,
        target_modules=["q_proj", "v_proj", "k_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
    )

    # ChatML format matching MLX inference adapter exactly
    def formatting_func(example):
        msgs = example["messages"]
        # Build ChatML string matching the inference prompt structure
        text = (
            f"<|im_start|>system\n{msgs[0]['content']}<|im_end|>\n"
            f"<|im_start|>user\n{msgs[1]['content']}<|im_end|>\n"
            f"<|im_start|>assistant\n{msgs[2]['content']}<|im_end|>"
        )
        return text + tokenizer.eos_token

    # Load the Fabio Logic dataset and split into train/eval
    full_dataset = load_dataset("json", data_files="training_data_fabio.jsonl", split="train")
    split = full_dataset.train_test_split(test_size=0.1, seed=42)
    train_dataset = split["train"]
    eval_dataset = split["test"]
    print(f"Dataset split: {len(train_dataset)} train, {len(eval_dataset)} eval")

    # Training Config
    training_args = SFTConfig(
        output_dir=OUTPUT_DIR,
        per_device_train_batch_size=BATCH_SIZE,
        gradient_accumulation_steps=4,
        warmup_ratio=0.05,
        num_train_epochs=NUM_EPOCHS,
        learning_rate=2e-5,
        weight_decay=0.01,
        fp16=False,
        bf16=False,
        logging_steps=5,
        optim="adamw_torch",
        save_strategy="epoch",
        eval_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        max_length=1024,
        packing=False,
        dataset_text_field="text"
    )

    # Initialize Trainer
    trainer = SFTTrainer(
        model=model,
        processing_class=tokenizer,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        formatting_func=formatting_func,
        args=training_args,
        peft_config=peft_config
    )

    print("Starting training on Fabio Logic Data (ChatML format)...")
    result = trainer.train()

    # Report final metrics
    train_loss = result.training_loss
    print(f"\nFinal training loss: {train_loss:.4f}")
    eval_results = trainer.evaluate()
    print(f"Final eval loss: {eval_results['eval_loss']:.4f}")

    print("\nSaving best adapter...")
    trainer.model.save_pretrained(OUTPUT_DIR)
    print("Done!")

if __name__ == "__main__":
    train()
