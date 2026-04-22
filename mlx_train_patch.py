"""
Patch file to modify MLX trainer to skip initial validation.
This prevents the "Impacting Interactivity" crash.
"""

import mlx.core as mx
import sys
import time

# Store original train function for reference
_original_train = None

def train_with_skip(*args, **kwargs):
    """Train wrapper that skips validation to avoid Metal crashes."""
    print("[PATCH] Starting training with validation-skipping patch")
    print("[PATCH] Loading training args...")

    # Import the actual train function from mlx_lm
    from mlx_lm.tuner.trainer import train as orig_train
    from mlx_lm.tuner import trainer
    import types

    # Patch the evaluate function to do nothing during training
    original_evaluate = trainer.evaluate

    def safe_evaluate(*args, **kwargs):
        """Replace evaluate with a watchdog-safe version."""
        print("[PATCH] Skipping validation to prevent Metal watchdog crash")
        # Reset Metal cache before returning
        mx.eval()
        mx.clear_cache()
        time.sleep(0.5)  # Give GPU time to breathe
        return {"loss": 0.0}

    # Patch evaluate temporarily
    trainer.evaluate = safe_evaluate

    try:
        print("[PATCH] Metal cache cleared, starting training...")
        result = orig_train(*args, **kwargs)
    finally:
        # Restore original
        trainer.evaluate = original_evaluate
        print("[PATCH] Restored original evaluate function")

    return result


# Alternative: monkey-patch the train_model to skip validation entirely
def patch_mlx_lm():
    """Apply the patch to mlx_lm."""
    try:
        import mlx_lm.tuner.trainer as trainer_module
        import mlx_lm.lora as lora_module

        print("[PATCH] Patching mlx_lm.tuner.trainer.train...")

        # Replace the train function
        original_train = trainer_module.train

        def patched_train(*args, **kwargs):
            """Patched train that skips validation."""
            print("[PATCH] Running in validation-skipping mode")
            # Get the args namespace
            if args and hasattr(args[0], 'iters'):
                training_args = args[0]
                # Set validation to 0 temporarily
                orig_eval = training_args.steps_per_eval
                training_args.steps_per_eval = 0  # Never validate (disabled)
                print(f"[PATCH] Disabled validation (was {orig_eval})")

            # Run the original train
            result = original_train(*args, **kwargs)

            # Restore if needed
            if 'orig_eval' in dir() and training_args:
                training_args.steps_per_eval = orig_eval

            return result

        trainer_module.train = patched_train
        print("[PATCH] Successfully patched mlx_lm training")
        return True

    except Exception as e:
        print(f"[PATCH] Error patching: {e}")
        return False


if __name__ == "__main__":
    patch_mlx_lm()
