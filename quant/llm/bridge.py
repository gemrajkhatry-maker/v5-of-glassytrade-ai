"""LLM Decision & Narrative Bridge — connects QuantEngine DecisionContext to MLX/LLM models.

Provides:
- Schema-faithful prompt formatting from live DecisionContext (NSE & MCX).
- Robust JSON extraction with two-stage rationale priming.
- Performance and accuracy evaluator (precision, recall, F1, confusion matrix, latency).
- Gate parity validator comparing LLM outputs against deterministic QuantEngine gates.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from quant.decision.context import DecisionContext
from quant.decision.pipeline import GatePipeline
from quant.decision.result import GateResult


SYSTEM_PROMPT = (
    "You are an elite Auction Market Theory (AMT) quant trading brain for Indian markets (NSE & MCX). "
    "Think strictly like Fabio Valentini: evaluate session phase, value area location (VAH/VAL/POC), "
    "order-flow aggression (CVD slope, OFI, tick aggression sigma), volume absorption, and structural R:R. "
    "When evaluating ENTRY (position_open=False), output action: ENTER_LONG, ENTER_SHORT, or FLAT. "
    "When managing an ACTIVE POSITION (position_open=True), output action: HOLD, TIGHTEN_SL, TAKE_PROFIT, or EXIT. "
    "Output ONLY valid JSON with keys: action, direction (LONG, SHORT, FLAT), setup (TRIPLE_A, VA_FADE, BREAKOUT, MANAGE_POSITION, NO_EDGE), "
    "confidence (High, Medium, Low), and rationale (concise 1-sentence market reasoning)."
)


def context_to_prompt(ctx: DecisionContext) -> Tuple[str, str]:
    """Convert a DecisionContext into system and user messages."""
    close_px = ctx.bar.close if ctx.bar is not None else 0.0
    vol = ctx.bar.volume if ctx.bar is not None else 0.0
    delta = ctx.bar.delta if ctx.bar is not None else 0.0

    user_payload: Dict[str, Any] = {
        "symbol": ctx.symbol,
        "time": ctx.time_str or (ctx.bar.time if ctx.bar else ""),
        "task": "MANAGE_POSITION" if ctx.position_open else "EVALUATE_ENTRY",
        "session_phase": ctx.session_phase or "PRIMARY",
        "market_state": str(ctx.market_state.value if hasattr(ctx.market_state, "value") else ctx.market_state),
        "price": round(close_px, 2),
        "volume": round(vol, 1),
        "bar_delta": round(delta, 1),
        "poc": round(ctx.poc, 2) if ctx.poc > 0 else None,
        "vah": round(ctx.vah, 2) if ctx.vah > 0 else None,
        "val": round(ctx.val, 2) if ctx.val > 0 else None,
        "cvd_slope": round(ctx.cvd_slope, 2),
        "absorption_side": ctx.absorption_side or "NONE",
        "profile_shape": ctx.profile_shape or "D",
        "spread": round(ctx.ask - ctx.bid, 2) if (ctx.ask > 0 and ctx.bid > 0) else 0.0,
        "option_delta": round(ctx.option_delta, 2) if ctx.option_delta is not None else None,
        "is_expiry": ctx.is_expiry,
        "stacked_imbalance": ctx.stacked_imbalance_direction or "NONE",
        "position_open": ctx.position_open,
        "risk_halted": ctx.risk_halted,
    }

    if ctx.position_open:
        user_payload["active_position"] = {
            "side": ctx.position_side,
            "entry_price": round(ctx.position_entry_price, 2),
            "current_price": round(close_px, 2),
            "size": round(ctx.position_size, 2),
            "unrealized_pnl": round(ctx.position_unrealized_pnl, 2),
            "stop_loss": round(ctx.position_sl, 2) if ctx.position_sl > 0 else None,
            "take_profit": round(ctx.position_tp, 2) if ctx.position_tp > 0 else None,
            "bars_held": ctx.position_bars_held,
        }

    if ctx.recent_decisions:
        user_payload["recent_decisions"] = list(ctx.recent_decisions)

    user_text = f"Market Auction Snapshot:\n{json.dumps(user_payload, indent=2)}"
    return SYSTEM_PROMPT, user_text


def extract_llm_json(raw_text: str, prime: str = '{\n  "rationale": "') -> Dict[str, Any]:
    """Extract and repair JSON from raw LLM completion output."""
    full_text = raw_text
    if not full_text.strip().startswith("{") and prime:
        full_text = prime + full_text

    # 1. Direct JSON parse
    try:
        start = full_text.find("{")
        end = full_text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(full_text[start : end + 1])
    except Exception:  # silent-except - JSON parse is best-effort; caller falls back to regex extraction
        pass

    # 2. Balanced bracket walk + repair
    start = full_text.find("{")
    if start >= 0:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(full_text)):
            c = full_text[i]
            if esc:
                esc = False
                continue
            if c == "\\" and in_str:
                esc = True
                continue
            if c == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    chunk = full_text[start : i + 1]
                    try:
                        return json.loads(chunk)
                    except json.JSONDecodeError:
                        cleaned = re.sub(r",\s*}", "}", chunk)
                        try:
                            return json.loads(cleaned)
                        except Exception:
                            break

    # 3. Regex key extraction fallback
    fallback = {}
    act_m = re.search(r'"action"\s*:\s*"([^"]+)"', full_text)
    if act_m:
        fallback["action"] = act_m.group(1).upper()

    dir_m = re.search(r'"direction"\s*:\s*"([^"]+)"', full_text)
    if dir_m:
        fallback["direction"] = dir_m.group(1).upper()
    elif "action" in fallback:
        if "LONG" in fallback["action"]:
            fallback["direction"] = "LONG"
        elif "SHORT" in fallback["action"]:
            fallback["direction"] = "SHORT"
        else:
            fallback["direction"] = "FLAT"

    rat_m = re.search(r'"rationale"\s*:\s*"([^"]+)"', full_text)
    if rat_m:
        fallback["rationale"] = rat_m.group(1)

    return fallback


@dataclass
class EvalMetrics:
    total: int
    correct: int
    accuracy_pct: float
    by_class: Dict[str, Dict[str, float]]
    json_parse_rate_pct: float
    avg_latency_ms: float


class LLMEvaluator:
    """Evaluates MLX model predictions on ground-truth AMT datasets."""

    def __init__(self, model_loader=None, generate_fn=None):
        self._model = None
        self._tokenizer = None
        self._model_loader = model_loader
        self._generate_fn = generate_fn

    def load_model(self, model_path: str, adapter_path: Optional[str] = None) -> None:
        if self._model_loader is not None:
            self._model, self._tokenizer = self._model_loader(model_path, adapter_path=adapter_path)
        else:
            from mlx_lm import load
            self._model, self._tokenizer = load(model_path, adapter_path=adapter_path)

    def evaluate_dataset(
        self,
        dataset: List[Dict[str, Any]],
        max_tokens: int = 160,
        temp: float = 0.3,
        prime: str = '{\n  "rationale": "',
    ) -> EvalMetrics:
        """Run evaluation across a dataset of prompt records."""
        from mlx_lm import generate
        from mlx_lm.sample_utils import make_sampler

        total = 0
        correct = 0
        parsed_ok = 0
        total_time_ms = 0.0
        by_class = {
            "LONG": {"tp": 0, "fp": 0, "fn": 0, "total": 0},
            "SHORT": {"tp": 0, "fp": 0, "fn": 0, "total": 0},
            "FLAT": {"tp": 0, "fp": 0, "fn": 0, "total": 0},
        }

        sampler = make_sampler(temp=temp)

        for item in dataset:
            msgs = item.get("messages", [])
            if len(msgs) < 3:
                continue

            expected_raw = json.loads(msgs[2]["content"]) if isinstance(msgs[2]["content"], str) else msgs[2]["content"]
            expected_dir = expected_raw.get("direction") or (
                "LONG" if "LONG" in expected_raw.get("action", "") else
                "SHORT" if "SHORT" in expected_raw.get("action", "") else "FLAT"
            )

            prompt_msgs = [{"role": "system", "content": msgs[0]["content"]}, {"role": "user", "content": msgs[1]["content"]}]
            prompt = self._tokenizer.apply_chat_template(prompt_msgs, tokenize=False, add_generation_prompt=True)

            t0 = time.perf_counter()
            out = generate(self._model, self._tokenizer, prompt=prompt + prime, max_tokens=max_tokens, sampler=sampler)
            t_elapsed = (time.perf_counter() - t0) * 1000.0
            total_time_ms += t_elapsed

            parsed = extract_llm_json(out, prime=prime)
            if parsed:
                parsed_ok += 1

            pred_dir = parsed.get("direction") or (
                "LONG" if "LONG" in parsed.get("action", "") else
                "SHORT" if "SHORT" in parsed.get("action", "") else "FLAT"
            )

            total += 1
            if expected_dir in by_class:
                by_class[expected_dir]["total"] += 1

            if pred_dir == expected_dir:
                correct += 1
                if pred_dir in by_class:
                    by_class[pred_dir]["tp"] += 1
            else:
                if pred_dir in by_class:
                    by_class[pred_dir]["fp"] += 1
                if expected_dir in by_class:
                    by_class[expected_dir]["fn"] += 1

        accuracy = (correct / total * 100.0) if total > 0 else 0.0
        json_rate = (parsed_ok / total * 100.0) if total > 0 else 0.0
        avg_lat = (total_time_ms / total) if total > 0 else 0.0

        class_stats = {}
        for k, v in by_class.items():
            tp, fp, fn, tot = v["tp"], v["fp"], v["fn"], v["total"]
            precision = (tp / (tp + fp)) if (tp + fp) > 0 else 0.0
            recall = (tp / (tp + fn)) if (tp + fn) > 0 else 0.0
            f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
            class_stats[k] = {
                "total": tot,
                "precision_pct": round(precision * 100.0, 1),
                "recall_pct": round(recall * 100.0, 1),
                "f1_score": round(f1, 3),
            }

        return EvalMetrics(
            total=total,
            correct=correct,
            accuracy_pct=round(accuracy, 2),
            by_class=class_stats,
            json_parse_rate_pct=round(json_rate, 2),
            avg_latency_ms=round(avg_lat, 2),
        )
