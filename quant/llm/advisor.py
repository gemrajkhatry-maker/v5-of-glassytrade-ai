"""LLMAdvisor — market reasoning and thesis advisor.

- No model_path: rule-based AMT narrative emitted synchronously (~0ms) so the
  WS snapshot never races ahead of the thesis.
- With MLX model_path: single-slot async queue (drops stale bars).
- Graceful degradation: MLX failure falls back to rule-based narrative.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

from quant.decision.context import DecisionContext
from quant.events import AgentDecisionProduced
from quant.llm.bridge import context_to_prompt, extract_llm_json
from quant.llm.narrative import (
    AdvisoryBackend as AdvisoryBackend,
    RuleBasedAdvisoryBackend as RuleBasedAdvisoryBackend,
    build_rule_based_narrative,
)

logger = logging.getLogger(__name__)


_MODEL_CACHE: Dict[Tuple[str, Optional[str]], Tuple[Any, Any]] = {}
_MODEL_CACHE_LOCK = threading.Lock()


_INFERENCE_LOCK = threading.Lock()


class LLMAdvisor:
    """Asynchronously generates AMT market reasoning without delaying live ticks."""

    def __init__(
        self,
        emit_fn: Optional[Callable[[Any], None]] = None,
        model_path: Optional[str] = None,
        adapter_path: Optional[str] = None,
        backend: Optional[AdvisoryBackend] = None,
    ) -> None:
        self._emit_fn = emit_fn
        self._model_path = model_path
        self._adapter_path = adapter_path
        # Explicit advisory seam (WS7): when a backend is injected it fully
        # owns the synchronous emission payload; default stays the built-in
        # rule-based narrative below.
        self._backend = backend
        self._model = None
        self._tokenizer = None
        self._model_loaded = False

        # Single-slot queue so slow inference drops stale bars instead of queueing up
        self._queue: queue.Queue[DecisionContext] = queue.Queue(maxsize=2)
        self._running = True
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True, name="LLMAdvisorWorker")
        self._worker_thread.start()

    def set_emit_fn(self, emit_fn: Callable[[Any], None]) -> None:
        self._emit_fn = emit_fn

    def on_context(self, ctx: DecisionContext) -> None:
        """Enqueue the latest DecisionContext for MLX analysis, emitting
        instant baseline narrative immediately so the UI is never blank.
        MLX inference runs asynchronously in the worker thread.
        """
        # 1. Instant baseline emission (0ms)
        decision = self._backend.analyze(ctx) if self._backend is not None else self._rule_based_narrative(ctx)
        self._emit_decision(ctx, decision)

        # 2. If MLX model is configured, queue for deep model reasoning
        if not self._model_path:
            return
        try:
            if self._queue.full():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
            self._queue.put_nowait(ctx)
        except Exception:
            pass

    def _emit_decision(self, ctx: DecisionContext, decision: Dict[str, Any] | None) -> None:
        if not self._emit_fn or not decision:
            return
        event_time = ctx.time_str or (ctx.bar.time if ctx.bar else "")
        self._emit_fn(AgentDecisionProduced(symbol=ctx.symbol, time=event_time, decision=decision))

    def _ensure_model(self) -> bool:
        if not self._model_path:
            return False
        if self._model_loaded and self._model is not None:
            return True

        with _MODEL_CACHE_LOCK:
            m_path = self._model_path
            a_path = self._adapter_path
            key = (m_path, a_path)
            if key in _MODEL_CACHE:
                self._model, self._tokenizer = _MODEL_CACHE[key]
                self._model_loaded = True
                return True
            try:
                from mlx_lm import load
                import os

                real_a_path = a_path if (a_path and os.path.exists(a_path)) else None
                logger.info("LLMAdvisor: loading MLX model %s (adapter: %s)...", m_path, real_a_path)
                model, tokenizer = load(m_path, adapter_path=real_a_path)
                _MODEL_CACHE[key] = (model, tokenizer)
                self._model = model
                self._tokenizer = tokenizer
                self._model_loaded = True
                logger.info("LLMAdvisor: model successfully loaded and cached in unified memory.")
                return True
            except Exception as e:
                logger.warning("LLMAdvisor: MLX load failed (%s) — using rule-based narrative fallback.", e)
                return False

    def _worker_loop(self) -> None:
        while self._running:
            try:
                ctx = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            try:
                self._emit_decision(ctx, self._analyze(ctx))
            except Exception as e:
                logger.debug("LLMAdvisor inference error: %s", e)
            finally:
                self._queue.task_done()

    def _analyze(self, ctx: DecisionContext) -> Dict[str, Any]:
        """Perform analysis via MLX model or deterministic reasoning fallback."""
        sys_prompt, user_prompt = context_to_prompt(ctx)

        if self._ensure_model() and self._model is not None and self._tokenizer is not None:
            try:
                from mlx_lm import generate
                from mlx_lm.sample_utils import make_sampler

                msgs = [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}]
                prompt = self._tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
                prime = '{\n  "rationale": "'

                t0 = time.perf_counter()
                with _INFERENCE_LOCK:
                    out = generate(
                        self._model,
                        self._tokenizer,
                        prompt=prompt + prime,
                        max_tokens=140,
                        sampler=make_sampler(temp=0.2),
                    )
                latency_ms = (time.perf_counter() - t0) * 1000.0
                parsed = extract_llm_json(out, prime=prime)
                if parsed and ("action" in parsed or "direction" in parsed):
                    parsed["latencyMs"] = round(latency_ms, 1)
                    parsed["source"] = "MLX_LOCAL"
                    parsed["symbol"] = ctx.symbol
                    return parsed
            except Exception as e:
                logger.debug("MLX generation error: %s", e)

        return self._rule_based_narrative(ctx)

    def _rule_based_narrative(self, ctx: DecisionContext) -> Dict[str, Any]:
        """Delegating shim: structured AMT narrative from raw ctx fields only.

        The rule table lives in quant/llm/narrative.py (WS7-lite extraction);
        this method remains so existing callers are unchanged. Reads ONLY raw
        inputs (price, POC/VAH/VAL, CVD slope, market state, session phase,
        absorption side, Triple-A phase, break type, drive number, VWAP bands,
        contested_bubble_zone) — ZERO coupling to gate functions.
        """
        return build_rule_based_narrative(ctx)

    def shutdown(self) -> None:
        self._running = False


class MLXAdvisoryBackend:
    """AdvisoryBackend adapter around LLMAdvisor's MLX inference path.

    Model loading (_ensure_model) and generation (_analyze) stay owned by
    LLMAdvisor; this adapter exposes the same explicit AdvisoryBackend seam
    as the deterministic RuleBasedAdvisoryBackend so hosts can swap advisory
    sources without touching engine code. On MLX failure _analyze degrades to
    the shared rule-based narrative, keeping both backends interchangeable.
    """

    def __init__(self, advisor: LLMAdvisor) -> None:
        self._advisor = advisor

    def analyze(self, ctx: DecisionContext) -> Dict[str, Any]:
        return self._advisor._analyze(ctx)
