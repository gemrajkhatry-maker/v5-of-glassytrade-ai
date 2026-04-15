"""Filter noisy Hugging Face Transformers logs for local MLX Gemma4 loads."""

from __future__ import annotations

import logging

_configured = False


def quiet_gemma4_tokenizer_config_warning() -> None:
    """Drop the bogus mismatch log when AutoTokenizer loads a Gemma4 MLX folder.

    Transformers compares config.json ``model_type`` (e.g. ``gemma4``) to the
    tokenizer config class's ``model_type`` (often empty), and emits::

        You are using a model of type `gemma4` to instantiate a model of type ``.

    Loading still succeeds; this is safe to silence for our MLX + local path flow.
    """
    global _configured
    if _configured:
        return

    class _Filter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            try:
                msg = record.getMessage()
            except Exception:
                return True
            if "You are using a model of type `" not in msg:
                return True
            if "to instantiate a model of type ``" in msg:
                return False
            return True

    logging.getLogger("transformers.configuration_utils").addFilter(_Filter())
    _configured = True
