"""System-wide lock for Metal GPU command buffer serialization.

Apple's Metal framework does NOT support concurrent command buffer
submissions. This lock prevents collisions between:
1. Multiple threads in the same process
2. Multiple processes (e.g., Training + Inference)

Uses a hybrid approach:
- threading.Lock for intra-process efficiency
- fcntl file locking for inter-process safety
"""
import os
import fcntl
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

class SystemGPULock:
    """A reentrant-like system-wide lock for GPU access."""
    
    def __init__(self):
        self._thread_lock = threading.Lock()
        # Use a hidden file in /tmp for cross-process locking
        self._lock_file_path = Path("/tmp/mlx_gpu_system.lock")
        self._fp = None

    def __enter__(self):
        # 1. Acquire thread lock first
        self._thread_lock.acquire()
        
        # 2. Acquire system-wide file lock
        try:
            if self._fp is None:
                self._fp = open(self._lock_file_path, "w")
            
            # This will block if another process holds the lock
            fcntl.flock(self._fp, fcntl.LOCK_EX)
        except Exception as e:
            self._thread_lock.release()
            logger.error("Failed to acquire system GPU lock: %s", e)
            raise

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if self._fp:
                fcntl.flock(self._fp, fcntl.LOCK_UN)
        finally:
            self._thread_lock.release()

# Global singleton instance
MLX_GPU_LOCK = SystemGPULock()
