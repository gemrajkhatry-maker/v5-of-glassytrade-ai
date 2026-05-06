"""GGUF inference adapter for backendv2."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional

from app.domain.shared.port import ILLMInference, LLMNotReadyError

logger = logging.getLogger(__name__)

# Keep JSON reminder consistent with the LLM contract expectations in v2.
ENTRY_JSON_RUNTIME_REMINDER = (
    "Return ONLY a valid JSON object with direction, confidence, and rationale keys. "
    "No markdown, no extra text, no prose outside the JSON."
)

# Global lock to serialize llama.cpp Metal calls.
GGUF_GPU_LOCK = threading.Lock()


class GGUFInferenceAdapter(ILLMInference):
    """Llama.cpp based GGUF inference adapter for high-capacity local models."""

    _instance = None
    _init_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
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
        self._n_gpu_layers = n_gpu_layers
        self._n_ctx = n_ctx
        self._start_background_loading()
        self._initialized = True

    def _start_background_loading(self):
        """Load model (synchronously) while avoiding Metal initialization races."""
        model_path = self._model_path or os.environ.get("GGUF_MODEL_PATH", "")
        if not model_path:
            logger.info("GGUF: No model path configured.")
            return

        # Allow explicit override from env.
        if self._n_gpu_layers == -1:
            env_gpu_layers = os.environ.get("GGUF_N_GPU_LAYERS", "")
            self._n_gpu_layers = int(env_gpu_layers) if env_gpu_layers else 40

        self._is_loading = True
        logger.info("Loading GGUF model synchronously (main thread) to avoid Metal segfaults...")
        try:
            self._load_model(model_path)
            self._is_loading = False
        except Exception as e:
            logger.error("Failed to load GGUF model: %s", e, exc_info=True)
            self._load_error = str(e)
            self._is_loading = False

    def _load_model(self, model_path: str):
        """Load the GGUF model using llama-cpp-python."""
        from llama_cpp import Llama

        with GGUF_GPU_LOCK:
            self.llm = Llama(
                model_path=model_path,
                n_gpu_layers=self._n_gpu_layers,
                n_ctx=self._n_ctx,
                verbose=False,
            )

        logger.info("GGUF model loaded successfully.")

    def predict(
        self,
        instruction: str,
        input_text: str,
        temperature: float = 0.7,
        max_tokens: int = 512,
        prefill: Optional[str] = None,
    ) -> str:
        """Generate a prediction using GGUF backend."""
        if not self.llm:
            if self._is_loading:
                raise LLMNotReadyError("GGUF model is still loading")
            raise LLMNotReadyError(f"GGUF model failed to load: {self._load_error}")

        prompt = f"<|im_start|>system\n{instruction}\n{ENTRY_JSON_RUNTIME_REMINDER}<|im_end|>\n"
        prompt += f"<|im_start|>user\n{input_text.strip()}<|im_end|>\n"
        prompt += "<|im_start|>assistant\n"
        if prefill:
            prompt += prefill

        t0 = time.time()
        with GGUF_GPU_LOCK:
            logger.info("[GGUF] Starting generation (max_tokens=%d)...", max_tokens)
            output = self.llm(
                prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                stop=["<|im_end|>", "}"],
                echo=False,
            )
            duration = time.time() - t0

        text = output["choices"][0]["text"]
        if prefill:
            text = prefill + text
        if not text.endswith("}") and "{" in text:
            text += "}"

        logger.info("[GGUF] Generation complete in %.2fs.", duration)
        return self._extract_json_candidate(text)

    @staticmethod
    def _extract_json_candidate(text: str) -> str:
        """Return the first balanced JSON object if present."""
        start = text.find("{")
        if start == -1:
            return text
        depth = 0
        for idx in range(start, len(text)):
            char = text[idx]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start : idx + 1]
        return text

    def is_ready(self) -> bool:
        return self.llm is not None and not self._is_loading

    def wait_until_ready(self, timeout: float = 120.0) -> bool:
        start = time.time()
        while time.time() - start < timeout:
            if self.is_ready():
                return True
            time.sleep(0.5)
        return self.is_ready()
