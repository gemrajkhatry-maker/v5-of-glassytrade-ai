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
    """OpenRouter cloud path is opt-in; local MLX is the default contract.
    
    When enabled (LLM_CLOUD_FALLBACK_ENABLED=1), ALL inference goes through
    OpenRouter and the local MLX model is not loaded at all.
    """
    v = (os.environ.get("LLM_CLOUD_FALLBACK_ENABLED") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


class MLXInferenceAdapter(ILLMInference):
    """MLX-based LLM inference adapter for Apple Silicon — 10-30x faster than PyTorch MPS."""

    _instance = None
    _env_loaded = False
    _init_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:  # Double-check after acquiring lock
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
        self._start_background_loading()
        self._initialized = True

    def _start_background_loading(self):
        """Kick off model loading on a daemon thread so the server starts immediately."""
        self._ensure_runtime_env_loaded()
        if not self._is_loading and self.model is None:
            # If cloud fallback is enabled, skip local model loading entirely
            if _cloud_fallback_enabled():
                logger.info(
                    "LLM_CLOUD_FALLBACK_ENABLED=1 — skipping local MLX model load, "
                    "using OpenRouter for all inference"
                )
                self._is_loading = False
                self._initialized = True
                return
            # Check if model path is configured
            model_path = self._effective_model_path()
            if not model_path:
                logger.info(
                    "MLX: No model path configured — set MLX_MODEL_PATH or LLM_CLOUD_FALLBACK_ENABLED=1"
                )
                self._is_loading = False
                self._initialized = True
                return
            
            # Check if we should defer loading (prevent Metal crashes during uvicorn startup)
            defer_loading = os.environ.get("MLX_DEFER_LOADING", "0").lower() in ("1", "true", "yes")
            if defer_loading:
                logger.info(
                    "MLX_DEFER_LOADING=1 — deferring model load to first inference request "
                    "(prevents Metal GPU crashes during uvicorn startup)"
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
                logger.error("Failed to load MLX model: %s", e)
                self._load_error = str(e)
                self._is_loading = False
                # If cloud fallback configured, we'll use that instead
                return

    def _load_model(self):
        """Load the MLX model and tokenizer from the configured path."""
        try:
            self._ensure_runtime_env_loaded()
            quiet_gemma4_tokenizer_config_warning()

            model_path = self._resolve_model_dir(
                self._model_path or os.environ.get("MLX_MODEL_PATH", "")
            )
            adapter_path = self._resolve_local_path(
                os.environ.get("MLX_ADAPTER_PATH", "")
            )
            
            logger.info("DEBUG: Resolving model architecture for %s", model_path)
            # Detect model architecture from config.json to choose the right loader.
            # Gemma 4 26B A4B is a VLM (Gemma4ForConditionalGeneration) and MUST
            # use mlx_vlm — mlx_lm will fail or misbehave on VLM architectures.
            use_vlm = self._detect_vlm_architecture(model_path)
            if use_vlm:
                logger.info("DEBUG: Importing mlx_vlm...")
                from mlx_vlm import load, generate
                logger.info("Using mlx_vlm loader (VLM architecture detected)")
            else:
                logger.info("DEBUG: Importing mlx_lm...")
                from mlx_lm import load, generate
                logger.info("Using mlx_lm loader (text-only architecture)")

            try:
                import mlx.core as mx
                self._runtime_device = str(mx.default_device())
                logger.info("DEBUG: MLX device: %s", self._runtime_device)
            except Exception as e:
                logger.warning("DEBUG: Failed to get MLX device: %s", e)
                self._runtime_device = None

            with MLX_GPU_LOCK:
                if adapter_path and os.path.exists(adapter_path):
                    logger.info(
                        f"Loading MLX model from {model_path} with adapter {adapter_path}..."
                    )
                    self.model, self.processor = load(
                        model_path, 
                        adapter_path=adapter_path
                    )
                else:
                    logger.info("Loading MLX model from %s (no adapter)...", model_path)
                    logger.info("DEBUG: Calling load()...")
                    self.model, self.processor = load(model_path)
                    logger.info("DEBUG: load() finished.")

            self._use_vlm = use_vlm
            self._is_loading = False
            logger.info("MLX model loaded successfully!")
            
            # Warm-up inference to pre-heat Metal GPU caches
            # This prevents latency spikes on first real inference
            try:
                logger.info("Running warm-up inference (pre-heats Metal GPU caches)...")
                self._run_warmup()
            except Exception as e:
                logger.warning("Warm-up inference failed (non-critical): %s", e)
        except Exception as e:
            logger.error("Failed to load MLX model: %s", e)
            import traceback
            logger.error(traceback.format_exc())
            self._load_error = str(e)
            self._use_vlm = None
            self._is_loading = False

    @staticmethod
    def _detect_vlm_architecture(model_path: str) -> bool:
        """Detect whether a model is a VLM by reading config.json.

        VLMs have architectures like Gemma4ForConditionalGeneration,
        LlavaForConditionalGeneration, etc. and contain vision/audio tokens.

        IMPORTANT: Some fused production models strip vision weights but keep
        the VLM config.json. We verify that vision/audio weights actually
        exist in the model files before returning True.
        """
        import json
        from pathlib import Path

        config_file = Path(model_path) / "config.json"
        if not config_file.exists():
            return False

        try:
            with open(config_file) as f:
                config = json.load(f)
            architectures = config.get("architectures", [])
            # VLM architectures contain "ConditionalGeneration" or "VLM"
            is_vlm_config = False
            for arch in architectures:
                if "ConditionalGeneration" in arch or "VLM" in arch:
                    is_vlm_config = True
                    break
            # Also check for vision/audio token configs
            if not is_vlm_config:
                if any("token_id" in k for k in config if k.startswith(("image_", "video_", "audio_", "vision_"))):
                    is_vlm_config = True

            if not is_vlm_config:
                return False

            # Config says VLM — but verify vision weights actually exist.
            # Fused production models strip vision_tower/embed_vision weights
            # while keeping the VLM config.json. Without vision weights,
            # mlx_vlm.load() will fail with "Missing N parameters".
            index_file = Path(model_path) / "model.safetensors.index.json"
            if index_file.exists():
                with open(index_file) as f:
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

    def _run_warmup(self) -> None:
        """Run a minimal inference pass to pre-heat Metal GPU caches.
        
        This prevents latency spikes on the first real trading inference by:
        1. Pre-compiling Metal GPU shaders
        2. Allocating KV cache memory upfront
        3. Warming up the tokenizer pipeline
        """
        if not self.model or not self.processor:
            return
            
        warmup_prompt = "Ready"
        try:
            if self._use_vlm:
                from mlx_vlm import generate
            else:
                from mlx_lm import generate

            # Minimal warmup: 10 tokens only
            generate(
                self.model,
                self.processor,
                prompt=warmup_prompt,
                max_tokens=10,
                verbose=False,
                temperature=0.0,  # Deterministic for warmup
            )
            logger.info("Metal GPU caches warmed successfully")
        except Exception as e:
            # Non-critical: main inference will still work
            logger.debug("Warmup skipped: %s", e)

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

    # ------------------------------------------------------------------
    # Cloud LLM: model fallback chain, serialized queue, smart 429 handling
    # ------------------------------------------------------------------

    # Class-level request serialization lock — prevents concurrent API calls
    # across all symbols/threads (OpenRouter free tier has very low concurrency)
    _cloud_lock = threading.Lock()
    _last_cloud_request_time: float = 0.0
    _cloud_cooldown_until: float = 0.0  # Timestamp until which we skip all requests
    _cloud_consecutive_429s: int = 0
    _cloud_last_working_model: str | None = None

    def _get_model_chain(self) -> list[str]:
        """Parse MODEL_ID (comma-separated) into a fallback chain, or use defaults."""
        raw = (os.environ.get("MODEL_ID") or "").strip()
        if raw:
            chain = [m.strip() for m in raw.split(",") if m.strip()]
            if chain:
                return chain
        # Default chain: tested working free models
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
        """Cloud LLM inference with model fallback chain and smart rate-limit handling.

        Key improvements over simple retry:
        1. Model fallback chain — tries next model on 429 instead of blind retry
        2. Serialized request queue — one API call at a time across all threads
        3. Smart 429 handling — reads Retry-After header, respects cooldown
        4. Cooldown escalation — after N consecutive 429s, pauses all requests
        5. Remembers last working model — tries it first next time
        """
        import json
        import time
        import urllib.request
        import urllib.error

        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        fallback_url = (
            (os.environ.get("CLOUD_FALLBACK_URL") or "").strip()
            or _DEFAULT_OPENROUTER_URL
        )
        if not api_key:
            raise LLMNotReadyError(
                "No OPENROUTER_API_KEY configured for cloud fallback"
            )

        model_chain = self._get_model_chain()
        # Prioritize the last model that worked
        if self._cloud_last_working_model and self._cloud_last_working_model in model_chain:
            model_chain.remove(self._cloud_last_working_model)
            model_chain.insert(0, self._cloud_last_working_model)

        # --- Cooldown gate: if we've been hammering, wait ---
        now = time.time()
        if now < MLXInferenceAdapter._cloud_cooldown_until:
            remaining = MLXInferenceAdapter._cloud_cooldown_until - now
            logger.info(
                f"[CLOUD] In cooldown for {remaining:.0f}s — returning FLAT"
            )
            return json.dumps({
                "direction": "FLAT",
                "rationale": f"Cloud LLM in cooldown ({remaining:.0f}s remaining) — rate limited",
                "confidence": "Low",
            })

        # --- Serialized request: only one API call at a time ---
        with MLXInferenceAdapter._cloud_lock:
            # Enforce minimum interval between requests (2s for free tier)
            min_interval = 2.0
            elapsed = time.time() - MLXInferenceAdapter._last_cloud_request_time
            if elapsed < min_interval:
                wait = min_interval - elapsed
                logger.debug("[CLOUD] Throttling: waiting %.1fs", wait)
                time.sleep(wait)
            MLXInferenceAdapter._last_cloud_request_time = time.time()

            temp = temperature if temperature is not None else self._temperature
            max_t = max_tokens if max_tokens is not None else self._max_new_tokens
            
            # Note: Most OpenRouter models support 'system', but we use a list
            # of messages that can be adjusted if needed.
            messages = [
                {"role": "system", "content": instruction},
                {"role": "user", "content": input_text},
            ]

            # --- Try each model in the chain ---
            last_error = None
            for model_id in model_chain:
                logger.info(
                    f"[CLOUD] Trying model={model_id} "
                    f"(chain_idx={model_chain.index(model_id)+1}/{len(model_chain)})"
                )

                payload = json.dumps({
                    "model": model_id,
                    "messages": messages,
                    "temperature": temp,
                    "max_tokens": max_t,
                }).encode()

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

                        # Success! Reset 429 counter and remember working model
                        MLXInferenceAdapter._cloud_consecutive_429s = 0
                        MLXInferenceAdapter._cloud_last_working_model = model_id
                        logger.info("[CLOUD] Success with %s (%d chars)", model_id, len(content))
                        return str(content)

                except urllib.error.HTTPError as e:
                    last_error = e
                    if e.code == 429:
                        MLXInferenceAdapter._cloud_consecutive_429s += 1

                        # Read Retry-After header if available
                        retry_after = e.headers.get("Retry-After")
                        if retry_after:
                            try:
                                delay = float(retry_after)
                            except ValueError:
                                delay = 10.0
                        else:
                            delay = 5.0

                        consecutive = MLXInferenceAdapter._cloud_consecutive_429s
                        logger.warning(
                            f"[CLOUD] 429 from {model_id} "
                            f"(consecutive={consecutive}, retry_after={delay:.0f}s) "
                            f"— trying next model"
                        )

                        # If we've hit 429 many times in a row, enter cooldown
                        if consecutive >= len(model_chain) * 2:
                            cooldown = min(delay * 3, 120)
                            MLXInferenceAdapter._cloud_cooldown_until = (
                                time.time() + cooldown
                            )
                            logger.warning(
                                f"[CLOUD] Entering cooldown for {cooldown:.0f}s "
                                f"(too many 429s)"
                            )
                            break  # Stop trying models, go to cooldown

                        # Small delay before trying next model (don't slam)
                        time.sleep(min(delay, 3.0))
                        continue  # Try next model in chain

                    else:
                        logger.error(
                            f"[CLOUD] HTTP {e.code} from {model_id}: {e.reason}"
                        )
                        continue  # Try next model

                except urllib.error.URLError as e:
                    logger.error("[CLOUD] Network error with %s: %s", model_id, e)
                    last_error = e
                    continue
                except Exception as e:
                    logger.error("[CLOUD] Unexpected error with %s: %s", model_id, e)
                    last_error = e
                    continue

        # All models failed
        msg = (
            f"Cloud LLM failed — all {len(model_chain)} models exhausted. "
            f"Last error: {last_error}"
        )
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
        # When cloud fallback is explicitly enabled, always use cloud inference
        if _cloud_fallback_enabled():
            return self._predict_cloud(
                instruction, input_text, temperature, max_tokens
            )
        
        # Lazy loading: Load model on first inference request if deferred
        if not self.model and not self._is_loading:
            defer_loading = os.environ.get("MLX_DEFER_LOADING", "0").lower() in ("1", "true", "yes")
            if defer_loading:
                logger.info("MLX_DEFER_LOADING: Loading model on first inference request...")
                self._is_loading = True
                try:
                    self._load_model()
                    logger.info("✅ MLX model loaded successfully on first request!")
                except Exception as e:
                    logger.error("Failed to load MLX model on first request: %s", e)
                    self._load_error = str(e)
                    self._is_loading = False
                    # Fallback to cloud if available
                    model_path = self._effective_model_path()
                    if _cloud_fallback_enabled() and not model_path:
                        return self._predict_cloud(
                            instruction, input_text, temperature, max_tokens
                        )
                    raise LLMNotReadyError(f"Model failed to load: {e}")
        
        if not self.model:
            if self._is_loading:
                raise LLMNotReadyError("Model is still loading")
            model_path = self._effective_model_path()
            if _cloud_fallback_enabled() and not model_path:
                return self._predict_cloud(
                    instruction, input_text, temperature, max_tokens
                )
            detail = getattr(self, '_load_error', None) or "failed to load"
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

        # Gemma and some other models do not support the 'system' role in their
        # default chat templates. We use a try-except block to fall back to
        # merging the system message into the user message if needed.
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
                logger.info("MLX: System role not supported by template, merging into user message.")
                messages = [
                    {"role": "user", "content": f"{sys_msg}\n\n{clean_input}"},
                ]
                prompt = self.processor.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True
                )
            else:
                raise

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
        from mlx_lm.sample_utils import make_sampler

        t0 = _time.time()
        with MLX_GPU_LOCK:
            logger.info("[%s] Starting generation (max_tokens=%d, temp=%s)...", target, max_t, self._temperature)
            # Pass sampling parameters for proper temperature control
            # Trading decisions need low temperature (0.3) for deterministic output
            # mlx_lm v0.31+ requires sampler object instead of direct temperature/top_p params
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
        """True when the LLM is ready for inference (local MLX or cloud)."""
        if _cloud_fallback_enabled():
            # Cloud mode is ready as long as we have an API key
            api_key = os.environ.get("OPENROUTER_API_KEY", "")
            return bool(api_key.strip())
        
        # If deferred loading is enabled, report ready so predict() can trigger lazy load
        defer_loading = os.environ.get("MLX_DEFER_LOADING", "0").lower() in ("1", "true", "yes")
        if defer_loading:
            # Ready if not currently loading and no error
            return self._is_loading is False and getattr(self, '_load_error', None) is None

        if self._is_loading:
            return False
        if getattr(self, '_load_error', None) is not None:
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
            logger.error("MLX model validation failed: %s", e)
            return False
