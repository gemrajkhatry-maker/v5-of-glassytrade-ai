# Exit Flow Authority — Audit Findings

Repo: `/Users/apple/Documents/v5-of-glassytrade-ai`
Branch: `feat/timesfm-paper-e2e-validation`
Method: read-only static audit (grep/sed/cat). No files modified, no pytest run.

---

## CRITICAL

### C1. Entire model exit authority is silently swallowed
**Severity:** CRITICAL
**file:line:** `quant/execution/exits.py:195-197`
```python
except Exception as exc:
    # Graceful fallback to deterministic exit rules on error
    pass
```
**Why it matters:** the whole `TimesFMRiskAuthority.evaluate_exit` block (`exits.py:162-194`) sits inside this `try`. A bug anywhere in the authority (dynamic VaR stop, trajectory-inflection take-profit, velocity-decay exit, monotonic quantile ratchet) silently disables every model-driven exit and stop-tightening for that bar. No log, `exc` unused. The position keeps running on the weaker deterministic stops with no signal to ops.
**Verdict:** real bug. A failing exit authority must at minimum log at warning/error.

### C2. Full close bypasses `_execute_full_close` and stamps no `exit_source`
**Severity:** CRITICAL
**file:line:** `quant/runtime.py:1402-1411`
```python
for pyr_pos in list(pm.pyramid_positions):
    pyr_fill = pm._oms.close(pyr_pos, price, ts, reason + "_PYRAMID")
    pm._exits.pop_trail(pyr_pos)
    pm._risk.record_trade(pyr_fill.pnl, count_as_trade=False)
    self._emit(PositionClosed(symbol=self.symbol, time=ts, fill=pyr_fill))
    risk_i = pm._pyramid_open_risk.pop(pyr_pos._id, 0.0)
    if pm._portfolio_risk is not None:
        pm._portfolio_risk.record_close(risk_i, float(pyr_fill.pnl))
pm.pyramid_positions = []
pm.pyramid_count = 0
```
**Why it matters:** direct OMS close bypasses `_execute_full_close` (`position_manager.py:239`), so there is no central `last_exit_source` stamp (`:267-269`), no `[POSITION CLOSED] ... exit_source=` log line (`:312-321`), no `_closed_ids` double-close guard, and no id validation. It violates the documented invariant "the ONLY full-close release path" (`runtime.py:1321`). Reachable via `multi_engine.eod_square_off` (`multi_engine.py:1049`) and `multi_engine.emergency_halt` (`:995`) when the base is gone but pyramid add-ons linger.
**Verdict:** real bug (observability + guard gap).

---

## HIGH

### H1. Bar path and tick path disagree on the stop price for the same breach
**Severity:** HIGH
**file:line:** `quant/execution/exit_checks.py:26-32` (bar) vs `quant/position_manager.py:334-338` (tick)
```python
# bar path — raw frozen SL
def check_stop_loss(position: Position, low: float, high: float) -> ExitDecision | None:
    sl = float(position.order.signal.sl)
    long = position.size > 0
    if (long and low <= sl) or (not long and high >= sl):
        return ExitDecision(True, "SL", sl)
```
```python
# tick path — tighter merged stop
effective_sl = sig_sl
if trail_stop is not None:
    effective_sl = max(effective_sl, float(trail_stop)) if is_long else min(effective_sl, float(trail_stop))
elif be_floor is not None:
    effective_sl = max(effective_sl, float(be_floor)) if is_long else min(effective_sl, float(be_floor))
```
**Why it matters:** Rule 2 runs before Rule 4b (`exits.py:200` vs `:227`), so a bar that pierces both the raw SL and the trail stop is booked `SL` at the worse price, while the identical tick breach books `TRAIL` at the trail. Same economic event, two exit prices and two `exit_source` values depending on which feed arrives first.
**Verdict:** real bug (inconsistent stop authority).

### H2. `TimesFMPositionAgent` is advisory only — it cannot move a real stop or close a position
**Severity:** HIGH
**file:line:** `quant/decision/timesfm_agents.py:445-452`, `:469`, `:477`, `:488`, `:512`, `:552`, `:564`, `:605`, `:611`; `quant/decision/timesfm_engine.py:400-403`; `quant/runtime.py:1565-1587`; `quant/multi_engine.py:817-868`; `quant/strategies/timesfm_strategy.py:144`
```python
# timesfm_agents.py:445-452 — computes a stop, but only into the payload
if side == "LONG":
    dyn_candidate = float(forecast.p10_path[0])
    dyn_stop = max(sl, dyn_candidate) if sl > 0 else dyn_candidate
```
```python
# timesfm_engine.py:400-403 — only invoked to build the UI decision
if ctx.position_open:
    result = self.position_agent.evaluate(ctx, forecast)
```
```python
# runtime.py:1586-1587 — stored as display state only
elif isinstance(event, AgentDecisionProduced):
    self._latest_agent_decision = event.decision
```
```python
# timesfm_agents.py:611 — the only dispatch on the action is display-only
"timing": "EXIT_NOW" if action == "EXIT" else ("REDUCE_NOW" if action == "SCALE_OUT" else "HOLD"),
```
```python
# timesfm_strategy.py:144 — entry strategy never calls the position agent
scan_res = self.scanning_agent.evaluate(ctx, forecast)
```
**Why it matters:** no code path reads `EXIT`/`TIGHTEN_SL`/`TAKE_PROFIT` to call `oms.close`, emit `StopMoved`, or tighten `signal.sl`. `multi_engine.py:817-868` only copies/patches `activePosition`/`dynamicTrailStop`/`role` for the WS snapshot. The real model exit authority is the separate `TimesFMRiskAuthority`, invoked from inside `ExitEngine.evaluate` (`exits.py:172-194`).
**Verdict:** intentional design (advisory/UI), but the payload does not mark `dynamicTrailStop` as advisory (see L4).

---

## MEDIUM

### M1. Duplicate/competing stop-tightening: ExitEngine trail and TimesFMRiskAuthority trail stack
**Severity:** MEDIUM
**file:line:** `quant/execution/exits.py:183-188` and `quant/execution/exit_checks.py:148-151`
```python
# exits.py:183-188 — TimesFM quantile ratchet writes _trail
if eval_res.new_stop is not None:
    if tr is None:
        tr = _Trail()
        self._trail[position._id] = tr
    tr.active = True
    tr.stop = eval_res.new_stop
```
```python
# exit_checks.py:148-151 — deterministic giveback then ratchets the same record
if trail_stop is None:
    trail_stop = candidate
else:
    trail_stop = max(trail_stop, candidate) if long else min(trail_stop, candidate)
```
**Why it matters:** two parallel stores (`ExitEngine._trail`, `TimesFMRiskAuthority._trail_stops`) are maintained for one position and never reconciled; the deterministic value is never fed back into the authority. Safe today only because both re-cap with `active_sl`/`current_sl` (`timesfm_risk.py:79-89`), so neither can loosen. The authority docstring claims it "replaces rigid 0.8R breakeven threshold and 20% giveback" (`timesfm_risk.py:3-4`) but the code stacks both.
**Verdict:** real but latent; a future change to either ratchet can produce a first-writer-wins stop for the same bar.

### M2. `_closed_ids` double-close guard is reset on every call
**Severity:** MEDIUM
**file:line:** `quant/position_manager.py:144-145` (claim at `:242`, consume at `:255-260`)
```python
# Double-close guard: position _ids that have already been fully closed.
self._closed_ids: set[str] = set()
```
**Why it matters:** rebuilt at the top of `manage_exit`, so it cannot block a cross-call re-close, contradicting "Double-close is prevented by the _closed_ids guard" (`:242`). The repo's own chaos test documents the defect: `tests/quant/chaos/test_crash_recovery.py:556-621` (`test_manage_exit_resets_closed_ids` asserts the set is empty after a call and that the same position closes twice). It is also not consulted before the C2 pyramid-only loop.
**Verdict:** real bug.

### M3. Base closes, then a pyramid close raises: state/OMS divergence
**Severity:** MEDIUM
**file:line:** `quant/position_manager.py:271-305`, `quant/runtime.py:1461-1470`
```python
fill = self._oms.close(position, exit_dec.close_price, time_str, exit_dec.reason)
self.last_fill = fill
...
for pyr_pos in self.pyramid_positions:
    pyr_fill = self._oms.close(pyr_pos, exit_dec.close_price, time_str, exit_dec.reason + "_PYRAMID")
    ...
self._closed_ids.add(pos_id)  # Mark as closed
```
**Why it matters:** the base is flat at the broker, then the pyramid close at `:279` can raise before `_closed_ids.add(pos_id)` (`:305`). `runtime._manage_exit:1461-1470` swallows and returns, leaving `pm.current_position` set and `_book_full_close` uncalled; the next bar re-evaluates an already-closed position and re-issues a close. PaperOMS-only today (LiveOMS pyramids raise, `live_oms.py:374-382`).
**Verdict:** real inconsistency on the documented single close path.

### M4. Tiered partial TPs implemented twice (bar vs tick) with divergent internals
**Severity:** MEDIUM
**file:line:** `quant/execution/exit_checks.py:68-88` + `quant/position_manager.py:204-208` (bar) vs `quant/position_manager.py:411-444` and `:446-474` (tick)
```python
# bar path — shared rule
if tp_tier == 0:
    if (long and high >= tp) or (not long and low <= tp):
        return ExitDecision(True, "TP1", tp, partial_fraction=0.5), 1
elif tp_tier == 1:
    tp2 = tp2_level(entry, tp)
```
```python
# consumed by manage_exit
if exit_dec.partial_fraction is not None and exit_dec.partial_fraction < 1.0:
    partial_fill, remaining = self._oms.close_partial(
        position, exit_dec.partial_fraction, exit_dec.close_price, bar.time, exit_dec.reason,
    )
```
```python
# tick path — re-implemented inline, writes ExitEngine privates directly
self._exits._tp_tier[position._id] = 1
self._exits._breakeven[position._id] = entry   # same effect as exits.py:160-161
```
**Why it matters:** two code paths must be hand-synced (comments admit "strict bar parity"); any ladder change in one and not the other silently diverges. Duplicated, not currently dead.
**Verdict:** real duplication risk.

---

## LOW

### L1. Dead code — `runtime._check_pyramid` has no production caller
**Severity:** LOW
**file:line:** `quant/runtime.py:1525-1531`
```python
def _check_pyramid(self, amt_dto: dict, bar) -> None:
    pm = self._get_position_manager()
    pm.check_pyramid(amt_dto, bar, pm.current_position, self._bar_index)
```
**Why it matters:** pyramid is driven from `manage_exit:232-233`, with the ratcheted base consumed at `:235`. Only tests reference this method (`tests/quant/runtime/test_exit_golden.py`).
**Verdict:** dead code.

### L2. Docstring/behavior drift in partial sizing
**Severity:** LOW
**file:line:** `quant/execution/exits.py:22-24`; `quant/execution/oms.py` close_partial docstring vs `exit_checks.py:87`, `position_manager.py:422`, `:455`
```python
# Fraction of the CURRENT position size to close. None (or 1.0) means a
# full close. < 1.0 means a tiered take-profit partial (spec §13.3).
partial_fraction: float | None = None
```
**Why it matters:** no rule ever returns `1.0`; the `close_partial` docstring says "TP2 = 25% ... Runner = remaining 25%" while both call paths pass `0.5`.
**Verdict:** misleading docs, no runtime effect.

### L3. Redundant exception tuple
**Severity:** LOW
**file:line:** `quant/position_manager.py:567`
```python
except (ValueError, NotImplementedError, Exception) as exc:
```
**Why it matters:** `Exception` already subsumes the others; harmless but misleading.
**Verdict:** cosmetic.

### L4. Advisory `dynamicTrailStop` could be mistaken for the live stop
**Severity:** LOW
**file:line:** `quant/decision/timesfm_agents.py:605`; surfaced via `quant/multi_engine.py:851`, `quant/decision/timesfm_advisor.py:116`
```python
"dynamicTrailStop": round(dyn_stop, 2) if dyn_stop is not None else None,
```
**Why it matters:** it appears in the WS payload but is never applied to any order or stop. Purely cosmetic unless an operator reconciles it against the real ExitEngine trail.
**Verdict:** intentional, but unmarked as advisory.

### L5. Swallowed exceptions on exit-adjacent paths (cannot skip an exit, but mask errors)
**Severity:** LOW
**file:line:** `quant/runtime.py:566, 572, 588, 997, 1161, 1348, 1518`
```python
            except Exception:
                pass
```
**Why it matters:** `:1518` sits in `_manage_exit`'s advisor-notify block and hides advisor failures on every positioned bar; `:1348` does the same inside `_book_full_close`. Non-exit paths, so LOW.
**Verdict:** real (error masking), not exit-skipping.

---

## Q1 — Every path that can close a position

Full closes (all route through `PositionManager._execute_full_close` except C2):
1. Bar: `manage_exit` → `ExitEngine.evaluate` → `_execute_full_close` (`position_manager.py:183-229`). Reasons: `DEAD_MARKET`, `SPREAD_BLOWOUT`, TimesFM `VAR_STOP`/`TRAJECTORY_INFLECTION`/`VELOCITY_DECAY`, `SL`, `CVD_KILL`, terminal `TP`, `BREAKEVEN`, `TRAIL`, `VWAP_DRIFT`, `TIME`, and `SESSION_CLOSE` injected at `:149-152`.
2. Tick: `manage_tick_exit` → `_execute_full_close` (`position_manager.py:325-409`, returns at `:366`, `:392`, `:408`, `:444`). Reasons `SL`/`TRAIL`/`BREAKEVEN`, terminal `TP`, degenerate-size `TP`.
3. Thesis flip: `runtime._check_thesis_flip` → `pm._execute_full_close(OPPOSING_SIGNAL)` (`runtime.py:1310-1315`).
4. EOD/emergency: `runtime.force_close_position` → `pm._execute_full_close` (`runtime.py:1398`), plus the C2 direct-OMS pyramid branch (`:1402-1411`). Callers `multi_engine.eod_square_off` (`multi_engine.py:1049`), `multi_engine.emergency_halt` (`:995`).

Partial closes (not full closes; no `exit_source` expected):
5. `manage_exit` partial branch (`position_manager.py:204-227`).
6. `_tick_tp_touch` (`position_manager.py:421`).
7. `_book_tick_tp2_partial` (`position_manager.py:454`).

`exit_source` stamped at 8 sites in `exits.py` (`:145,158,193,202,208,218,241,250`), re-stamped centrally at `position_manager.py:267-269`, printed only at `:312-321`.

## Q2 — Advisory or real?
Advisory. See H2. No path acts on the agent's `EXIT`/`TIGHTEN_SL`/`TAKE_PROFIT`.

## Q3 — Stop-tightening conflicts
Yes: (a) bar-vs-tick stop-price divergence (H1); (b) stacked ExitEngine trail vs TimesFMRiskAuthority trail with no reconciliation (M1). They agree today only because both re-cap against `active_sl`/`current_sl` (`timesfm_risk.py:79-89`); a future change to either ratchet can produce a first-writer-wins stop for the same bar.

## Q4 — Tiered TPs in more than one place / dead branches
Two implementations: `check_take_profit_tiers` (bar) and `_tick_tp_touch`/`_book_tick_tp2_partial` (tick) — M4. No dead branch found, but the tick ladder duplicates ExitEngine private-state writes (`:441-442`, `:473`). Separately, `runtime._check_pyramid` is dead (L1).

## Q5 — Closes without `_execute_full_close` or without `exit_source`
Only `runtime.py:1402-1411` (C2). Partial closes legitimately do not stamp `exit_source` since no full-close log is emitted.

## Q6 — Swallowed exceptions that could skip an exit
`exits.py:195-197` (C1) is the only swallow capable of skipping/weakening an exit. All others (`runtime.py:566,572,588,997,1161,1348,1518`) are journal/cert/advisor paths and cannot skip an exit, though `:1518` and `:1348` mask advisor errors.
