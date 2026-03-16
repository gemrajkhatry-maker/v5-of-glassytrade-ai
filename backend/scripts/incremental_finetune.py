"""Incremental fine-tuning — legacy adapter path for older training stacks.

Usage:
    python -m scripts.incremental_finetune [--data PATH] [--adapter PATH] [--steps INT]
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    parser = argparse.ArgumentParser(description="Incremental fine-tuning on new data")
    parser.add_argument("--data", default="new_training_data.jsonl")
    parser.add_argument("--base-model", default=None, help="Base model path")
    parser.add_argument("--adapter", default=None, help="Existing adapter path")
    parser.add_argument("--output", default=None, help="Output adapter path")
    parser.add_argument("--steps", type=int, default=100)
    parser.add_argument("--lr", type=float, default=1e-4)
    args = parser.parse_args()

    import torch
    from datasets import load_dataset
    from peft import PeftModel, LoraConfig, TaskType
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from trl import SFTTrainer, SFTConfig

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    poc_dir = os.path.join(project_root, "poc")

    base_path = args.base_model or os.path.join(poc_dir, "models", "Nanbeige4.1-3B")
    adapter_path = args.adapter or os.path.join(poc_dir, "lora_adapter_mac")
    output_path = args.output or os.path.join(poc_dir, "lora_adapter_mac_incremental")

    print(
        "WARNING: This script is a legacy Nanbeige/Alpaca incremental fine-tune path. "
        "The active paper-trading runtime uses the Qwen MLX JSON entry contract."
    )

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"Device: {device}")

    print(f"Loading base model from {base_path}...")
    tokenizer = AutoTokenizer.from_pretrained(base_path)
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    base_model = AutoModelForCausalLM.from_pretrained(
        base_path, torch_dtype=torch.float16, device_map=device, trust_remote_code=True
    )

    print(f"Loading existing adapter from {adapter_path}...")
    model = PeftModel.from_pretrained(base_model, adapter_path, is_trainable=True)

    alpaca_prompt = """Below is an instruction that describes a task, paired with an input that provides further context. Write a response that appropriately completes the request.

### Instruction:
{}

### Input:
{}

### Response:
{}"""

    def formatting_func(example):
        return alpaca_prompt.format(
            example["instruction"], example["input"], example["output"]
        ) + tokenizer.eos_token

    dataset = load_dataset("json", data_files=args.data, split="train")
    print(f"Loaded {len(dataset)} new training examples")

    training_args = SFTConfig(
        output_dir=output_path,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=4,
        warmup_steps=5,
        max_steps=args.steps,
        learning_rate=args.lr,
        fp16=False,
        bf16=False,
        logging_steps=5,
        optim="adamw_torch",
        save_strategy="no",
        max_length=1024,
        packing=False,
        dataset_text_field="text",
    )

    trainer = SFTTrainer(
        model=model,
        processing_class=tokenizer,
        train_dataset=dataset,
        formatting_func=formatting_func,
        args=training_args,
    )

    print(f"Starting incremental training ({args.steps} steps)...")
    trainer.train()

    print(f"Saving adapter to {output_path}...")
    trainer.model.save_pretrained(output_path)
    print("Done!")


if __name__ == "__main__":
    main()
