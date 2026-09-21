# Triage labels

Exactly five canonical labels are used across this repo. Do not introduce others.

| Label | Meaning | Who acts |
|---|---|---|
| `needs-triage` | Default for new issues. No classification yet. | Maintainer |
| `needs-info` | Missing repro, expected behaviour, or environment detail. | Reporter |
| `ready-for-agent` | Specified and testable: acceptance criteria written, blast radius known, no human sign-off required. | Coding agent |
| `ready-for-human` | Touches money-path design, live risk limits, or broker behaviour; or the fix requires a judgement call the repo has no authority for. | Human |
| `wontfix` | Closed deliberately, with a one-paragraph rationale in the issue body. | Maintainer |

## Flow

```
new -> needs-triage -> (needs-info | ready-for-agent | ready-for-human | wontfix)
```

`ready-for-agent` is the only label under which an agent should start work.
Money-path issues (decision gates, OMS, risk) default to `ready-for-human`
until the acceptance test is written down.
