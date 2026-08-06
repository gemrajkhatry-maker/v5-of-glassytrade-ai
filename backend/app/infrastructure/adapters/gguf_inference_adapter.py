import logging
import os
import threading
import time
from typing import Optional

from quant.inference.llm_contract import ENTRY_JSON_RUNTIME_REMINDER
from quant.contracts.ports.llm_inference import ILLMInference, LLMNotReadyError

logger = logging.getLogger(__name__)

# Global lock to prevent concurrent Metal GPU access (similar to MLX_GPU_LOCK)
GGUF_GPU_LOCK = threading.Lock()

class GGUFInferenceAdapter(ILLMInference):
    """Llama.cpp based GGUF inference adapter for high-capacity models like Gemopus-26B."""

    _instance = None
    _init_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:  # Double-check after acquiring lock
                    instance = super().__new__(cls)
                    instance._initialized = False
                    cls._instance = instance
        return cls._instance

    def __init__(self, model_path: str = "", n_gpu_layers: int = -1, n_ctx: int = 4096):
        if self._initialized:
            return
        self.llm = None
        self._is_loading = False
        self._load_error: Optional[str] = None
        self._model_path = model_path
        # Read n_gpu_layers from env to allow memory-safe configuration
        env_gpu_layers = os.environ.get("GGUF_N_GPU_LAYERS", "")
        if env_gpu_layers:
            self._n_gpu_layers = int(env_gpu_layers)
        elif n_gpu_layers != -1:
            self._n_gpu_layers = n_gpu_layers
        else:
            # Default: offload 40 layers (~60% for 26B models) to avoid Metal OOM
            self._n_gpu_layers = 40
        self._n_ctx = n_ctx
        # Load synchronously on main thread to avoid llama-cpp-python Metal segfaults.
        # llama.cpp's Metal backend must be initialized on the main thread.
        self._start_background_loading()
        self._initialized = True

    def _start_background_loading(self):
        """Load GGUF model synchronously on main thread to avoid Metal/llama.cpp segfaults.

        llama-cpp-python's Metal backend is not thread-safe during initialization.
        Loading on a background thread causes segmentation faults on macOS.
        See: https://github.com/ggerganov/llama.cpp/issues/5983
        """
        model_path = self._model_path or os.environ.get("GGUF_MODEL_PATH", "")
        if not model_path:
            logger.info("GGUF: No model path configured.")
            return

        self._is_loading = True
        logger.info("Loading GGUF model synchronously (main thread) to avoid Metal segfaults...")
        try:
            self._load_model(model_path)
        except Exception as e:
            logger.error(f"Failed to load GGUF model: {e}", exc_info=True)
            self._load_error = str(e)
            self._is_loading = False

    def _load_model(self, model_path: str):
        """Load the GGUF model using llama-cpp-python with Metal support."""
        from llama_cpp import Llama

        with GGUF_GPU_LOCK:
            self.llm = Llama(
                model_path=model_path,
                n_gpu_layers=self._n_gpu_layers,
                n_ctx=self._n_ctx,
                verbose=False
            )

        logger.info("GGUF model loaded successfully with Metal acceleration!")

    def predict(
        self,
        instruction: str,
        input_text: str,
        temperature: float = 0.7,
        max_tokens: int = 512,
        prefill: Optional[str] = None,
    ) -> str:
        """Generate a prediction using the GGUF backend."""
        if not self.llm:
            if self._is_loading:
                raise LLMNotReadyError("GGUF Model is still loading")
            raise LLMNotReadyError(f"GGUF Model failed to load: {self._load_error}")

        # Construct prompt (ChatML style as per Gemma/Gemopus defaults)
        prompt = f"<|im_start|>system\n{instruction}\n{ENTRY_JSON_RUNTIME_REMINDER}<|im_end|>\n"
        prompt += f"<|im_start|>user\n{input_text.strip()}<|im_end|>\n"
        prompt += f"<|im_start|>assistant\n"
        if prefill:
            prompt += prefill

        t0 = time.time()
        with GGUF_GPU_LOCK:
            logger.info(f"[GGUF] Starting generation (max_tokens={max_tokens})...")
            # Sampling logic
            output = self.llm(
                prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                stop=["<|im_end|>", "}"], 
                echo=False
            )
            duration = time.time() - t0
            
        text = output["choices"][0]["text"]
        if prefill:
            text = prefill + text
        
        # Ensure JSON is capped if we stopped at "}"
        if not text.endswith("}") and "{" in text:
             text += "}"

        logger.info(f"[GGUF] Generation complete in {duration:.2f}s.")
        return self._extract_json_candidate(text)

    @staticmethod
    def _extract_json_candidate(text: str) -> str:
        """Return the first balanced JSON object."""
        start = text.find("{")
        if start == -1: return text
        depth = 0
        for idx in range(start, len(text)):
            char = text[idx]
            if char == "{": depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0: return text[start : idx + 1]
        return text

    def is_ready(self) -> bool:
        return self.llm is not None and not self._is_loading

    def wait_until_ready(self, timeout: float = 120.0) -> bool:
        start = time.time()
        while time.time() - start < timeout:
            if self.is_ready(): return True
            time.sleep(0.5)
        return self.is_ready()
