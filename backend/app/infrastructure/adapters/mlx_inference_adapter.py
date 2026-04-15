import logging
import os
import threading
from pathlib import Path

from dotenv import load_dotenv
from app.domain.fabio_ai.services.llm_contract import ENTRY_JSON_RUNTIME_REMINDER
from app.domain.ports.llm_inference import ILLMInference, LLMNotReadyError
from app.infrastructure.mlx_gpu_lock import MLX_GPU_LOCK
from app.infrastructure.transformers_quiet import quiet_gemma4_tokenizer_config_warning

logger = logging.getLogger(__name__)

_DEFAULT_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _cloud_fallback_enabled() -> bool:
    """OpenRouter cloud path is opt-in; local MLX is the default contract."""
    v = (os.environ.get("LLM_CLOUD_FALLBACK_ENABLED") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


class MLXInferenceAdapter(ILLMInference):
    """MLX-based LLM inference adapter for Apple Silicon — 10-30x faster than PyTorch MPS."""

    _instance = None
    _env_loaded = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(
        self, model_path: str = "", temperature: float = 0.7, max_new_tokens: int = 256
    ):
        if self._initialized:
            return
        self.model = None
        self.processor = None
        self._is_loading = False
        self._load_error: str | None = None
        self._use_vlm: bool | None = None
        self._runtime_device: str | None = None
        self._model_path = model_path
        self._temperature = temperature
        self._max_new_tokens = max_new_tokens
        # Rate limiter: 1 request per second for OpenRouter
        self._last_request_time = 0.0
        self._min_request_interval = 1.0  # 1 second
        self._start_background_loading()
        self._initialized = True

    def _start_background_loading(self):
        """Kick off model loading on a daemon thread so the server starts immediately."""
        self._ensure_runtime_env_loaded()
        if not self._is_loading and self.model is None:
            # Check if model path is configured
            model_path = self._effective_model_path()
            if not model_path:
                logger.info(
                    "MLX: No model path configured — set MLX_MODEL_PATH or LLM_CLOUD_FALLBACK_ENABLED=1"
                )
                self._is_loading = False
                self._initialized = True
                return
            # Check if we should load immediately or defer
            # On macOS, MLX must be loaded in main thread, not background
            # So we load synchronously here to avoid OpenMP crashes
            self._is_loading = True
            logger.info("Loading MLX model synchronously (main thread)...")
            try:
                self._load_model()
            except Exception as e:
                logger.error(f"Failed to load MLX model: {e}")
                self._load_error = str(e)
                self._is_loading = False
                # If cloud fallback configured, we'll use that instead
                return

    def _load_model(self):
        """Load the MLX model and tokenizer from the configured path."""
        try:
            self._ensure_runtime_env_loaded()
            quiet_gemma4_tokenizer_config_warning()
            # Try mlx_lm first (text-only models), fallback to mlx_vlm (vision models)
            try:
                from mlx_lm import load, generate

                use_vlm = False
            except ImportError:
                from mlx_vlm import load, generate

                use_vlm = True

            model_path = self._resolve_model_dir(
                self._model_path or os.environ.get("MLX_MODEL_PATH", "")
            )
            adapter_path = self._resolve_local_path(
                os.environ.get("MLX_ADAPTER_PATH", "")
            )
            try:
                import mlx.core as mx

                self._runtime_device = str(mx.default_device())
            except Exception:
                self._runtime_device = None

            with MLX_GPU_LOCK:
                if adapter_path and os.path.exists(adapter_path):
                    logger.info(
                        f"Loading MLX model from {model_path} with adapter {adapter_path}..."
                    )
                    if use_vlm:
                        self.model, self.processor = load(
                            model_path, adapter_path=adapter_path
                        )
                    else:
                        self.model, self.tokenizer = load(
                            model_path, adapter_path=adapter_path
                        )
                        self.processor = self.tokenizer  # Compatibility
                else:
                    logger.info(f"Loading MLX model from {model_path} (no adapter)...")
                    if use_vlm:
                        self.model, self.processor = load(model_path)
                    else:
                        self.model, self.tokenizer = load(model_path)
                        self.processor = self.tokenizer  # Compatibility

            self._use_vlm = use_vlm
            self._is_loading = False
            logger.info("MLX model loaded successfully!")
        except Exception as e:
            logger.error(f"Failed to load MLX model: {e}")
            self._load_error = str(e)
            self._use_vlm = None
            self._is_loading = False

    @staticmethod
    def _resolve_local_path(path_value: str) -> str:
        """Resolve repo-relative adapter paths regardless of the current working directory."""
        if not path_value:
            return ""

        raw_path = Path(path_value).expanduser()
        candidates = [raw_path]

        if not raw_path.is_absolute():
            repo_root = Path(__file__).resolve().parents[4]
            candidates.append(repo_root / raw_path)

        for candidate in candidates:
            if candidate.exists():
                return str(candidate.resolve())

        return path_value

    @staticmethod
    def _resolve_model_dir(path_value: str) -> str:
        """Resolve local MLX weight dirs against cwd and repo root; leave HF hub ids unchanged."""
        p = (path_value or "").strip()
        if not p:
            return ""
        raw = Path(p).expanduser()
        if raw.is_file() or (raw.exists() and not raw.is_dir()):
            return str(raw.resolve())
        candidates: list[Path] = [raw, Path.cwd() / raw]
        if not raw.is_absolute():
            repo_root = Path(__file__).resolve().parents[4]
            candidates.append(repo_root / raw)
        for candidate in candidates:
            if candidate.exists():
                return str(candidate.resolve())
        return p

    def _effective_model_path(self) -> str:
        return self._resolve_model_dir(
            (self._model_path or os.environ.get("MLX_MODEL_PATH", "")).strip()
        )

    @classmethod
    def _ensure_runtime_env_loaded(cls) -> None:
        """Load the repo .env once so background model loading sees runtime config."""
        if cls._env_loaded:
            return

        # Look for .env in backend directory (3 levels up from adapter)
        backend_env_path = Path(__file__).resolve().parents[3] / ".env"
        # Also look in project root (4 levels up from adapter)
        root_env_path = Path(__file__).resolve().parents[4] / ".env"
        
        # Check backend directory first, then project root
        if backend_env_path.exists():
            env_path = backend_env_path
        elif root_env_path.exists():
            env_path = root_env_path
        else:
            # Fallback to project root
            env_path = root_env_path
        if env_path.exists():
            load_dotenv(env_path, override=False)
        cls._env_loaded = True

    def _predict_cloud(
        self,
        instruction: str,
        input_text: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Fallback: call OpenRouter cloud API when no local MLX model is available."""
        import json
        import time
        import urllib.request
        import urllib.error

        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        model_id = (os.environ.get("MODEL_ID") or "").strip() or "openrouter/auto"
        fallback_url = (
            (os.environ.get("CLOUD_FALLBACK_URL") or "").strip()
            or _DEFAULT_OPENROUTER_URL
        )
        if not fallback_url.strip():
            logger.error("CLOUD_FALLBACK_URL is empty after coercion; skipping urlopen")
            return json.dumps(
                {
                    "direction": "FLAT",
                    "rationale": "Cloud fallback URL is not configured",
                    "confidence": "Low",
                }
            )

        logger.info(
            f"[CLOUD] OpenRouter config: model={model_id}, url={fallback_url}, api_key_len={len(api_key)}"
        )

        if not api_key:
            raise LLMNotReadyError(
                "No OPENROUTER_API_KEY configured for cloud fallback"
            )

        # Rate limiting: enforce 1 request/second
        import time as time_module

        with threading.Lock():
            current_time = time_module.time()
            time_since_last = current_time - self._last_request_time
            if time_since_last < self._min_request_interval:
                wait_time = self._min_request_interval - time_since_last
                logger.info(
                    f"Rate limiting: waiting {wait_time:.2f}s before next OpenRouter request"
                )
                time_module.sleep(wait_time)
            self._last_request_time = time_module.time()

        # #Fix-429: Exponential backoff on rate limit errors
        max_retries = 3
        base_delay = 5.0  # seconds
        last_error = None

        for attempt in range(max_retries):
            temp = temperature if temperature is not None else self._temperature
            max_t = max_tokens if max_tokens is not None else self._max_new_tokens

            messages = [
                {"role": "system", "content": instruction},
                {"role": "user", "content": input_text},
            ]

            payload = json.dumps(
                {
                    "model": model_id,
                    "messages": messages,
                    "temperature": temp,
                    "max_tokens": max_t,
                }
            ).encode()

            req = urllib.request.Request(
                fallback_url,
                data=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "http://localhost:5190",
                    "X-Title": "GlassyTrade AI",
                },
                method="POST",
            )

            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    result = json.loads(resp.read())
                    choices = result.get("choices", [])
                    if not choices:
                        logger.warning(f"Cloud LLM returned no choices: {result}")
                        continue

                    content = choices[0].get("message", {}).get("content")
                    # Validate content is not None before returning
                    if content is None:
                        logger.warning("Cloud LLM returned None content")
                        continue
                    return str(content)
            except urllib.error.HTTPError as e:
                last_error = e
                if e.code == 429:
                    # Rate limited — exponential backoff
                    delay = base_delay * (2**attempt)
                    logger.warning(
                        f"Cloud LLM rate limited (429). "
                        f"Retry {attempt + 1}/{max_retries} in {delay:.0f}s"
                    )
                    time.sleep(delay)
                    continue
                else:
                    logger.error(f"Cloud LLM fallback HTTP {e.code} failed: {e.reason}")
                    last_error = e
            except urllib.error.URLError as e:
                logger.error(f"Cloud LLM fallback network failed: {e}")
                last_error = e
            except (json.JSONDecodeError, KeyError, IndexError) as e:
                logger.error(f"Cloud LLM response malformed: {e}")
                last_error = e
            except Exception as e:
                logger.error(f"Unexpected error in cloud fallback: {e}")
                last_error = e

        # All retries exhausted or fatal error
        msg = f"Cloud fallback failed after {max_retries} attempts. Last error: {last_error}"
        logger.error(msg)
        return json.dumps({"direction": "FLAT", "rationale": msg, "confidence": "Low"})

    def predict(
        self,
        instruction: str,
        input_text: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        prefill: str | None = None,
    ) -> str:
        """Generate a prediction using the active runtime contract.

        Args:
            instruction: System instruction for the model.
            input_text: User input text (market data prompt).
            temperature: Sampling temperature override.
            max_tokens: Max new tokens override.
            prefill: Optional prefill for assistant response.
        """
        self._ensure_runtime_env_loaded()
        if not self.model:
            if self._is_loading:
                raise LLMNotReadyError("Model is still loading")
            model_path = self._effective_model_path()
            if _cloud_fallback_enabled() and not model_path:
                return self._predict_cloud(
                    instruction, input_text, temperature, max_tokens
                )
            detail = self._load_error or "unknown error"
            raise LLMNotReadyError(
                f"Local MLX model not loaded (path={model_path or '(none)'}): {detail}"
            )

        if self._use_vlm:
            from mlx_vlm import generate
        else:
            from mlx_lm import generate

        # ChatML format with response prefill to keep output aligned with the
        # canonical runtime contract. Legacy structured parsing still exists as
        # a fallback, but JSON is the active paper-trading format.
        clean_input = input_text.strip()
        # Detect if this is an Overseer prompt or an Entry prompt
        is_overseer = "HOLD" in instruction and "FULL_EXIT" in instruction

        sys_msg = instruction
        if not is_overseer:
            sys_msg = f"{instruction}\n{ENTRY_JSON_RUNTIME_REMINDER}"

        if prefill is None:
            prefill = "{"

        messages = [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": clean_input},
        ]

        prompt = self.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        # Inject prefill (e.g., forcing JSON start)
        prompt += prefill

        max_t = max_tokens if max_tokens is not None else self._max_new_tokens

        target = (
            "OVERSEER"
            if is_overseer
            else ("REASONING" if prefill and "think" in prefill else "ENTRY")
        )

        # Metal GPU crashes on concurrent generate() calls — serialize with lock
        import time as _time

        t0 = _time.time()
        with MLX_GPU_LOCK:
            logger.info(f"[{target}] Starting generation (max_tokens={max_t})...")
            # mlx_vlm defaults to deterministic parsing when sampling kwargs are omitted seamlessly
            response = generate(
                self.model,
                self.processor,
                prompt=prompt,
                max_tokens=max_t,
                verbose=False,
            )
            duration = _time.time() - t0
            logger.info(f"[{target}] Generation complete in {duration:.2f}s.")

        rendered = prefill + (response or "").strip()
        if is_overseer:
            return self._truncate_repetition(rendered)
        return self._extract_json_candidate(rendered)

    @staticmethod
    def _truncate_repetition(text: str) -> str:
        """Robustly truncate rambling/repetitive thinking blocks.

        Uses a multi-delimiter split for sentence-level duplication and enforces
        a hard character limit for the 'thinking' portion.
        Specific logic added to catch 'Incremental List Rambling' (1., 2., 3...).
        """
        if not text:
            return text

        # Split into thinking and JSON if possible
        parts = text.split("```json")
        thinking = parts[0]
        json_part = "```json" + parts[1] if len(parts) > 1 else ""

        # 1. Hard character limit for thinking (rambling prevention)
        MAX_THINK_CHARS = 2500
        if len(thinking) > MAX_THINK_CHARS:
            thinking = thinking[:MAX_THINK_CHARS] + "\n...[thinking truncated]...\n"

        # 2. Multi-delimiter sentence repetition detection
        import re as _re

        # Split by periods, double dashes, or newlines
        segments = _re.split(r"[.\n]|--", thinking)

        result_segments = []
        seen_pattern_count = {}
        list_item_count = 0

        for s in segments:
            clean = s.strip()
            if not clean:
                continue

            # Use a normalized key for duplicate detection
            # Ignore numbers/prices to catch "Price at POC: [X]" rambling
            norm_key = _re.sub(r"\d+", "#", clean.lower())

            # Detect numbered list items (e.g., "14. **OI patterns**")
            is_numbered_list = _re.match(r"^[\*]*#[\.\)]", norm_key)
            if is_numbered_list:
                list_item_count += 1
                # If we have more than 15 list items in one reasoning block, it's likely rambling
                if list_item_count > 15:
                    result_segments.append("...[excessive list truncated]...")
                    break

            seen_pattern_count[norm_key] = seen_pattern_count.get(norm_key, 0) + 1
            if seen_pattern_count[norm_key] > 2:
                # If we've seen this exact pattern twice, skip it unless it's very short
                if len(clean) > 10:
                    continue

            result_segments.append(clean)

        # Reconstruct with reasonable spacing
        thinking_truncated = ". ".join(result_segments[:100])
        if thinking_truncated and not thinking_truncated.endswith("."):
            thinking_truncated += "."

        return (
            thinking_truncated + "\n\n" + json_part if json_part else thinking_truncated
        )

    @staticmethod
    def _extract_json_candidate(text: str) -> str:
        """Return the first balanced JSON object if one is present."""
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
        """True only when local MLX weights are loaded (cloud is not counted as ready)."""
        if self._is_loading:
            return False
        if self._load_error is not None:
            return False
        return self.model is not None

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
            ok = len((result or "").strip()) > 0
            if ok:
                logger.info(
                    f"MLX model validation passed. Sample output: {result[:80]}"
                )
            else:
                logger.error("MLX model validation failed: empty response")
            return ok
        except Exception as e:
            logger.error(f"MLX model validation failed: {e}")
            return False
