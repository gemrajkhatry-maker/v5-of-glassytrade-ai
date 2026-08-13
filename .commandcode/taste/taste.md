# Taste

- Prefers launching the app with the project's own virtual environment (e.g., `…/.venv/bin/python3`) instead of the system Python used by the default start scripts. Confidence: 0.7
- Reports frontend/connectivity bugs by pasting the full raw browser console/network error output (CORS errors, stack traces, retry logs) rather than a prose summary. Confidence: 0.5
- Raises issues by pasting the exact log line with its file:line reference (e.g., "ChartScene.tsx:279 [ChartScene] Ignored stale/out-of-order tick update: ...") and asking for a root-cause review. Confidence: 0.5
- Reports UI issues by pasting the literal on-screen text verbatim (e.g., status banner titles like "MONITORING — No setup", instrument headers like "BANKNIFTY 25 AUG 57200 CALL · Live book & AMT") and asks terse, informal "why no X" questions in lowercase with typos, rather than describing the symptom in prose. Confidence: 0.4
