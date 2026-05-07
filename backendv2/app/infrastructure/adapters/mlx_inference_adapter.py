"""MLX-based LLM inference adapter for backendv2.

This is a v2 port of the existing v1 adapter with minimal contract changes:
 - Implements :class:`ILLMInference`
 - Preserves MLX/local and OpenRouter cloud fallback behavior
 - Keeps deterministic JSON contract parsing behavior used by ``LLMEntryHandler``
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

from dotenv import load_dotenv

from app.domain.shared.port import ILLMInference, LLMNotReadyError

try:
    from app.core.cost_tracker import TokenUsage, get_cost_tracker
    _HAS_COST_TRACKING = True
except ImportError:
    _HAS_COST_TRACKING = False

try:  # pragma: no cover - optional cross-process lock dependency
    import fcntl
except Exception:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_DEFAULT_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Keep the original canonical entry contract wording in v2 runtime too.
ENTRY_JSON_RUNTIME_REMINDER = (
    "Return ONLY a valid JSON object with direction, confidence, and rationale keys. "
    "No markdown, no extra text, no prose outside the JSON."
)


def _cloud_fallback_enabled() -> bool:
    """OpenRouter cloud path is opt-in; local MLX is the default contract."""
    v = (os.environ.get("LLM_CLOUD_FALLBACK_ENABLED") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _ensure_transformers_quiet() -> None:
    """Filter noisy HF transformers warning seen with Gemma4 MLX loads."""
    global _QUIET_CONFIGURED
    if _QUIET_CONFIGURED:
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
    _QUIET_CONFIGURED = True


_QUIET_CONFIGURED = False


class _SystemGPULock:
    """Lightweight lock for MLX GPU access.

    v1 uses a cross-process lock in ``backend`` with ``fcntl``. v2 keeps the
    same concurrency safety intention while degrading gracefully on platforms
    without file-lock support.
    """

    def __init__(self):
        self._thread_lock = threading.Lock()
        self._fp = None
        self._lock_file_path = Path("/tmp/mlx_gpu_system.lock")

    def __enter__(self):
        self._thread_lock.acquire()
        if fcntl is None:
            return self
        try:
            if self._fp is None:
                self._fp = open(self._lock_file_path, "w")
            fcntl.flock(self._fp, fcntl.LOCK_EX)
        except Exception as e:
            self._thread_lock.release()
            logger.error("Failed to acquire MLX GPU lock: %s", e)
            raise
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if self._fp is not None and fcntl is not None:
                fcntl.flock(self._fp, fcntl.LOCK_UN)
        finally:
            self._thread_lock.release()


MLX_GPU_LOCK = _SystemGPULock()


class MLXInferenceAdapter(ILLMInference):
    """MLX-based LLM inference adapter for Apple Silicon."""

    STATE_UNINITIALIZED = "UNINITIALIZED"
    STATE_INIT = "INIT"
    STATE_DEFERRED = "DEFERRED_READY"
    STATE_LOADING = "LOADING_LOCAL"
    STATE_READY_LOCAL = "READY_LOCAL"
    STATE_READY_CLOUD = "READY_CLOUD"
    STATE_DEGRADED_NO_LOCAL_MODEL = "DEGRADED_NO_LOCAL_MODEL"
    STATE_FAILED_LOCAL = "FAILED_LOCAL"
    STATE_FAILED_CLOUD_CREDENTIALS = "FAILED_CLOUD_CREDENTIALS"

    _instance = None
    _env_loaded = False
    _init_lock = threading.Lock()

    # Class-level request serialization lock + cooldown state mirrors v1.
    _cloud_lock = threading.Lock()
    _last_cloud_request_time: float = 0.0
    _cloud_cooldown_until: float = 0.0
    _cloud_consecutive_429s: int = 0
    _cloud_last_working_model: str | None = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._init_lock:
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
        self._state = self.STATE_UNINITIALIZED
        self._state_reason: str | None = None
        self._start_background_loading()
        self._initialized = True

    def _set_state(self, state: str, reason: str | None = None) -> None:
        self._state = state
        self._state_reason = reason
        logger.info("MLX state=%s reason=%s", state, reason or "")

    def _start_background_loading(self):
        """Kick off model loading without blocking startup."""
        self._set_state(self.STATE_INIT, "bootstrap")
        self._ensure_runtime_env_loaded()
        if not self._is_loading and self.model is None:
            if _cloud_fallback_enabled():
                if not os.getenv("OPENROUTER_API_KEY", "").strip():
                    self._load_error = (
                        "LLM_CLOUD_FALLBACK_ENABLED but OPENROUTER_API_KEY is missing"
                    )
                    self._set_state(self.STATE_FAILED_CLOUD_CREDENTIALS, self._load_error)
                    self._is_loading = False
                    return
                self._set_state(self.STATE_READY_CLOUD, "cloud fallback enabled")
                return

            model_path = self._effective_model_path()
            if not model_path:
                self._set_state(
                    self.STATE_DEGRADED_NO_LOCAL_MODEL,
                    "No model path configured and cloud fallback disabled",
                )
                self._is_loading = False
                self._initialized = True
                return

            defer_loading = os.environ.get("MLX_DEFER_LOADING", "0").lower() in ("1", "true", "yes")
            if defer_loading:
                self._set_state(self.STATE_DEFERRED, "deferred loading active")
                self._is_loading = False
                self._initialized = True
                return

            # On macOS MLX must be loaded in main thread.
            self._set_state(self.STATE_LOADING, "loading local model synchronously")
            self._is_loading = True
            logger.info("Loading MLX model synchronously (main thread)...")
            try:
                self._load_model()
            except Exception as e:
                logger.error("Failed to load MLX model: %s", e)
                self._load_error = str(e)
                self._set_state(self.STATE_FAILED_LOCAL, self._load_error)
                self._is_loading = False

    def _load_model(self):
        """Load the MLX model and tokenizer from configured path."""
        self._set_state(self.STATE_LOADING, "loading local model")
        try:
            self._ensure_runtime_env_loaded()
            _ensure_transformers_quiet()

            model_path = self._resolve_model_dir(
                self._model_path or os.environ.get("MLX_MODEL_PATH", "")
            )
            adapter_path = self._resolve_local_path(
                os.environ.get("MLX_ADAPTER_PATH", "")
            )

            logger.info("Resolving model architecture for %s", model_path)
            use_vlm = self._detect_vlm_architecture(model_path)
            if use_vlm:
                from mlx_vlm import load
                logger.info("Using mlx_vlm loader (VLM architecture detected)")
            else:
                from mlx_lm import load
                logger.info("Using mlx_lm loader (text-only architecture)")

            try:
                import mlx.core as mx

                self._runtime_device = str(mx.default_device())
                logger.info("MLX device: %s", self._runtime_device)
            except Exception as e:
                logger.warning("Failed to get MLX device: %s", e)
                self._runtime_device = None

            with MLX_GPU_LOCK:
                if adapter_path and os.path.exists(adapter_path):
                    logger.info("Loading MLX model from %s with adapter %s...", model_path, adapter_path)
                    self.model, self.processor = load(model_path, adapter_path=adapter_path)
                else:
                    logger.info("Loading MLX model from %s (no adapter)...", model_path)
                    self.model, self.processor = load(model_path)

            self._use_vlm = use_vlm
            self._is_loading = False
            self._load_error = None
            self._set_state(self.STATE_READY_LOCAL, "local model loaded")
            logger.info("MLX model loaded successfully!")
        except Exception as e:
            logger.error("Failed to load MLX model: %s", e)
            import traceback
            logger.error(traceback.format_exc())
            self._load_error = str(e)
            self._use_vlm = None
            self._is_loading = False
            self._set_state(self.STATE_FAILED_LOCAL, self._load_error)

    @staticmethod
    def _detect_vlm_architecture(model_path: str) -> bool:
        """Detect VLM architecture from config.json if present."""
        config_file = Path(model_path) / "config.json"
        if not config_file.exists():
            return False

        try:
            with open(config_file, encoding="utf-8") as f:
                config = json.load(f)
            architectures = config.get("architectures", [])
            is_vlm_config = False
            for arch in architectures:
                if "ConditionalGeneration" in arch or "VLM" in arch:
                    is_vlm_config = True
                    break
            if not is_vlm_config:
                if any("token_id" in k for k in config if k.startswith(("image_", "video_", "audio_", "vision_"))):
                    is_vlm_config = True
            if not is_vlm_config:
                return False

            index_file = Path(model_path) / "model.safetensors.index.json"
            if index_file.exists():
                with open(index_file, encoding="utf-8") as f:
                    index = json.load(f)
                weight_keys = index.get("weight_map", index.get("metadata", {}))
                if isinstance(weight_keys, dict):
                    has_vision = any(
                        k.startswith(("vision_tower.", "embed_vision.", "visual."))
                        for k in weight_keys
                    )
                    if not has_vision:
                        logger.info(
                            "VLM config detected but no vision weights in model — "
                            "treating as text-only model"
                        )
                        return False
        except Exception:
            pass
        return True

    @staticmethod
    def _resolve_local_path(path_value: str) -> str:
        """Resolve repo-relative adapter paths regardless of cwd."""
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
        """Resolve model directories against cwd/repo; keep HF ids untouched."""
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
        """Load .env once so background model loading sees runtime config."""
        if cls._env_loaded:
            return

        backend_env_path = Path(__file__).resolve().parents[3] / ".env"
        root_env_path = Path(__file__).resolve().parents[4] / ".env"
        if backend_env_path.exists():
            env_path = backend_env_path
        elif root_env_path.exists():
            env_path = root_env_path
        else:
            env_path = root_env_path
        if env_path.exists():
            load_dotenv(env_path, override=False)
        cls._env_loaded = True

    # ------------------------------------------------------------------
    # Cloud inference + resilience handling.
    # ------------------------------------------------------------------
    def _get_model_chain(self) -> list[str]:
        raw = (os.environ.get("MODEL_ID") or "").strip()
        if raw:
            chain = [m.strip() for m in raw.split(",") if m.strip()]
            if chain:
                return chain
        return [
            "openai/gpt-oss-120b:free",
            "nvidia/nemotron-3-super-120b-a12b:free",
            "z-ai/glm-4.5-air:free",
        ]

    def _predict_cloud(
        self,
        instruction: str,
        input_text: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Cloud inference with model fallback, serialization, and cooldowns."""
        import time
        import urllib.error
        import urllib.request

        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        fallback_url = (
            (os.environ.get("CLOUD_FALLBACK_URL") or "").strip()
            or _DEFAULT_OPENROUTER_URL
        )
        if not api_key:
            raise LLMNotReadyError("No OPENROUTER_API_KEY configured for cloud fallback")

        model_chain = self._get_model_chain()
        if self._cloud_last_working_model and self._cloud_last_working_model in model_chain:
            model_chain.remove(self._cloud_last_working_model)
            model_chain.insert(0, self._cloud_last_working_model)

        now = time.time()
        if now < MLXInferenceAdapter._cloud_cooldown_until:
            remaining = MLXInferenceAdapter._cloud_cooldown_until - now
            logger.info("[CLOUD] In cooldown for %ds — returning FLAT", remaining)
            return json.dumps(
                {
                    "direction": "FLAT",
                    "rationale": f"Cloud LLM in cooldown ({remaining:.0f}s remaining) — rate limited",
                    "confidence": "Low",
                }
            )

        with MLXInferenceAdapter._cloud_lock:
            min_interval = 2.0
            elapsed = time.time() - MLXInferenceAdapter._last_cloud_request_time
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
            MLXInferenceAdapter._last_cloud_request_time = time.time()

            temp = temperature if temperature is not None else self._temperature
            max_t = max_tokens if max_tokens is not None else self._max_new_tokens
            messages = [
                {"role": "system", "content": instruction},
                {"role": "user", "content": input_text},
            ]

            last_error = None
            for model_id in model_chain:
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
                            logger.warning("[CLOUD] No choices from %s: %s", model_id, result)
                            continue
                        content = choices[0].get("message", {}).get("content")
                        if content is None:
                            logger.warning("[CLOUD] None content from %s", model_id)
                            continue
                        MLXInferenceAdapter._cloud_consecutive_429s = 0
                        MLXInferenceAdapter._cloud_last_working_model = model_id

                        # Track cloud token usage
                        if _HAS_COST_TRACKING:
                            try:
                                usage_data = result.get("usage", {})
                                usage = TokenUsage(
                                    prompt_tokens=usage_data.get("prompt_tokens", 0),
                                    completion_tokens=usage_data.get("completion_tokens", 0),
                                    total_tokens=usage_data.get("total_tokens", 0),
                                    model=model_id,
                                    is_cloud=True,
                                )
                                get_cost_tracker().record_llm_call(usage)
                            except Exception:
                                pass

                        return str(content)

                except urllib.error.HTTPError as e:
                    last_error = e
                    if e.code == 429:
                        MLXInferenceAdapter._cloud_consecutive_429s += 1
                        if _HAS_COST_TRACKING:
                            try:
                                get_cost_tracker().record_cloud_429()
                            except Exception:
                                pass
                        retry_after = e.headers.get("Retry-After")
                        if retry_after:
                            try:
                                delay = float(retry_after)
                            except ValueError:
                                delay = 5.0
                        else:
                            delay = 5.0

                        consecutive = MLXInferenceAdapter._cloud_consecutive_429s
                        logger.warning(
                            "[CLOUD] 429 from %s (consecutive=%d, retry_after=%.0fs) — trying next model",
                            model_id,
                            consecutive,
                            delay,
                        )
                        if consecutive >= len(model_chain) * 2:
                            cooldown = min(delay * 3, 120)
                            MLXInferenceAdapter._cloud_cooldown_until = time.time() + cooldown
                            logger.warning(
                                "[CLOUD] Entering cooldown for %ds (too many 429s)",
                                cooldown,
                            )
                            break
                        time.sleep(min(delay, 3.0))
                        continue
                    logger.error("[CLOUD] HTTP %s from %s: %s", e.code, model_id, e.reason)
                    continue
                except urllib.error.URLError as e:
                    logger.error("[CLOUD] Network error with %s: %s", model_id, e)
                    last_error = e
                    continue
                except Exception as e:
                    logger.error("[CLOUD] Unexpected error with %s: %s", model_id, e)
                    last_error = e
                    continue

        return json.dumps(
            {
                "direction": "FLAT",
                "rationale": f"Cloud LLM failed — all {len(model_chain)} models exhausted. Last error: {last_error}",
                "confidence": "Low",
            }
        )

    def predict(
        self,
        instruction: str,
        input_text: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        prefill: str | None = None,
    ) -> str:
        """Generate a prediction via MLX local model or OpenRouter fallback."""
        self._ensure_runtime_env_loaded()
        if _cloud_fallback_enabled():
            if not os.getenv("OPENROUTER_API_KEY", "").strip():
                raise LLMNotReadyError("Cloud fallback enabled but OPENROUTER_API_KEY is missing")
            self._set_state(self.STATE_READY_CLOUD, "cloud fallback path selected")
            return self._predict_cloud(instruction, input_text, temperature, max_tokens)

        # Lazy load on first request if deferred.
        if not self.model and not self._is_loading:
            defer_loading = os.environ.get("MLX_DEFER_LOADING", "0").lower() in ("1", "true", "yes")
            if defer_loading:
                self._set_state(self.STATE_LOADING, "lazy load on first request")
                self._is_loading = True
                try:
                    self._load_model()
                except Exception as e:
                    logger.error("Failed to load MLX model on first request: %s", e)
                    self._load_error = str(e)
                    self._set_state(self.STATE_FAILED_LOCAL, self._load_error)
                    self._is_loading = False
                    model_path = self._effective_model_path()
                    if _cloud_fallback_enabled() and not model_path:
                        return self._predict_cloud(instruction, input_text, temperature, max_tokens)
                    raise LLMNotReadyError(f"Model failed to load: {e}")

        if not self.model:
            if self._is_loading:
                raise LLMNotReadyError("Model is still loading")
            model_path = self._effective_model_path()
            if _cloud_fallback_enabled():
                if not os.getenv("OPENROUTER_API_KEY", "").strip():
                    self._set_state(
                        self.STATE_FAILED_CLOUD_CREDENTIALS,
                        "Cloud fallback enabled but API key missing",
                    )
                    raise LLMNotReadyError(
                        "Cloud fallback enabled but OPENROUTER_API_KEY is missing"
                    )
                return self._predict_cloud(instruction, input_text, temperature, max_tokens)
            detail = getattr(self, "_load_error", None) or "failed to load"
            raise LLMNotReadyError(
                f"Local MLX model not loaded (path={model_path or '(none)'}): {detail}"
            )

        if self._use_vlm:
            from mlx_vlm import generate
        else:
            from mlx_lm import generate

        clean_input = input_text.strip()
        is_overseer = "HOLD" in instruction and "FULL_EXIT" in instruction
        sys_msg = instruction if is_overseer else f"{instruction}\n{ENTRY_JSON_RUNTIME_REMINDER}"

        if prefill is None:
            prefill = "{"

        try:
            messages = [
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": clean_input},
            ]
            prompt = self.processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
        except Exception as e:
            err_str = str(e).lower()
            if "system" in err_str or "role" in err_str or "support" in err_str:
                logger.info("MLX: system role not supported by template, merging into user message.")
                messages = [{"role": "user", "content": f"{sys_msg}\n\n{clean_input}"}]
                prompt = self.processor.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True
                )
            else:
                raise

        prompt += prefill
        max_t = max_tokens if max_tokens is not None else self._max_new_tokens
        target = "OVERSEER" if is_overseer else ("REASONING" if prefill and "think" in prefill else "ENTRY")

        import time as _time
        from mlx_lm.sample_utils import make_sampler

        t0 = _time.time()
        with MLX_GPU_LOCK:
            logger.info("[%s] Starting generation (max_tokens=%d, temp=%s)...", target, max_t, self._temperature)
            sampler = make_sampler(temp=self._temperature, top_p=0.95)
            response = generate(
                self.model,
                self.processor,
                prompt=prompt,
                max_tokens=max_t,
                verbose=False,
                sampler=sampler,
            )
            duration = _time.time() - t0
            logger.info("[%s] Generation complete in %.2fs.", target, duration)

        rendered = prefill + (response or "").strip()

        # Track token usage for local inference (approximate)
        if _HAS_COST_TRACKING:
            try:
                prompt_tokens = len(self.processor.tokenize(prompt))
                completion_tokens = len(self.processor.tokenize(response or ""))
                usage = TokenUsage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=prompt_tokens + completion_tokens,
                    model=self._effective_model_path().split("/")[-1] or "mlx-local",
                    is_cloud=False,
                )
                get_cost_tracker().record_llm_call(usage)
            except Exception:
                pass  # Don't let cost tracking break inference

        if is_overseer:
            return self._truncate_repetition(rendered)
        return self._extract_json_candidate(rendered)

    @staticmethod
    def _truncate_repetition(text: str) -> str:
        """Truncate runaway repetitive blocks in model output."""
        if not text:
            return text

        parts = text.split("```json")
        thinking = parts[0]
        json_part = "```json" + parts[1] if len(parts) > 1 else ""

        MAX_THINK_CHARS = 2500
        if len(thinking) > MAX_THINK_CHARS:
            thinking = thinking[:MAX_THINK_CHARS] + "\n...[thinking truncated]...\n"

        import re as _re

        segments = _re.split(r"[.\n]|--", thinking)
        result_segments = []
        seen_pattern_count = {}
        list_item_count = 0

        for s in segments:
            clean = s.strip()
            if not clean:
                continue
            norm_key = _re.sub(r"\d+", "#", clean.lower())
            is_numbered_list = _re.match(r"^[\*]*#[\.\)]", norm_key)
            if is_numbered_list:
                list_item_count += 1
                if list_item_count > 15:
                    result_segments.append("...[excessive list truncated]...")
                    break

            seen_pattern_count[norm_key] = seen_pattern_count.get(norm_key, 0) + 1
            if seen_pattern_count[norm_key] > 2 and len(clean) > 10:
                continue
            result_segments.append(clean)

        thinking_truncated = ". ".join(result_segments[:100])
        if thinking_truncated and not thinking_truncated.endswith("."):
            thinking_truncated += "."
        return thinking_truncated + ("\n\n" + json_part if json_part else "")

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
        """True when LLM is ready for inference."""
        if _cloud_fallback_enabled():
            api_key = os.environ.get("OPENROUTER_API_KEY", "")
            return bool(api_key.strip())

        defer_loading = os.environ.get("MLX_DEFER_LOADING", "0").lower() in ("1", "true", "yes")
        if defer_loading:
            return self._is_loading is False and self._state in {
                self.STATE_DEFERRED,
                self.STATE_READY_LOCAL,
                self.STATE_READY_CLOUD,
            }

        if self._is_loading:
            return False
        if getattr(self, "_load_error", None) is not None:
            return False
        return self.model is not None

    def runtime_state(self) -> dict[str, str | None]:
        """Machine-readable MLX lifecycle state."""
        return {
            "state": self._state,
            "reason": self._state_reason,
            "load_error": self._load_error,
            "is_loading": str(self._is_loading),
        }

    def wait_until_ready(self, timeout: float = 120.0) -> bool:
        """Block until model is ready or timeout."""
        import time

        start = time.time()
        while time.time() - start < timeout:
            if self.is_ready():
                return True
            if not self._is_loading and self.model is None:
                return False
            time.sleep(0.5)
        return self.is_ready()

    def validate(self) -> bool:
        """Run a quick validation inference to confirm readiness."""
        if not self.is_ready():
            return False
        try:
            result = self.predict(
                instruction="Respond with OK if you can process this.",
                input_text="Validation check.",
            )
            ok = len((result or "").strip()) > 0
            if ok:
                logger.info("MLX model validation passed. Sample output: %s", result[:80])
            else:
                logger.error("MLX model validation failed: empty response")
            return ok
        except Exception as e:
            logger.error("MLX model validation failed: %s", e)
            return False
