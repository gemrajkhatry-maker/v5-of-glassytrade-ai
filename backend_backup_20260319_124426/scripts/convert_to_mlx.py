"""Convert fine-tuned LoRA model to MLX 4-bit quantized format.

Usage:
    python -m scripts.convert_to_mlx [--base-model PATH] [--adapter PATH] [--output PATH]
"""

import argparse
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def merge_and_convert(base_model_path: str, adapter_path: str, output_path: str) -> None:
    """Merge LoRA adapter into base model, then convert to MLX 4-bit."""
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    logger.info("Step 1/3: Loading base model and LoRA adapter...")
    tokenizer = AutoTokenizer.from_pretrained(base_model_path)
    base_model = AutoModelForCausalLM.from_pretrained(
        base_model_path, torch_dtype=torch.float16, trust_remote_code=True
    )
    model = PeftModel.from_pretrained(base_model, adapter_path)

    logger.info("Step 2/3: Merging LoRA weights into base model...")
    merged_model = model.merge_and_unload()

    merged_path = output_path + "_merged_hf"
    merged_model.save_pretrained(merged_path)
    tokenizer.save_pretrained(merged_path)
    logger.info(f"Merged HF model saved to {merged_path}")

    logger.info("Step 3/3: Converting to MLX 4-bit quantized format...")
    try:
        from mlx_lm import convert
        convert(merged_path, quantize=True, q_bits=4, mlx_path=output_path)
        logger.info(f"MLX 4-bit model saved to {output_path}")
    except ImportError:
        logger.error("mlx-lm not installed. Install with: pip install mlx-lm")
        sys.exit(1)


def main():
    # Default paths relative to project root
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    poc_dir = os.path.join(project_root, "poc")

    parser = argparse.ArgumentParser(description="Convert LoRA model to MLX format")
    parser.add_argument("--base-model", default=os.path.join(poc_dir, "models", "Nanbeige4.1-3B"))
    parser.add_argument("--adapter", default=os.path.join(poc_dir, "lora_adapter_mac"))
    parser.add_argument("--output", default=os.path.join(poc_dir, "models", "glassytrade-mlx-4bit"))
    args = parser.parse_args()

    merge_and_convert(args.base_model, args.adapter, args.output)


if __name__ == "__main__":
    main()
