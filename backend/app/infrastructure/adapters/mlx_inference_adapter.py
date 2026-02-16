import logging
import threading

from app.config import settings
from app.domain.ports.llm_inference import LLMInferencePort

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
                return "Analysis Warning: Model is still loading..."
            return "Analysis Error: Model failed to load."

        from mlx_lm import generate
        from mlx_lm.sample_utils import make_sampler

        alpaca_prompt = (
            "Below is an instruction that describes a task, paired with an input "
            "that provides further context. Write a response that appropriately "
            "completes the request.\n\n"
            "### Instruction:\n{}\n\n"
            "### Input:\n{}\n\n"
            "### Response:\n"
        )
        prompt = alpaca_prompt.format(instruction, input_text)
        sampler = make_sampler(temp=settings.LLM_TEMPERATURE)
        response = generate(
            self.model,
            self.tokenizer,
            prompt=prompt,
            max_tokens=settings.LLM_MAX_NEW_TOKENS,
            sampler=sampler,
        )
        return self._truncate_repetition(response.strip())

    @staticmethod
    def _truncate_repetition(text: str) -> str:
        """Cut off output if a sentence repeats more than twice."""
        sentences = [s.strip() for s in text.split('.') if s.strip()]
        seen: dict[str, int] = {}
        result = []
        for s in sentences:
            key = s.lower()
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
