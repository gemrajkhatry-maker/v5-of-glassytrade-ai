"""Port for LLM inference — domain-to-infrastructure boundary."""

from abc import ABC, abstractmethod


class LLMInferencePort(ABC):
    """Abstraction for LLM inference (fine-tuned model)."""

    @abstractmethod
    def predict(self, instruction: str, input_text: str) -> str:
        """Run inference on a fine-tuned model."""

    @abstractmethod
    def is_ready(self) -> bool:
        """Check if model is loaded and ready for inference."""

    def wait_until_ready(self, timeout: float = 120.0) -> bool:
        """Block until model is ready or timeout. Default: poll is_ready()."""
        import time
        start = time.time()
        while time.time() - start < timeout:
            if self.is_ready():
                return True
            time.sleep(0.5)
        return self.is_ready()

    def validate(self) -> bool:
        """Run a validation inference. Default: check is_ready()."""
        return self.is_ready()
