import logging
import threading

from app.config import settings
from app.domain.ports.llm_inference import LLMInferencePort, LLMNotReadyError

logger = logging.getLogger(__name__)


class MLXInferenceAdapter(LLMInferencePort):
    """MLX-based LLM inference adapter for Apple Silicon — 10-30x faster than PyTorch MPS."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.model = None
        self.tokenizer = None
        self._is_loading = False
        self._start_background_loading()
        self._initialized = True

    def _start_background_loading(self):
        """Kick off model loading on a daemon thread so the server starts immediately."""
        if not self._is_loading and self.model is None:
            self._is_loading = True
            logger.info("Starting MLX model loading in background...")
            thread = threading.Thread(target=self._load_model, daemon=True)
            thread.start()

    def _load_model(self):
        """Load the MLX model and tokenizer from the configured path."""
        try:
            from mlx_lm import load

            model_path = settings.MLX_MODEL_PATH
            logger.info(f"Loading MLX model from {model_path}...")
            self.model, self.tokenizer = load(model_path)
            self._is_loading = False
            logger.info("MLX model loaded successfully!")
        except Exception as e:
            logger.error(f"Failed to load MLX model: {e}")
            self._is_loading = False

    def predict(self, instruction: str, input_text: str) -> str:
        """Generate a prediction using the Alpaca prompt format."""
        if not self.model:
            if self._is_loading:
                raise LLMNotReadyError("Model is still loading")
            raise LLMNotReadyError("Model failed to load")

        from mlx_lm import generate
        from mlx_lm.sample_utils import make_sampler

        # ChatML format with response prefill to skip <think> and get structured output.
        # The model was fine-tuned on Market State:/Logic:/Trigger: format.
        # Strip any JSON instructions appended by prompt_builder — model doesn't understand JSON.
        clean_input = input_text.split("\n\nRespond ONLY with a JSON")[0]
        prompt = (
            "<|im_start|>system\n"
            f"{instruction} Always respond with exactly three lines:\n"
            "Market State: Balance or Imbalance\n"
            "Logic: brief reasoning\n"
            "Trigger: Enter Long, Enter Short, or Stay Flat<|im_end|>\n"
            f"<|im_start|>user\n{clean_input}<|im_end|>\n"
            "<|im_start|>assistant\nMarket State:"
        )
        sampler = make_sampler(temp=settings.LLM_TEMPERATURE)
        response = generate(
            self.model,
            self.tokenizer,
            prompt=prompt,
            max_tokens=settings.LLM_MAX_NEW_TOKENS,
            sampler=sampler,
        )
        return self._truncate_repetition("Market State:" + response.strip())

    @staticmethod
    def _truncate_repetition(text: str) -> str:
        """Cut off output if a sentence repeats more than twice.

        Preserves all sentences containing 'trigger:' to avoid losing
        the directional decision that the parser relies on.
        """
        sentences = [s.strip() for s in text.split('.') if s.strip()]
        seen: dict[str, int] = {}
        result = []
        for s in sentences:
            key = s.lower()
            # Always keep Trigger lines regardless of repetition
            if 'trigger' in key:
                result.append(s)
                continue
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > 2:
                break
            result.append(s)
        return '. '.join(result) + '.' if result else text

    def is_ready(self) -> bool:
        """Return True when the model is fully loaded and ready for inference."""
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
                logger.info(f"MLX model validation passed. Sample output: {result[:80]}")
            else:
                logger.error("MLX model validation failed: empty response")
            return ok
        except Exception as e:
            logger.error(f"MLX model validation failed: {e}")
            return False
