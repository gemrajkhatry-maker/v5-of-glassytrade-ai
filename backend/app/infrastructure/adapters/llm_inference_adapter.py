import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer
import logging
import threading

from app.config import settings
from app.domain.ports.llm_inference import LLMInferencePort

logger = logging.getLogger(__name__)


class LLMInferenceAdapter(LLMInferencePort):
    """Adapter for fine-tuned LLM inference using LoRA."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(LLMInferenceAdapter, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        self.model = None
        self.tokenizer = None
        self._is_loading = False
        self._start_background_loading()
        self._initialized = True

    def _start_background_loading(self):
        if not self._is_loading and self.model is None:
            self._is_loading = True
            logger.info("Starting AI Model loading in background thread...")
            thread = threading.Thread(target=self._load_model, daemon=True)
            thread.start()

    def _load_model(self):
        """Loads the model and tokenizer."""
        try:
            base_path = settings.LLM_BASE_MODEL_PATH
            adapter_path = settings.LLM_ADAPTER_PATH

            logger.info(f"Loading Base Model from {base_path} on {self.device}...")
            self.tokenizer = AutoTokenizer.from_pretrained(base_path)

            base_model = AutoModelForCausalLM.from_pretrained(
                base_path,
                torch_dtype=torch.float16,
                device_map=self.device,
                trust_remote_code=True,
            )

            logger.info(f"Loading LoRA Adapter from {adapter_path}...")
            self.model = PeftModel.from_pretrained(base_model, adapter_path)
            self.model.eval()
            self._is_loading = False
            logger.info("AI Model successfully loaded!")

        except Exception as e:
            logger.error(f"Failed to load AI Model: {str(e)}")
            self._is_loading = False

    def predict(self, instruction: str, input_text: str) -> str:
        """Runs inference on the loaded model."""
        if not self.model:
            if self._is_loading:
                return "Analysis Warning: Model is still loading..."
            return "Analysis Error: Model failed to load."

        alpaca_prompt = """Below is an instruction that describes a task, paired with an input that provides further context. Write a response that appropriately completes the request.

### Instruction:
{}

### Input:
{}

### Response:
"""
        prompt = alpaca_prompt.format(instruction, input_text)
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.device)

        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=settings.LLM_MAX_NEW_TOKENS,
                use_cache=True,
                temperature=settings.LLM_TEMPERATURE,
            )

        response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        clean_response = response.split("### Response:")[-1].strip()
        return clean_response

    def is_ready(self) -> bool:
        """Check if model is loaded and ready for inference."""
        return self.model is not None and not self._is_loading

    def wait_until_ready(self, timeout: float = 120.0) -> bool:
        """Block until model is loaded or timeout. Returns True if ready."""
        import time
        start = time.time()
        while time.time() - start < timeout:
            if self.is_ready():
                return True
            if not self._is_loading and self.model is None:
                return False  # Loading failed
            time.sleep(0.5)
        return self.is_ready()

    def validate(self) -> bool:
        """Run a quick validation inference to confirm the model works."""
        if not self.is_ready():
            return False
        try:
            result = self.predict(
                instruction="Respond with OK if you can process this.",
                input_text="Validation check.",
            )
            ok = len(result.strip()) > 0
            if ok:
                logger.info(f"Model validation passed. Sample output: {result[:80]}")
            else:
                logger.error("Model validation failed: empty response")
            return ok
        except Exception as e:
            logger.error(f"Model validation failed: {e}")
            return False
