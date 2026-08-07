# WS-NOREPLY — Remove the AI "reply/command" mode (make OUT OF SCOPE)

**Worktree:** `/Users/apple/Documents/wt-ws-noreply` (branch `migration/ws-noreply`). Work ONLY there.

**Context:** The architecture proposal's non-negotiable #8 is "delete over add — if a component doesn't feed the edge, it doesn't ship." The AI **command/reply mode** (natural-language chat overlay where the trader types "show nifty 15m bull cyan" and the service replies with config updates) is a dead interactive feature: the `/command` endpoint has **no frontend caller** and **no tests**. Per the user directive, remove this functionality and mark it OUT OF SCOPE.

**Scope (verified — nothing else references these):**

1. **`backend/app/application/services/ai_command_service.py`** — remove ONLY the NL-command reply machinery:
   - Delete `_SYMBOL_KEYWORDS`, `_INTERVAL_KEYWORDS`, `_COLOR_KEYWORDS` module constants.
   - Delete `parse_market_command(self, prompt) -> dict` (the entire method).
   - KEEP `analyze_market`, `get_decision_history`, `get_journal_endpoint`, `get_promotion` (the router uses them).
   - Update the module docstring to note the command/reply mode was removed as out-of-scope.

2. **`backend/app/api/routers/ai.py`** — remove:
   - The `CommandRequest` pydantic model.
   - The `@router.post("/command")` endpoint + `process_command`.
   - KEEP `/analyze`, `/history`, `/journal*`, and any other endpoints.
   - `_command_service` stays (analyze/history/journal still call it).

3. **`backend/app/infrastructure/serialization/schemas.py`** — remove `AICommandResponseDTO` (line ~313) and `CommandRequestDTO` (line ~355). KEEP `ChatMessageDTO` (verify it's used by the llm_history WS path — grep before removing; if it's truly unused too, you may remove it but only after confirming).

4. **Docs — mark OUT OF SCOPE:** append a short "Out of scope" section to `docs/AMT_ARCHITECTURE_PROPOSAL.md`? NO — that file is the reference spec. Instead append to `docs/AMT_UNIFICATION.md` a note: "**AI command/reply mode: REMOVED (out of scope).** The NL command overlay (`/command`, `AiCommandService.parse_market_command`) was dead code with no frontend caller or tests; deleted per the delete-over-add rule. Interactive AI that 'replies' to trader commands is not part of the edge — the LLM remains advisory-only (entry journal + overseer)."

**Verify:**
```bash
cd /Users/apple/Documents/wt-ws-noreply
grep -rn "parse_market_command\|/command\|CommandRequest\|AICommandResponseDTO\|CommandRequestDTO" backend/app backend/tests --include="*.py"   # must be EMPTY
cd backend && /Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/unit -q --tb=short --continue-on-collection-errors   # 0 failed/0 errors
PYTHONPATH=/Users/apple/Documents/wt-ws-noreply/backend /Users/apple/miniconda3/envs/amt_313/bin/python -c "import app.main"   # smoke
```
Report exact counts.

**Commits:** `feat(backend): remove AI command/reply mode (out of scope)`, `docs: mark AI command/reply mode out of scope`.

**Report:** `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/ws-noreply-report.md`. Reply: status, commits, the grep-empty evidence, test counts, concerns.
