# Issue tracker

Issues and PRDs for this repo live as GitHub issues. Use the `gh` CLI for all
issue operations — do not invent a local tracker.

## Reading

```bash
gh issue list --state open --limit 50
gh issue view <number>
```

## Labels

Apply the five canonical triage labels only (see
[triage-labels.md](./triage-labels.md)):

- `needs-triage` — new, unclassified
- `needs-info` — blocked on reporter input
- `ready-for-agent` — specified, testable, safe for an agent to pick up
- `ready-for-human` — requires human judgement (money-path design, risk sign-off)
- `wontfix` — closed with rationale

## Creating an issue from agent work

When a task uncovers work outside its footprint (the execution-graph rule:
"if a node touches a file not listed here, stop"), file it instead of expanding
scope:

```bash
gh issue create \
  --label ready-for-agent \
  --title "short imperative title" \
  --body "Context, evidence, files, and the acceptance test."
```

Reference the source doc (e.g. `docs/architecture/2026-09-21-v7-prune-execution-plan.md`)
and the node id (`N1`…`N9`) in the body.
