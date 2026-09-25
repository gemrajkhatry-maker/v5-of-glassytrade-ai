# glassytrade — dormant target stack (quarantined)

Status: **not wired into production.** This package is the landing shell of
the target architecture (`2026-09-24-target-architecture-and-refactor-design.md`)
merged at `a2916ed9`. It has no callers: `backend/app/main.py` refuses startup
with `GLASSYTRADE_RUNTIME_ENGINE=target` (pinned by
`backend/tests/unit/config/test_live_startup_policy.py`), and no glassytrade
router is registered on the production app.

## Isolation guarantees

- Legacy must not import this stack except the single allowlisted seam
  (`glassytrade.bootstrap.runtime_config` in `main.py`, needed for the refusal
  guard): pinned by `tests/architecture/test_dormant_stack_quarantine.py`.
- This stack must not import legacy code: pinned by
  `backend/tests/architecture/test_glassytrade_imports.py`.
- `frontend/src/projection/` is the matching dormant frontend shell — also
  unwired (only `src/app/useProjection.ts` and its own tests reference it).

## Known unresolved defects

The ~100 green tests here exercise the stack in isolation and **must not be
read as readiness evidence**. Defects recorded during the 2026-09-25 review
pass include at least: a `submit_entry` path calling a coordinator method
that does not exist; `Fill` restart-rebuild dropping fill `side` and intent
prices; protection activation colliding on `event_id`; and a `self.jroker`
attribute typo in `application/oms/protective_order_service.py:26`. Do not fix
them incidentally — they are repaired or superseded within their plan
packages.

## Activation gate

Composition of this stack requires, in order, the approved packages from
`~/.qoder/plans/infinite-cove-asp.md`: B1 (entry-persistence barrier), B2
(truthful outcomes), B3 (atomic durable transitions), L1 (completion-aware
lifecycle), C1 (single startup ownership), E1 (serialized execution owner) —
each with its own review gate. Until then this tree is a blueprint, not a
runtime.
