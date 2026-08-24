# rl_models — RL training checkpoints

Status as of the WS-CRUFT hygiene sweep (branch `migration/ws-cruft`):

- All 11 zips here are **versioned** (added in the initial commit `b1d2ddc`), forming a
  legitimate RL training history: `checkpoint_10000.zip` … `checkpoint_100000.zip` plus
  `valentini_final.zip`. Each is ~150 KB (~3.2 MB total). They are **kept** — not obviously
  stale and intentionally committed.
- Nothing in the codebase regenerates them (no trainer code references `rl_models/`), so they
  are not gitignored. If the RL pipeline is reintroduced and starts writing checkpoints here,
  add `backend/rl_models/*.zip` to `.gitignore` and store only final artifacts.
