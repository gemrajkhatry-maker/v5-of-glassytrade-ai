"""Process-wide lock for Metal GPU command buffer serialization.

Apple's Metal framework does NOT support concurrent command buffer
submissions from different threads. All mlx_lm.load() and
mlx_lm.generate() calls MUST be serialized through this lock.

Usage:
    from app.infrastructure.mlx_gpu_lock import MLX_GPU_LOCK

    with MLX_GPU_LOCK:
        model, tokenizer = load(path)

    with MLX_GPU_LOCK:
        output = generate(model, tokenizer, ...)
"""
import threading

MLX_GPU_LOCK = threading.Lock()
