# Task 0.4 — Reference port pattern: `vwap_breakout.py` (worked example)

**From:** docs/superpowers/plans/2026-08-06-quant-brain-migration.md — Phase 0, Task 0.4

**Goal:** Port the first real brain module — `backend/app/domain/fabio_ai/services/vwap_breakout.py` → `quant/decision/vwap_breakout.py` — using the exact move-with-shim + parity recipe that every Phase 1 track will follow. This is the template task.

**Files:**
- Move: `backend/app/domain/fabio_ai/services/vwap_breakout.py` → `quant/decision/vwap_breakout.py`
- Create shim: `backend/app/domain/fabio_ai/services/vwap_breakout.py`
- Create: `tests/quant/decision/test_vwap_breakout_parity.py`
- Create: `tests/quant/decision/__init__.py` only if it does not already exist

**Interfaces:**
- Consumes: nothing (this module is pure, zero deps — that's why it's the template).
- Produces (later tasks import it): `quant.decision.vwap_breakout.detect_vwap_breakout(vwap: float, std: float, price: float, volume: float, avg_volume: float) -> str | None`.

## Steps

- [ ] **Step 1: Check for existing backend tests** — run `grep -rn "detect_vwap_breakout" /Users/apple/Documents/v5-of-glassytrade-ai/backend/tests`. If any exist, port them into `tests/quant/decision/test_vwap_breakout.py` (imports → `quant.decision.vwap_breakout`).
- [ ] **Step 2: Move the module**
```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
git mv backend/app/domain/fabio_ai/services/vwap_breakout.py quant/decision/vwap_breakout.py
grep -n "app\." quant/decision/vwap_breakout.py   # MUST be empty (module is pure)
```
- [ ] **Step 3: Add the shim at the legacy path**
```python
# backend/app/domain/fabio_ai/services/vwap_breakout.py
"""Re-export shim — moved to quant/decision/vwap_breakout.py. Delete in Phase 3."""
from quant.decision.vwap_breakout import *  # noqa: F401,F403
```
- [ ] **Step 4: Write the parity test**
```python
# tests/quant/decision/test_vwap_breakout_parity.py
from quant.decision.vwap_breakout import detect_vwap_breakout as new
from app.domain.fabio_ai.services.vwap_breakout import detect_vwap_breakout as legacy
from tests.quant.parity import assert_parity


def test_parity():
    cases = [
        dict(vwap=100.0, std=1.0, price=102.0, volume=500, avg_volume=100),  # LONG
        dict(vwap=100.0, std=1.0, price=98.0, volume=500, avg_volume=100),   # SHORT
        dict(vwap=100.0, std=1.0, price=100.5, volume=50, avg_volume=100),   # None
        dict(vwap=100.0, std=0.0, price=100.0, volume=0, avg_volume=0),      # degenerate
        dict(vwap=100.0, std=1.0, price=102.0, volume=150, avg_volume=100),  # volume ratio edge
        dict(vwap=50.0, std=0.5, price=49.0, volume=90, avg_volume=100),     # SHORT edge
    ]
    for kw in cases:
        assert_parity(legacy, new, **kw)
```
Note: read the actual function body first — use `vwap`/`std`/`price` values that exercise the real branches (the above are a starting point; adjust to cover LONG/SHORT/None and the volume threshold exactly).
- [ ] **Step 5: Run, verify PASS**
```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant/decision/test_vwap_breakout_parity.py -q --tb=short
```
Then the full quant suite (must stay green) and the backend unit suite via the shim (must stay green):
```bash
/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant -q --tb=short
cd backend && /Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/unit -q --tb=short
```
- [ ] **Step 6: Commit** `refactor(quant): move vwap_breakout from backend brain`

## Report contract

Write your report to `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/task-0.4-report.md`: commit hash, the actual body of `detect_vwap_breakout` (copy it in), which case maps to which return value, test tails (parity + quant + backend unit). Return: status, commit, one-line test summary, concerns.
