# Workflow

- Prefers root-cause fixes over shotgun/band-aid patching when something regresses (e.g., UI flicker); explicitly asks to "fix root cause and not shotgun it". Confidence: 0.8
- Prefers strictly scoped edits when implementing plan tasks: modify only the files named in the task, preserve existing user changes, never reset/revert files, and don't commit unless necessary (leave changes in the shared worktree). Confidence: 0.8
- Prefers TDD when implementing plan tasks: read the plan first, add failing tests, implement the minimum fix, then run focused tests. Confidence: 0.8
- Prefers reporting test results with the exact commands run and their output, not just a summary. Confidence: 0.6
- Prefers code review reports structured as Critical/Important/Minor findings with file:line references and an explicit approval verdict. Confidence: 0.6
- Prefers clean code with no duplicated code or flows; explicitly asks to keep code clean and avoid duplicate code/flows. Confidence: 0.6
- Prefers investigating regressions by diffing against an older git commit or a stable reference branch (e.g., stable_v5) to find the divergence that caused the issue. Confidence: 0.6
- Prefers fixing issues in the current working state (including uncommitted changes) rather than starting fresh or resetting. Confidence: 0.6
- Prefers code reviews that go in depth over both the code and the data flows, explicitly hunting for issues, code duplications, and code smells — not just correctness bugs — and verifies suspected findings by reading the actual source before reporting them. Confidence: 0.6
